"""Offline (postal) Balance Confirmation letter generator.

For vendors / customers where email isn't feasible, the auditor can generate
a printable PDF letter addressed from the auditor to the party.  Each letter
includes a tear-off slip at the bottom giving the party TWO options:

   Option 1 — confirm the balance as per books is correct
   Option 2 — state their own closing balance and attach their ledger

Letters are packed into a ZIP (one PDF per party) and streamed to the
browser.

Entry point:  ``build_offline_letters_zip(...)``

Heavy I/O — not called during send; triggered by a separate download button
in the UI.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

INK     = colors.HexColor("#111827")
MUTED   = colors.HexColor("#6B7280")
ACCENT  = colors.HexColor("#0F172A")
BOX_BG  = colors.HexColor("#F9FAFB")
BORDER  = colors.HexColor("#9CA3AF")
DASH_HEX = "#9CA3AF"


def _safe(v: Any, default: str = "") -> str:
    """Stringify, strip, and XML-escape enough for Paragraph().  Empty/None → default."""
    s = (str(v).strip() if v is not None else "")
    if not s:
        return default
    # Minimal escape for Paragraph (ReportLab parses XML-ish tags).
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def _inr(n: float) -> str:
    """Lakh-style ₹ with 2 decimals; parentheses for negatives."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0.0
    s = f"{abs(n):,.2f}"
    return f"({s})" if n < 0 else s


def _bal_suffix(n: float, dr_cr: str) -> str:
    """Return 'X.XX Dr' / 'X.XX Cr' based on either explicit dr_cr or sign."""
    s = _inr(abs(n))
    flag = (dr_cr or "").strip().lower()
    if flag == "dr":
        return f"{s} Dr"
    if flag == "cr":
        return f"{s} Cr"
    # Fall back to sign (Tally convention: +ve = Cr, -ve = Dr)
    return f"{s} Dr" if (n or 0) < 0 else f"{s} Cr"


def _format_address(ledger: Dict[str, Any]) -> List[str]:
    """Return multi-line address from the split fields (preferred) or legacy blob."""
    line1 = _safe(ledger.get("address_line_1"))
    line2 = _safe(ledger.get("address_line_2"))
    city = _safe(ledger.get("city"))
    pincode = _safe(ledger.get("pincode"))
    out: List[str] = []
    if line1:
        out.append(line1)
    if line2:
        out.append(line2)
    tail = " ".join(x for x in (city, pincode) if x)
    if tail:
        out.append(tail)
    if not out and ledger.get("address"):
        out = [_safe(line) for line in str(ledger["address"]).split(",") if line.strip()]
    return out


# --------------------------------------------------------------------------- #
#                          Letter body (per party)                            #
# --------------------------------------------------------------------------- #
def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Heading1"], fontSize=13, leading=16,
            textColor=ACCENT, alignment=1, spaceAfter=4,
            fontName="Helvetica-Bold",
        ),
        "firm": ParagraphStyle(
            "firm", parent=base["Normal"], fontSize=11, leading=14,
            textColor=INK, fontName="Helvetica-Bold", alignment=1,
        ),
        "firm_sub": ParagraphStyle(
            "firm_sub", parent=base["Normal"], fontSize=8.5, leading=11,
            textColor=MUTED, alignment=1,
        ),
        "ref": ParagraphStyle(
            "ref", parent=base["Normal"], fontSize=9, leading=12,
            textColor=INK,
        ),
        "party_block": ParagraphStyle(
            "party_block", parent=base["Normal"], fontSize=9.5, leading=13,
            textColor=INK,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9.5, leading=14,
            textColor=INK, alignment=4,   # justify
        ),
        "body_bold": ParagraphStyle(
            "body_bold", parent=base["Normal"], fontSize=9.5, leading=14,
            textColor=INK, alignment=4, fontName="Helvetica-Bold",
        ),
        "signoff": ParagraphStyle(
            "signoff", parent=base["Normal"], fontSize=9.5, leading=13,
            textColor=INK,
        ),
        "slip_h": ParagraphStyle(
            "slip_h", parent=base["Normal"], fontSize=9.5, leading=12,
            textColor=INK, fontName="Helvetica-Bold", alignment=1,
        ),
        "slip": ParagraphStyle(
            "slip", parent=base["Normal"], fontSize=9, leading=12,
            textColor=INK,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=7.5, leading=10,
            textColor=MUTED, alignment=1,
        ),
    }


