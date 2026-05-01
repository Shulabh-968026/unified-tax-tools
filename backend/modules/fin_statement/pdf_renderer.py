"""FS Designer PDF renderer — v2.

Layout (matches client's in-house final statement style):
  • Page 1  — Balance Sheet (full portrait A4) + signatory footer.
  • Page 2  — Statement of Profit and Loss + signatory footer.
  • Page 3  — Cash Flow Statement + signatory footer.
  • Page 4+ — Notes, grouped with KeepTogether so individual notes never
              break mid-way across pages.
  • Last    — PPE (Fixed Asset) schedule.

Two templates: ``classic`` (monochrome CA look) and ``boardroom``
(slate + sky accents). They share identical structure; only palette
differs.
"""
from __future__ import annotations
import io
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.doctemplate import NextPageTemplate


# ---------- Palettes -------------------------------------------------
CLASSIC = {
    "ink":          colors.HexColor("#000000"),
    "mute":         colors.HexColor("#3F3F46"),
    "hair":         colors.HexColor("#000000"),
    "soft":         colors.HexColor("#E5E5E5"),
    "band":         colors.HexColor("#F5F5F5"),
    "accent":       colors.HexColor("#111111"),
    "header_bg":    colors.HexColor("#F8F8F5"),
}

BOARDROOM = {
    "ink":          colors.HexColor("#0F172A"),
    "mute":         colors.HexColor("#475569"),
    "hair":         colors.HexColor("#0C4A6E"),
    "soft":         colors.HexColor("#E0F2FE"),
    "band":         colors.HexColor("#F0F9FF"),
    "accent":       colors.HexColor("#0369A1"),
    "header_bg":    colors.HexColor("#F8FAFC"),
}


# ---------- Number formatting ----------------------------------------
def inr_rupee_paise(v: float, dash_zero: bool = False) -> str:
    """Indian-format with 2 decimals; negative in (brackets); optional
    dash for zero. Example: 12,34,567.89 or (12,34,567.89)."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "0.00"
    if dash_zero and abs(n) < 0.005:
        return "-"
    neg = n < 0
    s = f"{abs(n):,.2f}"
    int_part, _, dec_part = s.partition(".")
    int_part = int_part.replace(",", "")
    if len(int_part) <= 3:
        grouped = int_part
    else:
        head, tail = int_part[:-3], int_part[-3:]
        rev = head[::-1]
        grouped = (",".join([rev[i:i + 2] for i in range(0, len(rev), 2)])[::-1]
                   + "," + tail)
    res = f"{grouped}.{dec_part}"
    return f"({res})" if neg else res


# ---------- Shared frame helpers -------------------------------------
def _page_frame(doc: BaseDocTemplate, size: Tuple[float, float]) -> Frame:
    w, h = size
    return Frame(
        doc.leftMargin, doc.bottomMargin,
        w - doc.leftMargin - doc.rightMargin,
        h - doc.topMargin - doc.bottomMargin,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="body",
    )


def _draw_footer(canvas, doc, palette):
    """Simple centered page number footer."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(palette["mute"])
    canvas.drawCentredString(doc.pagesize[0] / 2, 6 * mm, f"- {doc.page} -")
    canvas.restoreState()


# ---------- Page-header block (repeats on every page) ----------------
def _page_header_block(doc_data: Dict[str, Any], palette, styles,
                       statement_title: str) -> List[Any]:
    co = doc_data.get("company", {})
    flow: List[Any] = []
    flow.append(Paragraph((co.get("name") or "").upper(), styles["co_name"]))
    if co.get("cin"):
        flow.append(Paragraph(f"CIN: {co['cin']}", styles["co_sub"]))
    if co.get("city"):
        flow.append(Paragraph(co["city"].upper(), styles["co_sub"]))
    flow.append(Spacer(1, 2.5 * mm))
    flow.append(Paragraph(statement_title, styles["statement_title"]))
    flow.append(Spacer(1, 1.5 * mm))
    return flow


