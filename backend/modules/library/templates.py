"""Template generators for Library file-types.

Some file-types — notably Party Master — can be **pre-populated** from
data we already hold in the Library.  Auditor downloads the template,
fills the gaps offline (emails, MSME status, etc.), and re-uploads.

Each generator is a callable:
    generator(*, firm_id, client_id, period, division) -> (xlsx_bytes, filename)

Generators are registered by file_type below.  A file_type with no
registered generator returns 404 from the controller — the UI hides
the "Download Template" button accordingly via the catalog's
`has_template` flag.
"""
from __future__ import annotations

import io
import json
from typing import Awaitable, Callable, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from modules.library import service as lib_svc
from modules.library.controller import DEFAULT_FIRM_ID  # for callers


# ---------------------------------------------------------------------------
# Styling helpers — keep templates visually consistent.
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
PREFILLED_FILL = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid")  # pale emerald
TODO_FILL = PatternFill(start_color="FFFBEB", end_color="FFFBEB", fill_type="solid")  # pale amber
SECTION_FILL = PatternFill(start_color="F3F4F1", end_color="F3F4F1", fill_type="solid")
SECTION_FONT = Font(name="Calibri", size=10, bold=True, color="52524E")


def _autosize(ws, headers: list[str], rows: list[list]):
    for ci, h in enumerate(headers, start=1):
        col = get_column_letter(ci)
        max_len = max([len(str(h or ""))] + [len(str(r[ci - 1]) if ci - 1 < len(r) else "") for r in rows])
        ws.column_dimensions[col].width = min(max(max_len + 2, 12), 48)


def _write_header(ws, headers: list[str], note_row: list[str] | None = None):
    """Write the first row as styled header; optional second row of notes."""
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28
    if note_row:
        for ci, n in enumerate(note_row, start=1):
            c = ws.cell(row=2, column=ci, value=n)
            c.fill = SECTION_FILL
            c.font = SECTION_FONT
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[2].height = 24


# ---------------------------------------------------------------------------
# Party Master template.
# ---------------------------------------------------------------------------
PARTY_HEADERS = [
    "Party Name",                     # pre-filled
    "Group / Subhead",                # pre-filled
    "Closing Balance (Cr / Dr)",      # pre-filled
    "GSTIN",                          # pre-filled (where available)
    "GST Registration Type",          # pre-filled (where available)
    "Country",                        # pre-filled (where available)
    "Email ID",                       # AUDITOR FILL
    "Alternate Email",                # AUDITOR FILL
    "Phone",                          # AUDITOR FILL
    "Address",                        # AUDITOR FILL
    "MSME Status",                    # AUDITOR FILL — Micro / Small / Medium / Not MSME
    "MSME Registration No.",          # AUDITOR FILL (if MSME)
    "PAN",                            # AUDITOR FILL
    "Notes",                          # AUDITOR FILL
]
PARTY_HEADER_NOTES = [
    "Pre-filled · do not edit",
    "Pre-filled · do not edit",
    "Pre-filled · do not edit (figure as on year-end)",
    "Pre-filled where Tally has it",
    "regular / composition / consumer / unregistered / overseas",
    "Pre-filled if non-India",
    "Required for Balance Confirmation",
    "Optional · CC on confirmation emails",
    "Optional",
    "Optional",
    "Required for 43B(h) MSME disallowance",
    "Mandatory if MSME Status ≠ 'Not MSME'",
    "Optional",
    "Free text",
]

# Categorization buckets — used to split parties into sheets for usability.
GROUP_BUCKETS = {
    "Sundry Creditors":  ["sundry creditors", "trade payable", "trade payables", "creditors"],
    "Sundry Debtors":    ["sundry debtors", "trade receivable", "trade receivables", "debtors"],
    "Loans & Advances":  ["loans", "advances", "loans & advances", "loans and advances"],
    "Other Parties":     [],  # everything else
}


def _bucket_for(group_or_subhead: str) -> str:
    s = (group_or_subhead or "").strip().lower()
    for bucket, hints in GROUP_BUCKETS.items():
        if any(h in s for h in hints):
            return bucket
    return "Other Parties"


def _row_for_party(name: str, ledger_rec: dict, json_party: dict | None) -> list:
    closing = ledger_rec.get("closingBalance")
    closing_str = ""
    if closing is not None:
        sign = "Cr" if closing < 0 else "Dr"
        closing_str = f"{abs(closing):,.2f} {sign}"
    json_party = json_party or {}
    country = (json_party.get("country") or "").strip()
    return [
        name,
        ledger_rec.get("subhead") or ledger_rec.get("groupParent") or "",
        closing_str,
        json_party.get("partyGSTIN") or "",
        (json_party.get("gstRegistrationType") or "").lower(),
        "" if country.lower() in ("india", "") else country,
        "",  # email — auditor
        "",  # alt email
        "",  # phone
        "",  # address
        "",  # MSME status
        "",  # MSME reg no
        "",  # PAN
        "",  # notes
    ]


