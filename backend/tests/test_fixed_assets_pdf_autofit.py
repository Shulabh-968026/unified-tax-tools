"""Verify the IT Depreciation PDF block summary table auto-fits column
widths to the widest data, so numbers never wrap — even at ₹999 Cr."""
import io
import pdfplumber
import pytest

from modules.fixed_assets.pdf_export import (
    _autofit_summary_geometry, _block_summary_table, build_pdf,
)
from reportlab.lib.units import mm

AVAILABLE = 180 * mm


def _normal_rows():
    return [
        {"block_label": "40% Block – Computers",        "rate": 40,
         "opening_wdv": 485453.0, "adds_full": 268950.0, "adds_half": 162550.0,
         "deletions": 0.0, "depreciation": 334271.20, "closing_wdv": 582681.80},
        {"block_label": "15% Block – Plant & Machinery", "rate": 15,
         "opening_wdv": 25783559.0, "adds_full": 8989183.43, "adds_half": 13692454.49,
         "deletions": 0.0, "depreciation": 6242845.45, "closing_wdv": 42222351.47},
        {"block_label": "10% Block – Furniture",        "rate": 10,
         "opening_wdv": 2911192.0, "adds_full": 1705828.38, "adds_half": 1353380.51,
         "deletions": 0.0, "depreciation": 529371.06, "closing_wdv": 5441029.83},
    ]


def _normal_totals():
    return {"opening_wdv": 30115657.0, "adds_full": 11052809.81,
            "adds_half": 15208385.0, "deletions": 0.0,
            "depreciation": 7373996.11, "closing_wdv": 48952855.70}


def _huge_rows():
    """Rows with ₹999 Cr opening WDV / depreciation values."""
    return [
        {"block_label": "15% Block – Plant & Machinery (Mega Mfg Co Ltd)",
         "rate": 15, "opening_wdv": 9999999999.99,
         "adds_full": 1234567890.12, "adds_half": 987654321.10,
         "deletions": 5000000.0, "depreciation": 1666666666.66,
         "closing_wdv": 11555555555.55},
    ]


def _huge_totals():
    return {"opening_wdv": 9999999999.99, "adds_full": 1234567890.12,
            "adds_half": 987654321.10, "deletions": 5000000.0,
            "depreciation": 1666666666.66, "closing_wdv": 11555555555.55}


def test_autofit_returns_widths_summing_to_available():
    widths, fs = _autofit_summary_geometry(
        _normal_rows(), _normal_totals(), available_width=AVAILABLE,
    )
    assert len(widths) == 8
    # Slack is given to the Block column → totals to AVAILABLE
    assert abs(sum(widths) - AVAILABLE) < 0.5
    assert fs >= 6.5  # comfortable font size for normal numbers


def test_autofit_shrinks_font_for_999cr_numbers():
    widths, fs = _autofit_summary_geometry(
        _huge_rows(), _huge_totals(), available_width=AVAILABLE,
    )
    assert sum(widths) <= AVAILABLE + 0.5
    # Body font is reduced (or stays at floor) so 16-char ₹ fits
    assert 6.0 <= fs <= 7.5


def test_pdf_no_wrapping_in_summary_for_huge_numbers():
    """Render a single-block PDF with ₹999 Cr-class numbers and verify the
    extracted text shows the depreciation value on ONE line (no wrap)."""
    blob = build_pdf(
        client_name="Mega Mfg Co Ltd", fy_label="2024-25",
        fy_start="2024-04-01", fy_end="2025-03-31",
        run_name="Test", rows=_huge_rows(), totals=_huge_totals(),
        additions=[], block_meta={"15% Block – Plant & Machinery (Mega Mfg Co Ltd)": 15.0},
    )
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    # Each numeric value the user circled in the bug report must appear
    # on one line (no '\n' in the middle of "1,66,66,66,666.66")
    expected = "1,66,66,66,666.66"  # depreciation
    assert expected in text, f"depreciation value missing or wrapped: {expected!r}"
    # Critically, the value should not be split across two lines —
    # extract_text inserts \n at line breaks; check there is no
    # wrapping artifact like "1,66,66,66,666.6\n6"
    bad = expected[:-1] + "\n" + expected[-1]
    assert bad not in text, "depreciation number wrapped onto two lines"


def test_normal_run_uses_full_width():
    """A normal-sized run should NOT shrink the font — comfort first."""
    widths, fs = _autofit_summary_geometry(
        _normal_rows(), _normal_totals(), available_width=AVAILABLE,
    )
    assert fs == 7.5
    # Block column is the largest (it gets the slack)
    assert widths[0] == max(widths)


def test_block_table_renders_without_exception():
    tbl = _block_summary_table(_normal_rows(), _normal_totals())
    assert tbl is not None
