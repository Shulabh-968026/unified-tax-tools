"""QA Test Pack PDF — module-by-module checklist for the user's QA team.

Builds a designer A4 PDF with one section per live module, each laid out
as a tick-box checklist grouped by area (functional, edge-case, UX,
integration, output validation).  Dropped in as a standalone utility so
it can be regenerated any time the module surface changes.
"""
from __future__ import annotations
import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)


PALETTE = {
    "ink":     colors.HexColor("#0F172A"),
    "mute":    colors.HexColor("#475569"),
    "hair":    colors.HexColor("#E2E8F0"),
    "soft":    colors.HexColor("#F1F5F9"),
    "accent":  colors.HexColor("#0369A1"),
    "ok":      colors.HexColor("#15803D"),
    "warn":    colors.HexColor("#B45309"),
    "danger":  colors.HexColor("#B91C1C"),
    "band":    colors.HexColor("#F0F9FF"),
}


# -------------------------------- modules -------------------------------
MODULES: List[Dict[str, Any]] = [
    {
        "code":   "FA",
        "title":  "Fixed Assets — Tax Audit (Block-wise IT Depn)",
        "owner":  "Audit Lead",
        "scope":  ("Computes IT-Act block-wise depreciation, ingests Tally JSON, "
                   "matches OCR'd invoices to additions, runs 3CD validation gates, "
                   "exports to Excel + A4 PDF, and surfaces an MIS Summary cockpit."),
        "areas": [
            {
                "name": "Run lifecycle & Roll-forward",
                "items": [
                    "Create a new FA run for a client and FY (e.g. FY 2024-25); confirm status flips draft → ingested → computed → exported.",
                    "Roll forward closing WDV from a prior-year run; verify Opening WDV per block matches prior closing.",
                    "Re-ingest the same Tally JSON; verify additions/deletions are de-duplicated (no doubles).",
                    "Delete a run and confirm cascade — additions / openings / OCR attachments / exports all gone.",
                ],
            },
            {
                "name": "Tally JSON ingest",
                "items": [
                    "Upload a small Tally JSON (~5 vouchers); confirm additions parsed with correct date/party/amount/voucher #.",
                    "Upload a large Tally JSON (>10 MB or >5k vouchers); confirm no timeout + spinner shows.",
                    "Upload an invalid file (.xlsx renamed to .json); confirm 400 with clear error message.",
                    "Upload a JSON with merged Discount/Credit child rows; confirm parent–child collapse fires and net amount reaches the additions table.",
                ],
            },
            {
                "name": "Additions table (auditor surface)",
                "items": [
                    "Sort columns (date, party, voucher, amount); inline-edit Block, Rate, PTU date, Asset Description.",
                    "Default 'Put to Use' (PTU) date must be BLANK on ingest — auditor must explicitly fill.",
                    "Bulk-set Block + PTU on a multi-row selection; verify changes persist on refresh.",
                    "Filter by block, by party, by amount range; clear filters returns full list.",
                    "Toggle 'Include' / 'Exclude' on a row; confirm excluded row drops out of the Compute totals but stays in audit log.",
                ],
            },
            {
                "name": "OCR invoice matching",
                "items": [
                    "Upload an invoice image/PDF; confirm Gemini OCR returns vendor + amount + date.",
                    "Auto-match suggestion appears for the closest addition row; manual override works.",
                    "Detach an OCR doc; verify the addition's match-status flips back to unmatched.",
                    "Test with a poor-quality scan; confirm graceful fallback (empty fields, no crash).",
                ],
            },
            {
                "name": "3CD drift gate",
                "items": [
                    "Edit an addition AFTER computing depreciation; confirm 'Drift detected' banner appears AND Compute button is disabled.",
                    "Click 'Resync 3CD JSON'; verify drift clears and Compute re-enables.",
                    "Confirm zero-value blocks are filtered out of Compute and exports.",
                ],
            },
            {
                "name": "Excel round-trip (Opening WDV)",
                "items": [
                    "Download the Opening WDV Excel template; modify a block's opening cost.",
                    "Re-upload the modified Excel; confirm the diff banner shows the changes for review before commit.",
                    "Apply the diff and verify Opening WDV updates in DB + UI.",
                ],
            },
            {
                "name": "Compute & PDF/Excel exports",
                "items": [
                    "Run Compute; confirm WDV closing per block matches manual computation (sample 1 block end-to-end).",
                    "Half-yearly rule: addition AFTER 30-Sep gets 50% rate; verify a row dated 15-Oct fires this rule.",
                    "Massive-number formatting: 999,99,99,999.00 in PDF & Excel — verify columns auto-fit, no wrapping.",
                    "PDF export — verify the A4 register groups by block, totals tally, page numbers, signatory placeholder.",
                    "Excel export — verify columns auto-size, formulas are NOT broken (try opening in LibreOffice).",
                ],
            },
            {
                "name": "MIS Summary tab",
                "items": [
                    "Audit flag tiles (e.g. 'Additions without PTU', 'OCR unmatched', 'Excluded rows') show counts.",
                    "Click an audit tile; confirm it routes to Additions tab pre-filtered with the correct query.",
                    "Numbers on Summary tab match the live Compute output.",
                ],
            },
        ],
    },
    {
        "code":  "FSD",
        "title": "Financial Statement Designer",
        "owner": "Audit Lead",
        "scope": ("Ingests a pre-aggregated Schedule III FinalStatement JSON and "
                  "renders a signature-ready PDF (Classic / Boardroom) with BS + "
                  "P&L + Cash Flow on dedicated single pages, full notes, ageing "
                  "schedules, PPE matrix and Details section."),
        "areas": [
            {
                "name": "Run lifecycle",
                "items": [
                    "Create a new FS run for a client (e.g. Velav Garments) for FY 2024-25.",
                    "Re-ingest after edits; confirm status flips ingested → rendered.",
                    "Delete a run; verify fs_books_raw + fs_documents collections cascade-cleaned.",
                ],
            },
            {
                "name": "JSON ingest",
                "items": [
                    "Upload the V-904 sample FinalStatement JSON; confirm 23 notes + 80 details + ageing populate.",
                    "Upload an invalid envelope (no message.balance_sheet_report); confirm 400 with helpful error.",
                    "Upload a 60+ MB file; confirm 413 'File too large' error.",
                    "Re-ingest with an updated JSON; confirm document is replaced (no duplicate entries).",
                ],
            },
            {
                "name": "Statement structure (page 1-3)",
                "items": [
                    "BS page (p.1) — TOTAL (I) ≡ TOTAL (II); roman + arabic + lettered numbering matches reference.",
                    "P&L page (p.2) — TOTAL (I) Income + TOTAL (II) Expenses + Profit Before Tax + Tax Expense + PAT lines.",
                    "Cash Flow (p.3) — Operating + Investing + Financing sections; Net change in cash matches BS movement.",
                    "All 3 statement pages must carry the FULL signatory footer (auditor + 2 directors with DINs).",
                    "Header on every page: company name + CIN + city + statement title.",
                ],
            },
            {
                "name": "Notes (page 4+)",
                "items": [
                    "Note 1 must be 'Share Capital' (not 'Shareholders' Funds'); CY = ₹16,92,04,730.54.",
                    "Note 8 must be 'Property, Plant and Equipment' with the matrix block (Gross / Depn / Net).",
                    "Notes 2–7, 9–24 must show lettered (a./b./c.) sub-items with totals.",
                    "Trade Payables (Note 5) ageing schedule appended (Not-Due / <1Y / 1-2Y / 2-3Y / >3Y).",
                    "Trade Receivables (Note 12) ageing schedule appended.",
                    "No note breaks awkwardly across pages (KeepTogether honoured).",
                ],
            },
            {
                "name": "Details to FS section",
                "items": [
                    "Separate section starts on its own page after notes.",
                    "Each entry numbered 'N (a)', 'N (b)' etc. (e.g. '1 (a) Share Capital', '23 (h) Payment to Auditors').",
                    "Each entry shows underlying ledger leaves with CY + PY amounts, totals tally to the parent note.",
                ],
            },
            {
                "name": "Templates & download",
                "items": [
                    "Download Classic template; confirm monochrome look.",
                    "Download Boardroom template; confirm slate + sky accent.",
                    "Filename pattern: <CompanyName>_FS_<FY>_<template>.pdf.",
                    "Bad template name in URL → 400 'Unknown template'.",
                ],
            },
        ],
    },
    {
        "code":  "C44",
        "title": "Clause 44 — Expense GST Bifurcation (3CD)",
        "owner": "Tax Lead",
        "scope": ("Tally Day Book ingest, GSTIN-aware classification of expenses "
                  "into 5 Clause-44 columns (Total / GST-Registered / Composition "
                  "/ Exempt / Unregistered)."),
        "areas": [
            {
                "name": "Ingest & mapping",
                "items": [
                    "Upload Day Book Excel; confirm rows parsed with vendor + amount + voucher.",
                    "GSTIN auto-classification (Regular / Composition / Exempt / Unregistered) — sample 5 vendors.",
                    "Manual override on a row's classification persists after refresh.",
                    "Bulk-classify a vendor across all its rows in one click.",
                ],
            },
            {
                "name": "Validation gates",
                "items": [
                    "Row totals must sum to Total Expense column; mismatch shows 'Out of Balance' badge.",
                    "Vendor with GSTIN but classified 'Unregistered' raises a warning.",
                ],
            },
            {
                "name": "Report output",
                "items": [
                    "Generate Clause 44 report; verify the 5 columns add up correctly per row + grand total.",
                    "PDF / Excel export; verify column auto-sizing for large amounts.",
                ],
            },
        ],
    },
    {
        "code":  "MSME",
        "title": "Section 43B(h) — MSME 45-Day Disallowance",
        "owner": "Tax Lead",
        "scope": ("Ingests creditor bills, MSME registration status, payment dates; "
                  "flags amounts paid beyond 45 / 15 days (per agreed credit terms) "
                  "as deemed disallowance under 43B(h)."),
        "areas": [
            {
                "name": "Master data",
                "items": [
                    "Upload vendor MSME master (Udyam ID + classification Micro/Small/Medium).",
                    "Confirm Medium-class vendors are EXCLUDED from 43B(h) net (per 2024 amendment).",
                ],
            },
            {
                "name": "Aging & disallowance",
                "items": [
                    "Outstanding > 45 days as at 31-Mar — confirm flagged for disallowance.",
                    "Bills with explicit credit terms longer than 15 days but no formal agreement — disallowance kicks in at day 16, not day 45.",
                    "Payment after year-end but before due date — confirm allowed.",
                    "Sample a creditor with mixed Allowed + Disallowed bills; verify the line-item split is correct.",
                ],
            },
            {
                "name": "Outputs",
                "items": [
                    "Disallowance computation report — total ₹ disallowed for FY.",
                    "Excel + PDF export with vendor-wise breakdown.",
                    "Reverse-disallowance schedule for next-year payments.",
                ],
            },
        ],
    },
    {
        "code":  "GST",
        "title": "GST Reconciliation (GSTR-2A/2B vs Books)",
        "owner": "Tax Lead",
        "scope": ("Matches purchase register entries with GSTR-2A/2B downloads to "
                  "surface mismatches by GSTIN, invoice #, amount, tax."),
        "areas": [
            {
                "name": "Ingest",
                "items": [
                    "Upload GSTR-2B Excel; confirm rows parsed.",
                    "Upload purchase register; confirm rows parsed.",
                    "Re-upload should replace prior data (no duplication).",
                ],
            },
            {
                "name": "Matching",
                "items": [
                    "Exact match on (GSTIN, invoice #, amount, tax); confirm matched flag.",
                    "Fuzzy match (slightly different invoice # — e.g. trailing space or case) — confirm grouping under 'Probable matches'.",
                    "Books-only entries (not in 2B) → 'Books extra' bucket.",
                    "2B-only entries (not in books) → '2B extra' bucket.",
                ],
            },
            {
                "name": "Output",
                "items": [
                    "Recon report Excel/PDF with summary + line-level mismatches.",
                    "Click a mismatch row → drill-down to underlying voucher.",
                ],
            },
        ],
    },
    {
        "code":  "BC",
        "title": "Balance Confirmation",
        "owner": "Audit Lead",
        "scope": ("Sends balance-confirmation requests to creditors / debtors via "
                  "Resend, tracks responses, generates draft confirmation letters."),
        "areas": [
            {
                "name": "Master data",
                "items": [
                    "Upload party master (name + email + outstanding balance + as-at date).",
                    "Manual edit an email; confirm validation (basic email regex).",
                ],
            },
            {
                "name": "Email send (Resend)",
                "items": [
                    "Send a single test confirmation email to your own address; confirm receipt + correct branding.",
                    "Bulk-send to 5 parties; confirm 5/5 sent successfully (status = sent).",
                    "Confirm a soft-bounce or hard-bounce; verify status flips to bounced.",
                    "Re-send to a single party (after correcting email).",
                ],
            },
            {
                "name": "Response capture",
                "items": [
                    "Confirm 'Match' response; status flips to confirmed.",
                    "Confirm 'Mismatch' with party-side balance; status flips to disputed + the delta is captured.",
                    "PDF letter generation for non-respondents (drop-2 reminder).",
                ],
            },
        ],
    },
    {
        "code":  "ADMIN",
        "title": "Cross-cutting — Auth, Clients, Admin",
        "owner": "Tech / PM",
        "scope": ("Login (Emergent Google OAuth), client switching, role-based "
                  "access, admin user management."),
        "areas": [
            {
                "name": "Auth & session",
                "items": [
                    "Login via Google; confirm redirect → /dashboard.",
                    "Logout; cookie cleared; protected routes bounce to /login.",
                    "Session persists across browser refresh.",
                    "Try opening a deep link without login; confirm redirect captures the original URL.",
                ],
            },
            {
                "name": "Client management",
                "items": [
                    "Create new client (name + GSTIN + PAN).",
                    "Switch active client; confirm utilities pages scope to that client only.",
                    "Edit client; verify CIN field for FS Designer (newly added).",
                    "Delete a client (admin only) — confirm cascade across modules.",
                ],
            },
            {
                "name": "Admin",
                "items": [
                    "Invite a new user via email; confirm invite arrives + accepts.",
                    "Promote / demote a user role; confirm permissions update on next login.",
                ],
            },
        ],
    },
    {
        "code":  "REG",
        "title": "Cross-module Regression",
        "owner": "QA Lead",
        "scope": "Quick smoke checklist to run AFTER any single-module fix.",
        "areas": [
            {
                "name": "Smoke",
                "items": [
                    "Login still works; dashboard renders client list.",
                    "Open each module from Utilities shelf; confirm landing page renders.",
                    "Upload + ingest a small file in each module; confirm no 500s.",
                    "Download an export from each module; confirm filename + size are sensible.",
                    "Logout works.",
                ],
            },
        ],
    },
]


