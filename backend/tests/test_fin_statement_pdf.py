"""Tests for the Financial Statement Designer normalizer + PDF renderer."""
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure backend on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from modules.fin_statement.normalizer import normalize_final_statement  # noqa: E402
from modules.fin_statement.pdf_renderer import render_pdf  # noqa: E402

SAMPLE_JSON = Path("/app/sample_data/v904_fs.json")


@pytest.fixture(scope="module")
def raw():
    assert SAMPLE_JSON.exists(), f"missing sample {SAMPLE_JSON}"
    return json.loads(SAMPLE_JSON.read_text())


@pytest.fixture(scope="module")
def doc(raw):
    return normalize_final_statement(raw)


def test_normalizer_returns_expected_shape(doc):
    for k in ("company", "period", "balance_sheet", "profit_loss",
             "cash_flow", "notes", "fixed_asset", "signatory", "counts"):
        assert k in doc, f"missing key {k}"


def test_company_and_period(doc):
    assert doc["company"]["name"].upper().startswith("VELAV")
    assert doc["period"]["fy_current"] == "2024-25"
    assert doc["period"]["fy_previous"] == "2023-24"


def test_balance_sheet_rows_and_totals(doc):
    bs = doc["balance_sheet"]
    # Must have at least the root "Equity and Liabilities" and "Assets"
    roots = [r for r in bs if r.get("indent") == 0]
    assert len(roots) >= 2
    # Totals of the two roots should equal each other (BS must balance)
    el = next(r for r in roots if "Equity" in r["label"] or "Liab" in r["label"])
    assets = next(r for r in roots if r["label"].strip().lower() == "assets")
    assert abs(el["current"] - assets["current"]) < 1


def test_cash_flow_has_operating_investing_financing(doc):
    labels = [r["label"].upper() for r in doc["cash_flow"]]
    text = " | ".join(labels)
    assert "OPERATING" in text
    assert "INVESTING" in text
    assert "FINANCIAL" in text or "FINANCING" in text


def test_notes_carry_detail_rows(doc):
    # Note 11 (Inventories) must have breakdown rows
    n11 = next((n for n in doc["notes"] if n["note"] == 11), None)
    assert n11 is not None
    assert n11["title"].lower().startswith("inventor")
    assert len(n11["details"]) > 0 or len(n11["children"]) > 0


def test_signatory_block(doc):
    s = doc["signatory"]
    assert s["firm_name"]
    assert s["place"]


def test_render_classic_pdf(doc):
    b = render_pdf(doc, template="classic")
    assert b.startswith(b"%PDF")
    assert len(b) > 5000


def test_render_boardroom_pdf(doc):
    b = render_pdf(doc, template="boardroom")
    assert b.startswith(b"%PDF")
    assert len(b) > 5000


def test_page1_is_landscape_and_contains_all_three_statements():
    """Extract text from page 1 to confirm BS + P&L + CFS are all present."""
    try:
        import pdfplumber
    except ImportError:
        pytest.skip("pdfplumber not installed")
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw)
    b = render_pdf(doc, template="classic")
    out = Path("/tmp/_fs_test.pdf")
    out.write_bytes(b)
    with pdfplumber.open(out) as p:
        pg1 = p.pages[0]
        # Landscape A4 is 842x595
        assert pg1.width > pg1.height, "page 1 must be landscape"
        txt = (pg1.extract_text() or "").upper()
        assert "BALANCE SHEET" in txt
        assert "PROFIT" in txt or "P&L" in txt
        assert "CASH FLOW" in txt
    os.unlink(out)


def test_notes_paginate_cleanly_after_page1():
    try:
        import pdfplumber
    except ImportError:
        pytest.skip("pdfplumber not installed")
    raw = json.loads(SAMPLE_JSON.read_text())
    doc = normalize_final_statement(raw)
    b = render_pdf(doc, template="boardroom")
    out = Path("/tmp/_fs_test2.pdf")
    out.write_bytes(b)
    with pdfplumber.open(out) as p:
        # Must have page 1 (landscape) + at least 1 notes page (portrait)
        assert len(p.pages) >= 2
        # Page 2 onwards must be portrait
        assert p.pages[1].height > p.pages[1].width
        text_all = "\n".join((pg.extract_text() or "") for pg in p.pages[1:])
        # Spot-check a handful of notes
        assert "Note 1:" in text_all
        assert "Note 11:" in text_all
    os.unlink(out)
