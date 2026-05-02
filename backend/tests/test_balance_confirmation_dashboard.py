"""Backend tests — Balance Confirmation Dashboard (analytics + summary downloads)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-tax-tools.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "qa_test_session_token_20260430_dev"
COOKIES = {"session_token": SESSION_TOKEN}

# QA-bot pre-existing run from the request
EXPECTED_RUN_ID = "e96d4d22-f7be-458b-a314-abb97acddf55"
EXPECTED_CLIENT_ID = "cli_8656f99622ae"

EXPECTED_STATUSES = {"confirmed", "reconciled", "disputed", "in_flight", "failed", "not_sent"}


@pytest.fixture(scope="module")
def picked_run():
    r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs", cookies=COOKIES, timeout=30)
    assert r.status_code == 200, f"runs list status={r.status_code} body={r.text[:300]}"
    data = r.json()
    runs = data if isinstance(data, list) else (data.get("runs") or data.get("items") or [])
    assert runs, f"no runs returned: {data}"
    # prefer expected run if present
    chosen = next((x for x in runs if x.get("id") == EXPECTED_RUN_ID or x.get("run_id") == EXPECTED_RUN_ID), runs[0])
    rid = chosen.get("id") or chosen.get("run_id")
    cid = chosen.get("client_id")
    assert rid, f"run has no id: {chosen}"
    return {"run_id": rid, "client_id": cid, "raw": chosen}


# ---------- Analytics endpoint ----------
class TestAnalyticsShape:
    def test_analytics_status_and_top_keys(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/analytics",
                         cookies=COOKIES, timeout=60)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:400]}"
        body = r.json()
        for key in ("overall", "categories", "funnel", "top_disputed",
                    "top_unresponsive", "subheads"):
            assert key in body, f"missing key {key}"

    def test_overall_six_status_buckets(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/analytics",
                         cookies=COOKIES, timeout=60)
        assert r.status_code == 200
        body = r.json()
        overall = body["overall"]
        assert "by_status" in overall and isinstance(overall["by_status"], dict)
        got = set(overall["by_status"].keys())
        assert got == EXPECTED_STATUSES, f"buckets mismatch got={got}"
        for st, cell in overall["by_status"].items():
            assert "count" in cell and "amount" in cell, f"bucket {st} missing count/amount"
            assert isinstance(cell["count"], int)
            assert isinstance(cell["amount"], (int, float))
        # Total count consistency
        sum_n = sum(c["count"] for c in overall["by_status"].values())
        assert sum_n == overall["count"], f"sum_by_status({sum_n}) != overall.count({overall['count']})"

    def test_categories_structure(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/analytics",
                         cookies=COOKIES, timeout=60)
        body = r.json()
        cats = body["categories"]
        assert isinstance(cats, list) and len(cats) >= 4
        keys = {c["key"] for c in cats}
        for required in ("trade_receivable", "trade_payable", "bank", "unsecured_loans"):
            assert required in keys, f"missing category key {required}"
        for c in cats:
            assert "label" in c and "count" in c and "amount" in c
            assert "by_status" in c and set(c["by_status"].keys()) == EXPECTED_STATUSES
            assert "coverage" in c
            for k in ("response_count_pct", "response_amount_pct",
                      "audit_count_pct", "audit_amount_pct"):
                assert k in c["coverage"], f"coverage missing {k}"

    def test_funnel_six_stages(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/analytics",
                         cookies=COOKIES, timeout=60)
        body = r.json()
        funnel = body["funnel"]
        assert len(funnel) == 6, f"expected 6 funnel stages, got {len(funnel)}"
        labels = [s["label"] for s in funnel]
        assert labels == ["Identified", "With email", "Dispatched",
                          "Delivered", "Opened", "Responded"], labels
        for s in funnel:
            for k in ("count", "amount", "count_pct", "amount_pct"):
                assert k in s

    def test_reconciled_consistency(self, picked_run):
        """`reconciled` bucket count should match top-level `reconciled_count`
        (when the disputed→recon-comment rule fires)."""
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/analytics",
                         cookies=COOKIES, timeout=60)
        body = r.json()
        recon_in_overall = body["overall"]["by_status"]["reconciled"]["count"]
        recon_top = body.get("reconciled_count", 0)
        # overall.reconciled count must equal the top-level ledger-id count
        assert recon_in_overall == recon_top, (
            f"overall.reconciled.count={recon_in_overall} but top reconciled_count={recon_top}"
        )


# ---------- Summary downloads ----------
class TestSummaryDownloads:
    def test_summary_pdf(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/summary.pdf",
                         cookies=COOKIES, timeout=120)
        assert r.status_code == 200, f"status={r.status_code}"
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct.lower(), f"content-type={ct}"
        assert r.content[:4] == b"%PDF", f"missing %PDF header: {r.content[:8]!r}"
        assert len(r.content) >= 5 * 1024, f"PDF too small ({len(r.content)} bytes)"

    def test_summary_xlsx(self, picked_run):
        rid = picked_run["run_id"]
        r = requests.get(f"{BASE_URL}/api/balance-confirmation/runs/{rid}/summary.xlsx",
                         cookies=COOKIES, timeout=120)
        assert r.status_code == 200, f"status={r.status_code}"
        # XLSX is a ZIP archive — magic bytes 'PK\x03\x04'
        assert r.content[:2] == b"PK", f"missing ZIP magic: {r.content[:8]!r}"
        assert len(r.content) >= 1024, f"XLSX too small ({len(r.content)} bytes)"
