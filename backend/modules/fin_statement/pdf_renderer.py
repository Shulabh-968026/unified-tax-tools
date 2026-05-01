"""FS Designer PDF renderer.

Two templates — ``classic`` (B/W compliance look) and ``boardroom``
(slate + sky accents). Both share the same content; they differ in
palette + cover treatment.

Layout:
  - Page 1  : Cover strip (company + FY) + Balance Sheet + P&L +
              Cash Flow, all on a single A4 landscape page with 3
              column-stacked tables.
  - Page 2+ : Notes, each wrapped in ``KeepTogether`` so a note never
              breaks awkwardly across pages.
  - Last page(s): Fixed-asset / PPE schedule + Signatory block.
"""
from __future__ import annotations
import io
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, PageBreak, Paragraph,
    Spacer, Table, TableStyle, KeepTogether,
)
from reportlab.platypus.doctemplate import NextPageTemplate

from modules.fin_statement.pdf_common import (
    CLASSIC, BOARDROOM, inr, mk_styles,
    build_statement_table, build_cashflow_table,
    build_note_block, build_signatory_block,
)


def _page_header(canvas, doc, company_name: str, period_label: str, palette):
    canvas.saveState()
    canvas.setFillColor(palette["ink"])
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(doc.leftMargin, doc.pagesize[1] - 9 * mm,
                      (company_name or "").upper())
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(palette["mute"])
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin,
                           doc.pagesize[1] - 9 * mm,
                           period_label)
    canvas.setStrokeColor(palette["hair"])
    canvas.setLineWidth(0.3)
    canvas.line(doc.leftMargin, doc.pagesize[1] - 11 * mm,
                doc.pagesize[0] - doc.rightMargin,
                doc.pagesize[1] - 11 * mm)
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(palette["mute"])
    canvas.drawCentredString(
        doc.pagesize[0] / 2, 7 * mm,
        f"Page {doc.page}",
    )
    canvas.drawString(doc.leftMargin, 7 * mm, "Financial Statements · FY " + period_label)
    canvas.restoreState()


def _cover_block(doc_data: Dict[str, Any], palette, styles) -> List[Any]:
    """Compact cover strip — title + period only. Page-1 real estate is
    precious since the 3 statements need to fit in ~524 pt vertical."""
    pd = doc_data.get("period", {})
    fy_cur = pd.get("fy_current", "")
    fy_prev = pd.get("fy_previous", "")
    title_style = ParagraphStyle(
        "cover_title", fontName="Helvetica-Bold", fontSize=10, leading=11,
        textColor=palette["ink"], spaceAfter=0,
    )
    line = (
        f"Balance Sheet, Statement of Profit &amp; Loss and Cash Flow Statement  ·  "
        f"FY {fy_cur}"
        + (f" (with FY {fy_prev} comparatives)" if fy_prev else "")
    )
    return [
        Paragraph(line, title_style),
        Spacer(1, 1 * mm),
    ]


def _statements_three_col(
    doc_data: Dict[str, Any], palette, styles, content_width: float
) -> Table:
    """3-column layout: BS | P&L | CFS side-by-side, all on one landscape page."""
    pd = doc_data["period"]
    fy_cur = pd.get("fy_current", "")
    fy_prev = pd.get("fy_previous", "")

    col_w = content_width / 3.0
    gap = 3 * mm
    inner_w = col_w - gap

    # Each inner table has 4 cols (label, note, cy, py). Allocate ~56/8/18/18.
    iw = (inner_w * 0.56, inner_w * 0.08, inner_w * 0.18, inner_w * 0.18)

    bs = build_statement_table("Balance Sheet",
                               doc_data["balance_sheet"], fy_cur, fy_prev,
                               palette, styles, iw)
    pl = build_statement_table("Statement of Profit & Loss",
                               doc_data["profit_loss"], fy_cur, fy_prev,
                               palette, styles, iw)
    cfs_iw = (inner_w * 0.60, inner_w * 0.06, inner_w * 0.17, inner_w * 0.17)
    cfs = build_cashflow_table(doc_data["cash_flow"], fy_cur, fy_prev,
                               palette, styles, cfs_iw)

    shell = Table([[bs, pl, cfs]],
                  colWidths=(col_w, col_w, col_w))
    shell.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return shell


