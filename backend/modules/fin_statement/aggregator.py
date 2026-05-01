"""Schedule III aggregator — turns Tally books JSON into a normalised
Financial Statement document ready for PDF rendering.

Phase 1 scope (this drop): Balance Sheet + P&L line items only — enough
to confirm the end-to-end wire before we build notes, cash flow and the
two designer PDF templates in Drop 2.

The aggregator walks the Tally group tree (every ledger's openingBalance
+ closingBalance with its `bsOrPnl` flag and recursive parentGroup chain)
and maps each ledger into a Schedule III head.

Deliberately pure-Python — no DB calls here; caller hands in a parsed
dict and receives a nested dict back. Keeps this trivially unit-testable
without Mongo.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Tuple


# Tally Primary group → Schedule III head.
# Keys are Tally's built-in group names; values are Schedule III anchors.
# When a ledger's reserved parent (walked up the chain) isn't in the map
# we fall back to "Other <section>" so nothing is silently dropped.
SCHEDULE_III_MAP = {
    # ----- Equity & Liabilities -----
    "Capital Account":          "Equity::Share Capital & Reserves",
    "Reserves & Surplus":       "Equity::Share Capital & Reserves",
    "Loans (Liability)":        "Liability::Long-term Borrowings",
    "Secured Loans":            "Liability::Long-term Borrowings",
    "Unsecured Loans":          "Liability::Long-term Borrowings",
    "Bank OD A/c":              "Liability::Short-term Borrowings",
    "Bank OCC A/c":             "Liability::Short-term Borrowings",
    "Sundry Creditors":         "Liability::Trade Payables",
    "Duties & Taxes":           "Liability::Other Current Liabilities",
    "Provisions":               "Liability::Short-term Provisions",
    "Current Liabilities":      "Liability::Other Current Liabilities",
    "Suspense A/c":             "Liability::Other Current Liabilities",
    "Branch / Divisions":       "Liability::Other Current Liabilities",
    # ----- Assets -----
    "Fixed Assets":             "Asset::Property, Plant & Equipment",
    "Investments":              "Asset::Non-current Investments",
    "Current Assets":           "Asset::Other Current Assets",
    "Stock-in-Hand":            "Asset::Inventories",
    "Sundry Debtors":           "Asset::Trade Receivables",
    "Cash-in-Hand":             "Asset::Cash & Cash Equivalents",
    "Bank Accounts":            "Asset::Cash & Cash Equivalents",
    "Bank OD Accounts":         "Asset::Cash & Cash Equivalents",
    "Deposits (Asset)":         "Asset::Long-term Loans & Advances",
    "Loans & Advances (Asset)": "Asset::Short-term Loans & Advances",
    "Misc. Expenses (ASSET)":   "Asset::Other Current Assets",
    # ----- P&L -----
    "Sales Accounts":           "Income::Revenue from Operations",
    "Direct Incomes":           "Income::Revenue from Operations",
    "Indirect Incomes":         "Income::Other Income",
    "Purchase Accounts":        "Expense::Cost of Materials Consumed",
    "Direct Expenses":          "Expense::Manufacturing & Direct Expenses",
    "Indirect Expenses":        "Expense::Other Expenses",
}


# Ordered Schedule III sections for rendering. Each head belongs to one
# section. The renderer uses this order; the aggregator just emits a
# flat dict keyed by "Section::Head" so we preserve grouping + sequence.
SECTION_ORDER = [
    ("Equity", [
        "Share Capital & Reserves",
    ]),
    ("Liability", [
        "Long-term Borrowings",
        "Short-term Borrowings",
        "Trade Payables",
        "Other Current Liabilities",
        "Short-term Provisions",
    ]),
    ("Asset", [
        "Property, Plant & Equipment",
        "Non-current Investments",
        "Long-term Loans & Advances",
        "Inventories",
        "Trade Receivables",
        "Cash & Cash Equivalents",
        "Short-term Loans & Advances",
        "Other Current Assets",
    ]),
    ("Income", [
        "Revenue from Operations",
        "Other Income",
    ]),
    ("Expense", [
        "Cost of Materials Consumed",
        "Manufacturing & Direct Expenses",
        "Other Expenses",
    ]),
]


def _build_parent_chain(groups: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map every group name → the Primary-group name it eventually belongs to.
    Walks parentGroup recursively; stops when parent == 'Primary' or unknown."""
    by_name = {g["name"]: g.get("parentGroup", "") for g in groups}
    primary: Dict[str, str] = {}
    for name in by_name:
        cur = name
        seen = set()
        while cur and cur not in seen and cur not in ("Primary", ""):
            parent = by_name.get(cur, "")
            if parent in ("Primary", ""):
                break
            seen.add(cur)
            cur = parent
        primary[name] = cur or name
    return primary


