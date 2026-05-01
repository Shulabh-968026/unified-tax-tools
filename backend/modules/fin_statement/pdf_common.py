"""Shared PDF helpers for the FS Designer templates.

Keep all the cross-template visual primitives here so the Classic and
Boardroom renderers diverge only in layout + accent colours.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer


# ----- number helpers -------------------------------------------------
def inr(v: float, dash_zero: bool = True) -> str:
    """Indian-style number formatting. 0 → '-' when dash_zero."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "-"
    if dash_zero and abs(n) < 0.005:
        return "-"
    s = f"{abs(n):,.2f}"
    # Convert to Indian grouping: 12,34,567.89
    int_part, _, dec_part = s.partition(".")
    int_part = int_part.replace(",", "")
    if len(int_part) <= 3:
        grouped = int_part
    else:
        head = int_part[:-3]
        tail = int_part[-3:]
        # group head in 2s from right
        rev = head[::-1]
        chunks = [rev[i:i + 2] for i in range(0, len(rev), 2)]
        head_grouped = ",".join(chunks)[::-1]
        grouped = f"{head_grouped},{tail}"
    formatted = f"{grouped}.{dec_part}"
    if n < 0:
        return f"({formatted})"
    return formatted


# ----- palette --------------------------------------------------------
CLASSIC = {
    "ink":       colors.HexColor("#0F172A"),
    "mute":      colors.HexColor("#475569"),
    "hair":      colors.HexColor("#CBD5E1"),
    "light":     colors.HexColor("#F1F5F9"),
    "accent":    colors.HexColor("#1F2937"),
    "table_hdr_bg": colors.HexColor("#1F2937"),
    "table_hdr_fg": colors.white,
    "alt":       colors.HexColor("#FAFAF7"),
}

BOARDROOM = {
    "ink":       colors.HexColor("#0F172A"),
    "mute":      colors.HexColor("#475569"),
    "hair":      colors.HexColor("#E2E8F0"),
    "light":     colors.HexColor("#F0F9FF"),
    "accent":    colors.HexColor("#0369A1"),
    "table_hdr_bg": colors.HexColor("#0C4A6E"),
    "table_hdr_fg": colors.white,
    "alt":       colors.HexColor("#F8FAFC"),
}


# ----- paragraph style factory ---------------------------------------
def mk_styles(palette: Dict[str, Any], body_size: float = 7.5) -> Dict[str, ParagraphStyle]:
    leading = max(body_size + 0.6, body_size * 1.08)
    base = dict(fontName="Helvetica", fontSize=body_size, leading=leading)
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13, leading=15,
                             textColor=palette["ink"], spaceAfter=1),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=9.5, leading=11,
                             textColor=palette["ink"], spaceAfter=1),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold",
                             fontSize=max(6.5, body_size - 0.5),
                             leading=max(7.5, body_size + 0.5),
                             textColor=palette["accent"], spaceAfter=0),
        "mono": ParagraphStyle("mono", fontName="Helvetica", fontSize=6.8, leading=8,
                               textColor=palette["mute"]),
        "body": ParagraphStyle("body", **base, textColor=palette["ink"]),
        "body_b": ParagraphStyle("body_b", **{**base, "fontName": "Helvetica-Bold"},
                                 textColor=palette["ink"]),
        "body_r": ParagraphStyle("body_r", **base, alignment=2, textColor=palette["ink"]),
        "body_rb": ParagraphStyle("body_rb", **{**base, "fontName": "Helvetica-Bold"},
                                  alignment=2, textColor=palette["ink"]),
        "body_mute": ParagraphStyle("body_mute", **base, textColor=palette["mute"]),
        "note_body": ParagraphStyle("note_body", fontName="Helvetica", fontSize=8,
                                    leading=10, textColor=palette["ink"]),
        "note_body_r": ParagraphStyle("note_body_r", fontName="Helvetica", fontSize=8,
                                      leading=10, alignment=2, textColor=palette["ink"]),
        "tiny": ParagraphStyle("tiny", fontName="Helvetica", fontSize=6.5, leading=8,
                               textColor=palette["mute"]),
    }


