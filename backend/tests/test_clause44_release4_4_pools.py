"""
Release 4.4 — Three-pool model unit tests.

Verifies that `compute_pools` produces:
  • Pool 1 (Exempt Purchases)  : bsOrPl='P' AND head ∉ revenue heads.
  • Pool 2 (ITC focused)       : bsOrPl='B' AND subhead ∈ ITC defaults.
    Pool 2 (ITC all-BS)        : every bsOrPl='B' ledger; default-view
                                  flag on the focused subset.
  • Pool 3 (Exclusions)        : (P-side) OR (B-side capex), excluding
                                  revenue heads.  Capex auto-ticked.

Uses synthetic mappings — no live HTTP, no DB.  Runs fast.
"""
from modules.clause44.service import compute_pools, ITC_SUBHEAD_DEFAULTS


def _mapping(rows):
    """Build a `ledgers_xlsx` dict from a list of (name, bsOrPl, head, subhead, gp, cb)."""
    return {
        name: {
            "bsOrPl": bp, "head": head, "subhead": sub,
            "groupParent": gp, "closingBalance": cb,
        }
        for name, bp, head, sub, gp, cb in rows
    }


def test_revenue_heads_excluded_from_exempt_and_exclusions():
    rows = [
        ("Sales A",          "P", "Revenue from Operations", "Sale of Goods", "Direct Income", -1000),
        ("Other Income X",   "P", "Other Income",            "Discount receipts", "Indirect Income", -200),
        ("Salaries",         "P", "Employee Benefits Expense","Office Salaries", "Indirect Expenses", 500),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    names_exempt = {r["name"] for r in pools["exempt_ledgers"]}
    names_excl   = {r["name"] for r in pools["exclusion_ledgers"]}
    assert names_exempt == {"Salaries"}
    assert names_excl == {"Salaries"}


def test_itc_focused_pool_uses_subhead_taxonomy():
    rows = [
        ("Input CGST",    "B", "Other Current Assets",      "Balance with Revenue Authorities", "Current Assets", 100),
        ("Output CGST",   "B", "Other Current Liabilities", "Statutory Dues Payable",            "Current Liabilities", -150),
        ("Bank ICICI",    "B", "Cash and Cash equivalents", "Cash on Hand",                      "Current Assets", 5000),
        ("Sundry Debtor", "B", "Trade Receivables",         "Sundry Debtors",                    "Current Assets", 8000),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    focused = {r["name"] for r in pools["itc_ledgers"]}
    assert focused == {"Input CGST", "Output CGST"}
    assert len(pools["itc_ledgers_all_bs"]) == 4
    in_def = {r["name"] for r in pools["itc_ledgers_all_bs"] if r["in_default_view"]}
    assert in_def == {"Input CGST", "Output CGST"}


def test_itc_subhead_match_is_case_insensitive():
    rows = [
        ("Input GST",  "B", "Other Current Assets",      "BALANCE WITH REVENUE AUTHORITIES ", "Current Assets", 50),
        ("Output GST", "B", "Other Current Liabilities", " statutory Dues PAYABLE",            "Current Liabilities", -75),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    assert {r["name"] for r in pools["itc_ledgers"]} == {"Input GST", "Output GST"}


def test_exclusion_includes_capex_and_does_not_auto_tick_them():
    """Capex (PPE + Intangibles) appears in the Exclusions pool but is
    NEVER auto-ticked — auditors decide per audit whether to bring capex
    into the recon as an add-back.  P-side keyword matches still
    auto-tick.  Each row carries `recon_role` so the UI can flag
    add-back vs subtract."""
    rows = [
        ("Plant & Machinery", "B", "Property, Plant and Equipment", "Plant and Machinery", "Fixed Assets", 200000),
        ("Goodwill",          "B", "Intangible Fixed Assets",       "Goodwill",            "Fixed Assets", 50000),
        ("Cash",              "B", "Cash and Cash equivalents",     "Cash on Hand",        "Current Assets", 1000),
        ("Salaries",          "P", "Employee Benefits Expense",     "Office Salaries",     "Indirect Expenses", 500),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    excl = {r["name"]: r for r in pools["exclusion_ledgers"]}
    assert set(excl) == {"Plant & Machinery", "Goodwill", "Salaries"}
    # Capex appears but NOT auto-ticked.
    assert excl["Plant & Machinery"]["suggested"] is False
    assert excl["Plant & Machinery"]["recon_role"] == "addback"
    assert excl["Goodwill"]["suggested"] is False
    assert excl["Goodwill"]["recon_role"] == "addback"
    # P-side keyword matches still auto-tick.
    assert excl["Salaries"]["suggested"] is True
    assert excl["Salaries"]["recon_role"] == "subtract"
    # Cash (BS, not capex) is NOT in the exclusion pool.
    assert "Cash" not in excl


def test_exclusion_keyword_pretick_still_works_for_pside():
    rows = [
        ("Depreciation",       "P", "Other Expense",  "Other Administrative Expenses", "Indirect Expenses", 10000),
        ("Office Stationery",  "P", "Other Expense",  "Printing and Stationery",       "Indirect Expenses", 500),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    excl = {r["name"]: r for r in pools["exclusion_ledgers"]}
    assert excl["Depreciation"]["suggested"] is True
    assert excl["Office Stationery"]["suggested"] is False


def test_exempt_pre_tick_uses_name_hint():
    rows = [
        ("Petrol Purchase",       "P", "Other Expense", "Vehicle Maintenance", "Indirect Expenses", 1000),
        ("Office Salaries",       "P", "Employee Benefits Expense", "Office Salaries", "Indirect Expenses", 5000),
        ("Life Insurance Premium","P", "Other Expense", "Other Administrative Expenses", "Indirect Expenses", 200),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    exempt = {r["name"]: r for r in pools["exempt_ledgers"]}
    assert exempt["Petrol Purchase"]["suggested"] is True
    assert exempt["Office Salaries"]["suggested"] is False
    assert exempt["Life Insurance Premium"]["suggested"] is True


def test_pools_use_head_subhead_not_group_parent():
    """A bizarre Group Parent shouldn't kick a ledger out of any pool."""
    rows = [
        # Auditor mis-grouped under "Misc" — should still surface.
        ("Input GST", "B", "Other Current Assets", "Balance with Revenue Authorities", "Misc", 100),
        ("Sundry Cr", "B", "Trade Payables",       "Creditors for Goods",              "Random", -500),
    ]
    pools = compute_pools(_mapping(rows), [], None)
    # ITC focused: Input GST passes via subhead alone (no Group Parent check).
    assert {r["name"] for r in pools["itc_ledgers"]} == {"Input GST"}
    # All-BS: both surface.
    assert len(pools["itc_ledgers_all_bs"]) == 2


def test_itc_subhead_defaults_constant():
    """Tighten contract: hard-coded subheads stay the two we agreed on."""
    assert ITC_SUBHEAD_DEFAULTS == (
        "balance with revenue authorities",
        "statutory dues payable",
    )


def test_json_only_ledgers_surface_in_universe():
    """Tally-exported ledgers without an XLSX mapping still appear when their
    bsOrPl can be inferred from the JSON's bsOrPnl field (legacy path)."""
    xlsx = _mapping([])
    json_ledgers = [
        {"name": "Unmapped Salary", "bsOrPnl": "P", "closingBalance": 1000, "parentGroup": "Indirect Expenses"},
    ]
    pools = compute_pools(xlsx, json_ledgers, None)
    # P-side, no head/subhead → exempt pool admits it (head check is "not in
    # revenue heads"; empty head obviously isn't).
    assert any(r["name"] == "Unmapped Salary" for r in pools["exempt_ledgers"])
