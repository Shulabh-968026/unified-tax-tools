"""Fixed Assets — Signature-ready PDF working-paper.

A4 portrait, multi-page, two-section deliverable a CA can attach to the
audit file alongside (or instead of) the multi-sheet Excel:

  Page 1   — Cover · Block-level IT Depreciation Schedule + grand totals
  Page 2+  — Additions Register, one card per asset:
              Row A — PTU Date · Particulars · Supplier · Capitalised Cost
              Row B — voucher / invoice / block / cost breakdown (muted)

Pure Python via reportlab.
"""
from __future__ import annotations
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)


# ============================ Theme ====================================
INK         = colors.HexColor("#0F172A")  # slate-900
INK_SOFT    = colors.HexColor("#334155")  # slate-700
MUTED       = colors.HexColor("#64748B")  # slate-500
FAINT       = colors.HexColor("#94A3B8")  # slate-400
BORDER      = colors.HexColor("#E2E8F0")  # slate-200
HAIR        = colors.HexColor("#CBD5E1")  # slate-300
HEADER_BG   = colors.HexColor("#0F172A")  # slate-900
HEADER_FG   = colors.HexColor("#FFFFFF")
ROW_ALT     = colors.HexColor("#F8FAFC")  # slate-50
PANEL_BG    = colors.HexColor("#F1F5F9")  # slate-100
ACCENT      = colors.HexColor("#0369A1")  # sky-700
ACCENT_BG   = colors.HexColor("#E0F2FE")  # sky-100
DANGER      = colors.HexColor("#B91C1C")  # red-700
DANGER_BG   = colors.HexColor("#FEE2E2")  # red-100