# ----- statement table (BS / P&L) -------------------------------------
def build_statement_table(
    title: str,
    rows: List[Dict[str, Any]],
    fy_cur: str,
    fy_prev: str,
    palette: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    col_widths: Tuple[float, float, float, float],
) -> Table:
    """Build a BS/P&L table. col_widths = (label, note, current, previous)."""
    header = [
        Paragraph(f"<b>{title}</b>", styles["h3"]),
        Paragraph("Note", styles["h3"]),
        Paragraph(f"FY {fy_cur}", styles["h3"]),
        Paragraph(f"FY {fy_prev}", styles["h3"]),
    ]
    data: List[List[Any]] = [header]
    row_styles: List[Tuple[str, Tuple[int, int], Tuple[int, int], Any]] = []
    for i, r in enumerate(rows, start=1):
        indent = "&nbsp;&nbsp;" * max(0, int(r.get("indent", 0)))
        label = r.get("label", "")
        label_html = f"{indent}{label}"
        is_h = r.get("is_header") or (r.get("indent", 0) == 0 and r.get("note") == "")
        is_sub = r.get("is_subtotal")
        lbl_style = styles["body_b"] if is_h else (
            styles["body_b"] if is_sub else styles["body"]
        )
        val_style = styles["body_rb"] if (is_h or is_sub) else styles["body_r"]
        data.append([
            Paragraph(label_html, lbl_style),
            Paragraph(str(r.get("note") or ""), styles["body_mute"]),
            Paragraph(inr(r.get("current", 0)), val_style),
            Paragraph(inr(r.get("previous", 0)), val_style),
        ])
        if is_h:
            row_styles.append(("LINEBELOW", (0, i), (-1, i), 0.4, palette["hair"]))
            row_styles.append(("BACKGROUND", (0, i), (-1, i), palette["light"]))

    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["table_hdr_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), palette["table_hdr_fg"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, palette["ink"]),
        ("VALIGN",    (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING",   (0, 0), (-1, -1), 0.8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0.8),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, palette["ink"]),
        ("BOX", (0, 0), (-1, -1), 0.4, palette["hair"]),
    ] + row_styles)
    t.setStyle(ts)
    return t


def build_cashflow_table(
    rows: List[Dict[str, Any]],
    fy_cur: str,
    fy_prev: str,
    palette: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    col_widths: Tuple[float, float, float, float],
) -> Table:
    header = [
        Paragraph("<b>Cash Flow Statement</b>", styles["h3"]),
        Paragraph("", styles["h3"]),
        Paragraph(f"FY {fy_cur}", styles["h3"]),
        Paragraph(f"FY {fy_prev}", styles["h3"]),
    ]
    data: List[List[Any]] = [header]
    row_styles: List[Tuple[str, Tuple[int, int], Tuple[int, int], Any]] = []
    for i, r in enumerate(rows, start=1):
        indent_html = "&nbsp;&nbsp;" * max(0, int(r.get("indent", 0)))
        is_h = r.get("is_header")
        is_b = r.get("is_bold")
        lbl_style = styles["body_b"] if (is_h or is_b) else styles["body"]
        val_style = styles["body_rb"] if (is_h or is_b) else styles["body_r"]
        label_html = f"{indent_html}{r.get('label', '')}"
        cy = "" if is_h and r.get("current", 0) == 0 else inr(r.get("current", 0))
        py = "" if is_h and r.get("previous", 0) == 0 else inr(r.get("previous", 0))
        data.append([
            Paragraph(label_html, lbl_style),
            Paragraph(str(r.get("serial") or ""), styles["body_mute"]),
            Paragraph(cy, val_style),
            Paragraph(py, val_style),
        ])
        if is_h:
            row_styles.append(("BACKGROUND", (0, i), (-1, i), palette["light"]))
            row_styles.append(("LINEBELOW", (0, i), (-1, i), 0.4, palette["hair"]))
        if r.get("line_top") and r["line_top"] != "NONE":
            row_styles.append(("LINEABOVE", (2, i), (3, i), 0.4, palette["ink"]))
        if r.get("line_below") and r["line_below"] != "NONE":
            row_styles.append(("LINEBELOW", (2, i), (3, i), 0.4, palette["ink"]))

    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["table_hdr_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), palette["table_hdr_fg"]),
        ("VALIGN",    (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING",   (0, 0), (-1, -1), 0.8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0.8),
        ("BOX", (0, 0), (-1, -1), 0.4, palette["hair"]),
    ] + row_styles)
    t.setStyle(ts)
    return t


# ----- note block -----------------------------------------------------
def build_note_block(
    note: Dict[str, Any],
    fy_cur: str,
    fy_prev: str,
    palette: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    content_width: float,
) -> List[Any]:
    """Return a list of flowables for a single Note block — intended to be
    wrapped in KeepTogether by the caller so notes never break awkwardly."""
    flow: List[Any] = []
    nn = note.get("note")
    title = note.get("title") or ""
    header_text = f"Note {nn}: {title}" if nn is not None else title
    flow.append(Paragraph(f"<b>{header_text}</b>", styles["h2"]))
    flow.append(Spacer(1, 1 * mm))

    # Sub-lines come from flattened children + details
    rows = note.get("children") or []
    if not rows:
        rows = note.get("details") or []

    col_widths = (content_width * 0.58, content_width * 0.21, content_width * 0.21)
    data: List[List[Any]] = [[
        Paragraph("<b>Particulars</b>", styles["h3"]),
        Paragraph(f"<b>FY {fy_cur}</b>", styles["h3"]),
        Paragraph(f"<b>FY {fy_prev}</b>", styles["h3"]),
    ]]
    for r in rows:
        indent_html = "&nbsp;&nbsp;" * max(0, int(r.get("indent", 0)))
        label = f"{indent_html}{r.get('label', '')}"
        is_sub = r.get("is_subtotal") or r.get("is_header")
        ls = styles["note_body"]
        if is_sub:
            label = f"<b>{label}</b>"
        data.append([
            Paragraph(label, ls),
            Paragraph(inr(r.get("current", 0)), styles["note_body_r"]),
            Paragraph(inr(r.get("previous", 0)), styles["note_body_r"]),
        ])
    # Total row
    data.append([
        Paragraph("<b>Total</b>", styles["note_body"]),
        Paragraph(f"<b>{inr(note.get('current', 0))}</b>", styles["note_body_r"]),
        Paragraph(f"<b>{inr(note.get('previous', 0))}</b>", styles["note_body_r"]),
    ])
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["table_hdr_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), palette["table_hdr_fg"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("BOX", (0, 0), (-1, -1), 0.4, palette["hair"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [palette["alt"], colors.white]),
    ]))
    flow.append(t)
    return flow