# ---------- Statement column-headers ---------------------------------
def _stmt_col_header(col_labels: List[str], styles, palette,
                     note_col: bool) -> Table:
    """The two-row column header block: dual-year 'As at' rows + the
    sub-heading row (PARTICULARS / Note / Rs. Ps. / Rs. Ps.)."""
    if note_col:
        # 4 cols: Particulars | Note | CY | PY
        data = [[
            Paragraph("", styles["hdr"]),
            Paragraph("", styles["hdr"]),
            Paragraph(col_labels[0], styles["hdr_c"]),
            Paragraph(col_labels[1], styles["hdr_c"]),
        ], [
            Paragraph("<b>PARTICULARS</b>", styles["hdr"]),
            Paragraph("<b>Note No.</b>", styles["hdr_c"]),
            Paragraph("<b>Rs. Ps.</b>", styles["hdr_c"]),
            Paragraph("<b>Rs. Ps.</b>", styles["hdr_c"]),
        ]]
        col_widths = ("62%", "10%", "14%", "14%")
    else:
        data = [[
            Paragraph("", styles["hdr"]),
            Paragraph(col_labels[0], styles["hdr_c"]),
            Paragraph(col_labels[1], styles["hdr_c"]),
        ], [
            Paragraph("<b>PARTICULARS</b>", styles["hdr"]),
            Paragraph("<b>Rs. Ps.</b>", styles["hdr_c"]),
            Paragraph("<b>Rs. Ps.</b>", styles["hdr_c"]),
        ]]
        col_widths = ("72%", "14%", "14%")
    return _HeaderTable(data, col_widths, palette)


def _HeaderTable(data, col_widths, palette):
    t = Table(data, colWidths=_resolve_widths(col_widths))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, palette["ink"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, palette["ink"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, palette["hair"]),
    ]))
    return t


# Width resolver with cached usable-width placeholder
_WIDTH_REF: Dict[str, float] = {}


def _resolve_widths(spec) -> List[float]:
    usable = _WIDTH_REF.get("usable", 180 * mm)
    return [usable * float(s.strip().rstrip("%")) / 100.0 for s in spec]


# ---------- BS / P&L renderer ----------------------------------------
def _fmt_label(row: Dict[str, Any]) -> str:
    """Render the prefix + label with appropriate indent."""
    indent = max(0, int(row.get("indent", 0)))
    prefix = row.get("prefix", "") or ""
    label = row.get("label", "") or ""
    indent_spaces = "&nbsp;" * (indent * 6)
    if row.get("kind") in ("total",):
        return f"{indent_spaces}<b>{label.upper()}</b>"
    if row.get("kind") in ("header", "root_line"):
        # Top-level section headers are UPPERCASE for emphasis
        if prefix:
            return f"{indent_spaces}<b>{prefix}&nbsp;&nbsp;{label.upper()}</b>"
        return f"{indent_spaces}<b>{label.upper()}</b>"
    if prefix and row.get("kind") == "subhead":
        return f"{indent_spaces}{prefix}&nbsp;&nbsp;<b>{label}</b>"
    if prefix:
        return f"{indent_spaces}{prefix}&nbsp;{label}"
    return f"{indent_spaces}{label}"


def _build_bs_pl_table(rows: List[Dict[str, Any]], styles, palette,
                       col_labels: List[str]) -> Table:
    # 4 cols: Particulars | Note | CY | PY
    data: List[List[Any]] = []
    # Header rows (as first 2 table rows so the header lives in the same table)
    data.append([
        Paragraph("", styles["body"]),
        Paragraph("", styles["body"]),
        Paragraph(col_labels[0], styles["body_cb"]),
        Paragraph(col_labels[1], styles["body_cb"]),
    ])
    data.append([
        Paragraph("<b>PARTICULARS</b>", styles["body"]),
        Paragraph("<b>Note No.</b>", styles["body_cb"]),
        Paragraph("<b>Rs. Ps.</b>", styles["body_cb"]),
        Paragraph("<b>Rs. Ps.</b>", styles["body_cb"]),
    ])

    body_start = len(data)
    row_styles: List[Any] = []
    for r in rows:
        kind = r.get("kind")
        is_bold_row = kind in ("header", "total", "subtotal", "root_line", "subhead")
        # Header / subhead rows in the reference PDF carry no values —
        # values appear only on the leaf rows and the TOTAL/Total(N) rows.
        hide_values = kind in ("header", "subhead")
        lbl_style = styles["body_b"] if is_bold_row else styles["body"]
        val_style = styles["body_rb"] if is_bold_row else styles["body_r"]
        label_html = _fmt_label(r)
        note_txt = str(r.get("note") or "")
        cur_txt = "" if hide_values else inr_rupee_paise(r.get("current", 0))
        prev_txt = "" if hide_values else inr_rupee_paise(r.get("previous", 0))
        data.append([
            Paragraph(label_html, lbl_style),
            Paragraph(note_txt, styles["body_c"]),
            Paragraph(cur_txt, val_style),
            Paragraph(prev_txt, val_style),
        ])
        i = len(data) - 1
        if kind == "total":
            row_styles.append(("LINEABOVE", (2, i), (-1, i), 0.6, palette["ink"]))
            row_styles.append(("LINEBELOW", (2, i), (-1, i), 0.8, palette["ink"]))
            row_styles.append(("BACKGROUND", (0, i), (-1, i), palette["band"]))
        elif kind == "subtotal":
            row_styles.append(("LINEABOVE", (2, i), (-1, i), 0.3, palette["hair"]))
            row_styles.append(("LINEBELOW", (2, i), (-1, i), 0.3, palette["hair"]))

    t = Table(data, colWidths=_resolve_widths(("62%", "10%", "14%", "14%")),
              repeatRows=body_start)
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ("LINEABOVE",     (0, 0),  (-1, 0), 0.8, palette["ink"]),
        ("LINEBELOW",     (0, 0),  (-1, 0), 0.3, palette["hair"]),
        ("LINEBELOW",     (0, 1), (-1, 1), 0.8, palette["ink"]),
    ] + row_styles))
    return t