def _header_block(S, auditor: Dict[str, Any]) -> list:
    firm = _safe(auditor.get("firm_name"), "AssureAI &amp; Co · Chartered Accountants")
    firm_addr = _safe(auditor.get("firm_address"), "102, Audit House, Connaught Place, New Delhi — 110001")
    firm_phone = _safe(auditor.get("firm_phone"))
    firm_email = _safe(auditor.get("firm_email"))
    tail_bits = [x for x in (firm_addr, firm_phone, firm_email) if x]
    return [
        Paragraph(firm, S["firm"]),
        Paragraph(" · ".join(tail_bits), S["firm_sub"]),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=0.6, color=ACCENT, spaceAfter=6),
    ]


def _party_addr_block(S, ledger: Dict[str, Any]) -> Paragraph:
    lines = [
        "<b>To,</b>",
        f"<b>{_safe(ledger.get('contact_name') or '')}</b>" if ledger.get("contact_name") else "",
        f"<b>{_safe(ledger.get('name'), '[Party Name]')}</b>",
    ]
    lines.extend(_format_address(ledger))
    gstin = _safe(ledger.get("gstin"))
    if gstin:
        lines.append(f"GSTIN: {gstin}")
    return Paragraph("<br/>".join(x for x in lines if x), S["party_block"])


def _tear_off_slip(S, *, ledger: Dict[str, Any], client: Dict[str, Any],
                   as_at_date: str, closing: float, dr_cr: str) -> KeepTogether:
    """Two-way confirmation slip with a dashed cut line above."""
    bal_txt = _bal_suffix(closing, dr_cr)
    client_name = _safe(client.get("name"), "[Client Name]")
    as_at = _safe(as_at_date, "—")

    # --------- Option 1 ----------
    opt1 = Paragraph(
        f"<b>Option 1 — Balance Confirmed</b><br/>"
        f"I/We confirm that the balance as at <b>{as_at}</b> in our books in the "
        f"account of <b>{client_name}</b> is <b>₹ {bal_txt}</b>, "
        f"which is in agreement with the balance as per your books.",
        S["slip"],
    )
    # --------- Option 2 ----------
    opt2 = Paragraph(
        f"<b>Option 2 — Balance Differs</b><br/>"
        f"The balance as per our books as at <b>{as_at}</b> in the account of "
        f"<b>{client_name}</b> is ₹ _______________________ "
        f"(tick one: ☐ Dr &nbsp;&nbsp; ☐ Cr). A copy of our ledger statement "
        f"for the year is enclosed. The differences, if any, are due to: "
        f"____________________________________________________________",
        S["slip"],
    )

    signoff_tbl = Table(
        [[
            Paragraph(
                "<b>Signature &amp; Stamp</b><br/><br/>"
                "____________________________<br/>"
                "Name: ______________________<br/>"
                "Designation: ________________<br/>"
                "Date: ______________________",
                S["slip"],
            ),
            Paragraph(
                "<b>Contact Details</b><br/><br/>"
                "Phone: ______________________<br/>"
                "Email: ______________________<br/>"
                "GSTIN: ______________________<br/>"
                "PAN: ________________________",
                S["slip"],
            ),
        ]],
        colWidths=[85 * mm, 85 * mm],
    )
    signoff_tbl.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))

    slip = [
        HRFlowable(
            width="100%", thickness=0.6, color=BORDER,
            dash=[2, 2], spaceBefore=6, spaceAfter=4,
        ),
        Paragraph("✂ — — — — — — — — — — — TEAR OFF ALONG THIS LINE — — — — — — — — — — — ✂",
                  S["small"]),
        Spacer(1, 4),
        Paragraph("BALANCE CONFIRMATION — REPLY SLIP", S["slip_h"]),
        Paragraph(
            f"Party: <b>{_safe(ledger.get('name'))}</b> &nbsp;·&nbsp; "
            f"GSTIN: {_safe(ledger.get('gstin')) or '—'} &nbsp;·&nbsp; "
            f"Reference: Confirmation Request for FY ending {_safe(client.get('fy_end'), as_at)}",
            S["slip"],
        ),
        Spacer(1, 4),
        opt1,
        Spacer(1, 4),
        opt2,
        Spacer(1, 6),
        signoff_tbl,
        Spacer(1, 4),
        Paragraph(
            "Please return this slip duly signed and stamped to the auditor at the address above, "
            "or scan and email to the auditor directly.",
            S["small"],
        ),
    ]
    return KeepTogether(slip)


