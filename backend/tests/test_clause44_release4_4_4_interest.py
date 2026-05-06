"""
Release 4.4.4 — Interest / Discount on Loans & Advances classification.

Per Schedule III of the CGST Act + GST Exemption Notification 12/2017-CT
entry 27 + ICAI Guidance Note Para 79.13: services by way of extending
deposits / loans / advances, where the consideration is interest or
discount, are *exempt supplies* — they belong in **Col 3 (Input A,
Exempt Purchases)**, NOT in **Col 8 (Exclusions)**.

Penal interest on tax dues (Income Tax / TDS / GST late-payment etc.)
remains a Schedule III no-supply and continues to auto-tick as
Exclusion + bucket under "Transactions in money / securities".
"""
from modules.clause44.service import (
    _is_exclusion_hint, _is_exempt_hint, _is_interest_or_discount_on_loans,
    compute_pools,
)


def test_financing_interest_pretickes_exempt_not_exclusion():
    cases = [
        "Interest on Term Loan",
        "Bank Interest Paid",
        "Interest on Working Capital Loan",
        "Interest on Deposits Received",
        "Interest on Cash Credit",
        "Interest on Loan from Director",
    ]
    for name in cases:
        assert _is_exempt_hint(name) is True,  f"{name} must be exempt-suggested"
        assert _is_exclusion_hint(name) is False, f"{name} must NOT be exclusion-suggested"


def test_penal_interest_remains_exclusion():
    """Penal / statutory interest is Sch III — stays in Col 8."""
    cases = [
        "Interest on Income Tax",
        "Interest on TDS",
        "Interest on Advance Tax",
        "Interest on GST",
        "Interest on GST Late Payment",
        "Interest u/s 234B",
        "Penal Interest on Loan",
        "Late Fee on Returns",
        "Penalty on Late Filing",
    ]
    for name in cases:
        assert _is_exclusion_hint(name) is True,  f"{name} must stay exclusion-suggested"
        assert _is_exempt_hint(name) is False,    f"{name} must NOT auto-tick as exempt"


def test_loan_discount_auto_ticks_exempt():
    cases = [
        "Bill Discounting Charges",
        "Discount on Bills",
        "LC Discounting Charges",
        "Discount on Loan",
    ]
    for name in cases:
        assert _is_exempt_hint(name) is True
        assert _is_exclusion_hint(name) is False


def test_capital_keyword_no_longer_overgreedy():
    """`capital` as a bare keyword used to flag every "Working Capital"
    / "Capital Goods" line — narrowed to proprietor-style accounts."""
    assert _is_exclusion_hint("Capital A/c") is True
    assert _is_exclusion_hint("Capital Account") is True
    assert _is_exclusion_hint("Working Capital Loan") is False
    assert _is_exclusion_hint("Capital Goods Repairs") is False


def test_helper_excludes_penal_interest_explicitly():
    assert _is_interest_or_discount_on_loans("Interest on Income Tax") is False
    assert _is_interest_or_discount_on_loans("Interest u/s 234A") is False
    assert _is_interest_or_discount_on_loans("Interest on Term Loan") is True


def test_compute_pools_seeds_interest_in_exempt_not_exclusion():
    """Synthetic mapping — verify the auto-tick bias on each pool."""
    rows = [
        # name,  bsOrPl, head,                            subhead,                      gp,                cb
        ("Interest on Term Loan",      "P", "Finance Costs",         "Interest on Term Loan",      "Indirect Expenses", 1_000_000),
        ("Interest on Income Tax",     "P", "Finance Costs",         "Interest on Statutory Dues", "Indirect Expenses",   25_000),
        ("Salaries",                   "P", "Employee Benefits Expense", "Office Salaries",        "Indirect Expenses",  500_000),
        ("Cash on Hand",               "B", "Cash and Cash equivalents", "Cash on Hand",           "Current Assets",      10_000),
        ("Sales A",                    "P", "Revenue from Operations",   "Sale of Goods",          "Direct Income",   -1_000_000),
    ]
    xlsx = {n: {"bsOrPl": bp, "head": h, "subhead": s, "groupParent": gp, "closingBalance": cb}
            for n, bp, h, s, gp, cb in rows}
    pools = compute_pools(xlsx, [], None)

    exempt = {r["name"]: r for r in pools["exempt_ledgers"]}
    excl   = {r["name"]: r for r in pools["exclusion_ledgers"]}

    # Both interest ledgers are P-side and not under revenue heads → both
    # appear in exempt + exclusion pools (auditor sees them in both
    # tabs).  But auto-tick differs:
    assert "Interest on Term Loan" in exempt
    assert exempt["Interest on Term Loan"]["suggested"] is True
    assert "Interest on Term Loan" in excl
    assert excl["Interest on Term Loan"]["suggested"] is False

    assert "Interest on Income Tax" in exempt
    assert exempt["Interest on Income Tax"]["suggested"] is False
    assert "Interest on Income Tax" in excl
    assert excl["Interest on Income Tax"]["suggested"] is True

    # Salaries — exclusion only.
    assert excl["Salaries"]["suggested"] is True
    assert exempt["Salaries"]["suggested"] is False