# ------------------------------ rendering -------------------------------
def _styles():
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18,
                             leading=21, textColor=PALETTE["ink"], spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                             leading=15, textColor=PALETTE["ink"], spaceAfter=3),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5,
                             leading=12, textColor=PALETTE["accent"],
                             spaceBefore=6, spaceAfter=2),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                leading=10, textColor=PALETTE["mute"]),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               leading=12, textColor=PALETTE["ink"]),
        "body_b": ParagraphStyle("body_b", fontName="Helvetica-Bold",
                                  fontSize=9.5, leading=12, textColor=PALETTE["ink"]),
        "tiny": ParagraphStyle("tiny", fontName="Helvetica", fontSize=7.5,
                               leading=9, textColor=PALETTE["mute"]),
        "item": ParagraphStyle("item", fontName="Helvetica", fontSize=9.2,
                               leading=11.5, textColor=PALETTE["ink"],
                               leftIndent=4),
    }


def _page_decor(canvas, doc):
    canvas.saveState()
    # Top header band
    canvas.setFillColor(PALETTE["ink"])
    canvas.rect(0, doc.pagesize[1] - 14 * mm,
                doc.pagesize[0], 14 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(colors.white)
    canvas.drawString(doc.leftMargin, doc.pagesize[1] - 9 * mm,
                      "ASSUREAI — QA TEST PACK")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin,
                           doc.pagesize[1] - 9 * mm,
                           "Internal use · v1.0")
    # Footer
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(PALETTE["mute"])
    canvas.drawCentredString(doc.pagesize[0] / 2, 7 * mm,
                             f"Page {doc.page} · Tester: ____________________  ·  Date: __ / __ / 2026")
    canvas.restoreState()