def _build_single_letter_pdf(
    *,
    ledger: Dict[str, Any],
    client: Dict[str, Any],
    auditor: Dict[str, Any],
    as_at_date: str,
    letter_date: str,
) -> bytes:
    """Render ONE party's confirmation letter as a PDF byte-string."""
    S = _build_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Balance Confirmation · {ledger.get('name', '')}",
    )

    closing = float(ledger.get("closing_balance") or 0)
    dr_cr = (ledger.get("dr_cr") or "").lower()
    bal_txt = _bal_suffix(closing, dr_cr)

    client_name = _safe(client.get("name"), "[Client Name]")
    client_gstin = _safe(client.get("gstin"))
    client_addr = _safe(client.get("address"))
    fy_end = _safe(client.get("fy_end"), as_at_date)
    firm_name = _safe(auditor.get("firm_name"), "AssureAI &amp; Co · Chartered Accountants")
    partner = _safe(auditor.get("partner_name"), "Engagement Partner")
    udin_line = _safe(auditor.get("udin"))

    story: List[Any] = []
    story.extend(_header_block(S, auditor))

    # Ref + date row
    ref_row = Table(
        [[
            Paragraph(f"<b>Ref:</b> BC/{(ledger.get('ledger_id') or '')[:6].upper() or 'XXX'}/"
                      f"{datetime.now(timezone.utc).strftime('%Y-%m')}", S["ref"]),
            Paragraph(f"<b>Date:</b> {_safe(letter_date, datetime.now(timezone.utc).strftime('%d %b %Y'))}",
                      S["ref"]),
        ]],
        colWidths=[100 * mm, 70 * mm],
    )
    ref_row.setStyle(TableStyle([
        ("ALIGN",       (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 0),
        ("TOPPADDING",  (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(ref_row)
    story.append(Spacer(1, 8))

    story.append(_party_addr_block(S, ledger))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        f"<b>Sub: Request for confirmation of balance as at {_safe(as_at_date, '—')}"
        f" — {client_name}</b>",
        S["body_bold"],
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Dear Sir / Madam,", S["body"]))
    story.append(Spacer(1, 4))

    client_ident_bits = [f"M/s <b>{client_name}</b>"]
    if client_gstin:
        client_ident_bits.append(f"GSTIN {client_gstin}")
    if client_addr:
        client_ident_bits.append(client_addr)
    client_ident = ", ".join(client_ident_bits)

    story.append(Paragraph(
        f"In connection with the statutory audit of {client_ident} for the financial "
        f"year ending {fy_end}, we request your confirmation of the balance "
        f"outstanding in your books in the account of <b>{client_name}</b> as at "
        f"<b>{_safe(as_at_date, '—')}</b>.",
        S["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"As per the books of account of {client_name}, the balance in your account "
        f"as on that date is <b>₹ {bal_txt}</b>.",
        S["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Kindly verify the balance against your books of account and either "
        "<b>(a)</b> confirm that it is in agreement, <b>OR</b> <b>(b)</b> state "
        "your closing balance along with a copy of the ledger account. Please fill "
        "and return the slip at the bottom of this letter by post, courier or "
        "e-mail. Your prompt reply will help us conclude the audit timely.",
        S["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "This request is issued solely for audit purposes. Your response will be "
        "treated as strictly confidential.",
        S["body"],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Thanking you,", S["signoff"]))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Yours faithfully,", S["signoff"]))
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"For <b>{firm_name}</b>", S["signoff"]))
    story.append(Paragraph("<i>Chartered Accountants</i>", S["signoff"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("____________________________", S["signoff"]))
    story.append(Paragraph(f"<b>{partner}</b>", S["signoff"]))
    if udin_line:
        story.append(Paragraph(f"UDIN: {udin_line}", S["signoff"]))
    story.append(Spacer(1, 6))

    # --------------- Tear-off slip ----------------
    story.append(_tear_off_slip(
        S, ledger=ledger, client={**client, "fy_end": fy_end},
        as_at_date=as_at_date, closing=closing, dr_cr=dr_cr,
    ))

    doc.build(story)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
#                                  Public API                                 #
# --------------------------------------------------------------------------- #
def _safe_filename(party_name: str, ledger_id: str) -> str:
    """Make a filesystem-friendly PDF filename."""
    base = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in (party_name or "Party"))
    base = base.strip().replace("  ", " ").replace(" ", "_")[:60]
    return f"{base}__{(ledger_id or '')[:6]}.pdf"


def build_offline_letters_zip(
    *,
    ledgers: Iterable[Dict[str, Any]],
    client: Dict[str, Any],
    auditor: Dict[str, Any],
    as_at_date: str,
    letter_date: Optional[str] = None,
) -> bytes:
    """Generate one PDF per ledger and pack them into a ZIP archive.

    Returns the ZIP bytes (streamed by the controller).  Does not touch the
    DB — pure I/O + PDF rendering.
    """
    letter_date = letter_date or datetime.now(timezone.utc).strftime("%d %b %Y")
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for L in ledgers:
            pdf_bytes = _build_single_letter_pdf(
                ledger=L, client=client, auditor=auditor,
                as_at_date=as_at_date, letter_date=letter_date,
            )
            zf.writestr(_safe_filename(L.get("name", ""), L.get("ledger_id", "")), pdf_bytes)
    return mem.getvalue()