def _classify_ledger(ledger: Dict[str, Any], primary: Dict[str, str]) -> Tuple[str, str]:
    """Return (section, head) for a ledger using its parent chain."""
    parent = ledger.get("parentGroup") or ""
    root = primary.get(parent, parent)
    mapped = SCHEDULE_III_MAP.get(root)
    if mapped:
        return tuple(mapped.split("::", 1))
    # Fallback: put it in the correct section by bsOrPnl but under a
    # catch-all head, so it's never silently lost.
    flag = (ledger.get("bsOrPnl") or "").upper()
    if flag == "B":
        # Rough sign-based fallback
        return ("Liability" if float(ledger.get("closingBalance", 0)) > 0 else "Asset",
                "Unmapped")
    return ("Expense", "Unmapped")


def aggregate_schedule_iii(books: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a normalised FS document.

    Input: parsed Tally JSON (with keys `groups`, `ledgers`, `vouchers`, …).
    Output:
      {
        "company": {name, gstin, ...},
        "balance_sheet": [{section, head, current, previous}, ...],
        "profit_loss":   [{section, head, current, previous}, ...],
        "totals": {
          "equity_and_liabilities_current": ..,
          "assets_current":                 ..,
          "revenue_current":                ..,
          "expenses_current":               ..,
          "pat_current":                    ..,    # revenue − expenses
        },
        "ledger_count": N,
        "voucher_count": N,
      }
    """
    groups = books.get("groups", []) or []
    ledgers = books.get("ledgers", []) or []
    primary = _build_parent_chain(groups)

    # Tally closing balance convention: positive = debit, negative = credit.
    # For a proper FS presentation we want liabilities + income reported
    # as positive values and assets + expenses as positive values (sign
    # flipped for liabilities + income).
    by_head: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
        lambda: {"current": 0.0, "previous": 0.0}
    )
    for led in ledgers:
        section, head = _classify_ledger(led, primary)
        cb = float(led.get("closingBalance", 0) or 0)
        ob = float(led.get("openingBalance", 0) or 0)
        # Sign convention: for Liability / Income, credits are positive so
        # flip the raw debit-positive Tally balance.
        if section in ("Liability", "Equity", "Income"):
            cb, ob = -cb, -ob
        by_head[(section, head)]["current"] += cb
        by_head[(section, head)]["previous"] += ob

    balance_sheet: List[Dict[str, Any]] = []
    profit_loss:   List[Dict[str, Any]] = []
    for section, heads in SECTION_ORDER:
        for head in heads:
            cell = by_head.get((section, head), {"current": 0.0, "previous": 0.0})
            row = {
                "section":  section,
                "head":     head,
                "current":  round(cell["current"], 2),
                "previous": round(cell["previous"], 2),
            }
            if section in ("Equity", "Liability", "Asset"):
                balance_sheet.append(row)
            else:
                profit_loss.append(row)

    # Emit any unmapped catch-all heads too, so nothing is hidden
    for (section, head), cell in by_head.items():
        if head == "Unmapped":
            row = {
                "section":  section,
                "head":     "Unmapped (review)",
                "current":  round(cell["current"], 2),
                "previous": round(cell["previous"], 2),
            }
            if section in ("Equity", "Liability", "Asset"):
                balance_sheet.append(row)
            else:
                profit_loss.append(row)

    # Roll-up totals
    eql_cur = sum(r["current"] for r in balance_sheet if r["section"] in ("Equity", "Liability"))
    asset_cur = sum(r["current"] for r in balance_sheet if r["section"] == "Asset")
    rev_cur = sum(r["current"] for r in profit_loss if r["section"] == "Income")
    exp_cur = sum(r["current"] for r in profit_loss if r["section"] == "Expense")

    return {
        "company":        books.get("company", {}),
        "balance_sheet":  balance_sheet,
        "profit_loss":    profit_loss,
        "totals": {
            "equity_and_liabilities_current": round(eql_cur, 2),
            "assets_current":                 round(asset_cur, 2),
            "revenue_current":                round(rev_cur, 2),
            "expenses_current":               round(exp_cur, 2),
            "pat_current":                    round(rev_cur - exp_cur, 2),
        },
        "ledger_count":   len(ledgers),
        "voucher_count":  len(books.get("vouchers", []) or []),
    }


__all__ = ["aggregate_schedule_iii", "SCHEDULE_III_MAP", "SECTION_ORDER"]