def _fa_schedule_block(fa: Dict[str, Any], palette, styles,
                       content_width: float) -> List[Any]:
    if not fa or (not fa.get("subheads") and not fa.get("total", {}).get("closing_cost")):
        return []
    flow: List[Any] = []
    flow.append(Paragraph("Property, Plant & Equipment — Schedule", styles["h2"]))
    flow.append(Spacer(1, 1.5 * mm))

    head = ["Particulars", "Opening Cost", "Additions", "Deletions",
            "Closing Cost", "Opening Depn", "Depn for Year",
            "Closing Depn", "Closing WDV"]
    rows = [head]
    for s in fa.get("subheads", []):
        rows.append([
            s.get("label", ""),
            inr(s.get("opening_cost", 0)),
            inr(s.get("additions", 0)),
            inr(s.get("deletions", 0)),
            inr(s.get("closing_cost", 0)),
            inr(s.get("opening_depreciation", 0)),
            inr(s.get("depreciation_for_year", 0)),
            inr(s.get("closing_depreciation", 0)),
            inr(s.get("closing_written_down_value", 0)),
        ])
    tot = fa.get("total", {})
    rows.append([
        "Total",
        inr(tot.get("opening_cost", 0)),
        inr(tot.get("additions", 0)),
        inr(tot.get("deletions", 0)),
        inr(tot.get("closing_cost", 0)),
        inr(tot.get("opening_depreciation", 0)),
        inr(tot.get("depreciation_for_year", 0)),
        inr(tot.get("closing_depreciation", 0)),
        inr(tot.get("closing_written_down_value", 0)),
    ])
    col_w = [content_width * 0.22] + [content_width * 0.0975] * 8
    t = Table(rows, colWidths=col_w, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["table_hdr_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), palette["table_hdr_fg"]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [palette["alt"], "white"]),
        ("BOX", (0, 0), (-1, -1), 0.4, palette["hair"]),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))
    return flow


def render_pdf(doc_data: Dict[str, Any], template: str = "classic") -> bytes:
    """Render the full FS pack as a PDF and return the bytes."""
    palette = BOARDROOM if template == "boardroom" else CLASSIC
    styles = mk_styles(palette, body_size=5.8)

    buf = io.BytesIO()
    landscape_size = landscape(A4)
    portrait_size = A4

    doc = BaseDocTemplate(
        buf,
        pagesize=landscape_size,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=14 * mm, bottomMargin=11 * mm,
        title=f"{doc_data.get('company', {}).get('name', 'Financial Statements')} — "
              f"FY {doc_data.get('period', {}).get('fy_current', '')}",
    )

    # Landscape frame for page 1 (3 statements)
    lw, lh = landscape_size
    land_frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        lw - doc.leftMargin - doc.rightMargin,
        lh - doc.topMargin - doc.bottomMargin,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="landscape",
    )
    # Portrait frames for notes + signatory
    pw, ph = portrait_size
    port_frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        pw - doc.leftMargin - doc.rightMargin,
        ph - doc.topMargin - doc.bottomMargin,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="portrait",
    )

    co_name = doc_data.get("company", {}).get("name", "")
    fy_cur = doc_data.get("period", {}).get("fy_current", "")

    def _h_land(c, d):
        c.setPageSize(landscape_size)
        d.pagesize = landscape_size
        _page_header(c, d, co_name, fy_cur, palette)

    def _h_port(c, d):
        c.setPageSize(portrait_size)
        d.pagesize = portrait_size
        _page_header(c, d, co_name, fy_cur, palette)

    doc.addPageTemplates([
        PageTemplate(id="Landscape", frames=[land_frame], onPage=_h_land,
                     pagesize=landscape_size),
        PageTemplate(id="Portrait", frames=[port_frame], onPage=_h_port,
                     pagesize=portrait_size),
    ])

    story: List[Any] = []

    # ----- Page 1: Cover + 3 statements side-by-side -------------
    story.extend(_cover_block(doc_data, palette, styles))
    landscape_content_width = lw - doc.leftMargin - doc.rightMargin
    story.append(_statements_three_col(doc_data, palette, styles,
                                       landscape_content_width))

    # ----- Switch to portrait for Notes ---------------------------
    story.append(NextPageTemplate("Portrait"))
    story.append(PageBreak())

    # Notes: one per KeepTogether block
    port_content_width = pw - doc.leftMargin - doc.rightMargin
    # Re-build portrait-specific styles at slightly larger body size
    notes_styles = mk_styles(palette, body_size=7.5)

    story.append(Paragraph("Notes forming part of the Financial Statements",
                           notes_styles["h1"]))
    story.append(Spacer(1, 2 * mm))

    for note in doc_data.get("notes", []):
        block = build_note_block(note, doc_data["period"].get("fy_current", ""),
                                 doc_data["period"].get("fy_previous", ""),
                                 palette, notes_styles, port_content_width)
        block.append(Spacer(1, 4 * mm))
        story.append(KeepTogether(block))

    # PPE schedule (its own section, may span pages)
    fa_block = _fa_schedule_block(doc_data.get("fixed_asset") or {}, palette,
                                  notes_styles, port_content_width)
    if fa_block:
        story.append(Spacer(1, 3 * mm))
        story.extend(fa_block)

    # Signatory block
    sig = doc_data.get("signatory") or {}
    if any(sig.values()):
        story.append(Spacer(1, 6 * mm))
        story.append(build_signatory_block(sig, palette, notes_styles,
                                           port_content_width))

    doc.build(story)
    return buf.getvalue()


__all__ = ["render_pdf"]
