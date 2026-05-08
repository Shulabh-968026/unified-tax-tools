"""Release 4.4.8 — Exempt × ITC voucher cross-check tests.

A voucher carrying an entry under an auditor-confirmed ITC ledger is
a *taxable* purchase by definition.  Any expense ledger on that
voucher therefore can't be an exempt supply.  This test file verifies
the helper demotes the pre-tick + reports overlap counters correctly,
without losing genuine exempt picks (petrol/diesel/etc.) where no ITC
was claimed.
"""
from modules.clause44.service import filter_exempt_by_itc_overlap


def _exempt_pool_row(name, suggested=True):
    return {
        "name": name,
        "subhead": "Misc Exp",
        "group_parent": "Indirect Expenses",
        "head": "Other Expenses",
        "closing_balance": -100000.0,
        "suggested": suggested,
    }


def _voucher(vtype, ledger_names):
    return {
        "voucherTypeName": vtype,
        "ledgerEntries": [{"ledger": ln} for ln in ledger_names],
    }


# ─────────────────────────────────────────────────────────────────────────
# Core demotion behaviour
# ─────────────────────────────────────────────────────────────────────────
def test_demotes_insurance_premium_when_voucher_has_input_cgst():
    pool = [_exempt_pool_row("Group Health Insurance Premium", suggested=True)]
    vouchers = [
        _voucher("Purchase", ["Group Health Insurance Premium",
                              "Input CGST", "Input SGST"]),
    ]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST", "Input SGST"], vouchers)
    r = out[0]
    assert r["itc_overlap_vouchers"] == 1
    assert r["total_vouchers"] == 1
    assert r["itc_overlap_demoted"] is True
    assert r["suggested"] is False


def test_keeps_petrol_diesel_when_no_itc_on_vouchers():
    """Genuine exempt purchase (petrol/diesel — no ITC under GST law)."""
    pool = [_exempt_pool_row("Petrol Expenses", suggested=True)]
    vouchers = [
        _voucher("Purchase", ["Petrol Expenses", "Cash"]),
        _voucher("Purchase", ["Petrol Expenses", "Bank"]),
    ]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST"], vouchers)
    r = out[0]
    assert r["itc_overlap_vouchers"] == 0
    assert r["total_vouchers"] == 2
    assert r["itc_overlap_demoted"] is False
    assert r["suggested"] is True       # un-touched


def test_zero_tolerance_demotes_on_single_overlap_among_many():
    """Mixed-use ledger — 1 of 100 vouchers has ITC.  Default rule is
    zero-tolerance: a single overlap demotes the suggestion.  The chip
    `1/100` is preserved so the auditor can re-tick if mixed-use is
    intentional."""
    pool = [_exempt_pool_row("Insurance Premium", suggested=True)]
    vouchers = [_voucher("Purchase", ["Insurance Premium", "Cash"])] * 99 + [
        _voucher("Purchase", ["Insurance Premium", "Input CGST"]),
    ]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST"], vouchers)
    r = out[0]
    assert r["total_vouchers"] == 100
    assert r["itc_overlap_vouchers"] == 1
    assert r["itc_overlap_demoted"] is True
    assert r["suggested"] is False


# ─────────────────────────────────────────────────────────────────────────
# No-op / fallback paths
# ─────────────────────────────────────────────────────────────────────────
def test_empty_itc_selection_passes_through():
    pool = [_exempt_pool_row("Insurance Premium", suggested=True)]
    vouchers = [
        _voucher("Purchase", ["Insurance Premium", "Input CGST"]),
    ]
    # ITC not selected → no cross-check.
    out = filter_exempt_by_itc_overlap(pool, [], vouchers)
    r = out[0]
    assert r["itc_overlap_vouchers"] == 0
    assert r["total_vouchers"] == 0
    assert r["itc_overlap_demoted"] is False
    assert r["suggested"] is True


