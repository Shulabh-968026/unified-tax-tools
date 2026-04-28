"""Shared helpers for GST Recon e2e tests — synthetic mapping XLSX + voucher
builders that match the new Tally-aware aggregator contract:

  • ledger entry key is `ledger` (NOT `ledgerName`)
  • voucher party is `partyLedgerName`
  • sign convention: +ve = Credit, -ve = Debit
  • books extraction is mapping-driven, so a synthetic mapping XLSX must be
    uploaded for any books_per_month / books_per_invoice assertions to be
    non-empty.
"""
from __future__ import annotations
import io
import json
from typing import Dict, List

import openpyxl


# Ledger names used across all e2e tests
LEDGER_SALES = "Sales Account"
LEDGER_OTHER_INCOME = "Interest Received"
LEDGER_PURCHASE = "Purchase Account"
LEDGER_OUTPUT_CGST = "Output CGST @ 9%"
LEDGER_OUTPUT_SGST = "Output SGST @ 9%"
LEDGER_OUTPUT_IGST = "Output IGST @ 18%"
LEDGER_INPUT_CGST = "Input CGST @ 9%"
LEDGER_INPUT_SGST = "Input SGST @ 9%"
LEDGER_INPUT_IGST = "Input IGST @ 18%"


def synthetic_mapping_xlsx() -> bytes:
    """Build a minimal but classification-complete Ledger Mapping XLSX with
    the required columns & rows so that:
        revenue     ⊇ {Sales Account, Interest Received}
        output_tax  ⊇ {Output CGST/SGST/IGST}
        input_tax   ⊇ {Input CGST/SGST/IGST}
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Ledger Name", "BS or PL", "Group Parent",
               "Map to Subhead", "Head", "Last Mapped Via"])
    rows = [
        # Revenue
        (LEDGER_SALES, "P", "Sales Accounts", "Sale of Goods",
         "Revenue from Operations", "—"),
        (LEDGER_OTHER_INCOME, "P", "Indirect Incomes", "Interest Income",
         "Other Income", "—"),
        # Output Tax (group_parent='Output Credit')
        (LEDGER_OUTPUT_CGST, "B", "Output Credit", "Statutory Dues Payable",
         "Other Current Liabilities", "—"),
        (LEDGER_OUTPUT_SGST, "B", "Output Credit", "Statutory Dues Payable",
         "Other Current Liabilities", "—"),
        (LEDGER_OUTPUT_IGST, "B", "Output Credit", "Statutory Dues Payable",
         "Other Current Liabilities", "—"),
        # Input Tax (group_parent='Input Credit')
        (LEDGER_INPUT_CGST, "B", "Input Credit", "Statutory Dues Receivable",
         "Other Current Assets", "—"),
        (LEDGER_INPUT_SGST, "B", "Input Credit", "Statutory Dues Receivable",
         "Other Current Assets", "—"),
        (LEDGER_INPUT_IGST, "B", "Input Credit", "Statutory Dues Receivable",
         "Other Current Assets", "—"),
        # Unmapped tax-flavoured ledger → goes into mapping_unmapped_ledgers
        ("Writeoff ITC Expenses", "P", "Indirect Expenses", "Other Expenses",
         "Other Expenses", "—"),
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sales_voucher(no: str, date: str, party_gstin: str,
                  taxable: float = 1000.0,
                  cgst: float = 90.0, sgst: float = 90.0,
                  party_name: str = "Acme Ltd") -> Dict:
    """Tally-shape sales voucher (B2B). Uses `ledger` + `partyLedgerName`
    and Tally sign convention (Cr=+ve, Dr=-ve)."""
    return {
        "date": date,
        "voucherTypeName": "Sales",
        "voucherNumber": no,
        "partyGSTIN": party_gstin,
        "partyLedgerName": party_name,
        "ledgerEntries": [
            {"ledger": party_name, "isPartyLedger": "Yes",
             "amount": -(taxable + cgst + sgst)},
            {"ledger": LEDGER_SALES, "amount": taxable},
            {"ledger": LEDGER_OUTPUT_CGST, "amount": cgst},
            {"ledger": LEDGER_OUTPUT_SGST, "amount": sgst},
        ],
    }


def purchase_voucher(no: str, date: str, party_gstin: str,
                     taxable: float = 500.0,
                     cgst: float = 45.0, sgst: float = 45.0,
                     party_name: str = "Suppl Vendor") -> Dict:
    """Tally-shape purchase voucher. Party is creditor (+ve), tax + purchase
    are debits (-ve)."""
    return {
        "date": date,
        "voucherTypeName": "Purchase",
        "voucherNumber": no,
        "partyGSTIN": party_gstin,
        "partyLedgerName": party_name,
        "ledgerEntries": [
            {"ledger": party_name, "isPartyLedger": "Yes",
             "amount": (taxable + cgst + sgst)},
            {"ledger": LEDGER_PURCHASE, "amount": -taxable},
            {"ledger": LEDGER_INPUT_CGST, "amount": -cgst},
            {"ledger": LEDGER_INPUT_SGST, "amount": -sgst},
        ],
    }


def books_payload(vouchers: List[Dict],
                  gstin: str,
                  books_from: str = "01-04-2024",
                  books_to: str = "31-03-2025") -> bytes:
    payload = {
        "company": {"booksFromDate": books_from, "booksToDate": books_to,
                    "gstin": gstin},
        "vouchers": vouchers,
    }
    return json.dumps(payload).encode("utf-8")
