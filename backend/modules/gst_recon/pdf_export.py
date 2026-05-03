"""GST Recon — PDF working-paper export.

Generates a single, signature-ready PDF that a CA can attach to the audit
file alongside (or instead of) the multi-sheet Excel. Layout mirrors the
on-screen Dashboard:

  Page 1 — Cover / Reconciliation Health
    * Client header (name, GSTIN, FY, run date, prepared-by)
    * 4 KPI cards (Books-vs-R1 / R1-vs-R3B / Books-vs-R2B / R2B-vs-R3B)
    * Status banner: "ALL RECONCILED" or "N MONTH-ISSUES FLAGGED"

  Page 2..3 — 12-Month Reconciliation
    * Outward Turnover table (Books / R1 / R3B + variances)
    * ITC table (Books / R2B / R3B + variances)
    * Annual totals row, amber-highlighted variance cells

  Page 4..N — Annual Party-wise variance
    * Outward (top-15 by absolute variance, then "+ N more")
    * Inward  (top-15 by absolute variance, then "+ N more")

  Last page — Sign-off block
    * Prepared by / Reviewed by / Date / Notes

Pure Python via reportlab — no system deps, ships clean in container.
"""
from __future__ import annotations
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)


# ============================ Theme tokens ====================================
INK         = colors.HexColor("#111827")  # gray-900
INK_SOFT    = colors.HexColor("#374151")  # gray-700
MUTED       = colors.HexColor("#6B7280")  # gray-500
BORDER      = colors.HexColor("#E5E7EB")  # gray-200
HEADER_BG   = colors.HexColor("#1F2937")  # gray-800
HEADER_FG   = colors.HexColor("#FFFFFF")
ROW_ALT     = colors.HexColor("#F9FAFB")  # gray-50
SECTION_BG  = colors.HexColor("#F3F4F6")  # gray-100

OK_BG       = colors.HexColor("#D1FAE5")  # emerald-100
OK_FG       = colors.HexColor("#065F46")
WARN_BG     = colors.HexColor("#FEF3C7")  # amber-100
WARN_FG     = colors.HexColor("#92400E")
DANGER_BG   = colors.HexColor("#FEE2E2")  # red-100
DANGER_FG   = colors.HexColor("#991B1B")

# Severity thresholds (rupees absolute) — match Dashboard cards
THRESH_OK   = 1.0
THRESH_WARN = 100_000.0


def _inr(n: Optional[float]) -> str:
    if n is None or n == 0:
        return "–"
    s = f"{abs(n):,.2f}"
    return f"({s})" if n < 0 else s


def _severity(variance: float) -> str:
    a = abs(variance or 0.0)
    if a < THRESH_OK:
        return "ok"
    if a < THRESH_WARN:
        return "warn"
    return "danger"


def _styles():
    """Return a dict of named ParagraphStyles used across the document."""
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"],
                             fontName="Helvetica-Bold", fontSize=16, leading=20,
                             textColor=INK, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                             fontName="Helvetica-Bold", fontSize=12, leading=15,
                             textColor=INK, spaceBefore=10, spaceAfter=6),
        "label": ParagraphStyle("label", parent=base["Normal"],
                                fontName="Helvetica", fontSize=7.5, leading=9,
                                textColor=MUTED, spaceAfter=1),
        "labelMono": ParagraphStyle("labelMono", parent=base["Normal"],
                                    fontName="Courier", fontSize=8, leading=10,
                                    textColor=MUTED),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontName="Helvetica", fontSize=9, leading=12,
                               textColor=INK_SOFT),
        "kpiNum": ParagraphStyle("kpiNum", parent=base["Normal"],
                                 fontName="Helvetica-Bold", fontSize=14, leading=16,
                                 textColor=INK),
        "kpiHint": ParagraphStyle("kpiHint", parent=base["Normal"],
                                  fontName="Helvetica", fontSize=7.5, leading=9,
                                  textColor=MUTED),
        "kpiTag": ParagraphStyle("kpiTag", parent=base["Normal"],
                                 fontName="Helvetica-Bold", fontSize=7, leading=8,
                                 textColor=INK_SOFT),
        "footer": ParagraphStyle("footer", parent=base["Normal"],
                                 fontName="Helvetica", fontSize=7.5, leading=9,
                                 textColor=MUTED),
    }


