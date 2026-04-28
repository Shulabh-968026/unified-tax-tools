"""Phase D unit tests — invoice-level extractors + rapidfuzz matching engine.

Pure-function tests — no DB, no HTTP. Run with:
  cd /app/backend && python -m pytest tests/test_gst_recon_phase_d.py -v
"""
from __future__ import annotations
import json

from modules.gst_recon.aggregators import (
    extract_books_invoices,
    extract_gstr1_invoices,
    extract_gstr2b_invoices,
)
from modules.gst_recon.service import _norm_inv_no, _to_iso_date, match_invoices


def _bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ---------------- normalisers ----------------
def test_norm_inv_no_strips_non_alnum_and_uppercases():
    assert _norm_inv_no("INV/2024-25/0001") == "INV2024250001"
    assert _norm_inv_no("inv 0001") == "INV0001"
    assert _norm_inv_no(None) == ""
    assert _norm_inv_no("") == ""


def test_to_iso_date_handles_dd_mm_yyyy_and_iso():
    assert _to_iso_date("15-04-2024") == "2024-04-15"
    assert _to_iso_date("2024-04-15") == "2024-04-15"
    assert _to_iso_date("15/04/2024") == "2024-04-15"
    assert _to_iso_date(None) is None
    assert _to_iso_date("garbage") is None


# ---------------- extract_books_invoices ----------------
def test_books_extractor_only_emits_party_gstin_b2b():
    j = {"vouchers": [
        {"date": "2024-04-15", "voucherTypeName": "Sales", "voucherNumber": "S-1",
         "partyGSTIN": "33ABCDE1234F1Z5", "partyLedgerName": "Acme Ltd",
         "ledgerEntries": [
             {"ledger": "Acme Ltd",          "isPartyLedger": "Yes", "amount": -1180},
             {"ledger": "Sales Account",     "amount": 1000},
             {"ledger": "Output CGST @ 9%",  "amount": 90},
             {"ledger": "Output SGST @ 9%",  "amount": 90},
         ]},
        {"date": "2024-04-16", "voucherTypeName": "Sales", "voucherNumber": "S-2",
         "partyGSTIN": "",  # B2C — must be skipped
         "ledgerEntries": [{"ledger": "Sales", "amount": 100}]},
    ]}
    rules = {"revenue": {"Sales Account"},
             "output_tax": {"Output CGST @ 9%", "Output SGST @ 9%"},
             "input_tax": set()}
    out = extract_books_invoices(_bytes(j), rules)
    assert len(out) == 1
    rec = out[0]
    assert rec["period"] == "042024"
    assert rec["direction"] == "outward"
    assert rec["party_gstin"] == "33ABCDE1234F1Z5"
    assert rec["voucher_no"] == "S-1"
    assert rec["taxable"] == 1000.0
    assert rec["cgst"] == 90.0
    assert rec["sgst"] == 90.0
    assert rec["total"] == 1180.0
    assert rec["date"] == "2024-04-15"


def test_books_extractor_purchase_inward():
    j = {"vouchers": [{
        "date": "2024-05-10", "voucherTypeName": "Purchase", "voucherNumber": "P-1",
        "partyGSTIN": "33SUPPL1234F1Z5",
        "ledgerEntries": [
            {"ledger": "Purchase Account",   "amount": -500},
            {"ledger": "Input CGST @ 9%",    "amount": -45},
            {"ledger": "Input SGST @ 9%",    "amount": -45},
            {"ledger": "Suppl Vendor",       "isPartyLedger": "Yes", "amount": 590},
        ],
    }]}
    rules = {"revenue": set(), "output_tax": set(),
             "input_tax": {"Input CGST @ 9%", "Input SGST @ 9%"}}
    out = extract_books_invoices(_bytes(j), rules)
    assert len(out) == 1
    assert out[0]["direction"] == "inward"
    assert out[0]["taxable"] == 500.0   # 590 creditor − 90 tax
    assert out[0]["cgst"] == 45.0


# ---------------- extract_gstr1_invoices ----------------
def test_gstr1_extractor_walks_b2b_invoices():
    j = {"gstin": "33SELL1234F1Z5", "fp": "042024", "b2b": [
        {"ctin": "33ABCDE1234F1Z5", "trdnm": "Acme Ltd", "inv": [
            {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
             "itms": [{"itm_det": {"txval": 1000, "iamt": 0, "camt": 90, "samt": 90, "csamt": 0}}]},
            {"inum": "S-2", "idt": "20-04-2024", "val": 590,
             "itms": [{"itm_det": {"txval": 500, "iamt": 90, "camt": 0, "samt": 0, "csamt": 0}}]},
        ]},
    ]}
    out = extract_gstr1_invoices(_bytes(j), default_period="042024")
    assert len(out) == 2
    assert out[0]["party_gstin"] == "33ABCDE1234F1Z5"
    assert out[0]["invoice_no"] == "S-1"
    assert out[0]["total"] == 1180.0
    assert out[0]["direction"] == "outward"
    assert out[1]["igst"] == 90.0


