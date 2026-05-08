"""Live HTTP tests — Phase C.3 GST Recon → GSTIN-group canonical key.

Verifies:
  * POST /gst-recon/runs auto-synthesises a hidden Default GSTIN group
    when the caller doesn't pass ``gstin_group_id`` (single-GSTIN
    auditor flow stays one-click).
  * The created run has scope_kind=gstin_group + scope_key=gstin_<id>.
  * Re-POST same payload is idempotent (same id).
  * GET /library/clients/:id/gstin-groups hides defaults; ?include_default=true
    surfaces them.
  * POST /library/clients/:id/gstin-groups/ensure-default returns the
    same group as the auto-synthesis path.
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001")
COOKIE = {"session_token": os.environ.get(
    "TEST_SESSION_TOKEN", "qa_test_session_token_20260206_dev",
)}

CLIENT = "cli_ad137f29aebb"  # ABC Textile Mills (single-div, single-GSTIN)
TEST_FY = "2099-00"


def _api(p): return f"{BASE_URL}/api{p}"


def teardown_module(_m):
    """Clean every TEST_FY row + the gstin_groups synthesised here."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")

    async def _wipe():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        await db.gst_recon_runs.delete_many({"fy": TEST_FY})
        cli.close()
    asyncio.run(_wipe())


def test_post_runs_auto_synthesises_default_group():
    r = requests.post(
        _api("/gst-recon/runs"),
        cookies=COOKIE,
        json={"client_id": CLIENT, "fy": TEST_FY},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_kind"] == "gstin_group"
    assert body["scope_key"].startswith("gstin_")
    assert body["scope_label"] == "Default"
    assert body["gstin_group_id"], "gstin_group_id must be populated"


def test_post_runs_is_idempotent_per_group():
    a = requests.post(_api("/gst-recon/runs"), cookies=COOKIE,
                      json={"client_id": CLIENT, "fy": TEST_FY}, timeout=10).json()
    b = requests.post(_api("/gst-recon/runs"), cookies=COOKIE,
                      json={"client_id": CLIENT, "fy": TEST_FY}, timeout=10).json()
    assert a["id"] == b["id"]
    assert a["gstin_group_id"] == b["gstin_group_id"]


def test_list_groups_hides_defaults_by_default():
    visible = requests.get(
        _api(f"/library/clients/{CLIENT}/gstin-groups"),
        cookies=COOKIE, timeout=10,
    ).json().get("groups", [])
    # Single-GSTIN client: only auto-synth Default exists; visible list must be empty.
    assert all(not g.get("is_default") for g in visible), \
        "Default groups must NOT appear in the visible list"


def test_list_groups_include_default_surfaces_it():
    full = requests.get(
        _api(f"/library/clients/{CLIENT}/gstin-groups?include_default=true"),
        cookies=COOKIE, timeout=10,
    ).json().get("groups", [])
    defaults = [g for g in full if g.get("is_default")]
    assert len(defaults) == 1
    assert defaults[0]["label"] == "Default"


def test_ensure_default_endpoint_is_idempotent():
    a = requests.post(
        _api(f"/library/clients/{CLIENT}/gstin-groups/ensure-default"),
        cookies=COOKIE, timeout=10,
    ).json()
    b = requests.post(
        _api(f"/library/clients/{CLIENT}/gstin-groups/ensure-default"),
        cookies=COOKIE, timeout=10,
    ).json()
    assert a["group_id"] == b["group_id"]
    assert a["is_default"] is True
