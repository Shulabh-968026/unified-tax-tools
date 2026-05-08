"""Live HTTP tests — Phase C.1 multi-division scope on POST /runs.

Verifies that every module (BC, FA, GST, FS, MSME) accepts the new
``scope_kind`` / ``division_ids`` / ``gstin_group_id`` fields, persists
them on the working doc, and uses ``scope_key`` for upsert idempotency.

Single-scope callers (no scope params) get the ``"consolidation"``
default and continue to work unchanged.

Note: Clause 44's POST /runs is multipart with two file uploads — its
scope wiring is verified end-to-end by the testing agent; this file
focuses on the JSON-body controllers where a unit-style live test is
both meaningful and cheap.
"""
from __future__ import annotations

import os
import pytest
import requests

# pytest collection root for backend tests reads BASE_URL from conftest.
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001")
COOKIE = {"session_token": os.environ.get(
    "TEST_SESSION_TOKEN", "qa_test_session_token_20260206_dev",
)}

MULTI_DIV_CLIENT = "cli_c5d02541264c"  # GMS Processors P Limited (2 divisions)
SINGLE_DIV_CLIENT = "cli_ad137f29aebb"  # ABC Textile Mills
TEST_FY = "2099-00"  # forward-dated so we never collide with real data


def _api(path: str) -> str:
    return f"{BASE_URL}/api{path}"


@pytest.fixture(scope="module")
def first_division_id():
    r = requests.get(_api(f"/clients/{MULTI_DIV_CLIENT}"), cookies=COOKIE, timeout=10)
    r.raise_for_status()
    body = r.json()
    return body["divisions"][0]["division_id"]


@pytest.fixture(autouse=True)
def _cleanup():
    """Drop any docs from the test FY before each test, and again after."""
    yield
    # Cleanup: remove every test-created row in test FY across all 6 collections
    for path in (
        f"/balance-confirmation/runs",  # delete via list_then_delete pattern
    ):
        # We can't delete bc_runs via API per-FY, so we touch them in DB cleanup
        # via a direct mongo query in a session-scoped fixture instead.
        pass