# ---------- Cash Flow renderer ---------------------------------------
def _build_cfs_table(rows: List[Dict[str, Any]], styles, palette,
                     col_labels: List[str]) -> Table:
    data: List[List[Any]] = [[
        Paragraph("", styles["body"]),
        Paragraph(col_labels[0], styles["body_cb"]),
        Paragraph(col_labels[1], styles["body_cb"]),
    ], [
        Paragraph("<b>PARTICULARS</b>", styles["body"]),
        Paragraph("<b>Rs. Ps.</b>", styles["body_cb"]),
        Paragraph("<b>Rs. Ps.</b>", styles["body_cb"]),
    ]]
    body_start = len(data)
    row_styles: List[Any] = []
    for r in rows:
        indent = max(0, int(r.get("indent", 0)))
        indent_spaces = "&nbsp;" * (indent * 6)
        serial = r.get("serial", "") or ""
        prefix = f"{serial}&nbsp;&nbsp;" if serial else ""
        is_h = r.get("is_header")
        is_b = r.get("is_bold")
        if is_h:
            label_html = f"{indent_spaces}<b>{prefix}{r.get('label', '')}</b>"
            lbl_style = styles["body_b"]
            val_style = styles["body_rb"]
        elif is_b:
            label_html = f"{indent_spaces}{prefix}<b>{r.get('label', '')}</b>"
            lbl_style = styles["body_b"]
            val_style = styles["body_rb"]
        else:
            label_html = f"{indent_spaces}{prefix}{r.get('label', '')}"
            lbl_style = styles["body"]
            val_style = styles["body_r"]
        cy = "" if (is_h and r.get("current", 0) == 0) else inr_rupee_paise(r.get("current", 0))
        py = "" if (is_h and r.get("previous", 0) == 0) else inr_rupee_paise(r.get("previous", 0))
        data.append([
            Paragraph(label_html, lbl_style),
            Paragraph(cy, val_style),
            Paragraph(py, val_style),
        ])
        i = len(data) - 1
        if is_h:
            row_styles.append(("BACKGROUND", (0, i), (-1, i), palette["band"]))
        if r.get("line_top") and r["line_top"] != "NONE":
            row_styles.append(("LINEABOVE", (1, i), (2, i), 0.6, palette["ink"]))
        if r.get("line_below") and r["line_below"] != "NONE":
            row_styles.append(("LINEBELOW", (1, i), (2, i), 0.6, palette["ink"]))

    t = Table(data, colWidths=_resolve_widths(("70%", "15%", "15%")),
              repeatRows=body_start)
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LINEABOVE",     (0, 0),  (-1, 0),  0.8, palette["ink"]),
        ("LINEBELOW",     (0, 1),  (-1, 1),  0.8, palette["ink"]),
    ] + row_styles))
    return t


