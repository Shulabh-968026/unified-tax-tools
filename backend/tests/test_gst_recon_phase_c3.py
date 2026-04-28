"""Phase C.3 unit tests for GST Recon aggregators + 12-month summary builder.

Pure-function tests — no DB, no HTTP. Run with:
  cd /app/backend && python -m pytest tests/test_gst_recon_phase_c3.py -v
"""
from __future__ import annotations
import json

from modules.gst_recon.aggregators import aggregate_books, aggregate_gstr1, aggregate_gstr2b
from modules.gst_recon.service import build_month_grid, build_summary


def _bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ---------------- aggregate_gstr1 ----------------
def test_gstr1_b2b_sum():
    j = {"gstin": "33A", "fp": "042024", "b2b": [{"ctin": "33X", "inv": [
        {"inum": "I1", "itms": [{"itm_det": {"txval": 1000, "iamt": 0, "camt": 90, "samt": 90, "csamt": 0}}]},
        {"inum": "I2", "itms": [{"itm_det": {"txval": 500, "iamt": 90, "camt": 0, "samt": 0, "csamt": 5}}]},
    ]}]}
    out = aggregate_gstr1(_bytes(j))
    assert out == {"taxable": 1500.0, "igst": 90.0, "cgst": 90.0, "sgst": 90.0, "cess": 5.0}


def test_gstr1_cdnr_credit_subtracts():
    j = {"cdnr": [{"nt": [
        {"ntty": "C", "itms": [{"itm_det": {"txval": 200, "camt": 18, "samt": 18}}]},
        {"ntty": "D", "itms": [{"itm_det": {"txval": 100, "camt": 9, "samt": 9}}]},
    ]}]}
    out = aggregate_gstr1(_bytes(j))
    assert out == {"taxable": -100.0, "igst": 0.0, "cgst": -9.0, "sgst": -9.0, "cess": 0.0}


def test_gstr1_invalid_json_returns_empty():
    assert aggregate_gstr1(b"not json") == {}


# ---------------- aggregate_gstr2b ----------------
def test_gstr2b_itcsumm_path():
    j = {"data": {"itcsumm": {"itcavl": {"nonrevsup": {
        "b2b":  {"iamt": 5000, "camt": 2500, "samt": 2500, "csamt": 0},
        "impg": {"iamt": 1000, "camt": 0,    "samt": 0,    "csamt": 100},
    }}}}}
    out = aggregate_gstr2b(_bytes(j))
    assert out == {"taxable": 0.0, "igst": 6000.0, "cgst": 2500.0, "sgst": 2500.0, "cess": 100.0}


def test_gstr2b_fallback_invoices_when_no_itcsumm():
    j = {"data": {"docdata": {"b2b": [{"inv": [
        {"txval": 1000, "igst": 0, "cgst": 90, "sgst": 90, "cess": 0},
        {"txval": 500,  "igst": 90, "cgst": 0, "sgst": 0,  "cess": 5},
    ]}]}}}
    out = aggregate_gstr2b(_bytes(j))
    assert out == {"taxable": 1500.0, "igst": 90.0, "cgst": 90.0, "sgst": 90.0, "cess": 5.0}


# ---------------- aggregate_books ----------------
def test_books_outward_excludes_party_ledger():
    """Ensure customer/vendor ledger is NOT double-counted as taxable value."""
    j = {"vouchers": [{
        "date": "2024-04-15", "voucherTypeName": "Sales",
        "ledgerEntries": [
            {"ledgerName": "ABC Customer Ltd", "amount": -1180},
            {"ledgerName": "Sales Account",     "amount": 1000},
            {"ledgerName": "Output CGST @ 9%",  "amount": 90},
            {"ledgerName": "Output SGST @ 9%",  "amount": 90},
        ],
    }]}
    out = aggregate_books(_bytes(j))
    assert "042024" in out
    apr = out["042024"]
    assert apr["out_taxable"] == 1000.0  # NOT 2180 — party ledger excluded
    assert apr["out_cgst"] == 90.0
    assert apr["out_sgst"] == 90.0
    assert apr["in_taxable"] == 0.0