# ---------------- extract_gstr2b_invoices ----------------
def test_gstr2b_extractor_walks_docdata_b2b():
    j = {"data": {"gstin": "33BUY1234F1Z5", "rtnprd": "042024", "docdata": {"b2b": [
        {"ctin": "33SUPPL1234F1Z5", "trdnm": "Suppl Vendor", "inv": [
            {"inum": "P-1", "dt": "10-05-2024", "val": 590, "txval": 500,
             "cgst": 45, "sgst": 45, "igst": 0, "cess": 0},
        ]},
    ]}}}
    out = extract_gstr2b_invoices(_bytes(j), default_period="052024")
    assert len(out) == 1
    rec = out[0]
    assert rec["party_gstin"] == "33SUPPL1234F1Z5"
    assert rec["direction"] == "inward"
    assert rec["taxable"] == 500.0
    assert rec["total"] == 590.0


# ---------------- match_invoices ----------------
def _book(no, gstin="33A", total=1180, taxable=1000, date="2024-04-15"):
    return {"voucher_no": no, "party_gstin": gstin, "total": total, "taxable": taxable,
            "date": date, "period": "042024", "direction": "outward",
            "igst": 0, "cgst": 90, "sgst": 90, "cess": 0}


def _portal(no, gstin="33A", total=1180, taxable=1000, date="15-04-2024"):
    return {"invoice_no": no, "party_gstin": gstin, "total": total, "taxable": taxable,
            "date": date, "period": "042024", "direction": "outward",
            "igst": 0, "cgst": 90, "sgst": 90, "cess": 0}


def test_match_exact():
    out = match_invoices([_book("S-1")], [_portal("S-1")])
    assert out["counts"]["matched"] == 1
    assert out["counts"]["missing_in_books"] == 0
    assert out["counts"]["missing_in_portal"] == 0


def test_match_value_mismatch():
    out = match_invoices([_book("S-1", total=1180)], [_portal("S-1", total=1500)])
    assert out["counts"]["value_mismatch"] == 1
    assert out["counts"]["matched"] == 0
    assert out["value_mismatch"][0]["value_diff"] == -320.0


def test_match_date_mismatch():
    out = match_invoices(
        [_book("S-1", date="2024-04-15")],
        [_portal("S-1", date="20-04-2024")],
    )
    assert out["counts"]["date_mismatch"] == 1


def test_match_missing_in_portal_when_books_only():
    out = match_invoices([_book("S-1")], [])
    assert out["counts"]["missing_in_portal"] == 1
    assert out["missing_in_portal"][0]["voucher_no"] == "S-1"


def test_match_missing_in_books_when_portal_only():
    out = match_invoices([], [_portal("S-1")])
    assert out["counts"]["missing_in_books"] == 1


def test_match_fuzzy_close_invoice_numbers():
    # Books "INV/0001" vs portal "INV0001" — non-alnum stripped → identical
    out = match_invoices(
        [_book("INV/0001")],
        [_portal("INV0001")],
    )
    assert out["counts"]["matched"] == 1


def test_match_fuzzy_typo_one_char():
    # Pass 1 fails (norm differs), Pass 2 fuzzy ratio ≥85 should match
    # 'INV2024S001' vs 'INV2024S00I'  — 1-char typo
    out = match_invoices(
        [_book("INV2024S001")],
        [_portal("INV2024S00I")],
    )
    assert out["counts"]["matched"] == 1
    pair = out["matched"][0]
    assert "fuzzy_score" in pair
    assert pair["fuzzy_score"] >= 85


def test_match_does_not_cross_gstin_boundary():
    """Same invoice number but different GSTINs must not match."""
    out = match_invoices(
        [_book("S-1", gstin="33A")],
        [_portal("S-1", gstin="33B")],
    )
    assert out["counts"]["matched"] == 0
    assert out["counts"]["missing_in_books"] == 1
    assert out["counts"]["missing_in_portal"] == 1


def test_match_value_tolerance_under_1_rupee_passes():
    out = match_invoices(
        [_book("S-1", total=1180.00)],
        [_portal("S-1", total=1180.50)],  # 50 paise diff < ₹1 tol
    )
    assert out["counts"]["matched"] == 1