async def generate_party_master_template(
    *, firm_id: str, client_id: str, period: str, division: str | None,
) -> Tuple[bytes, str]:
    """Build a multi-sheet Party Master template.

    Sheets:
      • README             — instructions + legend
      • Sundry Creditors   — pre-filled vendor list (most important)
      • Sundry Debtors     — pre-filled customer list
      • Loans & Advances   — pre-filled loan / advance parties
      • Other Parties      — anything else with a closing balance

    Pre-fill sources:
      • Ledger Mapping XLSX (current version) — name, group, closing balance.
      • Books JSON         (current version) — GSTIN, regType, country.
    """
    # ── 1. Read the latest Library files we need.
    ledger_map = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=client_id, period=period,
        division=division, file_type="ledger_mapping_xlsx",
    )
    books = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=client_id, period=period,
        division=division, file_type="books_json",
    )
    if not ledger_map:
        raise FileNotFoundError("Ledger Mapping XLSX must be uploaded first.")

    # The XLSX was already parsed by the Clause 44 controller into a
    # dict-of-records when its run was created.  Re-parse here so we
    # don't depend on that — the template should work even when no
    # Clause 44 run has been generated yet.
    from modules.clause44.service import parse_ledger_xlsx
    ledger_xlsx_bytes = await lib_svc.read_file_bytes(ledger_map["file_id"])
    ledger_records = parse_ledger_xlsx(ledger_xlsx_bytes)

    # Books JSON for GSTIN / reg-type / country.
    parties_by_name: dict[str, dict] = {}
    if books:
        try:
            data = json.loads(await lib_svc.read_file_bytes(books["file_id"]))
            for p in data.get("parties", []) or []:
                if p.get("name"):
                    parties_by_name[p["name"].strip()] = p
            # Some Tally exports name parties via the ledger object.
            for lg in data.get("ledgers", []) or []:
                nm = (lg.get("name") or "").strip()
                if nm and nm not in parties_by_name and lg.get("partyGSTIN"):
                    parties_by_name[nm] = lg
        except Exception:
            pass

    # ── 2. Bucket parties.
    buckets: dict[str, list[list]] = {b: [] for b in GROUP_BUCKETS}
    for name, rec in ledger_records.items():
        bucket = _bucket_for(rec.get("subhead") or rec.get("groupParent") or "")
        # Only include rows that look like a party — skip non-party BS heads
        # (no closing balance OR ledger has BS-or-PL == 'P').
        if rec.get("bsOrPl") == "P":
            continue
        if bucket == "Other Parties":
            # For "Other Parties" we further filter to entries that look
            # like contractual counter-parties (have a closing balance).
            if not rec.get("closingBalance"):
                continue
        buckets[bucket].append(_row_for_party(name, rec, parties_by_name.get(name)))

    # Sort each bucket by name for stable, scannable output.
    for b, rows in buckets.items():
        rows.sort(key=lambda r: r[0].lower())

    # ── 3. Build the workbook.
    wb = Workbook()
    # Default sheet → README.
    readme = wb.active
    readme.title = "README"
    readme["A1"] = "Party Master Template — AssureAI Audit Utilities"
    readme["A1"].font = Font(bold=True, size=14)
    readme["A3"] = "How to use"
    readme["A3"].font = Font(bold=True, size=11)
    instructions = [
        "1. The Party Name, Group, Closing Balance, GSTIN, GST Registration Type and Country columns are pre-filled from your Tally Books JSON and Ledger Mapping XLSX.  Do NOT edit them.",
        "2. Fill the Email ID column for every party that needs a balance confirmation.  Add an Alternate Email if you'd like a CC.",
        "3. For 43B(h) MSME disallowance, set MSME Status = Micro / Small / Medium for every MSME-registered supplier and capture the MSME Registration No.",
        "4. Save and re-upload via the Library panel — the engine will pick up the enrichment automatically.",
        "5. You can leave a row's email blank if you don't intend to seek confirmation from that party.",
        "",
        "Legend",
        "  • Pre-filled (read-only) cells are shown with a pale emerald background.",
        "  • Auditor-fill cells are shown with a pale amber background.",
        "",
        "Sheets",
        "  • Sundry Creditors  — vendors / suppliers (highest priority for confirmations + 43B(h) MSME).",
        "  • Sundry Debtors    — customers (for receivable confirmations).",
        "  • Loans & Advances  — counter-parties for loans, advances, deposits.",
        "  • Other Parties     — anything else with a closing balance.",
    ]
    for i, line in enumerate(instructions, start=4):
        readme.cell(row=i, column=1, value=line)
    readme.column_dimensions["A"].width = 110

    # ── 4. One sheet per bucket.
    for bucket in GROUP_BUCKETS:
        rows = buckets[bucket]
        ws = wb.create_sheet(title=bucket)
        _write_header(ws, PARTY_HEADERS, note_row=PARTY_HEADER_NOTES)
        # Highlight pre-filled vs auditor-fill columns.
        prefilled_cols = (1, 2, 3, 4, 5, 6)   # 1-indexed
        for ri, row in enumerate(rows, start=3):
            for ci, val in enumerate(row, start=1):
                c = ws.cell(row=ri, column=ci, value=val)
                c.fill = PREFILLED_FILL if ci in prefilled_cols else TODO_FILL
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
        if not rows:
            ws.cell(row=3, column=1, value="(no parties in this bucket)").font = Font(italic=True, color="8A8A83")
        _autosize(ws, PARTY_HEADERS, rows)
        ws.freeze_panes = "A3"  # both header rows fixed
        ws.sheet_view.showGridLines = False

    # ── 5. Stream out.
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), f"party_master_template__{client_id}__{period}.xlsx"


# ---------------------------------------------------------------------------
# Registry — file_type → generator.  Add new entries as we extend support.
# ---------------------------------------------------------------------------
TemplateGenerator = Callable[..., Awaitable[Tuple[bytes, str]]]
TEMPLATE_GENERATORS: dict[str, TemplateGenerator] = {
    "party_master_xlsx": generate_party_master_template,
}


def has_template(file_type: str) -> bool:
    return file_type in TEMPLATE_GENERATORS


async def generate_template(
    *, file_type: str, firm_id: str, client_id: str, period: str, division: str | None,
) -> Tuple[bytes, str]:
    gen = TEMPLATE_GENERATORS.get(file_type)
    if not gen:
        raise FileNotFoundError(f"No template generator registered for '{file_type}'")
    return await gen(
        firm_id=firm_id, client_id=client_id, period=period, division=division,
    )
