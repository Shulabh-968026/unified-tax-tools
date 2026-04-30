"""Excel export — IT Depreciation Schedule.

Single workbook, 4 sheets:
  1. Block Summary  — mirrors the user's Sample IT Depreciation Schedule
  2. Additions Register
  3. Deletions Register
  4. Workings — formula notes for audit trail
"""
from __future__ import annotations
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


_THIN = Side(style="thin", color="888888")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
HDR_FILL = PatternFill("solid", fgColor="F1F5F9")
TOT_FILL = PatternFill("solid", fgColor="E2E8F0")
TITLE_FONT = Font(bold=True, size=14)
HDR_FONT = Font(bold=True, size=11)
NUM_FMT = "#,##,##0.00;(#,##,##0.00);-"


def _set(cell, value, *, bold=False, fill=None, num=False, align=None):
    cell.value = value
    if bold:
        cell.font = HDR_FONT
    if fill:
        cell.fill = fill
    if num:
        cell.number_format = NUM_FMT
    if align:
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    cell.border = BORDER


def _autosize(ws, widths: Dict[int, int]):
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def write_block_summary(ws, *, client_name: str, fy_start: str, fy_end: str,
                        rows: List[Dict[str, Any]], totals: Dict[str, float]):
    ws.title = "Block Summary"
    # Title rows
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
    ws.cell(1, 1).value = client_name or ""
    ws.cell(1, 1).font = TITLE_FONT
    ws.cell(1, 1).alignment = Alignment(horizontal="center")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=10)
    ws.cell(2, 1).value = f"IT Depreciation Schedule for the period {fy_start} to {fy_end}"
    ws.cell(2, 1).font = Font(bold=True, size=11)
    ws.cell(2, 1).alignment = Alignment(horizontal="center")

    # Header row (row 4)
    headers = [
        ("PARTICULARS", 36),
        ("Rate", 7),
        ("Opening WDV", 15),
        ("Adds ≥ 180 days", 17),
        ("Adds < 180 days", 17),
        ("Deletions (Sales)", 17),
        ("Total before Depn", 17),
        ("Depreciation", 15),
        ("STCG u/s 50", 13),
        ("Closing WDV", 16),
    ]
    for i, (h, _w) in enumerate(headers, start=1):
        _set(ws.cell(4, i), h, bold=True, fill=HDR_FILL, align="center")
    _autosize(ws, {i: w for i, (_h, w) in enumerate(headers, start=1)})

    # Data rows
    r = 5
    for row in rows:
        _set(ws.cell(r, 1), row["block_label"], align="left")
        _set(ws.cell(r, 2), f"{row['rate']:.0f}%" if row.get("rate") else "", align="center")
        _set(ws.cell(r, 3), row["opening_wdv"], num=True, align="right")
        _set(ws.cell(r, 4), row["adds_full"], num=True, align="right")
        _set(ws.cell(r, 5), row["adds_half"], num=True, align="right")
        _set(ws.cell(r, 6), row["deletions"], num=True, align="right")
        _set(ws.cell(r, 7), row["total_block"], num=True, align="right")
        _set(ws.cell(r, 8), row["depreciation"], num=True, align="right")
        _set(ws.cell(r, 9), row.get("stcg_sec50", 0), num=True, align="right")
        _set(ws.cell(r, 10), row["closing_wdv"], num=True, align="right")
        r += 1

    # Totals
    _set(ws.cell(r, 1), "TOTAL", bold=True, fill=TOT_FILL, align="left")
    _set(ws.cell(r, 2), "", fill=TOT_FILL)
    _set(ws.cell(r, 3), totals["opening_wdv"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 4), totals["adds_full"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 5), totals["adds_half"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 6), totals["deletions"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 7), totals["total_block"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 8), totals["depreciation"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 9), totals["stcg_sec50"], bold=True, fill=TOT_FILL, num=True, align="right")
    _set(ws.cell(r, 10), totals["closing_wdv"], bold=True, fill=TOT_FILL, num=True, align="right")