# ---------- Signatory footer (detailed, repeats on BS/P&L/CFS) -------
def _signatory_footer(sig: Dict[str, Any], styles, palette,
                      content_width: float) -> Table:
    firm_text = sig.get("firm_text") or ""
    client_text = sig.get("client_text") or ""
    frn = sig.get("firm_registration") or ""
    partner_name = sig.get("partner_name") or ""
    partner_title = sig.get("partner_title") or "Partner"
    mno = sig.get("membership_number") or ""
    place = sig.get("place") or ""
    date = sig.get("date") or ""
    udin = sig.get("udin") or ""
    directors = sig.get("directors") or []

    # Left column (auditor)
    left: List[Any] = [
        Paragraph(f"<b>{firm_text}</b>", styles["sig"]),
        Paragraph("<i>Chartered Accountants</i>", styles["sig"]),
        Paragraph(f"Firm Regn. No.: {frn}", styles["sig"]),
        Spacer(1, 12 * mm),
        Paragraph(f"<b>{partner_name}</b>" if partner_name else "", styles["sig"]),
        Paragraph(partner_title, styles["sig"]),
        Paragraph(f"Membership No.: {mno}", styles["sig"]),
        Paragraph(f"Place: {place}", styles["sig"]),
        Paragraph(f"Date: {date}", styles["sig"]),
    ]
    if udin:
        left.append(Paragraph(f"UDIN: {udin}", styles["sig"]))

    # Right column (client) — two directors side-by-side, name + role + DIN
    right: List[Any] = [Paragraph(f"<b>{client_text}</b>", styles["sig"]),
                        Spacer(1, 10 * mm)]
    if directors:
        # Compose a 2-col mini-table of director names/roles/DINs
        d_head: List[Any] = []
        d_role: List[Any] = []
        d_din: List[Any] = []
        for dr in directors[:2]:
            d_head.append(Paragraph(f"<b>{dr.get('name', '')}</b>", styles["sig"]))
            d_role.append(Paragraph(dr.get("role", ""), styles["sig"]))
            d_din.append(Paragraph(f"DIN: {dr.get('din', '')}", styles["sig"]))
        # Pad to 2 columns if only 1 director
        while len(d_head) < 2:
            d_head.append(Paragraph("", styles["sig"]))
            d_role.append(Paragraph("", styles["sig"]))
            d_din.append(Paragraph("", styles["sig"]))
        half = (content_width * 0.5) / 2 - 2
        dtbl = Table(
            [d_head, d_role, d_din],
            colWidths=(half, half),
        )
        dtbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 1),
        ]))
        right.append(dtbl)

    text_on_top = sig.get("text_on_top") or "Subject to our report of even date"

    outer = Table(
        [
            [Paragraph("<i>The Accompanying Notes form an integral part of "
                       "the Financial Statements.</i>", styles["sig_note"]), ""],
            [Paragraph(f"<i>{text_on_top}</i>", styles["sig_note"]), ""],
            [left, right],
        ],
        colWidths=(content_width * 0.5, content_width * 0.5),
    )
    outer.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("SPAN", (0, 1), (-1, 1)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, 1), 1),
        ("BOTTOMPADDING",(0, 0), (-1, 1), 2),
        ("TOPPADDING",   (0, 2), (-1, 2), 6),
    ]))
    return outer


# ---------- Note block -----------------------------------------------
def _note_block(note: Dict[str, Any], styles, palette,
                content_width: float, col_labels: List[str]) -> List[Any]:
    flow: List[Any] = []
    title = f"Note No : {note.get('note', '')}  {note.get('title', '')}"
    flow.append(Paragraph(f"<b>{title}</b>", styles["note_title"]))
    flow.append(Spacer(1, 1 * mm))

    rows = note.get("details") or []
    if not rows:
        rows = note.get("children") or []

    data: List[List[Any]] = []
    for r in rows:
        indent = max(0, int(r.get("indent", 0)))
        indent_spaces = "&nbsp;" * (indent * 4)
        label = r.get("label", "") or ""
        is_sub = r.get("has_children")
        label_html = f"{indent_spaces}<b>{label}</b>" if is_sub else f"{indent_spaces}{label}"
        data.append([
            Paragraph(label_html, styles["note_body"]),
            Paragraph(inr_rupee_paise(r.get("current", 0)), styles["note_body_r"]),
            Paragraph(inr_rupee_paise(r.get("previous", 0)), styles["note_body_r"]),
        ])
    # Total row
    data.append([
        Paragraph("<b>Total</b>", styles["note_body"]),
        Paragraph(f"<b>{inr_rupee_paise(note.get('current', 0))}</b>", styles["note_body_r"]),
        Paragraph(f"<b>{inr_rupee_paise(note.get('previous', 0))}</b>", styles["note_body_r"]),
    ])

    t = Table(data, colWidths=_resolve_widths(("70%", "15%", "15%")))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, palette["ink"]),
    ]))
    flow.append(t)
    return flow


