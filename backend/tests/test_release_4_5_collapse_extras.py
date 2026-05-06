"""Release 4.5 — Extra coverage: upsert idempotency + stale-id redirect + generations envelope.

Complements tests/test_release_4_5_collapse_live.py. All tests use the QA bypass session.
"""
from __future__ import annotations
import pytest
import requests

from tests.conftest import BASE_URL  # noqa: F401


COOKIES = {"session_token": "qa_test_session_token_20260206_dev"}
TEST_CLIENT = "cli_ad137f29aebb"  # ABC Textile Mills


def _api(p: str) -> str:
    return f"{BASE_URL.rstrip('/')}{p}"


# ---------------------------------------------------------------------------
# UPSERT IDEMPOTENCY — same (client_id, fy) returns same canonical id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,payload", [
    ("/api/balance-confirmation/runs", {"client_id": TEST_CLIENT, "fy": "2023-24"}),
    ("/api/fixed-assets/runs",         {"client_id": TEST_CLIENT, "fy": "2023-24"}),
    ("/api/fin-statement/runs",        {"client_id": TEST_CLIENT, "fy": "2023-24",
                                         "fy_start": "2023-04-01", "fy_end": "2024-03-31"}),
    ("/api/gst-recon/runs",            {"client_id": TEST_CLIENT, "fy": "2023-24"}),
    ("/api/msme/sessions",             {"client_id": TEST_CLIENT, "fy": "2023-24"}),
])
def test_post_runs_is_upsert(path, payload):
    r1 = requests.post(_api(path), json=payload, cookies=COOKIES, timeout=15)
    assert r1.status_code in (200, 201), r1.text
    j1 = r1.json()
    id1 = j1.get("id") or j1.get("run_id") or j1.get("session_id")
    assert id1, f"no id field in {j1}"

    r2 = requests.post(_api(path), json=payload, cookies=COOKIES, timeout=15)
    assert r2.status_code in (200, 201), r2.text
    j2 = r2.json()
    id2 = j2.get("id") or j2.get("run_id") or j2.get("session_id")
    assert id2 == id1, f"upsert violated for {path}: {id1} vs {id2}"


# ---------------------------------------------------------------------------
# STALE / COLLAPSED ID REDIRECT — GET on archived doc returns canonical winner
# ---------------------------------------------------------------------------

def test_msme_stale_session_redirects_to_canonical():
    """GET on an archived MSME session id returns the canonical (un-archived) winner."""
    stale_id = "9c7d41c3-27ee-4bd6-bf89-7782bcda33ea"
    canonical = "25f823c3-d834-44ab-bfbf-9ba325d4c410"
    r = requests.get(_api(f"/api/msme/sessions/{stale_id}"), cookies=COOKIES, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    returned = body.get("id") or body.get("session_id")
    assert returned == canonical, f"expected redirect to {canonical}, got {returned}"
    assert body.get("archived") in (False, None), "winner doc must not be archived"


def test_clause44_stale_run_redirects_to_canonical():
    """Old archived run should redirect to current canonical winner.
    The exact winner id can shift when migrations re-collapse — we just
    assert that the redirected doc is non-archived and id != stale_id."""
    stale_id = "run_8d427d1f97e0"
    r = requests.get(_api(f"/api/runs/{stale_id}"), cookies=COOKIES, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    returned = body.get("run_id")
    assert returned and returned != stale_id, f"expected redirect, got same id {stale_id}"
    assert body.get("archived") in (False, None), "winner doc must not be archived"


# ---------------------------------------------------------------------------
# GENERATIONS ENVELOPE — every module returns {run_id, generations: [...]}
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("get_url, gen_url_fmt, id_key", [
    ("/api/balance-confirmation/runs", "/api/balance-confirmation/runs/{rid}/generations", "id"),
    ("/api/fixed-assets/runs",         "/api/fixed-assets/runs/{rid}/generations",         "id"),
    ("/api/fin-statement/runs",        "/api/fin-statement/runs/{rid}/generations",        "id"),
    ("/api/gst-recon/runs",            "/api/gst-recon/runs/{rid}/generations",            "id"),
    ("/api/msme/sessions",             "/api/msme/sessions/{rid}/generations",             "id"),
])
def test_generations_envelope_shape(get_url, gen_url_fmt, id_key):
    r = requests.get(_api(get_url), cookies=COOKIES, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("runs") or rows.get("sessions") or []
    if not rows:
        pytest.skip(f"No active runs for {get_url}")
    rid = rows[0][id_key]
    g = requests.get(_api(gen_url_fmt.format(rid=rid)), cookies=COOKIES, timeout=15)
    assert g.status_code == 200, g.text
    body = g.json()
    assert "run_id" in body and "generations" in body, body
    assert isinstance(body["generations"], list)
    # Each row (if any) must carry the audit shape
    for gen in body["generations"]:
        assert "gen_id" in gen or "_id" not in gen
        assert "module" in gen


def test_msme_canonical_session_has_generation_row():
    """Spec: a 43BH compute on a session with yearend bills appends >= 1 generation row.
    The canonical session 25f823c3-... was already computed during seed. Verify history."""
    canonical = "25f823c3-d834-44ab-bfbf-9ba325d4c410"
    g = requests.get(_api(f"/api/msme/sessions/{canonical}/generations"),
                     cookies=COOKIES, timeout=15)
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["run_id"] == canonical
    assert len(body["generations"]) >= 1, "expected at least one synthesised/computed gen row"
    row = body["generations"][0]
    assert row["module"] == "msme43bh"
    assert row.get("client_id") == TEST_CLIENT


# ---------------------------------------------------------------------------
# ARCHIVED ROWS HIDDEN FROM GET /runs LISTING
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/balance-confirmation/runs",
    "/api/fixed-assets/runs",
    "/api/fin-statement/runs",
    "/api/gst-recon/runs",
    "/api/msme/sessions",
    "/api/runs?archived=false",
])
def test_listing_filters_archived(path):
    r = requests.get(_api(path), cookies=COOKIES, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("runs") or rows.get("sessions") or []
    for row in rows:
        assert row.get("archived") in (False, None), \
            f"archived row leaked in {path}: id={row.get('id') or row.get('run_id')}"
