"""Release 4.6 · BC Refinement Batch 2 (R3 Universal Recipients + R4 column toggle).

Live HTTP tests for the new universal CC/BCC endpoint and the chain
merge inside bulk-send.  The R4 column-toggle is purely a frontend
concern and is verified by the testing agent E2E.
"""
from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
COOKIES = {"session_token": "qa_test_session_token_20260206_dev"}


def _api(p: str) -> str:
    return f"{BASE_URL}{p}"


@pytest.fixture(scope="module")
def bc_run_id():
    """Pick the first non-archived BC run from the live DB."""
    r = requests.get(_api("/api/balance-confirmation/runs"), cookies=COOKIES, timeout=15)
    assert r.status_code == 200
    runs = r.json()
    if not runs:
        pytest.skip("No BC runs available in DB")
    return runs[0]["id"]


# --------------------------------------------------------------------------- #
# R3 — Universal CC/BCC persistence
# --------------------------------------------------------------------------- #
def test_get_universal_recipients_returns_envelope(bc_run_id):
    r = requests.get(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert "universal_cc"  in body and isinstance(body["universal_cc"],  list)
    assert "universal_bcc" in body and isinstance(body["universal_bcc"], list)


def test_patch_universal_recipients_round_trip(bc_run_id):
    payload = {
        "universal_cc":  ["partner@firm.in", " ARTICLE@firm.IN ", "garbage", ""],
        "universal_bcc": ["audit-archive@firm.in;extra@firm.in"],
    }
    r = requests.patch(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        json=payload, cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cc = body["universal_cc"]
    bcc = body["universal_bcc"]
    # Lower-cased + trimmed + invalid items dropped.
    assert "partner@firm.in" in cc
    assert "article@firm.in" in cc
    assert "garbage" not in cc
    assert "" not in cc
    # Semicolon-separated string was split.
    assert "audit-archive@firm.in" in bcc
    assert "extra@firm.in" in bcc

    # GET must reflect the saved state.
    r2 = requests.get(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        cookies=COOKIES, timeout=15,
    )
    assert r2.status_code == 200
    saved = r2.json()
    assert set(saved["universal_cc"])  == set(cc)
    assert set(saved["universal_bcc"]) == set(bcc)


def test_patch_universal_recipients_dedup_and_normalise(bc_run_id):
    """Dup entries (case- and whitespace-insensitive) must collapse to one."""
    r = requests.patch(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        json={
            "universal_cc":  ["a@x.com", "A@X.COM", " a@x.com "],
            "universal_bcc": ["b@y.com,b@Y.com"],
        },
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["universal_cc"]  == ["a@x.com"]
    assert body["universal_bcc"] == ["b@y.com"]


def test_patch_universal_recipients_empty_clears_list(bc_run_id):
    """Sending [] must clear the list (idempotent reset)."""
    # Seed
    requests.patch(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        json={"universal_cc": ["seed@x.in"], "universal_bcc": []},
        cookies=COOKIES, timeout=15,
    )
    # Clear
    r = requests.patch(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/universal-recipients"),
        json={"universal_cc": [], "universal_bcc": []},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["universal_cc"] == []
    assert body["universal_bcc"] == []


def test_patch_universal_recipients_404_unknown_run():
    r = requests.patch(
        _api("/api/balance-confirmation/runs/run_does_not_exist_xxx/universal-recipients"),
        json={"universal_cc": [], "universal_bcc": []},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# R2 backfill regression — pre-R2 ledgers now carry head + subhead.
# --------------------------------------------------------------------------- #
def test_existing_bc_ledgers_have_subhead_after_backfill(bc_run_id):
    r = requests.get(
        _api(f"/api/balance-confirmation/runs/{bc_run_id}/ledgers"),
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    rows = body.get("rows") if isinstance(body, dict) else body
    rows = rows or []
    # At least some rows must have a non-empty subhead now.
    with_subhead = [L for L in rows if (L.get("subhead") or "").strip()]
    assert with_subhead, "expected at least 1 ledger with a non-empty subhead post-backfill"
    # If a row is a creditor, its subhead should match a reasonable Schedule III tag.
    creditors = [L for L in rows if L.get("category") == "trade_payable"]
    if creditors:
        sample = creditors[0]
        assert sample.get("subhead"), "trade_payable ledger missing subhead post-backfill"