# ---------- PPE schedule block --------------------------------------
def _fa_block(fa: Dict[str, Any], styles, palette, content_width: float) -> List[Any]:
    if not fa or not fa.get("subheads"):
        return []
    flow: List[Any] = []
    flow.append(Paragraph("<b>Note No : 8  Property, Plant and Equipment</b>", styles["note_title"]))
    flow.append(Spacer(1, 1 * mm))
    head = ["Particulars", "Opening Cost", "Additions", "Deletions",
            "Closing Cost", "Opening Depn", "Depn / Year",
            "Closing Depn", "Closing WDV"]
    rows = [head]
    for s in fa.get("subheads", []):
        rows.append([
            s.get("label", ""),
            inr_rupee_paise(s.get("opening_cost", 0)),
            inr_rupee_paise(s.get("additions", 0)),
            inr_rupee_paise(s.get("deletions", 0)),
            inr_rupee_paise(s.get("closing_cost", 0)),
            inr_rupee_paise(s.get("opening_depreciation", 0)),
            inr_rupee_paise(s.get("depreciation_for_year", 0)),
            inr_rupee_paise(s.get("closing_depreciation", 0)),
            inr_rupee_paise(s.get("closing_written_down_value", 0)),
        ])
    tot = fa.get("total", {})
    rows.append([
        "Total",
        inr_rupee_paise(tot.get("opening_cost", 0)),
        inr_rupee_paise(tot.get("additions", 0)),
        inr_rupee_paise(tot.get("deletions", 0)),
        inr_rupee_paise(tot.get("closing_cost", 0)),
        inr_rupee_paise(tot.get("opening_depreciation", 0)),
        inr_rupee_paise(tot.get("depreciation_for_year", 0)),
        inr_rupee_paise(tot.get("closing_depreciation", 0)),
        inr_rupee_paise(tot.get("closing_written_down_value", 0)),
    ])
    col_w = [content_width * 0.22] + [content_width * 0.0975] * 8
    t = Table(rows, colWidths=col_w, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTSIZE",  (0, 0), (-1, -1), 6.8),
        ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND",(0, 0), (-1, 0), palette["band"]),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, palette["ink"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, palette["ink"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, palette["ink"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, palette["ink"]),
        ("FONTNAME",  (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))
    return flow


# ---------- Styles factory -------------------------------------------
def _mk_styles(palette, body_size: float = 8.2):
    lead = body_size + 1.4
    base = dict(fontName="Helvetica", fontSize=body_size, leading=lead,
                textColor=palette["ink"])
    return {
        "co_name":  ParagraphStyle("co_name", fontName="Helvetica-Bold",
                                    fontSize=11.5, leading=13, alignment=1,
                                    textColor=palette["ink"]),
        "co_sub":   ParagraphStyle("co_sub", fontName="Helvetica",
                                    fontSize=8.5, leading=10, alignment=1,
                                    textColor=palette["mute"]),
        "statement_title": ParagraphStyle(
            "statement_title", fontName="Helvetica-Bold", fontSize=10.5,
            leading=12.5, alignment=1, textColor=palette["ink"],
            spaceAfter=2),
        "hdr":    ParagraphStyle("hdr", fontName="Helvetica", fontSize=8.3,
                                  leading=10, textColor=palette["ink"]),
        "hdr_c":  ParagraphStyle("hdr_c", fontName="Helvetica", fontSize=8.3,
                                  leading=10, alignment=1,
                                  textColor=palette["ink"]),
        "body":    ParagraphStyle("body", **base),
        "body_b":  ParagraphStyle("body_b", **{**base, "fontName": "Helvetica-Bold"}),
        "body_c":  ParagraphStyle("body_c", **{**base, "alignment": 1}),
        "body_cb": ParagraphStyle("body_cb", **{**base, "alignment": 1, "fontName": "Helvetica-Bold"}),
        "body_r":  ParagraphStyle("body_r", **{**base, "alignment": 2}),
        "body_rb": ParagraphStyle("body_rb", **{**base, "alignment": 2, "fontName": "Helvetica-Bold"}),
        "sig_note": ParagraphStyle("sig_note", fontName="Helvetica",
                                    fontSize=8, leading=10,
                                    textColor=palette["ink"], spaceAfter=0),
        "sig":     ParagraphStyle("sig", fontName="Helvetica", fontSize=8,
                                   leading=10, textColor=palette["ink"],
                                   spaceAfter=0),
        "note_title": ParagraphStyle("note_title", fontName="Helvetica-Bold",
                                      fontSize=9, leading=11,
                                      textColor=palette["ink"], spaceAfter=1),
        "note_body":  ParagraphStyle("note_body", fontName="Helvetica",
                                      fontSize=8, leading=10,
                                      textColor=palette["ink"]),
        "note_body_r": ParagraphStyle("note_body_r", fontName="Helvetica",
                                       fontSize=8, leading=10, alignment=2,
                                       textColor=palette["ink"]),
    }


# ---------- Main entry -----------------------------------------------
def render_pdf(doc_data: Dict[str, Any], template: str = "classic") -> bytes:
    palette = BOARDROOM if template == "boardroom" else CLASSIC
    styles = _mk_styles(palette)

    buf = io.BytesIO()
    page_w, page_h = A4
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=(doc_data.get("company", {}).get("name", "Financial Statements")
               + " — FY " + doc_data.get("period", {}).get("fy_current", "")),
    )
    content_w = page_w - doc.leftMargin - doc.rightMargin
    _WIDTH_REF["usable"] = content_w

    def _footer(c, d):
        _draw_footer(c, d, palette)

    doc.addPageTemplates([
        PageTemplate(id="Body", frames=[_page_frame(doc, A4)], onPage=_footer),
    ])

    period = doc_data.get("period", {})
    end_long = period.get("current_end_long") or period.get("current_end", "")
    cur_label = f"As at {period.get('current_end_short', '')}"
    prev_label = f"As at {period.get('previous_end_short', '')}"
    cur_ye = f"Y.E. {period.get('current_end_short', '').replace('/', '.')}"
    prev_ye = f"Y.E. {period.get('previous_end_short', '').replace('/', '.')}"

    story: List[Any] = []

    # --- Page 1: Balance Sheet ---
    story.extend(_page_header_block(doc_data, palette, styles,
                                    f"Balance Sheet as at {end_long}"))
    story.append(_build_bs_pl_table(doc_data.get("balance_sheet", []),
                                    styles, palette,
                                    [cur_label, prev_label]))
    story.append(Spacer(1, 3 * mm))
    story.append(_signatory_footer(doc_data.get("signatory", {}),
                                   styles, palette, content_w))
    story.append(PageBreak())

    # --- Page 2: P&L ---
    story.extend(_page_header_block(doc_data, palette, styles,
                                    f"Statement of Profit and Loss for the year ended {end_long}"))
    story.append(_build_bs_pl_table(doc_data.get("profit_loss", []),
                                    styles, palette,
                                    [cur_ye, prev_ye]))
    story.append(Spacer(1, 3 * mm))
    story.append(_signatory_footer(doc_data.get("signatory", {}),
                                   styles, palette, content_w))
    story.append(PageBreak())

    # --- Page 3: Cash Flow ---
    story.extend(_page_header_block(doc_data, palette, styles,
                                    f"Cash Flow Statement as at {end_long}"))
    story.append(_build_cfs_table(doc_data.get("cash_flow", []),
                                  styles, palette,
                                  [cur_label, prev_label]))
    story.append(Spacer(1, 3 * mm))
    story.append(_signatory_footer(doc_data.get("signatory", {}),
                                   styles, palette, content_w))
    story.append(PageBreak())

    # --- Pages 4+: Notes ---
    story.extend(_page_header_block(doc_data, palette, styles,
                                    f"Notes to Financial Statements for the year ended {end_long}"))
    for note in doc_data.get("notes", []):
        block = _note_block(note, styles, palette, content_w,
                            [cur_label, prev_label])
        block.append(Spacer(1, 3 * mm))
        story.append(KeepTogether(block))

    # --- PPE schedule (long table; allowed to span pages naturally) ---
    fa_block_flow = _fa_block(doc_data.get("fixed_asset") or {}, styles,
                              palette, content_w)
    if fa_block_flow:
        story.append(Spacer(1, 3 * mm))
        story.extend(fa_block_flow)

    doc.build(story)
    return buf.getvalue()


__all__ = ["render_pdf", "inr_rupee_paise"]
