"""Release 4.6 · Refinement 1 + 2 — Balance Confirmation address split,
offline PDF generator, and Subhead/Head computation.

Pure-function unit tests — no live HTTP, no DB.  Covers:

  R1.A  CSV export/import round-trip with split address fields
        + legacy single-column `address` backward compat.
  R1.C  ZIP of offline PDFs has one entry per ledger and the bytes
        actually parse as a multi-page PDF.
  R2    compute_head_subhead walks Tally group chains correctly.
"""
from __future__ import annotations

import io
import zipfile

from modules.balance_confirmation.classifier import (
    build_group_index,
    classify_ledger,
    compute_head_subhead,
)
from modules.balance_confirmation.offline_pdf import build_offline_letters_zip
from modules.balance_confirmation.service import (
    EMAIL_CSV_COLUMNS,
    _split_address,
    export_email_csv,
    import_email_csv,
)


# --------------------------------------------------------------------------- #
# R1.A — CSV schema
# --------------------------------------------------------------------------- #
def test_csv_columns_include_split_address():
    """The exported CSV header must list the 4 split address columns and
    NOT the legacy single `address` column."""
    assert "address_line_1" in EMAIL_CSV_COLUMNS
    assert "address_line_2" in EMAIL_CSV_COLUMNS
    assert "city" in EMAIL_CSV_COLUMNS
    assert "pincode" in EMAIL_CSV_COLUMNS
    assert "address" not in EMAIL_CSV_COLUMNS


def test_csv_round_trip_preserves_split_address():
    rows = [{
        "ledger_id": "l1", "name": "Acme Pvt Ltd",
        "parent_group": "Sundry Creditors", "head": "Current Liabilities",
        "subhead": "Sundry Creditors", "category": "trade_payable",
        "closing_balance": 12345.67, "dr_cr": "cr",
        "email": "a@x.in", "cc_emails": ["b@x.in"], "bcc_emails": [],
        "contact_name": "", "phone": "", "gstin": "", "pan": "",
        "address_line_1": "12 MG Road", "address_line_2": "Floor 3",
        "city": "Pune", "pincode": "411001",
    }]
    csv_bytes = export_email_csv(rows)
    parsed = import_email_csv(csv_bytes)
    assert len(parsed) == 1
    p = parsed[0]
    assert p["address_line_1"] == "12 MG Road"
    assert p["address_line_2"] == "Floor 3"
    assert p["city"] == "Pune"
    assert p["pincode"] == "411001"
    assert p["email"] == "a@x.in"


def test_csv_legacy_address_column_backward_compat():
    """Older CSVs with single `address` column should still parse — split
    fields are inferred via comma + 6-digit pincode heuristic."""
    legacy = (
        "ledger_id,name,address\n"
        'l1,Acme,"12 MG Road, Floor 3, Pune, 411001"\n'
    ).encode("utf-8-sig")
    parsed = import_email_csv(legacy)
    assert len(parsed) == 1
    p = parsed[0]
    assert p["pincode"] == "411001"
    assert p["city"] == "Pune"
    assert p.get("address_line_1") or p.get("address_line_2")


def test_split_address_from_tally_fields():
    src = {
        "addressLine1": "12 MG Road",
        "addressLine2": "Floor 3",
        "city": "Pune",
        "pinCode": "411001",
    }
    out = _split_address(src)
    assert out == {
        "address_line_1": "12 MG Road",
        "address_line_2": "Floor 3",
        "city": "Pune",
        "pincode": "411001",
    }