def test_books_groups_by_month():
    j = {"vouchers": [
        {"date": "2024-04-15", "voucherTypeName": "Sales",
         "ledgerEntries": [{"ledgerName": "Sales", "amount": 100}]},
        {"date": "2024-05-10", "voucherTypeName": "Purchase",
         "ledgerEntries": [{"ledgerName": "Purchase", "amount": -50}]},
        {"date": "2025-03-31", "voucherTypeName": "Sales",
         "ledgerEntries": [{"ledgerName": "Sales", "amount": 200}]},
    ]}
    out = aggregate_books(_bytes(j))
    assert out["042024"]["out_taxable"] == 100.0
    assert out["052024"]["in_taxable"] == 50.0
    assert out["032025"]["out_taxable"] == 200.0


# ---------------- build_summary ----------------
def _doc_with_one_month():
    months = build_month_grid("2024-25", [])
    return {
        "fy": "2024-25",
        "months": months,
        "files": [
            {"bucket": "books", "books_per_month": {
                "042024": {"out_taxable": 1000000, "out_igst": 50000, "out_cgst": 25000, "out_sgst": 25000, "out_cess": 0,
                           "in_taxable": 600000, "in_igst": 30000, "in_cgst": 15000, "in_sgst": 15000, "in_cess": 0}}},
            {"bucket": "gstr1", "period": "042024",
             "r1_outward": {"taxable": 1000000, "igst": 50000, "cgst": 25000, "sgst": 25000, "cess": 0}},
            {"bucket": "gstr2b", "period": "042024",
             "r2b_itc": {"igst": 30000, "cgst": 15000, "sgst": 15000, "cess": 0}},
            {"bucket": "gstr3b", "period": "042024",
             "table_3_1": {"a": {"taxable_value": 999000, "igst": 49950, "cgst": 24975, "sgst": 24975, "cess": 0}},
             "table_4": {"c_net_itc": {"igst": 29500, "cgst": 14750, "sgst": 14750, "cess": 0}}},
        ],
    }


def test_summary_returns_12_rows_in_fy_order():
    s = build_summary(_doc_with_one_month())
    assert len(s["rows"]) == 12
    assert s["rows"][0]["month_label"] == "Apr 2024"
    assert s["rows"][-1]["month_label"] == "Mar 2025"
    assert s["fy"] == "2024-25"


def test_summary_apr_aggregates_correctly():
    s = build_summary(_doc_with_one_month())
    apr = s["rows"][0]
    assert apr["books_outward_taxable"] == 1000000.0
    assert apr["r1_outward_taxable"] == 1000000.0
    assert apr["r3b_outward_taxable"] == 999000.0
    assert apr["books_itc_total"] == 60000.0    # 30k+15k+15k
    assert apr["r2b_itc_total"] == 60000.0
    assert apr["r3b_itc_total"] == 59000.0       # 29.5k+14.75k+14.75k


def test_summary_variance_columns():
    s = build_summary(_doc_with_one_month())
    apr = s["rows"][0]
    assert apr["var_r1_vs_r3b_outward"] == 1000.0  # 10L - 9.99L
    assert apr["var_r2b_vs_r3b_itc"] == 1000.0      # 60k - 59k
    assert apr["var_books_vs_r1_outward"] == 0.0
    assert apr["var_books_vs_r2b_itc"] == 0.0


def test_summary_annual_totals():
    s = build_summary(_doc_with_one_month())
    t = s["totals"]
    assert t["r1_outward_taxable"] == 1000000.0
    assert t["r3b_outward_taxable"] == 999000.0
    assert t["var_r1_vs_r3b_outward"] == 1000.0


def test_summary_handles_empty_run():
    months = build_month_grid("2024-25", [])
    s = build_summary({"fy": "2024-25", "months": months, "files": []})
    assert len(s["rows"]) == 12
    # All zeros
    for r in s["rows"]:
        assert r["r1_outward_taxable"] == 0.0
        assert r["var_r1_vs_r3b_outward"] == 0.0
