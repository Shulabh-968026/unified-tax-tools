"""Release 4.4.9 — Capex auto-flow tests.

Verifies:
  Fix 5A — BS-side capex (PPE / Intangibles / CWIP) no longer surface
           in the Exclusions pool.
  Fix 5B — Recon's `capex_total` is computed from the books-XLSX `head`
           value (not the parent-group chain), so the Para 79.18 row
           populates even when the Tally chain doesn't contain the
           literal word "fixed asset".
  Fix 5C — `_FA_HEADS` accepts common Schedule III spellings + CWIP.
"""
from modules.clause44.service import (
    compute_pools, compute_recon_and_filter, _FA_HEADS,
)


def _xlsx_row(bs_or_pl, head, subhead="", group_parent="", closing_balance=1000.0):
    return {
        "bsOrPl": bs_or_pl,
        "head": head,
        "subhead": subhead,
        "groupParent": group_parent,
        "closingBalance": closing_balance,
    }


# ─────────────────────────────────────────────────────────────────────────
# Fix 5C — FA_HEADS coverage
# ─────────────────────────────────────────────────────────────────────────
def test_fa_heads_covers_canonical_spellings():
    expected = {
        "property, plant and equipment",
        "intangible assets",
        "intangible fixed assets",
        "capital work-in-progress",
    }
    assert expected.issubset(_FA_HEADS)


