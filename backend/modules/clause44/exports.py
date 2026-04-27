"""Excel export builder for single + consolidated runs."""
import io
from typing import Dict, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from fastapi.responses import StreamingResponse

INDIAN_FMT = "[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00"


def build_export_response(run: Dict[str, Any], fname_prefix: str):
    summary = run.get("summary", {}) or {}
    by_ledger = run.get("by_ledger", {}) or {}
    txns = run.get("transactions", []) or []
    recon = run.get("recon") or {}

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Clause 44"

    bold = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0F172A")
    thin = Side(style="thin", color="D4D4D0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    title_font = Font(bold=True, size=14)

    ws1["A1"] = "Clause 44 of Form 3CD — Expenditure Summary"
    ws1["A1"].font = title_font
    ws1.merge_cells("A1:G1")
    ws1["A2"] = f"Company: {run.get('company_name','')}"
    ws1["A3"] = f"Generated: {run.get('generated_at','')}"

    headers = [
        "Particulars",
        "Col 2: Total Expenditure",
        "Col 3: Exempt Supply",
        "Col 4: Composition Dealer",
        "Col 5: Other Registered (ITC)",
        "Col 6: Total (3+4+5)",
        "Col 7: Unregistered",
    ]
    ws1.append([])
    ws1.append(headers)
    hr = ws1.max_row
    for col in range(1, len(headers) + 1):
        c = ws1.cell(row=hr, column=col)
        c.font = bold
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border

    ws1.append([
        "Aggregate (All Expenditure)",
        summary.get("col2_total", 0),
        summary.get("col3", 0),
        summary.get("col4", 0),
        summary.get("col5", 0),
        summary.get("col6", 0),
        summary.get("col7", 0),
    ])

    ws1.append([])
    ws1.append(["Per-Ledger Breakdown"])
    ws1.cell(ws1.max_row, 1).font = title_font
    ws1.append(headers)
    hr = ws1.max_row
    for col in range(1, len(headers) + 1):
        c = ws1.cell(row=hr, column=col)
        c.font = bold
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border

    for lname, row in sorted(by_ledger.items(), key=lambda kv: kv[1].get("total", 0), reverse=True):
        ws1.append([
            lname,
            row.get("total", 0),
            row.get("col3", 0),
            row.get("col4", 0),
            row.get("col5", 0),
            row.get("col3", 0) + row.get("col4", 0) + row.get("col5", 0),
            row.get("col7", 0),
        ])

    ws1.column_dimensions["A"].width = 36
    for col_letter in ["B", "C", "D", "E", "F", "G"]:
        ws1.column_dimensions[col_letter].width = 22

    for row in ws1.iter_rows(min_row=5, min_col=2, max_col=7):
        for c in row:
            if isinstance(c.value, (int, float)):
                c.number_format = INDIAN_FMT

    # Sheet 2 - Reconciliation
    ws_r = wb.create_sheet("Reconciliation")
    ws_r["A1"] = "Reconciliation — Books to Clause 44"
    ws_r["A1"].font = title_font
    ws_r.merge_cells("A1:B1")
    ws_r.append([])
    ws_r.append(["Particulars", "Amount"])
    hr = ws_r.max_row
    for col in (1, 2):
        c = ws_r.cell(row=hr, column=col)
        c.font = bold
        c.fill = header_fill
        c.alignment = Alignment(horizontal="left", vertical="center")
        c.border = border

    ws_r.append(["Total Expenditure as per Books", recon.get("total_books", 0)])
    ws_r.append(["Less : Expenditures excluded from Clause 44 Report", None])
    for line in (recon.get("excluded_lines") or []):
        ws_r.append([f"   • {line['name']}", -float(line.get("amount") or 0)])
    ws_r.append(["Expenditure as per Clause 44 Report", recon.get("balance", 0)])
    last_row = ws_r.max_row
    for col in (1, 2):
        c = ws_r.cell(row=last_row, column=col)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="F3F4F1")
        c.border = border
    ws_r.column_dimensions["A"].width = 60
    ws_r.column_dimensions["B"].width = 22
    for row in ws_r.iter_rows(min_row=4, min_col=2, max_col=2):
        for c in row:
            if isinstance(c.value, (int, float)):
                c.number_format = INDIAN_FMT

    # Sheet 3 - Audit trail
    ws2 = wb.create_sheet("Transaction Audit Trail")
    headers2 = ["Date", "Voucher Type", "Voucher No", "Ledger", "Party", "Party GSTIN", "Party Reg.", "Amount", "Bucket", "Reason"]
    if any(t.get("division_name") for t in txns):
        headers2.insert(3, "Division")
    ws2.append(headers2)
    for col in range(1, len(headers2) + 1):
        c = ws2.cell(row=1, column=col)
        c.font = bold
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border

    bucket_label = {"col3": "Col 3 — Exempt", "col4": "Col 4 — Composition", "col5": "Col 5 — Other Registered (ITC)", "col7": "Col 7 — Unregistered"}
    has_div = "Division" in headers2
    for t in txns:
        row = [t.get("date", ""), t.get("voucher_type", ""), t.get("voucher_number", "")]
        if has_div:
            row.append(t.get("division_name", "—"))
        row += [
            t.get("ledger_name", ""), t.get("party_name", ""), t.get("party_gstin", ""),
            t.get("party_reg", ""), t.get("amount", 0),
            bucket_label.get(t.get("bucket"), t.get("bucket", "")), t.get("reason", ""),
        ]
        ws2.append(row)
    base_widths = [12, 14, 14, 28, 28, 18, 14, 16, 26, 60]
    if has_div:
        base_widths.insert(3, 16)
    for i, w in enumerate(base_widths, 1):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    amount_col = 9 if has_div else 8
    for row in ws2.iter_rows(min_row=2, min_col=amount_col, max_col=amount_col):
        for c in row:
            if isinstance(c.value, (int, float)):
                c.number_format = INDIAN_FMT

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"{fname_prefix}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
