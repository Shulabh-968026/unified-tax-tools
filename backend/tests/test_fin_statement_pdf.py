"""Tests for the Financial Statement Designer normalizer + PDF renderer."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from modules.fin_statement.normalizer import normalize_final_statement  # noqa: E402
from modules.fin_statement.pdf_renderer import render_pdf, inr_rupee_paise  # noqa: E402

SAMPLE_JSON = Path("/app/sample_data/v904_fs.json")
CLIENT_REC = {"cin": "U17299TZ2022PTC037953"}


@pytest.fixture(scope="module")
def raw():
    assert SAMPLE_JSON.exists()
    return json.loads(SAMPLE_JSON.read_text())


@pytest.fixture(scope="module")
def doc(raw):
    return normalize_final_statement(raw, client_record=CLIENT_REC)


def test_normalizer_shape(doc):
    for k in ("company", "period", "balance_sheet", "profit_loss",
             "cash_flow", "notes", "details", "ageing", "fixed_asset",
             "signatory", "counts"):
        assert k in doc


def test_company_period_and_cin(doc):
    assert doc["company"]["name"].upper().startswith("VELAV")
    assert doc["company"]["cin"] == "U17299TZ2022PTC037953"
    assert doc["period"]["fy_current"] == "2024-25"


def test_numbering_prefixes(doc):
    bs = doc["balance_sheet"]
    assert bs[0]["prefix"] == "I"
    assert any(r["prefix"] == "1" and r["indent"] == 1 for r in bs)
    assert any(r["prefix"] == "a." and r["indent"] == 2 for r in bs)
    assert any(r["kind"] == "total" and "TOTAL (I)" in r["label"] for r in bs)
    assert any(r["kind"] == "subtotal" and r["label"] == "Total(1)" for r in bs)


def test_signatory_with_directors(doc):
    s = doc["signatory"]
    assert s["firm_name"] == "MSS and Co"
    assert s["partner_name"] == "S. Dhananjayan"
    assert s["date"] == "10-07-2025"
    assert len(s["directors"]) == 2
    assert {d["din"] for d in s["directors"]} == {"09463440", "06637132"}
    assert s["cin"] == "U17299TZ2022PTC037953"


def test_inr_format():
    assert inr_rupee_paise(0) == "0.00"
    assert inr_rupee_paise(1234.5) == "1,234.50"
    assert inr_rupee_paise(12345678.99) == "1,23,45,678.99"
    assert inr_rupee_paise(-5000).startswith("(")


def test_notes_titles_resolved_from_bs_tree(doc):
    """Note 1 must resolve to "Share Capital" (BS leaf) not the wrapper
    "Shareholders' Funds". Note 8 must be PPE (BS leaf) not Depreciation
    (P&L leaf, same note number)."""
    notes_by_id = {n["note"]: n for n in doc["notes"]}
    assert notes_by_id[1]["title"] == "Share Capital"
    # Share Capital total must match the BS leaf, not the parent grouping
    assert abs(notes_by_id[1]["current"] - 169204730.54) < 1
    # Note 8 = PPE (not "Depreciation and Amortisation Expense")
    assert "Property, Plant and Equipment" in notes_by_id[8]["title"]
    assert abs(notes_by_id[8]["current"] - 46241795.83) < 1


def test_note_subitems_with_letter_prefixes(doc):
    notes_by_id = {n["note"]: n for n in doc["notes"]}
    # Note 3 → a. Term Loans / b. Unsecured Loans
    n3 = notes_by_id[3]
    assert n3["subitems"][0]["prefix"] == "a."
    assert "Term Loans" in n3["subitems"][0]["label"]
    assert n3["subitems"][1]["prefix"] == "b."
    # Note 11 → 4 sub-items (Inventories breakdown)
    assert len(notes_by_id[11]["subitems"]) == 4


def test_no_subitem_fallback_for_note_8(doc):
    """Note 8 must have NO sub-items — the renderer attaches the PPE
    matrix block instead."""
    notes_by_id = {n["note"]: n for n in doc["notes"]}
    assert notes_by_id[8]["subitems"] == []


def test_details_section_built(doc):
    """Details should be lettered N (a) / N (b) etc., grouped by note."""
    assert len(doc["details"]) > 50
    refs = [d["ref"] for d in doc["details"]]
    assert "1 (a)" in refs
    assert "23 (a)" in refs


def test_ageing_normalized(doc):
    """Trade payables / receivables ageing must be available per FY."""
    ag = doc["ageing"]
    assert "trade payables" in ag
    assert "trade receivables" in ag
    tp_2024 = list(ag["trade payables"].values())[0]
    assert "rows" in tp_2024
    assert len(tp_2024["rows"]) > 0


def test_classic_pdf_structure_matches_reference():
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw, client_record=CLIENT_REC)
    b = render_pdf(doc, template="classic")
    assert b.startswith(b"%PDF")
    out = Path("/tmp/_t_classic.pdf")
    out.write_bytes(b)
    try:
        import pdfplumber
        with pdfplumber.open(out) as p:
            assert len(p.pages) >= 5
            t1 = (p.pages[0].extract_text() or "").upper()
            t2 = (p.pages[1].extract_text() or "").upper()
            t3 = (p.pages[2].extract_text() or "").upper()
            assert "BALANCE SHEET AS AT 31ST MARCH 2025" in t1
            assert "EQUITY AND LIABILITIES" in t1
            assert "TOTAL (I)" in t1
            assert "STATEMENT OF PROFIT AND LOSS" in t2
            assert "CASH FLOW STATEMENT" in t3
            # All 3 statement pages must carry the full signatory footer
            for t in (t1, t2, t3):
                assert "MSS AND CO" in t
                assert "FIRM REGN. NO.: 001893S" in t
                assert "DIN: 09463440" in t
                assert "DIN: 06637132" in t
                assert "PLACE: TIRUPPUR" in t
                assert "DATE: 10-07-2025" in t
            # Notes pages
            notes_text = "\n".join((pg.extract_text() or "") for pg in p.pages[3:]).upper()
            for needle in ("NOTE NO : 1 SHARE CAPITAL",
                           "NOTE NO : 8 PROPERTY, PLANT AND EQUIPMENT",
                           "NOTE NO : 11 INVENTORIES"):
                assert needle in notes_text, f"missing {needle!r}"
            # Details section (lettered N (a) / N (b))
            details_text = notes_text  # In the same range
            assert "DETAILS TO FINANCIAL STATEMENTS" in details_text
            assert "1 (A) SHARE CAPITAL" in details_text
            assert "23 (A)" in details_text
    finally:
        out.unlink()


def test_boardroom_template_renders():
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw, client_record=CLIENT_REC)
    b = render_pdf(doc, template="boardroom")
    assert b.startswith(b"%PDF")
    assert len(b) > 30000


def test_balance_sheet_balances(doc):
    bs = doc["balance_sheet"]
    totals = [r for r in bs if r["kind"] == "total"]
    assert len(totals) >= 2
    assert abs(totals[0]["current"] - totals[1]["current"]) < 1
    assert abs(totals[0]["previous"] - totals[1]["previous"]) < 1