# ─────────────────────────────────────────────────────────────────────────
# Fix 5A — Exclusions pool no longer surfaces BS-side capex
# ─────────────────────────────────────────────────────────────────────────
def test_pool3_excludes_bs_side_ppe_ledger():
    """A BS-side PPE ledger (no chain match) must NOT appear in Pool 3."""
    ledgers_xlsx = {
        "Plant & Machinery @ 18%": _xlsx_row(
            "B", "Property, Plant and Equipment", "Plant and Machinery",
            "Plant & Machineries",
        ),
        # Sanity — a P-side depreciation ledger MUST still appear.
        "Depreciation": _xlsx_row(
            "P", "Other Expenses", "Depreciation", "Indirect Expenses",
            closing_balance=-50000,
        ),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    names = {r["name"] for r in pools["exclusion_ledgers"]}
    assert "Plant & Machinery @ 18%" not in names
    assert "Depreciation" in names


def test_pool3_excludes_bs_side_intangible_ledger():
    ledgers_xlsx = {
        "Software License - 18%": _xlsx_row(
            "B", "Intangible Assets", "Software", "Software & Licences",
        ),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    assert pools["exclusion_ledgers"] == []


def test_pool3_excludes_bs_side_cwip_ledger():
    ledgers_xlsx = {
        "Plant & Machinery @ 18% - WIP": _xlsx_row(
            "B", "Capital Work-in-progress", "Capital work-in-Progress",
            "Plant & Machinery - Under work",
        ),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    assert pools["exclusion_ledgers"] == []


def test_pool3_keeps_pside_sch3_exclusions():
    """Sanity — non-capex P-side rows still come through as exclusion
    candidates and pre-tick fires on the keyword match."""
    ledgers_xlsx = {
        "Salary": _xlsx_row("P", "Employee Benefits Expense", "Salary",
                            "Salary & Wages", closing_balance=-500000),
        "PF Contribution": _xlsx_row("P", "Employee Benefits Expense",
                                     "PF", "PF & ESI", closing_balance=-50000),
        "Interest on Income Tax": _xlsx_row(
            "P", "Finance Costs", "Interest", "Interest Paid",
            closing_balance=-1000),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    names = {r["name"] for r in pools["exclusion_ledgers"]}
    assert names == {"Salary", "PF Contribution", "Interest on Income Tax"}
    suggested = {r["name"] for r in pools["exclusion_ledgers"] if r["suggested"]}
    # All three match an exclusion-hint keyword.
    assert suggested == {"Salary", "PF Contribution", "Interest on Income Tax"}


def test_pool3_recon_role_is_subtract_for_all():
    """After Release 4.4.9 every Pool 3 row is `subtract` (no addback)."""
    ledgers_xlsx = {
        "Salary": _xlsx_row("P", "Employee Benefits Expense", "Salary",
                            "Salary & Wages", closing_balance=-500000),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    assert all(r["recon_role"] == "subtract" for r in pools["exclusion_ledgers"])


# ─────────────────────────────────────────────────────────────────────────
# Fix 5B — Head-based capex split in recon
# ─────────────────────────────────────────────────────────────────────────
def _make_recon_inputs(by_ledger, ledgers_xlsx, group_chains=None,
                       summary_overrides=None):
    full_result = {
        "by_ledger": by_ledger,
        "summary": {"col2_total": sum(v["total"] for v in by_ledger.values()),
                    "col3": 0, "col4": 0, "col5": 0, "col6": 0,
                    "col7": 0, "col8": 0, "reportable_total": 0,
                    **(summary_overrides or {})},
        "by_party": {},
        "transactions": [],
    }
    return full_result, ledgers_xlsx, (group_chains or {})


def test_recon_capex_total_from_head_when_chain_does_not_match():
    """The whole point of Fix 5B — Tally chain `Plant & Machineries`
    does NOT contain the word "fixed asset", but the books-XLSX head
    is `Property, Plant and Equipment`.  Capex must be captured."""
    by_ledger = {
        "Plant & Machinery @ 18%": {"total": 4_00_00_000},
        "Office Rent": {"total": 12_00_000},
    }
    ledgers_xlsx = {
        "Plant & Machinery @ 18%": _xlsx_row(
            "B", "Property, Plant and Equipment", "Plant and Machinery",
            "Plant & Machineries",
        ),
        "Office Rent": _xlsx_row("P", "Other Expenses", "Rent",
                                 "Indirect Expenses"),
    }
    group_chains = {"plant & machineries": "plant & machineries"}
    full, lx, gc = _make_recon_inputs(by_ledger, ledgers_xlsx, group_chains)
    out = compute_recon_and_filter(full, set(), ledgers_xlsx=lx, group_chains=gc)
    assert out["recon"]["capex_total"] == 4_00_00_000
    assert out["recon"]["pl_total"]    == 12_00_000


def test_recon_capex_total_for_intangible_assets_head():
    by_ledger = {
        "Software Licence Purchase": {"total": 25_00_000},
    }
    ledgers_xlsx = {
        "Software Licence Purchase": _xlsx_row(
            "B", "Intangible Assets", "Software", "Software & Licences",
        ),
    }
    full, lx, gc = _make_recon_inputs(by_ledger, ledgers_xlsx, {})
    out = compute_recon_and_filter(full, set(), ledgers_xlsx=lx, group_chains=gc)
    assert out["recon"]["capex_total"] == 25_00_000
    assert out["recon"]["pl_total"]    == 0


def test_recon_capex_total_includes_cwip():
    by_ledger = {
        "P&M @ 18% - WIP":  {"total": 70_00_000},
        "Plant Already Capitalised": {"total": 1_50_00_000},
    }
    ledgers_xlsx = {
        "P&M @ 18% - WIP": _xlsx_row(
            "B", "Capital Work-in-progress", "Capital work-in-Progress",
            "P&M - Under work",
        ),
        "Plant Already Capitalised": _xlsx_row(
            "B", "Property, Plant and Equipment", "Plant and Machinery",
            "Plant & Machineries",
        ),
    }
    full, lx, gc = _make_recon_inputs(by_ledger, ledgers_xlsx, {})
    out = compute_recon_and_filter(full, set(), ledgers_xlsx=lx, group_chains=gc)
    assert out["recon"]["capex_total"] == 70_00_000 + 1_50_00_000


def test_recon_capex_split_falls_back_to_chain_when_head_is_empty():
    """Legacy runs uploaded before head-mapping was mandatory still
    work via the parent-group chain fallback."""
    by_ledger = {
        "Old Fixed Asset Ledger": {"total": 5_00_000},
    }
    ledgers_xlsx = {
        "Old Fixed Asset Ledger": _xlsx_row(
            "B", "", "", "Plant & Machinery",   # empty head
        ),
    }
    # Chain places this ledger under "Fixed Assets".
    group_chains = {"plant & machinery": "fixed assets > plant & machinery"}
    full, lx, gc = _make_recon_inputs(by_ledger, ledgers_xlsx, group_chains)
    out = compute_recon_and_filter(full, set(), ledgers_xlsx=lx, group_chains=gc)
    assert out["recon"]["capex_total"] == 5_00_000


def test_recon_capex_split_pside_ledger_goes_to_pl_total():
    """A P-side ledger never goes into capex_total even if mis-mapped."""
    by_ledger = {
        "Repairs - Plant": {"total": 8_00_000},
    }
    ledgers_xlsx = {
        # P-side, head is "Other Expenses" (not in _FA_HEADS).
        "Repairs - Plant": _xlsx_row(
            "P", "Other Expenses", "Repairs", "Repairs & Maintenance",
            closing_balance=-8_00_000,
        ),
    }
    full, lx, gc = _make_recon_inputs(by_ledger, ledgers_xlsx, {})
    out = compute_recon_and_filter(full, set(), ledgers_xlsx=lx, group_chains=gc)
    assert out["recon"]["capex_total"] == 0
    assert out["recon"]["pl_total"]    == 8_00_000