def test_no_vouchers_passes_through():
    pool = [_exempt_pool_row("Insurance Premium", suggested=True)]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST"], [])
    r = out[0]
    assert r["itc_overlap_vouchers"] == 0
    assert r["itc_overlap_demoted"] is False
    assert r["suggested"] is True


def test_empty_pool_returns_empty_list():
    assert filter_exempt_by_itc_overlap([], ["Input CGST"], []) == []


# ─────────────────────────────────────────────────────────────────────────
# Counter accuracy across many vouchers
# ─────────────────────────────────────────────────────────────────────────
def test_counters_count_distinct_vouchers_not_entries():
    """A single voucher with 5 entries (1 exempt + 1 ITC + 3 others)
    counts as ONE total voucher and ONE overlap."""
    pool = [_exempt_pool_row("Insurance Premium")]
    vouchers = [
        _voucher("Purchase", ["Insurance Premium", "Input CGST",
                              "Input SGST", "Cash", "Bank"]),
    ]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST"], vouchers)
    r = out[0]
    assert r["total_vouchers"] == 1
    assert r["itc_overlap_vouchers"] == 1


def test_only_demotes_already_suggested_rows():
    """A row with `suggested=False` stays False — demotion logic is a
    one-way `True → False` flip.  Counters still populate so the chip
    is informative even on un-suggested rows."""
    pool = [_exempt_pool_row("Some Office Expense", suggested=False)]
    vouchers = [_voucher("Purchase", ["Some Office Expense", "Input CGST"])]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST"], vouchers)
    r = out[0]
    assert r["suggested"] is False           # stayed False
    assert r["itc_overlap_demoted"] is False  # nothing was demoted
    assert r["itc_overlap_vouchers"] == 1
    assert r["total_vouchers"] == 1


# ─────────────────────────────────────────────────────────────────────────
# End-to-end mixed pool sanity
# ─────────────────────────────────────────────────────────────────────────
def test_mixed_pool_partial_demotion():
    pool = [
        _exempt_pool_row("Petrol Expenses", suggested=True),
        _exempt_pool_row("Group Health Insurance", suggested=True),
        _exempt_pool_row("Liquor Stock", suggested=True),
        _exempt_pool_row("Office Tea", suggested=False),
    ]
    vouchers = [
        # Petrol — exempt, no ITC ever.
        _voucher("Purchase", ["Petrol Expenses", "Cash"]),
        _voucher("Purchase", ["Petrol Expenses", "Bank"]),
        # Group Health — taxable post-2022, voucher carries Input GST.
        _voucher("Purchase", ["Group Health Insurance", "Input CGST", "Input SGST"]),
        # Liquor — exempt under GST, no ITC.
        _voucher("Purchase", ["Liquor Stock", "Cash"]),
        # Office Tea — incidental ITC voucher, but row wasn't suggested.
        _voucher("Purchase", ["Office Tea", "Input CGST"]),
    ]
    out = filter_exempt_by_itc_overlap(pool, ["Input CGST", "Input SGST"], vouchers)
    by_name = {r["name"]: r for r in out}

    # Petrol — un-touched.
    assert by_name["Petrol Expenses"]["suggested"] is True
    assert by_name["Petrol Expenses"]["itc_overlap_demoted"] is False
    assert by_name["Petrol Expenses"]["itc_overlap_vouchers"] == 0

    # Group Health — demoted.
    assert by_name["Group Health Insurance"]["suggested"] is False
    assert by_name["Group Health Insurance"]["itc_overlap_demoted"] is True
    assert by_name["Group Health Insurance"]["itc_overlap_vouchers"] == 1

    # Liquor — un-touched.
    assert by_name["Liquor Stock"]["suggested"] is True
    assert by_name["Liquor Stock"]["itc_overlap_demoted"] is False

    # Office Tea — already not-suggested; demotion didn't happen even
    # though counters show overlap.
    assert by_name["Office Tea"]["suggested"] is False
    assert by_name["Office Tea"]["itc_overlap_demoted"] is False
    assert by_name["Office Tea"]["itc_overlap_vouchers"] == 1
