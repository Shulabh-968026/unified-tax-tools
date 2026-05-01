"""Tests for the Financial Statement Designer normalizer + PDF renderer."""
import json
import os
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
             "cash_flow", "notes", "fixed_asset", "signatory", "counts"):
        assert k in doc


def test_company_period_and_cin(doc):
    assert doc["company"]["name"].upper().startswith("VELAV")
    assert doc["company"]["cin"] == "U17299TZ2022PTC037953"
    assert doc["period"]["fy_current"] == "2024-25"
    assert doc["period"]["current_end_long"] == "31st March 2025"
    assert doc["period"]["current_end_short"] == "31/03/2025"


def test_numbering_prefixes(doc):
    bs = doc["balance_sheet"]
    # First root should carry Roman 'I'
    assert bs[0]["prefix"] == "I"
    assert bs[0]["kind"] == "header"
    # Second-level should carry Arabic 1
    assert any(r["prefix"] == "1" and r["indent"] == 1 for r in bs)
    # Third-level should carry 'a.'
    assert any(r["prefix"] == "a." and r["indent"] == 2 for r in bs)
    # Must emit a synthesized 'TOTAL (I)' row
    assert any(r["kind"] == "total" and "TOTAL (I)" in r["label"] for r in bs)
    # And a subtotal 'Total(1)' after Shareholders' Funds closes
    assert any(r["kind"] == "subtotal" and r["label"] == "Total(1)" for r in bs)


def test_signatory_enriched_with_directors(doc):
    s = doc["signatory"]
    assert s["firm_name"] == "MSS and Co"
    assert s["firm_registration"] == "001893S"
    assert s["partner_name"] == "S. Dhananjayan"
    assert s["date"] == "10-07-2025"  # DD-MM-YYYY
    assert len(s["directors"]) == 2
    dirs = {d["din"] for d in s["directors"]}
    assert {"09463440", "06637132"}.issubset(dirs)
    assert s["cin"] == "U17299TZ2022PTC037953"


def test_inr_format():
    assert inr_rupee_paise(0) == "0.00"
    assert inr_rupee_paise(1234.5) == "1,234.50"
    assert inr_rupee_paise(12345678.99) == "1,23,45,678.99"
    assert inr_rupee_paise(-5000).startswith("(") and inr_rupee_paise(-5000).endswith(")")


def test_classic_pdf_has_bs_pl_cfs_on_separate_pages():
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw, client_record=CLIENT_REC)
    b = render_pdf(doc, template="classic")
    assert b.startswith(b"%PDF")
    out = Path("/tmp/_t_classic.pdf")
    out.write_bytes(b)
    try:
        import pdfplumber
        with pdfplumber.open(out) as p:
            # Must have >= 3 pages
            assert len(p.pages) >= 4
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
                assert "MEMBERSHIP NO.: 207277" in t
                assert "PLACE: TIRUPPUR" in t
                assert "DATE: 10-07-2025" in t
            # All pages should be portrait A4
            for pg in p.pages[:3]:
                assert pg.height > pg.width
    finally:
        out.unlink()


def test_boardroom_template_also_renders():
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw, client_record=CLIENT_REC)
    b = render_pdf(doc, template="boardroom")
    assert b.startswith(b"%PDF")
    assert len(b) > 10000


def test_notes_pages_have_company_header_and_note_titles():
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw, client_record=CLIENT_REC)
    b = render_pdf(doc, template="classic")
    out = Path("/tmp/_t_notes.pdf")
    out.write_bytes(b)
    try:
        import pdfplumber
        with pdfplumber.open(out) as p:
            # Notes start from page 4 onwards
            assert len(p.pages) >= 5
            notes_text = "\n".join((pg.extract_text() or "") for pg in p.pages[3:])
            # Spot-check a handful
            for needle in ("Note No : 1", "Note No : 11", "Note No : 16"):
                assert needle in notes_text, f"missing {needle}"
            # First notes page must still carry the company header
            p4_text = p.pages[3].extract_text() or ""
            assert "VELAV GARMENTS" in p4_text.upper()
            assert "NOTES TO FINANCIAL STATEMENTS" in p4_text.upper()
    finally:
        out.unlink()


def test_balance_sheet_balances(doc):
    # TOTAL (I) and TOTAL (II) should be equal
    bs = doc["balance_sheet"]
    totals = [r for r in bs if r["kind"] == "total"]
    assert len(totals) >= 2
    assert abs(totals[0]["current"] - totals[1]["current"]) < 1
    assert abs(totals[0]["previous"] - totals[1]["previous"]) < 1
