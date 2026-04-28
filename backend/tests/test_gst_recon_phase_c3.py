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


def test_gstr2b_camelcase_itcSumm_itcAvl_nonRevSup():
    """OLD GSTN format (pre-Aug 2024) used camelCase keys. Must still parse."""
    j = {"data": {"gstin": "33X", "rtnPrd": "042024",
        "itcSumm": {"itcAvl": {"nonRevSup": {
            "b2b":  {"iamt": 5000, "camt": 2500, "samt": 2500, "csamt": 0},
            "impg": {"iamt": 1000, "camt": 0,    "samt": 0,    "csamt": 0},
        }}}}}
    out = aggregate_gstr2b(_bytes(j))
    assert out == {"taxable": 0.0, "igst": 6000.0, "cgst": 2500.0, "sgst": 2500.0, "cess": 0.0}


def test_gstr2b_itcavl_directly_no_nonrevsup_wrapper():
    """Some export tools omit the nonrevsup wrapper and put b2b/impg directly under itcavl."""
    j = {"data": {"itcsumm": {"itcavl": {
        "b2b": {"iamt": 7000, "camt": 3500, "samt": 3500, "csamt": 50},
    }}}}
    out = aggregate_gstr2b(_bytes(j))
    assert out == {"taxable": 0.0, "igst": 7000.0, "cgst": 3500.0, "sgst": 3500.0, "cess": 50.0}


def test_gstr2b_real_user_format_igst_keys_with_totals_at_nonrevsup_level():
    """User's actual GSTR-2B JSON (Apr 2024) — uses igst/cgst/sgst/cess keys
    (not iamt/camt/samt/csamt), AND the totals sit at nonrevsup level alongside
    the b2b sub-dict. Parser must read the parent totals and not double-count
    by also summing the b2b child."""
    j = {"data": {"gstin": "33X", "rtnprd": "042024",
        "itcsumm": {"itcavl": {"nonrevsup": {
            "sgst": 15776.96, "cgst": 15776.96, "igst": 0, "cess": 0,
            "b2b": {"sgst": 15776.96, "txval": 581347.24,
                    "cgst": 15776.96, "cess": 0, "igst": 0},
        }}}}}
    out = aggregate_gstr2b(_bytes(j))
    # Must match parent totals exactly — NOT 2x because of double-summing
    assert out == {"taxable": 0.0, "igst": 0.0, "cgst": 15776.96, "sgst": 15776.96, "cess": 0.0}


def test_gstr2b_invoice_extractor_reads_items_array():
    """Real 2B invoices put tax breakdown inside items[] array, NOT at invoice level."""
    j = {"data": {"rtnprd": "042024", "docdata": {"b2b": [{
        "ctin": "33SUPPL", "trdnm": "ARUN PACKS",
        "inv": [{"inum": "11", "dt": "30-04-2024", "val": 21169.2,
            "items": [{"sgst": 1614.6, "rt": 18, "txval": 17940, "cgst": 1614.6, "cess": 0, "igst": 0}],
        }],
    }]}}}
    from modules.gst_recon.aggregators import extract_gstr2b_invoices
    invs = extract_gstr2b_invoices(_bytes(j), "042024")
    assert len(invs) == 1
    inv = invs[0]
    assert inv["taxable"] == 17940.0
    assert inv["cgst"] == 1614.6
    assert inv["sgst"] == 1614.6
    assert inv["igst"] == 0.0
    assert inv["invoice_no"] == "11"
    assert inv["party_gstin"] == "33SUPPL"


# ---------------- aggregate_books ----------------
def test_books_outward_excludes_party_ledger():
    """Ensure customer/vendor ledger is NOT double-counted as taxable value."""
    j = {"vouchers": [{
        "date": "2024-04-15", "voucherTypeName": "Sales",
        "ledgerEntries": [
            {"ledger": "ABC Customer Ltd",   "isPartyLedger": "Yes", "amount": -1180},
            {"ledger": "Sales Account",      "amount": 1000},
            {"ledger": "Output CGST @ 9%",   "amount": 90},
            {"ledger": "Output SGST @ 9%",   "amount": 90},
        ],
    }]}
    rules = {"revenue": {"Sales Account"},
             "output_tax": {"Output CGST @ 9%", "Output SGST @ 9%"},
             "input_tax": set()}
    out = aggregate_books(_bytes(j), rules)
    assert "042024" in out
    apr = out["042024"]
    assert apr["out_taxable"] == 1000.0  # NOT 2180 — party ledger excluded
    assert apr["out_cgst"] == 90.0
    assert apr["out_sgst"] == 90.0
    assert apr["in_taxable"] == 0.0


def test_books_groups_by_month():
    j = {"vouchers": [
        {"date": "2024-04-15", "voucherTypeName": "Sales",
         "ledgerEntries": [{"ledger": "Sales", "amount": 100}]},
        {"date": "2024-05-10", "voucherTypeName": "Purchase",
         "ledgerEntries": [
             {"ledger": "Vendor", "isPartyLedger": "Yes", "amount": 50},
             {"ledger": "Input CGST @ 9%", "amount": -4.5},
             {"ledger": "Input SGST @ 9%", "amount": -4.5},
         ]},
        {"date": "2025-03-31", "voucherTypeName": "Sales",
         "ledgerEntries": [{"ledger": "Sales", "amount": 200}]},
    ]}
    rules = {"revenue": {"Sales"}, "output_tax": set(),
             "input_tax": {"Input CGST @ 9%", "Input SGST @ 9%"}}
    out = aggregate_books(_bytes(j), rules)
    assert out["042024"]["out_taxable"] == 100.0
    # Purchase voucher: party Cr = 50, tax = 9 (4.5+4.5), so taxable = 41
    assert out["052024"]["in_taxable"] == 41.0
    assert out["052024"]["in_cgst"] == 4.5
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