def _module_card(mod, styles, content_w):
    flow: List[Any] = []
    # Header strip
    head_data = [[
        Paragraph(f"<b>{mod['code']}</b>", styles["body_b"]),
        Paragraph(f"<b>{mod['title']}</b>", styles["body_b"]),
        Paragraph(f"<i>Owner: {mod['owner']}</i>", styles["tiny"]),
    ]]
    head = Table(head_data, colWidths=[18 * mm, content_w - 18 * mm - 35 * mm, 35 * mm])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALETTE["accent"]),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(head)
    flow.append(Paragraph(f'<font color="#475569"><i>{mod["scope"]}</i></font>',
                          styles["small"]))
    flow.append(Spacer(1, 2 * mm))

    # Areas + checkboxes
    for area in mod["areas"]:
        rows: List[List[Any]] = [
            [Paragraph(f"<b>{area['name']}</b>", styles["h3"]),
             Paragraph("Pass", styles["tiny"]),
             Paragraph("Fail", styles["tiny"]),
             Paragraph("Notes / Bug ID", styles["tiny"])],
        ]
        for it in area["items"]:
            rows.append([
                Paragraph(it, styles["item"]),
                Paragraph("☐", styles["body"]),
                Paragraph("☐", styles["body"]),
                Paragraph("", styles["body"]),
            ])
        col_w = (content_w * 0.62, content_w * 0.07,
                 content_w * 0.07, content_w * 0.24)
        t = Table(rows, colWidths=col_w, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PALETTE["band"]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BOX", (0, 0), (-1, -1), 0.4, PALETTE["hair"]),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, PALETTE["hair"]),
            ("ALIGN", (1, 1), (2, -1), "CENTER"),
            ("FONTSIZE", (1, 1), (2, -1), 11),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 2.5 * mm))

    flow.append(Spacer(1, 4 * mm))
    return flow