def test_match_returns_no_internal_norm_keys():
    """_norm scratch field must be stripped from response."""
    out = match_invoices([_book("S-1")], [_portal("S-1")])
    pair = out["matched"][0]
    assert "_norm" not in pair["books"]
    assert "_norm" not in pair["portal"]


# ---------------- match_invoices: relaxed mode (Pass 3) -------------
def test_relaxed_matches_same_gstin_period_total_when_inv_no_differs():
    """Different bill numbers + dates, but same gstin+period+total → relaxed match."""
    b = _book("Books-145", gstin="33A", total=327.73, date="2024-12-31")
    p = _portal("3301122400701397", gstin="33A", total=327.73, date="31-12-2024")
    # Strict mode — different inv-no, no fuzz hit → no match
    strict = match_invoices([b], [p], relaxed=False)
    assert strict["counts"]["matched"] == 0
    assert strict["counts"]["missing_in_books"] == 1
    assert strict["counts"]["missing_in_portal"] == 1
    # Relaxed mode → should match via Pass 3
    relaxed = match_invoices([b], [p], relaxed=True)
    assert relaxed["counts"]["matched"] + relaxed["counts"]["date_mismatch"] + relaxed["counts"]["value_mismatch"] == 1
    assert relaxed["counts"]["missing_in_books"] == 0
    assert relaxed["counts"]["missing_in_portal"] == 0
    # Find the relaxed_match flag
    pair = (relaxed["matched"] + relaxed["value_mismatch"] + relaxed["date_mismatch"])[0]
    assert pair.get("relaxed_match") is True


def test_relaxed_does_not_cross_period_boundary():
    """Same gstin+total but different MMYYYY periods must NOT match in relaxed."""
    b = _book("S-1", total=1000)
    b["period"] = "042024"
    p = _portal("Diff-1", total=1000)
    p["period"] = "052024"
    out = match_invoices([b], [p], relaxed=True)
    assert out["counts"]["matched"] == 0
    assert out["counts"]["missing_in_books"] == 1
    assert out["counts"]["missing_in_portal"] == 1


def test_relaxed_picks_closest_date_when_multiple_candidates():
    """Two portal candidates with same total — should match the one with closest date."""
    b = _book("S-1", total=500, date="2024-04-15")
    p1 = _portal("PortalA", total=500, date="01-04-2024")  # 14 days off
    p2 = _portal("PortalB", total=500, date="14-04-2024")  # 1 day off
    out = match_invoices([b], [p1, p2], relaxed=True)
    assert out["counts"]["missing_in_portal"] == 0  # books matched
    assert out["counts"]["missing_in_books"] == 1   # one portal still unmatched
    # The matched portal must be PortalB (closer date)
    pair = (out["matched"] + out["date_mismatch"] + out["value_mismatch"])[0]
    assert pair["portal"]["invoice_no"] == "PortalB"
    # PortalA remains missing-in-books
    assert out["missing_in_books"][0]["invoice_no"] == "PortalA"


def test_relaxed_handles_user_screenshot_scenario():
    """Reproduces the specific bug from user's screenshot: same party, same period,
    same exact total but completely different bill numbers (Tally voucher # vs
    portal IRN-style ID)."""
    # User's data — May 2024, party 33AAACS8577K1ZW (Tata-AIG)
    books = _book("32", gstin="33AAACS8577K1ZW", total=11.80, date="2024-05-31")
    books["period"] = "052024"
    portal = _portal("T0524331W4309", gstin="33AAACS8577K1ZW", total=11.80, date="31-05-2024")
    portal["period"] = "052024"

    # Strict: should NOT match (bill numbers differ entirely, no fuzz hit)
    strict = match_invoices([books], [portal], relaxed=False)
    assert strict["counts"]["matched"] == 0
    assert strict["counts"]["missing_in_portal"] == 1
    assert strict["counts"]["missing_in_books"] == 1

    # Relaxed: SHOULD match via Pass 3
    relaxed = match_invoices([books], [portal], relaxed=True)
    total_matched = (relaxed["counts"]["matched"]
                    + relaxed["counts"]["value_mismatch"]
                    + relaxed["counts"]["date_mismatch"])
    assert total_matched == 1
    assert relaxed["counts"]["missing_in_books"] == 0
    assert relaxed["counts"]["missing_in_portal"] == 0
    pair = (relaxed["matched"] + relaxed["value_mismatch"] + relaxed["date_mismatch"])[0]
    assert pair.get("relaxed_match") is True
    assert pair["books"]["voucher_no"] == "32"
    assert pair["portal"]["invoice_no"] == "T0524331W4309"
