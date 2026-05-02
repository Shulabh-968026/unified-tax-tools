"""Per-party Ledger Extract PDF builder for Balance Confirmation.

Walks the original Tally Books JSON, finds every voucher where the target
ledger appears (either as `partyLedgerName` or as a member of `ledgerEntries`),
sorts by date and computes a running balance. Renders to a one-page-per-party
PDF table that ships as an attachment alongside the confirmation email.

Tally sign convention: ledgerEntries[].amount > 0 = Credit; < 0 = Debit.
For a Sundry Debtor (asset), debit increases balance owed to us; the running
balance shown is **as the party views it** — credit (we owe them) is
shown positive, debit (they owe us) is shown negative — matching what the
party will compare against their statement.

Used by sender.py at send time. Heavy operation (parses ~1MB JSON), so the
batch sender pre-loads & decompresses books once per run, then renders all
extracts in a tight loop.
"""
from __future__ import annotations
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)


GREEN = colors.HexColor("#047857")
INK   = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
ROW_ALT = colors.HexColor("#F9FAFB")
BORDER  = colors.HexColor("#E5E7EB")


def _f(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _inr(n: float) -> str:
    if not n:
        return "–"
    s = f"{abs(n):,.2f}"
    return f"({s})" if n < 0 else s


def _bal(n: float) -> str:
    """Format a credit-positive balance as 'X.XX Dr' / 'X.XX Cr' / '–'.

    Used for the Opening / Closing / running-Balance cells in the ledger
    extract so negatives appear as 'X.XX Dr' without brackets.
    """
    if not n:
        return "–"
    s = f"{abs(n):,.2f}"
    return f"{s} Dr" if n < 0 else f"{s} Cr"


def _date_iso(d: str) -> str:
    """Tally dates can be 'YYYY-MM-DD' or sometimes 'YYYY-MM-DDTHH:MM:SS'."""
    return (d or "")[:10]


def find_ledger_vouchers(books: Dict[str, Any], ledger_name: str) -> List[Dict[str, Any]]:
    """Return every voucher touching `ledger_name` along with the signed amount
    that hit that ledger. Tally puts the party-line `amount` in `ledgerEntries`
    where `ledger == ledger_name` (or `partyLedgerName` matches).
    """
    target = (ledger_name or "").strip().lower()
    if not target:
        return []
    out: List[Dict[str, Any]] = []
    for v in (books.get("vouchers") or []):
        date = _date_iso(v.get("date") or "")
        vtype = v.get("voucherTypeName") or ""
        vno = v.get("voucherNumber") or ""
        narration = v.get("narration") or ""

        # Find the ledger's entry inside this voucher
        amt = 0.0
        hit = False
        for le in (v.get("ledgerEntries") or []):
            ln = (le.get("ledger") or "").strip().lower()
            if ln == target:
                amt += _f(le.get("amount"))
                hit = True
        if not hit:
            # Sometimes Tally records the party only at voucher level (e.g.
            # opening balance carry-forward) — fall back to partyLedgerName.
            if (v.get("partyLedgerName") or "").strip().lower() == target:
                # Best effort: take total of party ledger entries (already 0 above), skip
                continue
            continue

        out.append({
            "date": date,
            "vtype": vtype,
            "vno": vno,
            "narration": narration[:80],
            "amount": round(amt, 2),
        })

    out.sort(key=lambda r: r["date"] or "9999")
    return out


def build_ledger_extract_pdf(*,
                             ledger: Dict[str, Any],
                             books: Dict[str, Any],
                             client: Dict[str, Any],
                             as_at_date: str,
                             auditor_firm: str = "") -> bytes:
    """Render the extract PDF for one ledger and return the bytes."""
    rows = find_ledger_vouchers(books, ledger.get("name", ""))
    opening = _f(ledger.get("opening_balance"))
    closing = _f(ledger.get("closing_balance"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Ledger Extract · {ledger.get('name')}",
    )
    base = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=14, leading=17,
                        textColor=INK, fontName="Helvetica-Bold", spaceAfter=2)
    H2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=10, leading=12,
                        textColor=GREEN, fontName="Helvetica-Bold", spaceAfter=4)
    BODY = ParagraphStyle("body", parent=base["Normal"], fontSize=8.5, leading=11,
                          textColor=INK)
    SMALL = ParagraphStyle("small", parent=base["Normal"], fontSize=7.5, leading=10,
                           textColor=MUTED)

    story: List[Any] = []
    story.append(Paragraph(f"Ledger Extract — {ledger.get('name', '')}", H1))
    story.append(Paragraph(
        f"{client.get('name', '')} · GSTIN {client.get('gstin') or '—'} · "
        f"As at {as_at_date or '—'}", H2))

    meta = Table([[
        Paragraph(f"<b>Party GSTIN</b><br/>{ledger.get('gstin') or '—'}", BODY),
        Paragraph(f"<b>Group</b><br/>{ledger.get('parent_group') or '—'}", BODY),
        Paragraph(f"<b>Opening Bal.</b><br/>{_bal(-opening)}", BODY),
        Paragraph(f"<b>Closing Bal.</b><br/>"
                  f"<font color='{GREEN.hexval()[2:]}'>{_bal(-closing)}</font>",
                  BODY),
    ]], colWidths=[45 * mm, 50 * mm, 40 * mm, 51 * mm])
    meta.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta)
    story.append(Spacer(1, 8))

    # Vouchers table
    headers = ["Date", "Voucher Type", "Voucher #", "Debit", "Credit", "Balance"]
    table_data: List[List[Any]] = [headers]

    # In Tally, amount > 0 = Credit, < 0 = Debit. We want columns:
    #   Debit  = -amt if amt < 0 else 0
    #   Credit =  amt if amt > 0 else 0
    # Running balance = prior + amt (credit-positive convention)
    running = -opening  # opening_balance: -ve = Dr, +ve = Cr; convert to credit-pos
    table_data.append([
        "", "Opening Balance", "", "", "", _bal(running),
    ])
    for r in rows:
        amt = r["amount"]
        running += amt
        table_data.append([
            r["date"],
            r["vtype"],
            r["vno"],
            _inr(-amt) if amt < 0 else "",
            _inr(amt)  if amt > 0 else "",
            _bal(running),
        ])
    # Closing line — should match -closing (sign-converted to credit-pos)
    table_data.append([
        "", "Closing Balance", "", "", "", _bal(-closing),
    ])

    t = Table(table_data,
              colWidths=[22 * mm, 38 * mm, 34 * mm, 30 * mm, 30 * mm, 32 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("ALIGN",      (3, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ECFDF5")),
        ("TEXTCOLOR",  (0, -1), (-1, -1), GREEN),
        ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F1F5F9")),
        ("FONTNAME",   (0, 1), (-1, 1), "Helvetica-Bold"),
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",  (0, 0), (-1, 0), 0.6, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y · %H:%M UTC')} · "
        f"{auditor_firm or 'MSS × Assure Audit Utilities'} · "
        "This extract is auto-generated from books of account for the sole purpose "
        "of balance confirmation. Please reconcile against your statement and respond "
        "via the secure link in the accompanying email.", SMALL))

    doc.build(story)
    return buf.getvalue()