# ============================ KPI card builder ===============================
def _kpi_card(label: str, base_value: float, variance: float,
              months_flagged: int, total_months: int, S):
    sev = _severity(variance)
    bg, fg = {
        "ok":     (OK_BG, OK_FG),
        "warn":   (WARN_BG, WARN_FG),
        "danger": (DANGER_BG, DANGER_FG),
    }[sev]
    pct = (abs(variance) / base_value * 100.0) if base_value else 0.0
    badge = {"ok": "RECONCILED", "warn": "REVIEW", "danger": "FLAGGED"}[sev]

    inner = Table([
        [Paragraph(label, S["label"])],
        [Paragraph(f"<b>{_inr(variance)}</b>", S["kpiNum"])],
        [Paragraph(f"{pct:.2f}% of {_inr(base_value)}", S["kpiHint"])],
        [Paragraph(f"{months_flagged} / {total_months} months flagged", S["kpiHint"])],
        [Paragraph(badge, S["kpiTag"])],
    ], colWidths=[60 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 4), (0, 4), bg),
        ("TEXTCOLOR",  (0, 4), (0, 4), fg),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return inner


def _dashboard_kpis(summary: Dict[str, Any], S):
    rows = summary.get("rows", []) or []
    totals = summary.get("totals", {}) or {}

    def _flagged(field: str) -> int:
        return sum(1 for r in rows if abs(r.get(field) or 0.0) >= THRESH_OK)

    cards = [
        _kpi_card(
            "BOOKS vs GSTR-1 · Outward Turnover",
            totals.get("books_outward_taxable", 0.0),
            totals.get("var_books_vs_r1_outward", 0.0),
            _flagged("var_books_vs_r1_outward"), len(rows), S),
        _kpi_card(
            "GSTR-1 vs GSTR-3B · Outward Turnover",
            totals.get("r3b_outward_taxable", 0.0),
            totals.get("var_r1_vs_r3b_outward", 0.0),
            _flagged("var_r1_vs_r3b_outward"), len(rows), S),
        _kpi_card(
            "BOOKS vs GSTR-2B · ITC",
            totals.get("books_itc_total", 0.0),
            totals.get("var_books_vs_r2b_itc", 0.0),
            _flagged("var_books_vs_r2b_itc"), len(rows), S),
        _kpi_card(
            "GSTR-2B vs GSTR-3B · ITC",
            totals.get("r3b_itc_total", 0.0),
            totals.get("var_r2b_vs_r3b_itc", 0.0),
            _flagged("var_r2b_vs_r3b_itc"), len(rows), S),
    ]
    grid = Table([[cards[0], cards[1]], [cards[2], cards[3]]],
                 colWidths=[90 * mm, 90 * mm], hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return grid


def _status_banner(summary: Dict[str, Any], S):
    rows = summary.get("rows", []) or []
    flag_fields = ("var_books_vs_r1_outward", "var_r1_vs_r3b_outward",
                   "var_books_vs_r2b_itc", "var_r2b_vs_r3b_itc")
    flagged = 0
    severity = "ok"
    for r in rows:
        for f in flag_fields:
            v = r.get(f) or 0.0
            sev = _severity(v)
            if sev != "ok":
                flagged += 1
                if sev == "danger":
                    severity = "danger"
                elif severity == "ok":
                    severity = "warn"
    bg, fg = {"ok": (OK_BG, OK_FG), "warn": (WARN_BG, WARN_FG),
              "danger": (DANGER_BG, DANGER_FG)}[severity]
    label = "ALL RECONCILED" if severity == "ok" else f"{flagged} VARIANCE(S) FLAGGED — REVIEW"
    t = Table([[Paragraph(f"<b>{label}</b>", S["kpiNum"])]],
              colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("TEXTCOLOR",     (0, 0), (-1, -1), fg),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return t


# ============================ 12-Month tables =================================
def _summary_table(summary: Dict[str, Any], kind: str, S):
    """kind = 'outward' | 'itc'."""
    rows = summary.get("rows", []) or []
    totals = summary.get("totals", {}) or {}

    if kind == "outward":
        headers = ["Month", "Books", "GSTR-1", "GSTR-3B",
                   "Books−R1", "R1−R3B"]
        keys = ["books_outward_taxable", "r1_outward_taxable", "r3b_outward_taxable",
                "var_books_vs_r1_outward", "var_r1_vs_r3b_outward"]
    else:  # itc
        headers = ["Month", "Books", "GSTR-2B", "GSTR-3B",
                   "Books−R2B", "R2B−R3B"]
        keys = ["books_itc_total", "r2b_itc_total", "r3b_itc_total",
                "var_books_vs_r2b_itc", "var_r2b_vs_r3b_itc"]

    body: List[List[Any]] = [headers]
    variance_cells: List[tuple] = []  # (col, row, severity)

    for ridx, r in enumerate(rows, start=1):
        line = [r.get("month_label", "")] + [_inr(r.get(k)) for k in keys]
        body.append(line)
        # last 2 columns are variances → flag severity
        for col_offset, var_key in enumerate(keys[-2:], start=4):
            sev = _severity(r.get(var_key) or 0.0)
            if sev != "ok":
                variance_cells.append((col_offset, ridx, sev))

    body.append(["Annual Total"] + [_inr(totals.get(k)) for k in keys])

    t = Table(body, colWidths=[24 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm],
              repeatRows=1)
    style = [
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR",  (0, 0), (-1, 0), HEADER_FG),
        ("ALIGN",      (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",      (0, 0), (0, -1),  "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), SECTION_BG),
        ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",  (0, 0), (-1, 0), 0.6, INK),
        ("LINEABOVE",  (0, -1), (-1, -1), 0.5, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]
    for col, row, sev in variance_cells:
        bg = WARN_BG if sev == "warn" else DANGER_BG
        fg = WARN_FG if sev == "warn" else DANGER_FG
        style += [
            ("BACKGROUND", (col, row), (col, row), bg),
            ("TEXTCOLOR",  (col, row), (col, row), fg),
        ]
    t.setStyle(TableStyle(style))
    return t


# ============================ Party-wise tables ==============================
def _partywise_table(partywise: Dict[str, Any], direction: str, S, top_n: int = 15):
    rows = list(partywise.get("rows") or [])
    totals = partywise.get("totals", {}) or {}

    portal_label = "GSTR-1" if direction == "outward" else "GSTR-2B"
    if direction == "inward":
        # ITC view — show tax (igst+cgst+sgst+cess)
        b_key, p_key, d_key = "books_tax", "portal_tax", "diff_tax"
        money_label = "ITC"
    else:
        b_key, p_key, d_key = "books_taxable", "portal_taxable", "diff_taxable"
        money_label = "Taxable"

    rows.sort(key=lambda r: abs(r.get(d_key) or 0.0), reverse=True)
    extra = max(0, len(rows) - top_n)
    rows = rows[:top_n]

    headers = ["Party GSTIN", "Party Name",
               f"Books {money_label}", f"{portal_label} {money_label}", "Δ"]
    body: List[List[Any]] = [headers]
    flagged_rows: List[tuple] = []

    for ridx, r in enumerate(rows, start=1):
        body.append([
            r.get("party_gstin", ""),
            r.get("party_name", "") or "",
            _inr(r.get(b_key)),
            _inr(r.get(p_key)),
            _inr(r.get(d_key)),
        ])
        sev = _severity(r.get(d_key) or 0.0)
        if sev != "ok":
            flagged_rows.append((ridx, sev))

    if extra:
        body.append([f"+ {extra} more parties (see Excel for full list)", "", "", "", ""])

    body.append(["Total", "",
                 _inr(totals.get(b_key)),
                 _inr(totals.get(p_key)),
                 _inr(totals.get(d_key))])

    t = Table(body, colWidths=[30 * mm, 60 * mm, 30 * mm, 30 * mm, 30 * mm],
              repeatRows=1)
    style = [
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR",  (0, 0), (-1, 0), HEADER_FG),
        ("ALIGN",      (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN",      (0, 0), (1, -1),  "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), SECTION_BG),
        ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",  (0, 0), (-1, 0), 0.6, INK),
        ("LINEABOVE",  (0, -1), (-1, -1), 0.5, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]
    for ridx, sev in flagged_rows:
        bg = WARN_BG if sev == "warn" else DANGER_BG
        fg = WARN_FG if sev == "warn" else DANGER_FG
        style += [
            ("BACKGROUND", (4, ridx), (4, ridx), bg),
            ("TEXTCOLOR",  (4, ridx), (4, ridx), fg),
        ]
    if extra:
        # The "+ N more" row is right above the totals row; highlight it muted
        more_row = len(body) - 2
        style += [
            ("SPAN", (0, more_row), (-1, more_row)),
            ("FONTSIZE", (0, more_row), (-1, more_row), 7),
            ("TEXTCOLOR", (0, more_row), (-1, more_row), MUTED),
            ("ALIGN", (0, more_row), (-1, more_row), "LEFT"),
            ("BACKGROUND", (0, more_row), (-1, more_row), ROW_ALT),
        ]
    t.setStyle(TableStyle(style))
    return t


# ============================ Cover header ===================================
def _client_header(run: Dict[str, Any], client: Optional[Dict[str, Any]], S):
    name = (client or {}).get("name", "—") if client else "—"
    gstin = (client or {}).get("gstin") or run.get("client_gstin") or "—"
    fy = run.get("fy", "—")
    rid = run.get("id", "")
    generated = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    file_no = (client or {}).get("file_number") or "—"

    rows = [
        [Paragraph("CLIENT", S["label"]),
         Paragraph(f"<b>{name}</b>", S["body"]),
         Paragraph("FILE NO", S["label"]),
         Paragraph(file_no, S["labelMono"])],
        [Paragraph("GSTIN", S["label"]),
         Paragraph(gstin, S["labelMono"]),
         Paragraph("RUN ID", S["label"]),
         Paragraph(rid[:18] + "…" if len(rid) > 20 else rid, S["labelMono"])],
        [Paragraph("FINANCIAL YEAR", S["label"]),
         Paragraph(fy, S["body"]),
         Paragraph("GENERATED", S["label"]),
         Paragraph(generated, S["labelMono"])],
    ]
    t = Table(rows, colWidths=[28 * mm, 70 * mm, 22 * mm, 60 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


# ============================ Sign-off block =================================
def _signoff_block(S):
    cells = [
        [Paragraph("PREPARED BY", S["label"]),
         Paragraph("REVIEWED BY", S["label"]),
         Paragraph("DATE", S["label"])],
        [Paragraph("&nbsp;<br/>&nbsp;<br/>______________________",
                   S["body"]),
         Paragraph("&nbsp;<br/>&nbsp;<br/>______________________",
                   S["body"]),
         Paragraph("&nbsp;<br/>&nbsp;<br/>______________________",
                   S["body"])],
        [Paragraph("Name & Signature", S["kpiHint"]),
         Paragraph("Name & Signature", S["kpiHint"]),
         Paragraph("DD-MM-YYYY", S["kpiHint"])],
    ]
    t = Table(cells, colWidths=[60 * mm, 60 * mm, 60 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBETWEEN", (0, 0), (-1, -1), 0.3, BORDER),
    ]))
    return t


# ============================ Page footer ====================================
def _make_footer_drawer(S, run: Dict[str, Any]):
    rid = run.get("id", "")[:18]
    fy = run.get("fy", "")
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        text = f"GST Recon Working-Paper · FY {fy} · Run {rid} · Page {doc.page}"
        canvas.drawString(15 * mm, 10 * mm, text)
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm,
                               "AssureAI · Audit Utilities")
        canvas.restoreState()
    return _draw


# ============================ Public entry ====================================
def build_pdf(run: Dict[str, Any],
              summary: Dict[str, Any],
              partywise_outward: Optional[Dict[str, Any]] = None,
              partywise_inward: Optional[Dict[str, Any]] = None,
              client: Optional[Dict[str, Any]] = None) -> bytes:
    """Build the PDF working-paper and return its bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="GST Recon Working-Paper",
        author="AssureAI",
    )
    S = _styles()
    story: List[Any] = []

    # ───────── Page 1 — Cover + Health ─────────
    story.append(Paragraph("GST Turnover &amp; ITC Reconciliation",
                           S["h1"]))
    story.append(Paragraph("Audit Working-Paper · Section 44AB",
                           S["body"]))
    story.append(Spacer(1, 4))
    story.append(_client_header(run, client, S))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Reconciliation Health", S["h2"]))
    story.append(_status_banner(summary, S))
    story.append(Spacer(1, 6))
    story.append(_dashboard_kpis(summary, S))

    # ───────── Page 2..3 — 12-Month tables ─────────
    story.append(PageBreak())
    story.append(Paragraph("12-Month Reconciliation · Outward Turnover",
                           S["h2"]))
    story.append(_summary_table(summary, "outward", S))
    story.append(Spacer(1, 12))
    story.append(Paragraph("12-Month Reconciliation · Input Tax Credit",
                           S["h2"]))
    story.append(_summary_table(summary, "itc", S))

    # ───────── Page 4..N — Party-wise ─────────
    if partywise_outward and (partywise_outward.get("rows") or []):
        story.append(PageBreak())
        story.append(Paragraph(
            "Annual Party-wise · Outward (Books vs GSTR-1)", S["h2"]))
        story.append(_partywise_table(partywise_outward, "outward", S))

    if partywise_inward and (partywise_inward.get("rows") or []):
        story.append(PageBreak())
        story.append(Paragraph(
            "Annual Party-wise · Inward / ITC (Books vs GSTR-2B)", S["h2"]))
        story.append(_partywise_table(partywise_inward, "inward", S))

    # ───────── Sign-off ─────────
    story.append(PageBreak())
    story.append(Paragraph("Sign-off", S["h2"]))
    story.append(Paragraph(
        "Notes: This working-paper is auto-generated from the uploaded Tally Books, "
        "GSTR-1, GSTR-2B and GSTR-3B JSON/PDF files. Variances above ₹1 lakh are "
        "highlighted in red; variances above ₹1 are highlighted in amber. The full "
        "voucher-level reconciliation (every Books ↔ Portal pair) is available in "
        "the companion Excel workbook.",
        S["body"]))
    story.append(Spacer(1, 16))
    story.append(_signoff_block(S))

    drawer = _make_footer_drawer(S, run)
    doc.build(story, onFirstPage=drawer, onLaterPages=drawer)
    return buf.getvalue()
