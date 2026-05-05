"""Excel export helpers for 43B(h) MSME Disallowance — profile template & final audit workbook."""
from __future__ import annotations

import io
from typing import Any, Dict, List

import pandas as pd
from fastapi.responses import StreamingResponse

from modules.msme43bh.schemas import SECTOR_OPTIONS, MSME_TYPE_OPTIONS

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_profile_template(profiles: List[Dict[str, Any]], sid: str) -> StreamingResponse:
    df = pd.DataFrame([
        {
            "Creditor Name": p["ledger_name"],
            "MSME Number": p.get("msme_number", ""),
            "Sector": p.get("sector", ""),
            "MSME Type": p.get("msme_type", ""),
            "Capital goods Creditor / Fund Creditor": p.get("capital_goods", ""),
        }
        for p in profiles
    ])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="MSME Profiles", index=False)
        ws = writer.sheets["MSME Profiles"]
        ws.set_column("A:A", 35)
        ws.set_column("B:B", 22)
        ws.set_column("C:E", 18)
        ws.data_validation(1, 2, len(df) + 1, 2, {"validate": "list", "source": SECTOR_OPTIONS})
        ws.data_validation(1, 3, len(df) + 1, 3, {"validate": "list", "source": MSME_TYPE_OPTIONS})
        ws.data_validation(1, 4, len(df) + 1, 4, {"validate": "list", "source": ["Yes", "No"]})
    output.seek(0)
    return StreamingResponse(
        output, media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="MSME_Profile_Template_{sid[:8]}.xlsx"'},
    )


def build_audit_export_bytes(results: Dict[str, Any]) -> bytes:
    """Same workbook as `build_audit_export` but returns raw bytes (for
    Library auto-save during compute)."""
    rows = results["audit_rows"]
    summary = results["summary"]
    df = pd.DataFrame([
        {
            "Creditor": r["ledger_name"],
            "Invoice #": r["voucher_no"],
            "Bill Date": r["voucher_date"],
            "Amount (INR)": r["bill_amount"],
            "Analysis Type": r["analysis_type"],
            "Source Due Date": r["source_due_date"] or "",
            "Statutory Due Date": r["statutory_due_date"] or "",
            "Due Date Basis": r["due_date_basis"],
            "FIFO Forced": "Yes" if r.get("fifo_forced") else "",
            "Payment Date": r["payment_date"] or "",
            "Delay Days": r["delay_days"] if r["delay_days"] is not None else "",
            "Year-End Flag": r["year_end_flag"],
            "Sector": r["sector"],
            "MSME Type": r["msme_type"],
            "Capital Goods/Fund": r["capital_goods"],
            "Status": r["status"],
            "Disallowance (INR)": r["disallowance"],
            "Reason": r["reason"],
        }
        for r in rows
    ])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df = pd.DataFrame([
            ["Total Outstanding (INR)", summary["total_outstanding"]],
            ["Total Exempt (INR)", summary["total_exempt"]],
            ["Total Allowed (INR)", summary["total_allowed"]],
            ["Final Disallowance u/s 43B(h) (INR)", summary["final_disallowance"]],
            ["Bill Count", summary["bill_count"]],
            ["Disallowed Count", summary["disallowed_count"]],
            ["Allowed Count", summary["allowed_count"]],
            ["Exempt Count", summary["exempt_count"]],
            ["Force FIFO Applied", "Yes" if summary.get("force_fifo") else "No"],
            ["FIFO Forced Bill Count", summary.get("fifo_forced_count", 0)],
            ["Computed At (UTC)", summary["computed_at"]],
        ], columns=["Metric", "Value"])
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        df.to_excel(writer, sheet_name="Audit Detail", index=False)
        disc_df = pd.DataFrame([
            ["Disclaimer 1", "Outstanding amount includes GST; disallowance is calculated on the gross amount for conservative compliance."],
            ["Disclaimer 2", "In the absence of a tracked credit agreement, a statutory maximum of 45 days is assumed."],
            ["Disclaimer 3", "When 'Force FIFO' is enabled, all bills are evaluated against Voucher Date + 45 days, ignoring any source Due Date provided by the books."],
        ], columns=["#", "Note"])
        disc_df.to_excel(writer, sheet_name="Disclaimers", index=False)
        for sheet_name, frame in [("Summary", summary_df), ("Audit Detail", df), ("Disclaimers", disc_df)]:
            ws = writer.sheets[sheet_name]
            for i, col in enumerate(frame.columns):
                width = max(14, min(40, int(frame[col].astype(str).map(len).max() if len(frame) else 12) + 2))
                ws.set_column(i, i, width)
    output.seek(0)
    return output.getvalue()


def build_audit_export(results: Dict[str, Any], sid: str) -> StreamingResponse:
    blob = build_audit_export_bytes(results)
    return StreamingResponse(
        io.BytesIO(blob), media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="AssureAI_43Bh_Audit_{sid[:8]}.xlsx"'},
    )