def write_additions(ws, additions: List[Dict[str, Any]]):
    ws.title = "Additions Register"
    headers = [
        ("Block", 28), ("Voucher No", 16), ("Voucher Type", 14),
        ("Acc Date", 12), ("Inv Date", 12), ("PTU Date", 12),
        ("Half Rate?", 11),
        ("Party", 32), ("Particulars", 40),
        ("Invoice Cost", 14),
        ("Discount/Credits", 16), ("Other Expenses", 14), ("ITC Reversed", 13),
        ("Interest Cap", 13), ("Forex", 11),
        ("Capitalised Cost", 16), ("Ledger", 30),
    ]
    for i, (h, _w) in enumerate(headers, start=1):
        _set(ws.cell(1, i), h, bold=True, fill=HDR_FILL, align="center")
    _autosize(ws, {i: w for i, (_h, w) in enumerate(headers, start=1)})

    from modules.fixed_assets.compute import adjusted_cost
    r = 2
    for a in additions:
        cap = adjusted_cost(a)
        _set(ws.cell(r, 1),  a.get("block_label", ""))
        _set(ws.cell(r, 2),  a.get("voucher_no", ""))
        _set(ws.cell(r, 3),  a.get("voucher_type", ""))
        _set(ws.cell(r, 4),  a.get("accounting_date", ""))
        _set(ws.cell(r, 5),  a.get("invoice_date", ""))
        _set(ws.cell(r, 6),  a.get("put_to_use_date", ""))
        _set(ws.cell(r, 7),  "Yes" if not a.get("is_more_than_180", True) else "")
        _set(ws.cell(r, 8),  a.get("party_name", ""))
        _set(ws.cell(r, 9),  a.get("particulars", "")[:200])
        _set(ws.cell(r, 10), float(a.get("invoice_cost") or 0), num=True, align="right")
        _set(ws.cell(r, 11), float(a.get("discount_credits") or 0), num=True, align="right")
        _set(ws.cell(r, 12), float(a.get("other_expenses") or 0), num=True, align="right")
        _set(ws.cell(r, 13), float(a.get("itc_reversed") or 0), num=True, align="right")
        _set(ws.cell(r, 14), float(a.get("interest_capitalized") or 0), num=True, align="right")
        _set(ws.cell(r, 15), float(a.get("forex_fluctuations") or 0), num=True, align="right")
        _set(ws.cell(r, 16), cap, bold=True, num=True, align="right")
        _set(ws.cell(r, 17), a.get("ledger_name", ""))
        r += 1


def write_deletions(ws, deletions: List[Dict[str, Any]]):
    ws.title = "Deletions Register"
    headers = [
        ("Block", 28), ("Voucher No", 16), ("Sale Date", 12), ("Buyer", 32),
        ("Sale Value", 14), ("Particulars", 40), ("Ledger", 30),
    ]
    for i, (h, _w) in enumerate(headers, start=1):
        _set(ws.cell(1, i), h, bold=True, fill=HDR_FILL, align="center")
    _autosize(ws, {i: w for i, (_h, w) in enumerate(headers, start=1)})
    r = 2
    for d in [d for d in deletions if (d.get("classification") or "") == "sale"]:
        _set(ws.cell(r, 1), d.get("block_label", ""))
        _set(ws.cell(r, 2), d.get("voucher_no", ""))
        _set(ws.cell(r, 3), d.get("sale_date", ""))
        _set(ws.cell(r, 4), d.get("buyer_name", ""))
        _set(ws.cell(r, 5), float(d.get("sale_value") or 0), num=True, align="right")
        _set(ws.cell(r, 6), d.get("particulars", "")[:200])
        _set(ws.cell(r, 7), d.get("ledger_name", ""))
        r += 1


def write_workings(ws):
    ws.title = "Workings"
    ws.column_dimensions["A"].width = 110
    notes = [
        "Computation method — Section 32, Income-tax Act, 1961 — WDV (Block of Assets):",
        "",
        "1. Capitalised Cost per addition  =  Invoice Cost  −  Discount / Credits  +  Other Expenses",
        "                                       −  ITC Reversed  +  Interest Capitalised  +  Forex Fluctuations.",
        "",
        "2. Block WDV before depreciation  =  Opening WDV  +  Total Additions (full + half)  −  Sales (deletions).",
        "",
        "3. 180-day rule:",
        "      Adds ≥ 180 days (PTU on/before Oct 3 for FY ending 31 March)  ⇒  full statutory rate.",
        "      Adds < 180 days  ⇒  half the statutory rate (rate ÷ 2).",
        "",
        "4. Sale allocation: Sales first reduce the full-rate pool (Opening + Adds≥180);",
        "   any excess reduces the half-rate pool (Adds<180).",
        "",
        "5. Depreciation =  (Eligible_at_full_rate × rate)  +  (Eligible_at_half_rate × rate ÷ 2).",
        "",
        "6. Sec 50 STCG: When Block WDV before depreciation < 0, depreciation = 0;",
        "   block extinguishes; the negative amount is reported as Short-Term Capital Gain.",
        "",
        "7. Closing WDV = Block WDV before depreciation − Depreciation.",
    ]
    for i, line in enumerate(notes, start=1):
        ws.cell(i, 1).value = line
        if i == 1:
            ws.cell(i, 1).font = HDR_FONT


def build_workbook(*, client_name: str, fy_start: str, fy_end: str,
                   rows: List[Dict[str, Any]], totals: Dict[str, float],
                   additions: List[Dict[str, Any]],
                   deletions: List[Dict[str, Any]]) -> bytes:
    wb = Workbook()
    write_block_summary(wb.active, client_name=client_name, fy_start=fy_start,
                        fy_end=fy_end, rows=rows, totals=totals)
    write_additions(wb.create_sheet(), additions)
    write_deletions(wb.create_sheet(), deletions)
    write_workings(wb.create_sheet())
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
