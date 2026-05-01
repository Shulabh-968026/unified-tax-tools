"""
Fixed Assets — Discount/Credit row merge into a parent asset.

Validates:
  * POST /runs/{rid}/additions/discount-{cid}/link routes the credit's
    magnitude into the parent's chosen adjustment column (default
    discount_credits).
  * Idempotent re-link does NOT double-count.
  * Switching linked_as moves the value cleanly between columns.
  * Unlink restores the parent's column to 0 and clears credit's linkage.
  * Compute totals are invariant: linked (rolled into parent) === unlinked
    (surfaced as negative pseudo-row). I.e. no double-subtract.
  * Discount row resurfaces with parent_addition_id set so the UI can
    render it as "Merged".
  * Discount row's parent must belong to the same IT block.
  * Reclassifying a discount → sale/pending auto-clears the linkage.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://unified-tax-tools.preview.emergentagent.com",
).rstrip("/")
TOKEN = "qa_test_session_token_20260430_dev"
RID = "0e4cc62f-52f9-4668-b598-f60bd0c52803"

# Pre-seeded discount + parent ids in the 15% Block of the demo run
DAID = "discount-2de5895e-1f53-439f-bbb1-07fed1cbeff8"  # amt 7582
PAID = "39447e67-c369-4edd-aa22-7067659240db"             # Haier Split A/C
BLOCK = "15% Block – Plant & Machinery"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.cookies.set("session_token", TOKEN)
    return s


def _addition(session, addition_id):
    r = session.get(f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions",
                    params={"block": BLOCK}, timeout=30)
    r.raise_for_status()
    for row in r.json().get("rows", []):
        if row.get("addition_id") == addition_id:
            return row
    return None


def _reset_parent(session):
    """Reset the parent's adjustment columns + ensure no stale link."""
    session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/unlink",
        timeout=30,
    )
    session.patch(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{PAID}",
        json={"discount_credits": 0.0, "other_expenses": 0.0},
        timeout=30,
    )


@pytest.fixture(autouse=True)
def _reset(session):
    _reset_parent(session)
    yield
    _reset_parent(session)


def _link(session, linked_as="discount_credits"):
    return session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/link",
        json={"parent_addition_id": PAID, "linked_as": linked_as},
        timeout=30,
    )


def test_link_routes_magnitude_into_parent_column(session):
    r = _link(session)
    assert r.status_code == 200, r.text
    p = _addition(session, PAID)
    assert p is not None
    assert p["discount_credits"] == 7582.0
    d = _addition(session, DAID)
    assert d is not None
    assert d["parent_addition_id"] == PAID
    assert d["linked_as"] == "discount_credits"


def test_relink_is_idempotent(session):
    _link(session).raise_for_status()
    _link(session).raise_for_status()
    p = _addition(session, PAID)
    assert p["discount_credits"] == 7582.0  # NOT 15164


def test_switch_linked_as_moves_value(session):
    _link(session, "discount_credits").raise_for_status()
    _link(session, "other_expenses").raise_for_status()
    p = _addition(session, PAID)
    assert p["discount_credits"] == 0.0
    assert p["other_expenses"] == 7582.0


def test_unlink_clears_parent_and_child(session):
    _link(session).raise_for_status()
    r = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/unlink",
        timeout=30,
    )
    assert r.status_code == 200
    p = _addition(session, PAID)
    d = _addition(session, DAID)
    assert p["discount_credits"] == 0.0
    assert d["parent_addition_id"] == ""
    assert d["linked_as"] == ""


def test_compute_invariant_under_link(session):
    base = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/compute", timeout=60,
    ).json()
    base_15 = next(b for b in base["rows"] if b["block_label"] == BLOCK)

    _link(session).raise_for_status()
    after = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/compute", timeout=60,
    ).json()
    after_15 = next(b for b in after["rows"] if b["block_label"] == BLOCK)

    # Depreciation + closing must be identical (no double-subtract)
    assert round(base_15["depreciation"], 2) == round(after_15["depreciation"], 2)
    assert round(base_15["closing_wdv"], 2) == round(after_15["closing_wdv"], 2)


def test_link_to_self_rejected(session):
    r = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/link",
        json={"parent_addition_id": DAID, "linked_as": "discount_credits"},
        timeout=30,
    )
    assert r.status_code == 400


def test_link_unknown_parent_404(session):
    r = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/link",
        json={
            "parent_addition_id": "00000000-0000-0000-0000-000000000000",
            "linked_as": "discount_credits",
        },
        timeout=30,
    )
    assert r.status_code == 404


def test_link_invalid_column_rejected(session):
    r = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/additions/{DAID}/link",
        json={"parent_addition_id": PAID, "linked_as": "bogus_column"},
        timeout=30,
    )
    assert r.status_code == 400


def test_reclassify_discount_to_sale_unlinks(session):
    """Reclassifying out of 'discount' must auto-clear any prior linkage."""
    cid = DAID.split("-", 1)[1]
    _link(session).raise_for_status()
    p_before = _addition(session, PAID)
    assert p_before["discount_credits"] == 7582.0

    # Flip credit to sale
    r = session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/credits/{cid}/classify",
        json={"classification": "sale", "sale_value": 7582.0,
              "buyer_name": "Test"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    p_after = _addition(session, PAID)
    assert p_after["discount_credits"] == 0.0  # auto-decremented

    # Restore back to discount for downstream tests
    session.post(
        f"{BASE_URL}/api/fixed-assets/runs/{RID}/credits/{cid}/classify",
        json={"classification": "discount"},
        timeout=30,
    )
