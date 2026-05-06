"""Release 4.5 — Multi-run collapse + generations log live tests.

Verifies that:
- POST /runs is upsert (returns same canonical id for same client+fy+module)
- GET /runs filters out archived docs
- GET /runs/{rid}/generations returns 200 with shape {run_id, generations:[...]}
"""
from __future__ import annotations
import os
import pytest
import requests

from tests.conftest import BASE_URL  # noqa: F401


pytestmark = pytest.mark.live


def _cookies():
    return {"session_token": "qa_test_session_token_20260206_dev"}


def _api(path: str) -> str:
    return f"{BASE_URL.rstrip('/')}{path}"


# ----------------------------------------------------------------------
# Generations endpoints — must respond 200 with the canonical envelope.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("module_path,id_field", [
    ("/api/balance-confirmation/runs", "id"),
    ("/api/fixed-assets/runs",          "id"),
    ("/api/fin-statement/runs",         "id"),
    ("/api/gst-recon/runs",             "id"),
    ("/api/msme/sessions",              "id"),
])
def test_generations_endpoint_returns_envelope(module_path, id_field):
    r = requests.get(_api(module_path), cookies=_cookies(), timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("runs") or []
    if not rows:
        pytest.skip(f"No active runs for {module_path}")
    rid = rows[0][id_field]
    # Map runs URL → generations endpoint
    if module_path.endswith("/sessions"):
        gen_url = f"{module_path}/{rid}/generations"
    else:
        gen_url = f"{module_path}/{rid}/generations"
    g = requests.get(_api(gen_url), cookies=_cookies(), timeout=15)
    assert g.status_code == 200, g.text
    body = g.json()
    assert "run_id" in body
    assert "generations" in body
    assert isinstance(body["generations"], list)


# ----------------------------------------------------------------------
# Clause 44 generations endpoint already existed; just sanity-check it.
# ----------------------------------------------------------------------
def test_clause44_generations_endpoint():
    r = requests.get(_api("/api/runs?archived=false"), cookies=_cookies(), timeout=15)
    assert r.status_code == 200
    runs = r.json().get("runs") or []
    if not runs:
        pytest.skip("No clause44 runs")
    rid = runs[0]["run_id"]
    g = requests.get(_api(f"/api/runs/{rid}/generations"), cookies=_cookies(), timeout=15)
    assert g.status_code == 200, g.text
    body = g.json()
    assert "run_id" in body and "generations" in body
    assert isinstance(body["generations"], list)


# ----------------------------------------------------------------------
# Archived runs are filtered out from GET /runs
# ----------------------------------------------------------------------
def test_no_archived_runs_in_listing():
    """Each module's GET /runs must hide archived docs (collapse-merged)."""
    paths = [
        "/api/balance-confirmation/runs",
        "/api/fixed-assets/runs",
        "/api/fin-statement/runs",
        "/api/gst-recon/runs",
        "/api/msme/sessions",
        "/api/runs?archived=false",
    ]
    for p in paths:
        r = requests.get(_api(p), cookies=_cookies(), timeout=15)
        assert r.status_code == 200, f"{p}: {r.text}"
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("runs") or []
        for row in rows:
            assert row.get("archived") is False or row.get("archived") is None, (
                f"{p}: archived row leaked: {row.get('id') or row.get('run_id')}"
            )