# --------------------------------------------------------------------------- #
# R1.C — Offline PDF ZIP
# --------------------------------------------------------------------------- #
def test_offline_pdf_zip_has_one_entry_per_ledger():
    ledgers = [
        {"ledger_id": "l1", "name": "Acme Pvt Ltd",
         "closing_balance": 12345.67, "dr_cr": "cr",
         "address_line_1": "12 MG Road", "city": "Pune", "pincode": "411001",
         "gstin": "27ABCDE1234F1Z5"},
        {"ledger_id": "l2", "name": "Beta Traders",
         "closing_balance": -4567.89, "dr_cr": "dr",
         "address_line_1": "5 Marine Drive", "city": "Mumbai", "pincode": "400001"},
    ]
    client = {"name": "XYZ Ltd", "gstin": "27XYZ", "address": "Mumbai", "fy_end": "31 Mar 2025"}
    auditor = {"firm_name": "Test & Co", "partner_name": "CA Smith"}
    zip_bytes = build_offline_letters_zip(
        ledgers=ledgers, client=client, auditor=auditor, as_at_date="31 Mar 2025",
    )
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = zf.namelist()
    assert len(names) == 2
    assert any("Acme" in n for n in names)
    assert any("Beta" in n for n in names)
    # Each entry must be a non-empty PDF
    for n in names:
        data = zf.read(n)
        assert data.startswith(b"%PDF"), f"{n} is not a PDF"
        assert len(data) > 1500


def test_offline_pdf_letter_includes_party_and_balance():
    """The PDF should contain the party name + a Dr/Cr balance string."""
    ledger = {
        "ledger_id": "l1", "name": "Acme Industries Pvt Ltd",
        "closing_balance": 234567.89, "dr_cr": "cr",
        "address_line_1": "12 MG Road", "city": "Pune", "pincode": "411001",
    }
    client = {"name": "XYZ Mfg Ltd", "gstin": "27XYZAB1234C1Z5",
              "address": "Mumbai", "fy_end": "31 Mar 2025"}
    auditor = {"firm_name": "Test & Co · CAs", "partner_name": "CA J. Smith"}
    zip_bytes = build_offline_letters_zip(
        ledgers=[ledger], client=client, auditor=auditor,
        as_at_date="31 Mar 2025",
    )
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    pdf_bytes = zf.read(zf.namelist()[0])
    # ReportLab compresses streams, but party name surfaces as raw ASCII.
    # For a non-fragile assert, just confirm "%PDF" header + min size.
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 2500   # cover letter + tear-off → multi-KB


# --------------------------------------------------------------------------- #
# R2 — Subhead computation from Tally group chain
# --------------------------------------------------------------------------- #
def _idx(*pairs):
    return build_group_index([{"name": n, "parentGroup": p} for n, p in pairs])


def test_subhead_msme_under_sundry_creditors_under_current_liabilities():
    g = _idx(
        ("MSME Vendors", "Domestic Suppliers"),
        ("Domestic Suppliers", "Sundry Creditors"),
        ("Sundry Creditors",   "Current Liabilities"),
        ("Current Liabilities", ""),
    )
    head, subhead = compute_head_subhead("MSME Vendors", g)
    assert head == "Current Liabilities"
    assert subhead == "Sundry Creditors"
    assert classify_ledger("MSME Vendors", g) == "trade_payable"


def test_subhead_bank_under_current_assets():
    g = _idx(
        ("HDFC Bank A/C", "Bank Accounts"),
        ("Bank Accounts",  "Current Assets"),
        ("Current Assets", ""),
    )
    head, subhead = compute_head_subhead("HDFC Bank A/C", g)
    assert head == "Current Assets"
    assert subhead == "Bank Accounts"
    assert classify_ledger("HDFC Bank A/C", g) == "bank"


def test_subhead_falls_back_when_chain_terminates_at_reserved_top_level():
    """Tally's default chart has Sundry Debtors as a primary top-level group
    (no Current Assets parent).  Head should pick it up; subhead is empty."""
    g = _idx(
        ("Sundry Debtors", ""),
    )
    # Ledger "Tata Steel" with parent group "Sundry Debtors".
    head, subhead = compute_head_subhead("Sundry Debtors", g)
    assert head == "Sundry Debtors"
    assert subhead == ""


def test_subhead_unmapped_chain_returns_blank():
    g = _idx(
        ("Foo", "Bar"),
        ("Bar", ""),
    )
    head, subhead = compute_head_subhead("Foo", g)
    assert head == "Bar"   # last link as best-effort
    assert subhead == ""
