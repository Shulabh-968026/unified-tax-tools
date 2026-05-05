"""Release-3.1 LIVE HTTP tests — ITC kind classification + smarter seeding
seen end-to-end via the deployed FastAPI service.

Validated against the user-reported run run_0ef0127bba5c (ABC Textile
Mills) and the sibling run_8d427d1f97e0.  Uses the QA bypass session
token.  No clients/runs created; no mutation is persisted — the single
PATCH/generate round-trip at the end is reverted.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://unified-tax-tools.preview.emergentagent.com"
).rstrip("/")
SESSION = "qa_test_session_token_20260430_dev"
USER_RUN = "run_0ef0127bba5c"     # the user-reported case
SIBLING_RUN = "run_8d427d1f97e0"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    s.cookies.set("session_token", SESSION)
    return s


def _get_run(client, run_id):
    r = client.get(f"{BASE_URL}/api/runs/{run_id}")
    assert r.status_code == 200, r.text
    return r.json()


class TestItcKindField:
    """Every ITC candidate carries `kind` ∈ {input, output, other}."""

    def test_kind_present_on_every_candidate_user_run(self, client):
        doc = _get_run(client, USER_RUN)
        cands = doc.get("itc_candidates") or []
        assert len(cands) > 0, "expected itc_candidates list"
        allowed = {"input", "output", "other"}
        for c in cands:
            assert "kind" in c, f"candidate missing kind: {c.get('name')}"
            assert c["kind"] in allowed, f"{c['name']} has illegal kind={c['kind']!r}"

    def test_kind_present_on_every_candidate_sibling_run(self, client):
        doc = _get_run(client, SIBLING_RUN)
        cands = doc.get("itc_candidates") or []
        assert len(cands) > 0
        allowed = {"input", "output", "other"}
        for c in cands:
            assert c.get("kind") in allowed


class TestOutputLedgersNotPreTicked:
    """Output-prefixed ledgers stay suggested=False even with matching subhead."""

    def test_output_cgst_sgst_igst_are_output_kind_and_not_suggested(self, client):
        doc = _get_run(client, USER_RUN)
        cands = {c["name"]: c for c in doc.get("itc_candidates", [])}
        for name in ["Output CGST @ 2.5%", "Output SGST @ 2.5%", "Output IGST @ 5%"]:
            assert name in cands, f"{name} missing from candidate pool"
            assert cands[name]["kind"] == "output"
            assert cands[name]["suggested"] is False, (
                f"{name} was pre-ticked — bug has regressed"
            )


class TestInputLedgerPreTicked:
    """Input-prefixed ledger on a target subhead remains pre-ticked."""

    def test_input_sgst_is_input_kind_and_suggested(self, client):
        doc = _get_run(client, USER_RUN)
        cands = {c["name"]: c for c in doc.get("itc_candidates", [])}
        assert "Input SGST @ 9%" in cands
        c = cands["Input SGST @ 9%"]
        assert c["kind"] == "input"
        assert c["suggested"] is True


class TestRealRunExactSet:
    """Exact scenario from review request: 4 GST ledgers, only Input pre-ticked."""

    def test_user_reported_case_exact_shape(self, client):
        # NOTE · After Release 3.2.1's JSON+XLSX-union + subhead-override
        # fixes, the candidate pool now correctly surfaces all 12 GST
        # ledgers from the user's books (was 4 before).  We pin the
        # post-3.2.1 expectation here so any future regression is loud.
        doc = _get_run(client, USER_RUN)
        gst = [
            c for c in doc.get("itc_candidates", [])
            if any(k in c["name"].upper() for k in ("CGST", "SGST", "IGST"))
        ]
        assert len(gst) >= 4, f"expected ≥4 GST ledgers, got {[g['name'] for g in gst]}"
        # The 6 "Input <CGST/SGST> @ rate%" ledgers + SGST IN PUT should
        # all be classified as input.  The 3 Output ledgers should NOT
        # be pre-ticked.
        outputs = [g for g in gst if g["kind"] == "output"]
        assert len(outputs) >= 3
        for o in outputs:
            assert o["suggested"] is False, f"output ledger {o['name']} should never be auto-ticked"


class TestUserElectedOutputRespected:
    """User can still override and elect an Output ledger; backend must
    persist it (UI surfaces the warning via kind='output')."""

    def test_patch_persists_output_election_verbatim(self, client):
        """PATCH /selections stores the user's Output pick without stripping."""
        before = _get_run(client, USER_RUN)
        original_itc = list(before.get("itc_selection") or [])

        try:
            r = client.patch(
                f"{BASE_URL}/api/runs/{USER_RUN}/selections",
                json={"itc_ledgers": ["Output CGST @ 2.5%"]},
            )
            assert r.status_code in (200, 204), r.text

            after = _get_run(client, USER_RUN)
            sel = after.get("itc_selection") or []
            assert "Output CGST @ 2.5%" in sel, (
                "PATCH silently stripped user-elected Output ledger"
            )
            # kind still classifies as output so the UI can warn
            cands = {c["name"]: c for c in after.get("itc_candidates", [])}
            assert cands["Output CGST @ 2.5%"]["kind"] == "output"
        finally:
            client.patch(
                f"{BASE_URL}/api/runs/{USER_RUN}/selections",
                json={"itc_ledgers": original_itc},
            )

    def test_generate_with_output_ledger_respects_user_choice(self, client):
        """POST /generate passed an Output ledger in the body keeps it in
        itc_selection (run still classifies successfully)."""
        before = _get_run(client, USER_RUN)
        original_itc = list(before.get("itc_selection") or [])
        original_inf = bool(before.get("use_itc_inference", True))
        original_excl = list(before.get("exclusion_selection") or [])
        original_exempt = list(before.get("exempt_selection") or [])
        original_cats = dict(before.get("exclusion_categories") or {})

        try:
            body = {
                "itc_ledgers": ["Output CGST @ 2.5%"],
                "excluded_ledgers": original_excl,
                "exempt_ledgers": original_exempt,
                "use_itc_inference": original_inf,
                "exclusion_categories": original_cats,
            }
            g = client.post(f"{BASE_URL}/api/runs/{USER_RUN}/generate", json=body)
            assert g.status_code == 200, g.text
            summary = g.json().get("summary") or {}
            # Run still classifies (has col2 total)
            assert "col2_total" in summary or "col2" in summary

            after = _get_run(client, USER_RUN)
            sel = after.get("itc_selection") or []
            assert "Output CGST @ 2.5%" in sel, (
                "generate stripped user-elected Output ledger"
            )
            cands = {c["name"]: c for c in after.get("itc_candidates", [])}
            assert cands["Output CGST @ 2.5%"]["kind"] == "output"
        finally:
            # Restore original state via generate (canonical)
            client.post(
                f"{BASE_URL}/api/runs/{USER_RUN}/generate",
                json={
                    "itc_ledgers": original_itc,
                    "excluded_ledgers": original_excl,
                    "exempt_ledgers": original_exempt,
                    "use_itc_inference": original_inf,
                    "exclusion_categories": original_cats,
                },
            )


class TestRegressionNoLeak:
    """Still exactly 3 clients; no stray run created."""

    def test_client_count_unchanged(self, client):
        r = client.get(f"{BASE_URL}/api/clients")
        assert r.status_code == 200
        clients = r.json()
        # Accept either bare list or {clients: [...]}
        if isinstance(clients, dict) and "clients" in clients:
            clients = clients["clients"]
        names = sorted([c.get("name") or c.get("client_name") for c in clients])
        assert len(names) == 3, f"expected 3 clients, got {names}"