# ----- signatory block -----------------------------------------------
def build_signatory_block(
    sig: Dict[str, Any],
    palette: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    content_width: float,
) -> Table:
    """Two-column signatory footer — auditor on the left, client on the right."""
    firm_text = sig.get("firm_text") or ""
    client_text = sig.get("client_text") or ""
    firm_name = sig.get("firm_name") or ""
    mno = sig.get("membership_number") or ""
    title = sig.get("title") or ""
    place = sig.get("place") or ""
    date = sig.get("date") or ""
    udin = sig.get("udin") or ""
    sclient = sig.get("signatories_client") or ""
    roles = sig.get("auth_roles") or []
    text_on_top = sig.get("text_on_top") or ""

    left = [
        Paragraph(f"<i>{text_on_top}</i>" if text_on_top else "", styles["tiny"]),
        Paragraph(f"<b>{firm_text}</b>", styles["note_body"]),
        Paragraph(f"FRN: {sig.get('firm_registration') or '—'}", styles["tiny"]),
        Spacer(1, 10 * mm),
        Paragraph("______________________", styles["note_body"]),
        Paragraph(f"<b>{firm_name}</b>", styles["note_body"]),
        Paragraph(title, styles["tiny"]),
        Paragraph(f"M. No.: {mno}", styles["tiny"]),
        Paragraph(f"Place: {place}", styles["tiny"]),
        Paragraph(f"Date: {date}", styles["tiny"]),
        Paragraph(f"UDIN: {udin}" if udin else "", styles["tiny"]),
    ]
    right_rows = [
        Paragraph(f"<b>{client_text}</b>", styles["note_body"]),
        Spacer(1, 10 * mm),
    ]
    if sclient:
        right_rows += [
            Paragraph("______________________", styles["note_body"]),
            Paragraph(f"<b>{sclient}</b>", styles["note_body"]),
        ]
    # role labels
    for role in roles[:2]:
        right_rows.append(Paragraph(str(role), styles["tiny"]))

    t = Table(
        [[left, right_rows]],
        colWidths=(content_width * 0.5, content_width * 0.5),
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, palette["hair"]),
    ]))
    return t


__all__ = [
    "CLASSIC", "BOARDROOM", "inr",
    "mk_styles",
    "build_statement_table", "build_cashflow_table",
    "build_note_block", "build_signatory_block",
]
