"""
Fixed Assets — Summary MIS endpoint.

Validates GET /runs/{rid}/summary returns the full payload shape with
populated KPIs, counts, audit flags, blocks, top additions, top suppliers,
adjustment usage, quarterly distribution, and OCR coverage.
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


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.cookies.set("session_token", TOKEN)
    return s


@pytest.fixture(scope="module")
def summary(session):
    r = session.get(f"{BASE_URL}/api/fixed-assets/runs/{RID}/summary", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_payload_top_level_shape(summary):
    for k in ("run_id", "client_name", "fy_label", "fy_start", "fy_end",
             "kpis", "validation", "counts", "audit_flags",
             "open_flag_count", "blocks", "top_additions", "top_suppliers",
             "adjustments", "quarterly", "ocr"):
        assert k in summary, f"missing key: {k}"


def test_kpis_match_compute(session, summary):
    """The 6 KPI numbers must match the /compute totals."""
    r = session.post(f"{BASE_URL}/api/fixed-assets/runs/{RID}/compute", timeout=60)
    totals = r.json()["totals"]
    for k in ("opening_wdv", "adds_full", "adds_half", "deletions",
             "depreciation", "closing_wdv"):
        assert round(summary["kpis"][k], 2) == round(float(totals[k]), 2), k


def test_counts_match_db(summary):
    c = summary["counts"]
    # The demo run has 95 active capitalised additions + 6 merged children.
    assert c["additions"]["count"] >= 80
    assert c["additions"]["value"] > 0
    # Coverage % is between 0 and 100
    assert 0 <= c["coverage_pct"] <= 100
    # Discounts summing positive
    assert c["discounts"]["count"] >= 1
    assert c["discounts"]["value"] >= 0
    # bills_attached + bills_unattached = additions count
    assert c["bills_attached"]["count"] + c["bills_unattached"]["count"] \
           == c["additions"]["count"]


def test_audit_flags_shape(summary):
    f = summary["audit_flags"]
    for key in ("missing_ptu", "ptu_after_fy_end", "missing_party",
                "unreviewed", "discount_pending", "zero_or_negative_cost"):
        assert key in f
        assert "count" in f[key] and "value" in f[key]
        assert f[key]["count"] >= 0
    # open_flag_count should equal the number of flags with count > 0
    open_n = sum(1 for v in f.values() if v["count"] > 0)
    assert summary["open_flag_count"] == open_n


def test_blocks_have_rate_and_count(summary):
    blocks = summary["blocks"]
    assert len(blocks) >= 4  # demo run has ≥4 active blocks
    # Sorted by descending rate
    rates = [b["rate"] for b in blocks]
    assert rates == sorted(rates, reverse=True)
    for b in blocks:
        assert b["additions_count"] >= 0
        assert b["rate"] > 0


def test_top_additions_descending_by_value(summary):
    rows = summary["top_additions"]
    assert len(rows) <= 10
    if len(rows) >= 2:
        assert rows[0]["capitalised_cost"] >= rows[1]["capitalised_cost"]
    # Each row carries the audit-essentials
    for r in rows:
        for k in ("addition_id", "description", "party_name", "block_label",
                 "put_to_use_date", "capitalised_cost", "is_more_than_180"):
            assert k in r


def test_top_suppliers_descending_by_value(summary):
    rows = summary["top_suppliers"]
    assert len(rows) <= 5
    if len(rows) >= 2:
        assert rows[0]["value"] >= rows[1]["value"]


def test_adjustments_carry_each_column(summary):
    keys = {a["key"] for a in summary["adjustments"]}
    assert keys == {"other_expenses", "itc_reversed",
                    "interest_capitalized", "forex_fluctuations",
                    "discount_credits"}
    # Discounts/Credits must flag as cost-reducing
    disc = next(a for a in summary["adjustments"] if a["key"] == "discount_credits")
    assert disc["reduces_cost"] is True


def test_quarterly_buckets_sum_to_additions_count(summary):
    """Sum of quarterly counts must equal the active-additions count."""
    total = sum(q["count"] for q in summary["quarterly"])
    assert total == summary["counts"]["additions"]["count"]


def test_ocr_coverage_consistency(summary):
    o = summary["ocr"]
    assert o["chunks_applied"] <= o["chunks_total"]
    assert o["chunks_remaining"] == max(0, o["chunks_total"] - o["chunks_applied"])
    assert o["uploads_pending"] <= o["uploads_total"]