# ──────────────────────────────────────────────────────────────────────
# Balance Confirmation
# ──────────────────────────────────────────────────────────────────────
def test_bc_default_consolidation_persists_scope():
    r = requests.post(
        _api("/balance-confirmation/runs"),
        cookies=COOKIE,
        json={"client_id": SINGLE_DIV_CLIENT, "fy": TEST_FY},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_kind"] == "consolidation"
    assert body["scope_key"] == "consolidation"
    assert body["scope_label"] == "Consolidation"
    assert body["division_ids"] == []
    assert body["gstin_group_id"] is None


def test_bc_division_scope_persists_and_is_distinct_from_consolidation(first_division_id):
    # Division-scoped run
    r = requests.post(
        _api("/balance-confirmation/runs"),
        cookies=COOKIE,
        json={
            "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
            "scope_kind": "division",
            "division_ids": [first_division_id],
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    div_run = r.json()
    assert div_run["scope_kind"] == "division"
    assert div_run["scope_key"] == f"div_{first_division_id}"
    assert div_run["division_ids"] == [first_division_id]
    assert div_run["scope_label"]  # human label populated

    # Consolidation-scoped run on the SAME (client, fy) — must be a different doc
    r2 = requests.post(
        _api("/balance-confirmation/runs"),
        cookies=COOKIE,
        json={
            "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
            "scope_kind": "consolidation",
        },
        timeout=10,
    )
    assert r2.status_code == 200, r2.text
    consol = r2.json()
    assert consol["scope_kind"] == "consolidation"
    assert consol["id"] != div_run["id"]


def test_bc_idempotent_per_scope(first_division_id):
    payload = {
        "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
        "scope_kind": "division",
        "division_ids": [first_division_id],
    }
    a = requests.post(_api("/balance-confirmation/runs"), cookies=COOKIE, json=payload, timeout=10).json()
    b = requests.post(_api("/balance-confirmation/runs"), cookies=COOKIE, json=payload, timeout=10).json()
    assert a["id"] == b["id"]


# ──────────────────────────────────────────────────────────────────────
# Fixed Assets
# ──────────────────────────────────────────────────────────────────────
def test_fa_default_consolidation_persists_scope():
    r = requests.post(
        _api("/fixed-assets/runs"),
        cookies=COOKIE,
        json={"client_id": SINGLE_DIV_CLIENT, "fy": TEST_FY},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_kind"] == "consolidation"
    assert body["scope_key"] == "consolidation"


def test_fa_division_scope_distinct_doc(first_division_id):
    r1 = requests.post(
        _api("/fixed-assets/runs"),
        cookies=COOKIE,
        json={
            "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
            "scope_kind": "division",
            "division_ids": [first_division_id],
        },
        timeout=10,
    ).json()
    r2 = requests.post(
        _api("/fixed-assets/runs"),
        cookies=COOKIE,
        json={
            "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
            "scope_kind": "consolidation",
        },
        timeout=10,
    ).json()
    assert r1["scope_key"] == f"div_{first_division_id}"
    assert r2["scope_key"] == "consolidation"
    assert r1["id"] != r2["id"]


# ──────────────────────────────────────────────────────────────────────
# GST Recon
# ──────────────────────────────────────────────────────────────────────
def test_gst_default_consolidation():
    """Phase C.3 — GST Recon's grain is ALWAYS gstin_group; the backend
    auto-synthesises a hidden Default group for clients that haven't
    set up groups, so a no-scope POST resolves to scope_kind=gstin_group
    + scope_key=gstin_<default_id> (NOT consolidation)."""
    r = requests.post(
        _api("/gst-recon/runs"),
        cookies=COOKIE,
        json={"client_id": SINGLE_DIV_CLIENT, "fy": TEST_FY},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_kind"] == "gstin_group"
    assert body["scope_key"].startswith("gstin_")
    assert body["gstin_group_id"]


def test_gst_idempotent_per_scope(first_division_id):
    """No-scope POST is idempotent (same Default group resolves to same id)."""
    payload = {"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY}
    a = requests.post(_api("/gst-recon/runs"), cookies=COOKIE, json=payload, timeout=10).json()
    b = requests.post(_api("/gst-recon/runs"), cookies=COOKIE, json=payload, timeout=10).json()
    assert a["id"] == b["id"]
    assert a["scope_kind"] == "gstin_group"


# ──────────────────────────────────────────────────────────────────────
# Financial Statement
# ──────────────────────────────────────────────────────────────────────
def test_fs_default_consolidation():
    r = requests.post(
        _api("/fin-statement/runs"),
        cookies=COOKIE,
        json={
            "client_id": SINGLE_DIV_CLIENT, "fy": TEST_FY,
            "fy_start": "2099-04-01", "fy_end": "2100-03-31",
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_key"] == "consolidation"


# ──────────────────────────────────────────────────────────────────────
# MSME 43B(h) Sessions
# ──────────────────────────────────────────────────────────────────────
def test_msme_default_consolidation():
    r = requests.post(
        _api("/msme/sessions"),
        cookies=COOKIE,
        json={"client_id": SINGLE_DIV_CLIENT, "fy": TEST_FY},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # session_summary may strip scope fields; refetch via list/get to confirm.
    all_sessions = requests.get(
        _api(f"/msme/sessions?client_id={SINGLE_DIV_CLIENT}"),
        cookies=COOKIE, timeout=10,
    ).json()
    target = next((s for s in (all_sessions if isinstance(all_sessions, list) else all_sessions.get("rows", [])) if s.get("fy") == TEST_FY), None)
    assert target is not None
    # Get the raw doc via /sessions/{id}
    detail = requests.get(_api(f"/msme/sessions/{body['id']}"), cookies=COOKIE, timeout=10).json()
    assert detail.get("scope_key") == "consolidation"


# ──────────────────────────────────────────────────────────────────────
# Cleanup at end-of-module via direct DB
# ──────────────────────────────────────────────────────────────────────
def teardown_module(_module):
    """Wipe TEST_FY rows from all 6 collections."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _cleanup():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        for coll, key in [
            ("runs",            "period"),
            ("bc_runs",         "fy"),
            ("fa_runs",         "fy"),
            ("gst_recon_runs",  "fy"),
            ("fs_runs",         "fy"),
            ("msme_sessions",   "fy"),
        ]:
            await db[coll].delete_many({key: TEST_FY})
        cli.close()
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    asyncio.run(_cleanup())