def _cover(styles, content_w):
    flow: List[Any] = []
    flow.append(Spacer(1, 30 * mm))
    flow.append(Paragraph("AssureAI", styles["h2"]))
    flow.append(Paragraph("Audit Utilities — QA Test Pack", styles["h1"]))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(
        "This pack contains a structured, tick-box checklist for every live "
        "module. Run one module per tester, capture defects in the Notes / "
        "Bug ID column, then circulate the completed pack back to the audit "
        "lead. Areas are intentionally split so two QAs can work in parallel "
        "without stepping on each other.",
        styles["body"]))
    flow.append(Spacer(1, 8 * mm))

    # Summary table of modules
    rows = [["Code", "Module", "Owner", "# Areas", "# Items"]]
    for m in MODULES:
        n_items = sum(len(a["items"]) for a in m["areas"])
        rows.append([m["code"], m["title"], m["owner"], str(len(m["areas"])), str(n_items)])
    rows.append(["", "Total", "",
                 str(sum(len(m["areas"]) for m in MODULES)),
                 str(sum(sum(len(a["items"]) for a in m["areas"]) for m in MODULES))])
    col_w = (15 * mm, content_w - 15 * mm - 30 * mm - 18 * mm - 18 * mm,
             30 * mm, 18 * mm, 18 * mm)
    t = Table(rows, colWidths=col_w, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALETTE["accent"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), PALETTE["soft"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (3, 0), (4, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.4, PALETTE["hair"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, PALETTE["hair"]),
    ]))
    flow.append(t)

    flow.append(Spacer(1, 10 * mm))
    flow.append(Paragraph(
        "<b>How to run this pack</b><br/>"
        "1. Pick one module section per tester.<br/>"
        "2. Read each item, perform the action, tick Pass or Fail.<br/>"
        "3. For Fail, record reproduction steps + screenshots in the Notes column.<br/>"
        "4. Hand back the marked-up pack to the audit lead at end-of-day.<br/>"
        "5. Block any module with &gt; 5 Fail items from production until re-tested.",
        styles["body"]))

    flow.append(PageBreak())
    return flow


def render_qa_pack() -> bytes:
    buf = io.BytesIO()
    page_w, page_h = A4
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=20 * mm, bottomMargin=12 * mm,
        title="AssureAI — QA Test Pack",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        page_w - doc.leftMargin - doc.rightMargin,
        page_h - doc.topMargin - doc.bottomMargin,
        id="body",
    )
    doc.addPageTemplates([
        PageTemplate(id="Body", frames=[frame], onPage=_page_decor),
    ])

    styles = _styles()
    content_w = page_w - doc.leftMargin - doc.rightMargin

    story: List[Any] = []
    story.extend(_cover(styles, content_w))
    for mod in MODULES:
        # Module header should stay with first area
        story.append(KeepTogether(_module_card(mod, styles, content_w)[:3]))
        for block in _module_card(mod, styles, content_w)[3:]:
            story.append(block)
        story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


__all__ = ["render_qa_pack"]