# ============================ Styles ====================================
def _styles():
    return {
        "h1":      ParagraphStyle("h1",      fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=INK),
        "h2":      ParagraphStyle("h2",      fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK),
        "kicker":  ParagraphStyle("kicker",  fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=MUTED, spaceAfter=2),
        "body":    ParagraphStyle("body",    fontName="Helvetica", fontSize=9.5, leading=12, textColor=INK_SOFT),
        "small":   ParagraphStyle("small",   fontName="Helvetica", fontSize=8, leading=10, textColor=MUTED),
        "muted":   ParagraphStyle("muted",   fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
        "card_t":  ParagraphStyle("card_t",  fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK),
        "card_b":  ParagraphStyle("card_b",  fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
        "amt":     ParagraphStyle("amt",     fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK, alignment=2),  # right
        "th":      ParagraphStyle("th",      fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=HEADER_FG, alignment=1),
        "td":      ParagraphStyle("td",      fontName="Helvetica", fontSize=8.5, leading=10, textColor=INK_SOFT),
        "td_r":    ParagraphStyle("td_r",    fontName="Helvetica", fontSize=8.5, leading=10, textColor=INK_SOFT, alignment=2),
        "td_b":    ParagraphStyle("td_b",    fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=INK, alignment=2),
        "summ_th": ParagraphStyle("summ_th", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=HEADER_FG, alignment=1),
        "summ_l":  ParagraphStyle("summ_l",  fontName="Helvetica", fontSize=7.5, leading=9, textColor=INK_SOFT),
        "summ_r":  ParagraphStyle("summ_r",  fontName="Helvetica", fontSize=7.5, leading=9, textColor=INK_SOFT, alignment=2),
        "summ_b":  ParagraphStyle("summ_b",  fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=INK, alignment=2),
    }


# ============================ Formatters ===============================
def _inr(v: Optional[float]) -> str:
    n = float(v or 0)
    if n == 0:
        return "—"
    s = f"{abs(n):,.2f}"
    # Indian grouping (lakhs/crores) — convert 1234567.89 → 12,34,567.89
    parts = s.split(".")
    intpart = parts[0].replace(",", "")
    if len(intpart) > 3:
        last3 = intpart[-3:]
        rest  = intpart[:-3]
        rest  = ",".join([rest[max(0, i-2):i] for i in range(len(rest), 0, -2)][::-1])
        intpart = f"{rest},{last3}"
    formatted = intpart + ("." + parts[1] if len(parts) > 1 else "")
    return f"({formatted})" if n < 0 else formatted


def _fmt_date(s: Any) -> str:
    if not s:
        return "—"
    s = str(s)[:10]
    return s if len(s) == 10 else "—"


# ============================ Page chrome ==============================
def _page_chrome(
    *, client_name: str, fy_label: str, run_name: str, doc_title: str,
):
    def draw(canvas, doc):
        canvas.saveState()
        # Header band
        canvas.setStrokeColor(BORDER)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(15 * mm, A4[1] - 12 * mm, doc_title)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 12 * mm,
                               f"{client_name}  ·  FY {fy_label}")
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(15 * mm, A4[1] - 14 * mm, A4[0] - 15 * mm, A4[1] - 14 * mm)
        # Footer band
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(15 * mm, 10 * mm, f"{run_name}")
        canvas.drawCentredString(A4[0] / 2, 10 * mm, "MSS × Assure  ·  Audit Working-Paper")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.line(15 * mm, 13 * mm, A4[0] - 15 * mm, 13 * mm)
        canvas.restoreState()
    return draw


# ============================ Cover + summary ==========================
def _cover_block(*, client_name: str, fy_label: str, fy_start: str, fy_end: str,
                 run_name: str, totals: Dict[str, float],
                 stamp_iso: str) -> List[Any]:
    s = _styles()
    out: List[Any] = []
    out.append(Paragraph("IT Depreciation Schedule", s["h1"]))
    out.append(Spacer(1, 1 * mm))
    out.append(Paragraph(f"{client_name}  ·  FY {fy_label}", s["body"]))
    out.append(Paragraph(
        f"Period {fy_start} to {fy_end}  ·  Generated {stamp_iso[:10]} {stamp_iso[11:16]} UTC  ·  Run {run_name}",
        s["small"],
    ))
    out.append(Spacer(1, 5 * mm))

    # KPI strip — 4 metric cards
    def card(label, amount, accent=False):
        cell = [
            [Paragraph(label.upper(), s["kicker"])],
            [Paragraph(f"₹ {_inr(amount)}", s["card_t"])],
        ]
        t = Table(cell, colWidths=[42.5 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("BACKGROUND", (0, 0), (-1, -1), ACCENT_BG if accent else PANEL_BG),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    grid = Table([[
        card("Opening WDV", totals.get("opening_wdv", 0)),
        card("Capitalised Adds", totals.get("adds_full", 0) + totals.get("adds_half", 0)),
        card("Depreciation", totals.get("depreciation", 0), accent=True),
        card("Closing WDV", totals.get("closing_wdv", 0)),
    ]], colWidths=[44 * mm] * 4)
    grid.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    out.append(grid)
    out.append(Spacer(1, 6 * mm))
    return out


# ============================ Block summary table =====================
def _block_summary_table(rows: List[Dict[str, Any]], totals: Dict[str, float]) -> Table:
    s = _styles()
    head = [
        Paragraph("Block", s["summ_th"]),
        Paragraph("Rate", s["summ_th"]),
        Paragraph("Opening WDV", s["summ_th"]),
        Paragraph("Adds ≥ 180d", s["summ_th"]),
        Paragraph("Adds < 180d", s["summ_th"]),
        Paragraph("Sales", s["summ_th"]),
        Paragraph("Depn", s["summ_th"]),
        Paragraph("Closing WDV", s["summ_th"]),
    ]
    data = [head]
    for r in rows:
        data.append([
            Paragraph(r["block_label"], s["summ_l"]),
            Paragraph(f"{int(round(r['rate']))}%", ParagraphStyle("c", parent=s["summ_l"], alignment=1)),
            Paragraph(_inr(r["opening_wdv"]), s["summ_r"]),
            Paragraph(_inr(r["adds_full"]), s["summ_r"]),
            Paragraph(_inr(r["adds_half"]), s["summ_r"]),
            Paragraph(_inr(r["deletions"]), s["summ_r"]),
            Paragraph(_inr(r["depreciation"]), s["summ_b"]),
            Paragraph(_inr(r["closing_wdv"]), s["summ_b"]),
        ])
    data.append([
        Paragraph("TOTAL", ParagraphStyle("totl", parent=s["summ_l"], textColor=INK, fontName="Helvetica-Bold")),
        Paragraph("", s["summ_l"]),
        Paragraph(_inr(totals.get("opening_wdv")), s["summ_b"]),
        Paragraph(_inr(totals.get("adds_full")), s["summ_b"]),
        Paragraph(_inr(totals.get("adds_half")), s["summ_b"]),
        Paragraph(_inr(totals.get("deletions")), s["summ_b"]),
        Paragraph(_inr(totals.get("depreciation")), s["summ_b"]),
        Paragraph(_inr(totals.get("closing_wdv")), s["summ_b"]),
    ])

    # Column widths sum = 180mm (A4 portrait usable width = 210 − 2×15 mm)
    widths = [48 * mm, 10 * mm, 22 * mm, 22 * mm, 22 * mm, 17 * mm, 17 * mm, 22 * mm]
    tbl = Table(data, colWidths=widths, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), PANEL_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    tbl.setStyle(style)
    return tbl


# ============================ Additions Register ======================
def _block_header_strip(*, block_label: str, rate: float, count: int, total: float, widths) -> Table:
    """Sticky-style block sub-header rendered as a single-row table that
    spans the same column widths as the asset cards underneath. Slate-900
    band on the left with the block name; muted right-aligned summary
    `N assets · ₹X.XX`."""
    rate_pill = (
        f"<font face='Helvetica-Bold' size='8' color='#FACC15'>"
        f"{int(round(rate))}%</font>"
    )
    left = Paragraph(
        f"<font face='Helvetica-Bold' size='10.5' color='#FFFFFF'>{_p(block_label)}</font>"
        f"&nbsp;&nbsp;&nbsp;{rate_pill}",
        ParagraphStyle("blkL", fontName="Helvetica-Bold",
                       fontSize=10.5, textColor=HEADER_FG, leading=13),
    )
    right = Paragraph(
        f"<font face='Helvetica' size='8.5' color='#CBD5E1'>"
        f"{count} asset{'s' if count != 1 else ''} &nbsp;·&nbsp; "
        f"₹ {_inr(total)}</font>",
        ParagraphStyle("blkR", fontName="Helvetica", fontSize=8.5,
                       textColor=HEADER_FG, leading=11, alignment=2),
    )
    # Merge widths into 2 logical halves so the right text gets the
    # capitalised-cost column real estate.
    left_w = sum(widths[:2])
    right_w = widths[2]
    t = Table([[left, right]], colWidths=[left_w, right_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _column_header_strip(widths) -> Table:
    """Three-column sub-header rendered in slate-50 below each block strip.
    Provides the auditor with a column-name reference per block."""
    th = ParagraphStyle("th2", fontName="Helvetica-Bold", fontSize=7.5,
                        leading=9, textColor=MUTED, alignment=0,
                        spaceAfter=0)
    th_r = ParagraphStyle("th2r", parent=th, alignment=2)
    hdr = [
        Paragraph("PTU DATE", th),
        Paragraph("PARTICULARS / SUPPLIER", th),
        Paragraph("CAPITALISED COST", th_r),
    ]
    t = Table([hdr], colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ROW_ALT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HAIR),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _asset_card(a: Dict[str, Any], widths) -> List[Any]:
    """One asset card: Row A (primary scan path) + Row B (muted metadata)."""
    from modules.fixed_assets.compute import adjusted_cost
    s = _styles()
    cap = adjusted_cost(a)
    ptu = _fmt_date(a.get("put_to_use_date") or a.get("invoice_date"))
    title = (a.get("description") or a.get("particulars") or "(no description)").strip()
    supplier = (a.get("party_name") or "").strip() or "—"
    half = " · ½ rate" if not a.get("is_more_than_180", True) else ""

    row_a = [[
        Paragraph(ptu, s["td"]),
        Paragraph(
            f"<b>{_p(title)}</b><br/>"
            f"<font color='#64748B'>{_p(supplier)}</font>",
            ParagraphStyle("pt", parent=s["td"], leading=11),
        ),
        Paragraph(f"<b>₹ {_inr(cap)}</b>{half}", s["td_b"]),
    ]]
    ta = Table(row_a, colWidths=widths)
    ta.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    # ------ Row B — muted metadata strip ---------
    meta_bits = []
    if a.get("voucher_no"):
        meta_bits.append(f"<b>Voucher</b> {_p(a['voucher_no'])}")
    if a.get("invoice_no"):
        meta_bits.append(f"<b>Inv #</b> {_p(a['invoice_no'])}")
    inv_dt = _fmt_date(a.get("invoice_date"))
    if inv_dt != "—":
        meta_bits.append(f"<b>Inv Dt</b> {inv_dt}")
    if a.get("ledger_name"):
        meta_bits.append(f"<b>Ledger</b> {_p(a['ledger_name'])}")

    breakdown_bits = []
    ic = float(a.get("invoice_cost") or 0)
    if ic:
        breakdown_bits.append(f"Inv ₹{_inr(ic)}")
    for k, label, sign in (
        ("other_expenses", "Other Exp", "+"),
        ("itc_reversed",   "ITC Rev",   "−"),
        ("interest_capitalized", "Int Cap", "+"),
        ("forex_fluctuations", "Forex", "+"),
        ("discount_credits", "Disc/Cr", "−"),
    ):
        v = float(a.get(k) or 0)
        if v:
            breakdown_bits.append(f"{sign} {label} ₹{_inr(v)}")

    meta_html = "  ·  ".join(meta_bits) if meta_bits else "—"
    breakdown_html = "  ".join(breakdown_bits) if breakdown_bits else ""
    row_b = [[
        Paragraph("", s["small"]),
        Paragraph(
            f"<font color='#64748B'>{meta_html}</font>"
            + (f"<br/><font color='#94A3B8'>{breakdown_html}</font>" if breakdown_html else ""),
            ParagraphStyle("meta", parent=s["small"], leading=10),
        ),
        Paragraph("", s["small"]),
    ]]
    tb = Table(row_b, colWidths=widths)
    tb.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [ta, tb]


def _additions_section(
    additions: List[Dict[str, Any]],
    block_meta: Dict[str, float],
) -> List[Any]:
    """Block-grouped additions register. Each block gets a sticky-style
    header strip (block name · rate · asset count · capitalised total)
    followed by its asset cards. Blocks are ordered by descending rate
    so the audit reads top-down by impact."""
    from modules.fixed_assets.compute import adjusted_cost
    s = _styles()
    out: List[Any] = []
    out.append(Paragraph("Additions Register", s["h1"]))
    out.append(Paragraph(
        f"{len(additions)} asset(s) capitalised in this run, grouped by IT Block.",
        s["small"],
    ))
    out.append(Spacer(1, 4 * mm))

    if not additions:
        out.append(Paragraph("No additions recorded.", s["muted"]))
        return out

    widths = [22 * mm, 130 * mm, 28 * mm]

    # Group by block_label; preserve the user's intended audit order
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for a in additions:
        bl = a.get("block_label") or "(Unclassified)"
        groups.setdefault(bl, []).append(a)

    # Sort blocks by descending rate (using block_meta for the rate
    # lookup; fall back to 0 for unclassified).
    ordered_blocks = sorted(
        groups.keys(),
        key=lambda bl: (-(float(block_meta.get(bl) or 0)), bl),
    )

    for idx, bl in enumerate(ordered_blocks):
        cards = groups[bl]
        # Sort cards within a block by PTU date, then supplier
        cards.sort(key=lambda a: (
            (a.get("put_to_use_date") or a.get("invoice_date") or ""),
            a.get("party_name") or "",
        ))
        rate = float(block_meta.get(bl) or 0)
        block_total = sum(adjusted_cost(a) for a in cards)

        # Glue the block header + column header + first asset together
        # so a block strip never gets orphaned at the bottom of a page.
        header_bundle: List[Any] = [
            _block_header_strip(
                block_label=bl, rate=rate,
                count=len(cards), total=block_total,
                widths=widths,
            ),
            _column_header_strip(widths),
        ]
        first_card = _asset_card(cards[0], widths)
        out.append(KeepTogether(header_bundle + first_card))

        for a in cards[1:]:
            out.append(KeepTogether(_asset_card(a, widths)))

        # Light separator between blocks (skip after the last group)
        if idx != len(ordered_blocks) - 1:
            out.append(Spacer(1, 5 * mm))

    return out


def _p(text: Any) -> str:
    """Tiny defensive escape for Paragraph() — strips inline tags + escapes < & >."""
    s = str(text or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:200]


# ============================ Public entry =============================
def build_pdf(
    *,
    client_name: str,
    fy_label: str,
    fy_start: str,
    fy_end: str,
    run_name: str,
    rows: List[Dict[str, Any]],
    totals: Dict[str, float],
    additions: List[Dict[str, Any]],
    block_meta: Dict[str, float] | None = None,
) -> bytes:
    """Render the working-paper as A4 portrait PDF bytes.

    `block_meta`: {block_label: rate} for sub-header rendering. If omitted,
    derived from `rows` (which carry rate per block_label)."""
    bio = io.BytesIO()
    doc = BaseDocTemplate(
        bio, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title=f"IT Depreciation — {client_name} {fy_label}",
        author="MSS × Assure",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height,
                  id="main", showBoundary=0)
    chrome = _page_chrome(
        client_name=client_name, fy_label=fy_label,
        run_name=run_name,
        doc_title="IT Depreciation Working-Paper",
    )
    doc.addPageTemplates([PageTemplate(id="A4", frames=[frame], onPage=chrome)])

    if block_meta is None:
        block_meta = {r["block_label"]: float(r.get("rate") or 0) for r in rows}

    stamp_iso = datetime.now(timezone.utc).isoformat()
    story: List[Any] = []
    story.extend(_cover_block(
        client_name=client_name, fy_label=fy_label,
        fy_start=fy_start, fy_end=fy_end, run_name=run_name,
        totals=totals, stamp_iso=stamp_iso,
    ))
    story.append(_block_summary_table(rows, totals))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Computation per Sec 32 (WDV method). Adds &lt; 180 days ⇒ half rate. "
        "Sales first reduce the full-rate pool; STCG u/s 50 when block extinguished.",
        _styles()["muted"],
    ))
    story.append(PageBreak())
    story.extend(_additions_section(additions, block_meta))

    doc.build(story)
    return bio.getvalue()


__all__ = ["build_pdf"]
