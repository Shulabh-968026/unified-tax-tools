"""Verify the IT Depreciation Excel workbook auto-fits column widths to
content — numbers never wrap (even at ₹999 Cr), and short text columns
shrink to fit their actual data."""
import io
from openpyxl import load_workbook

from modules.fixed_assets.export import build_workbook, _format_inr_indian


_FY_START = "2024-04-01"
_FY_END = "2025-03-31"


def _normal_args():
    rows = [
        {"block_label": "40% Block – Computers", "rate": 40,
         "opening_wdv": 485453.0, "adds_full": 268950.0, "adds_half": 162550.0,
         "deletions": 0.0, "total_block": 916953.0,
         "depreciation": 334271.20, "closing_wdv": 582681.80, "stcg_sec50": 0},
        {"block_label": "15% Block – Plant & Machinery", "rate": 15,
         "opening_wdv": 25783559.0, "adds_full": 8989183.43,
         "adds_half": 13692454.49, "deletions": 0.0,
         "total_block": 48465196.92, "depreciation": 6242845.45,
         "closing_wdv": 42222351.47, "stcg_sec50": 0},
    ]
    totals = {"opening_wdv": 26269012.0, "adds_full": 9258133.43,
              "adds_half": 13855004.49, "deletions": 0.0,
              "total_block": 49382149.92, "depreciation": 6577116.65,
              "closing_wdv": 42805033.27, "stcg_sec50": 0}
    return rows, totals


def _huge_args():
    rows = [
        {"block_label": "15% Block – Plant & Machinery (Mega Mfg Co Ltd)",
         "rate": 15, "opening_wdv": 9999999999.99,
         "adds_full": 1234567890.12, "adds_half": 987654321.10,
         "deletions": 5000000.0, "total_block": 12217222211.21,
         "depreciation": 1666666666.66,
         "closing_wdv": 11555555555.55, "stcg_sec50": 0},
    ]
    totals = {"opening_wdv": 9999999999.99, "adds_full": 1234567890.12,
              "adds_half": 987654321.10, "deletions": 5000000.0,
              "total_block": 12217222211.21, "depreciation": 1666666666.66,
              "closing_wdv": 11555555555.55, "stcg_sec50": 0}
    return rows, totals


def _build(rows, totals, additions=None, deletions=None):
    return build_workbook(
        client_name="Demo Client", fy_start=_FY_START, fy_end=_FY_END,
        rows=rows, totals=totals,
        additions=additions or [], deletions=deletions or [],
    )


def _widths(blob, sheet):
    wb = load_workbook(io.BytesIO(blob))
    ws = wb[sheet]
    return {c: ws.column_dimensions[c].width for c in ws.column_dimensions}


def test_indian_inr_format_widest_999cr():
    """₹999.99 Cr renders to 16 chars (incl. .XX) — table must fit."""
    s = _format_inr_indian(9999999999.99)
    assert s == "9,99,99,99,999.99"
    assert len(s) == 17  # 17 with comma grouping


def test_normal_run_widths_fit_actual_numbers():
    rows, totals = _normal_args()
    blob = _build(rows, totals)
    widths = _widths(blob, "Block Summary")
    # The 6 numeric columns (C–J on row 4) must each be at least the
    # width of the longest formatted value in that column.
    longest_dep = len(_format_inr_indian(6577116.65))  # 11 chars
    # Depreciation column = column H (index 8)
    assert widths["H"] >= longest_dep
    # Block-label column (A) shouldn't blow up — capped at 42
    assert widths["A"] <= 42
    # Rate column should be small
    assert widths["B"] <= 8


def test_huge_run_widths_accommodate_999cr():
    rows, totals = _huge_args()
    blob = _build(rows, totals)
    widths = _widths(blob, "Block Summary")
    # Closing WDV column (J) — must hold 16-char "11,55,55,55,555.55"
    longest_close = len(_format_inr_indian(11555555555.55))
    assert widths["J"] >= longest_close, \
        f"closing column too narrow: {widths['J']} < {longest_close}"
    longest_open = len(_format_inr_indian(9999999999.99))
    assert widths["C"] >= longest_open


def test_additions_register_caps_text_runaway():
    """A 200-char particulars must NOT explode the column width past the cap."""
    a = {
        "block_label": "15% Block – P&M",
        "voucher_no": "V/0001", "voucher_type": "Purchase",
        "accounting_date": "2024-04-15", "invoice_date": "2024-04-10",
        "put_to_use_date": "", "is_more_than_180": True,
        "party_name": "Acme Inc",
        "particulars": ("X" * 250),  # extreme
        "invoice_cost": 100000.0, "discount_credits": 0, "other_expenses": 0,
        "itc_reversed": 0, "interest_capitalized": 0, "forex_fluctuations": 0,
        "ledger_name": "Plant & Machinery",
    }
    rows, totals = _normal_args()
    blob = _build(rows, totals, additions=[a])
    widths = _widths(blob, "Additions Register")
    # particulars is column 9 (I) — must be capped (text_cap=50)
    assert widths["I"] <= 50, f"particulars column not capped: {widths['I']}"
    # Capitalised Cost column (P, idx 16) is numeric — sized to value width
    assert widths["P"] >= len(_format_inr_indian(100000.0))


def test_block_summary_total_row_value_widths_respected():
    """The total-row figure (often the largest) must drive the column width."""
    rows, totals = _normal_args()
    # Force totals.depreciation to be larger than any single block's value
    totals["depreciation"] = 999999999.99  # 14 chars
    blob = _build(rows, totals)
    widths = _widths(blob, "Block Summary")
    expected = len(_format_inr_indian(999999999.99))
    assert widths["H"] >= expected
