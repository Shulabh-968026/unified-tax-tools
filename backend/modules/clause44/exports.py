"""Excel export builder for single + consolidated runs.

Workbook layout (user-requested):
  1.  Clause 44 Summary   — Aggregate + per-ledger six-column pivot (the
                            "consolidated pivotable list").
  2.  Reconciliation      — Books → Schedule tie-out.
  3.  Col 3 · Exempt      — vouchers classified into Col 3.
  4.  Col 4 · Composition — vouchers classified into Col 4.
  5.  Col 5 · Other Reg.  — vouchers classified into Col 5 (ITC).
  6.  Col 7 · Unregistered — vouchers classified into Col 7.

Each cohort sheet can be pivoted in Excel (all columns present, no merged
cells inside the data region) so auditors can slice further without going
back to the app.
"""
import io
from typing import Dict, Any, List
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from fastapi.responses import StreamingResponse

INDIAN_FMT = "[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00"

BOLD_WHITE = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="0F172A")
THIN = Side(style="thin", color="D4D4D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TITLE_FONT = Font(bold=True, size=14)

BUCKET_META = [
    ("col3", "Col 3 · Exempt",        "Col 3 — Exempt"),
    ("col4", "Col 4 · Composition",   "Col 4 — Composition"),
    ("col5", "Col 5 · Other Reg ITC", "Col 5 — Other Registered (ITC)"),
    ("col7", "Col 7 · Unregistered",  "Col 7 — Unregistered"),
]
BUCKET_LABEL = {k: long for k, _, long in BUCKET_META}


def _style_header_row(ws, row_idx: int, n_cols: int):
    for col in range(1, n_cols + 1):
        c = ws.cell(row=row_idx, column=col)
        c.font = BOLD_WHITE
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER


def _apply_indian_fmt(ws, min_row: int, cols: List[int]):
    max_col = max(cols)
    min_col = min(cols)
    for row in ws.iter_rows(min_row=min_row, min_col=min_col, max_col=max_col):
        for c in row:
            if c.column in cols and isinstance(c.value, (int, float)):
                c.number_format = INDIAN_FMT


def _write_summary_sheet(wb, run: Dict[str, Any]):
    summary = run.get("summary", {}) or {}
    by_ledger = run.get("by_ledger", {}) or {}

    ws = wb.active
    ws.title = "Clause 44 Summary"

    ws["A1"] = "Clause 44 of Form 3CD — Expenditure Summary"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:G1")
    ws["A2"] = f"Company: {run.get('company_name','')}"
    ws["A3"] = f"Generated: {run.get('generated_at','')}"

    headers = [
        "Particulars",
        "Col 2: Total Expenditure",
        "Col 3: Exempt Supply",
        "Col 4: Composition Dealer",
        "Col 5: Other Registered (ITC)",
        "Col 6: Total (3+4+5)",
        "Col 7: Unregistered",
    ]

    # Aggregate row
    ws.append([])
    ws.append(headers)
    _style_header_row(ws, ws.max_row, len(headers))
    ws.append([
        "Aggregate (All Expenditure)",
        summary.get("col2_total", 0),
        summary.get("col3", 0),
        summary.get("col4", 0),
        summary.get("col5", 0),
        summary.get("col6", 0),
        summary.get("col7", 0),
    ])

    # Per-ledger pivot
    ws.append([])
    ws.append(["Per-Ledger Breakdown (six-column pivot)"])
    ws.cell(ws.max_row, 1).font = TITLE_FONT
    ws.append(headers)
    pivot_header_row = ws.max_row
    _style_header_row(ws, pivot_header_row, len(headers))

    for lname, row in sorted(by_ledger.items(), key=lambda kv: kv[1].get("total", 0), reverse=True):
        col3 = row.get("col3", 0) or 0
        col4 = row.get("col4", 0) or 0
        col5 = row.get("col5", 0) or 0
        col7 = row.get("col7", 0) or 0
        total = row.get("total", 0) or (col3 + col4 + col5 + col7)
        ws.append([
            lname,
            total,
            col3, col4, col5,
            col3 + col4 + col5,
            col7,
        ])

    ws.column_dimensions["A"].width = 36
    for col_letter in ["B", "C", "D", "E", "F", "G"]:
        ws.column_dimensions[col_letter].width = 22
    _apply_indian_fmt(ws, min_row=5, cols=[2, 3, 4, 5, 6, 7])

    # Freeze the pivot header row so scrolling keeps it visible.
    ws.freeze_panes = ws.cell(row=pivot_header_row + 1, column=2)


def _write_recon_sheet(wb, run: Dict[str, Any]):
    recon = run.get("recon") or {}
    ws = wb.create_sheet("Reconciliation")
    ws["A1"] = "Reconciliation — Books to Clause 44 (ICAI Para 79.4)"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:B1")
    ws.append([])
    ws.append(["Particulars", "Amount"])
    _style_header_row(ws, ws.max_row, 2)

    pl_total = recon.get("pl_total")
    capex_total = recon.get("capex_total")
    reportable = recon.get("reportable_total")

    # ICAI 5-line format — render only when the new fields are present.
    if pl_total is not None and capex_total is not None:
        ws.append(["Total Expenditure as per Profit & Loss", float(pl_total or 0)])
        ws.append(["+ Capital expenditure additions (ICAI Para 79.18)", float(capex_total or 0)])

        buckets = [
            ("non_cash", "Less: Non-cash charges (depreciation, provisions, fair-value losses)"),
            ("sch3",     "Less: Schedule III items (salary, wages, PF/ESI, gratuity, dividend declared, sale of land/building)"),
            ("money",    "Less: Money / Securities transactions (interest, TDS, investments, share transactions)"),
            ("other",    "Less: Other auditor-elected exclusions"),
        ]
        for key, label in buckets:
            lines = recon.get(f"{key}_lines") or []
            total = recon.get(f"{key}_total") or 0
            ws.append([label, -float(total or 0)])
            header_row = ws.max_row
            ws.cell(row=header_row, column=1).font = Font(bold=True)
            for line in lines:
                ws.append([f"   • {line['name']}", -float(line.get('amount') or 0)])

        ws.append(["= Reportable Expenditure (Col 2 of Clause 44)", float(reportable or 0)])
        last_row = ws.max_row
        for col in (1, 2):
            c = ws.cell(row=last_row, column=col)
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3F4F1")
            c.border = BORDER
    else:
        # Legacy single-bucket recon (pre-Release-1 runs).
        ws.append(["Total Expenditure as per Books", recon.get("total_books", 0)])
        ws.append(["Less : Expenditures excluded from Clause 44 Report", None])
        for line in (recon.get("excluded_lines") or []):
            ws.append([f"   • {line['name']}", -float(line.get("amount") or 0)])
        ws.append(["Expenditure as per Clause 44 Report", recon.get("balance", 0)])
        last_row = ws.max_row
        for col in (1, 2):
            c = ws.cell(row=last_row, column=col)
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3F4F1")
            c.border = BORDER

    # Disclaimer block — appended regardless of recon shape.
    disclaimer = run.get("disclaimer_text") or ""
    if disclaimer:
        ws.append([])
        ws.append(["Disclaimer"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.append([disclaimer])
        ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[ws.max_row].height = 90
        ws.merge_cells(start_row=ws.max_row, start_column=1, end_row=ws.max_row, end_column=2)

    ws.column_dimensions["A"].width = 70
    ws.column_dimensions["B"].width = 22
    _apply_indian_fmt(ws, min_row=4, cols=[2])


def _write_cohort_sheet(wb, sheet_name: str, long_label: str, txns: List[Dict[str, Any]]):
    ws = wb.create_sheet(sheet_name)
    ws["A1"] = f"{long_label} — Transaction Breakup"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:L1")

    has_division = any(t.get("division_name") for t in txns)
    # ICAI Para 79.20 illustrative working-paper columns:
    #   Date | Voucher Type | Voucher No | [Division] | Ledger | Party |
    #   Party GSTIN | Party Reg | Country | RCM | Amount |
    #   Value Eligible for ITC | Reason for NIL GST / Notes | Auditor Remarks
    headers = ["Date", "Voucher Type", "Voucher No"]
    if has_division:
        headers.append("Division")
    headers += [
        "Ledger", "Party", "Party GSTIN", "Party Reg.", "Country",
        "RCM", "Amount", "Value Eligible for ITC",
        "Reason for NIL GST / Classification Notes", "Auditor Remarks",
    ]

    ws.append([])
    ws.append(headers)
    header_row = ws.max_row
    _style_header_row(ws, header_row, len(headers))

    # Dynamically compute column indices so division-injection doesn't break them.
    idx = {h: i + 1 for i, h in enumerate(headers)}
    amount_col = idx["Amount"]
    itc_col = idx["Value Eligible for ITC"]

    total = 0.0
    total_itc = 0.0
    for t in txns:
        row = [t.get("date", ""), t.get("voucher_type", ""), t.get("voucher_number", "")]
        if has_division:
            row.append(t.get("division_name", "—"))
        amt = float(t.get("amount") or 0)
        total += amt
        # Per Para 79.20 "Value eligible for ITC": amount only if a proper ITC-
        # ledger entry sat on the voucher AND the voucher isn't RCM AND the
        # line isn't an exempt-tagged Input A contribution.  The engine
        # already stores these flags on each line.
        itc_eligible = 0.0
        if t.get("has_itc_ledger") and not t.get("is_rcm") and t.get("col3_source") != "input_a":
            itc_eligible = amt
        total_itc += itc_eligible
        row += [
            t.get("ledger_name", ""),
            t.get("party_name", ""),
            t.get("party_gstin", ""),
            t.get("party_reg", ""),
            t.get("party_country", ""),
            "Yes" if t.get("is_rcm") else "",
            amt,
            itc_eligible,
            t.get("reason", ""),
            "",  # blank column for the auditor to note remarks
        ]
        ws.append(row)

    if txns:
        footer = ["Total"] + [""] * (len(headers) - 1)
        footer[amount_col - 1] = total
        footer[itc_col - 1] = total_itc
        ws.append(footer)
        last_row = ws.max_row
        for col in range(1, len(headers) + 1):
            c = ws.cell(row=last_row, column=col)
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3F4F1")
            c.border = BORDER
    else:
        ws.append(["— No vouchers classified into this cohort —"])

    # Column widths — keep the meta columns tight, the narratives wide.
    base_widths = [12, 14, 14]
    if has_division:
        base_widths.append(16)
    base_widths += [28, 28, 18, 14, 14, 8, 16, 18, 60, 28]
    for i, w in enumerate(base_widths[:len(headers)], 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    _apply_indian_fmt(ws, min_row=header_row + 1, cols=[amount_col, itc_col])

    # Freeze header row + auto-filter (pivot-friendly out of the box).
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"{ws.cell(row=header_row, column=1).coordinate}:{ws.cell(row=header_row, column=len(headers)).coordinate}"


def build_export_response(run: Dict[str, Any], fname_prefix: str):
    txns = run.get("transactions", []) or []

    wb = openpyxl.Workbook()

    # Sheet 1 — Summary + per-ledger pivot
    _write_summary_sheet(wb, run)

    # Sheet 2 — Reconciliation
    _write_recon_sheet(wb, run)

    # Sheets 3-6 — One per cohort column
    for key, short, long_label in BUCKET_META:
        cohort_txns = [t for t in txns if t.get("bucket") == key]
        _write_cohort_sheet(wb, short, long_label, cohort_txns)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"{fname_prefix}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
