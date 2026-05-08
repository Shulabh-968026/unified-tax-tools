"""Release 4.4.6 — Voucher-usage NEGATIVE list tests.

Verifies that BS-side ledgers matching the auditor-curated negative list
(TDS / TCS / Advance-Tax / Bank-charge GST / penal-interest patterns)
are NOT upgraded to ``kind == "input"`` via voucher-usage inference and
therefore are NOT pre-ticked, even when they appear on multiple
purchase vouchers.
"""
from modules.clause44.service import (
    _is_blocked_from_usage_upgrade,
    compute_pools,
)


# ─────────────────────────────────────────────────────────────────────────
# Unit-level: the helper itself
# ─────────────────────────────────────────────────────────────────────────
def test_block_helper_catches_tds_name():
    assert _is_blocked_from_usage_upgrade("Tds Payable - Contracts 2%", "Duties & Taxes Payable") is True
    assert _is_blocked_from_usage_upgrade("TDS Payable - Purchase of Goods 194Q", "Duties & Taxes Payable") is True
    assert _is_blocked_from_usage_upgrade("TDS Form 16 A - 26 AS", "Advance Taxes") is True


def test_block_helper_catches_tcs_name():
    assert _is_blocked_from_usage_upgrade("TCS Receivable", "Advance Taxes") is True


def test_block_helper_catches_bank_gst():
    assert _is_blocked_from_usage_upgrade("Bank GST", "Bank Accounts") is True
    assert _is_blocked_from_usage_upgrade("Bank Charges GST", "Bank Accounts") is True


def test_block_helper_catches_advance_tax_group():
    # Even with a benign-looking name, group=Advance Taxes blocks the upgrade.
    assert _is_blocked_from_usage_upgrade("Refund Receivable 23-24", "Advance Taxes") is True


def test_block_helper_catches_penal_interest():
    assert _is_blocked_from_usage_upgrade("Interest on Income Tax", "Duties & Taxes Payable") is True
    assert _is_blocked_from_usage_upgrade("Late Fee GSTR-3B", "Duties & Taxes Payable") is True


def test_block_helper_does_not_catch_genuine_input_ledger():
    # Name-side input markers are unaffected — the block only stops the
    # voucher-usage upgrade for `other`-classified names.  This helper
    # alone returns True for any name that contains TDS/TCS, but the
    # caller in compute_pools first checks ``name_kind == "other"`` so a
    # ledger called "Input TDS Recoverable" still goes through.
    # Here we just verify the bare ITC names are NOT blocked.
    assert _is_blocked_from_usage_upgrade("Input CGST", "GST Input Credit") is False
    assert _is_blocked_from_usage_upgrade("CGST Deferred Input Credit", "GST Deffered Input Credit") is False
    assert _is_blocked_from_usage_upgrade("INPUT SGST", "GST Input Credit") is False


# ─────────────────────────────────────────────────────────────────────────
# Integration-level: compute_pools end-to-end with vouchers
# ─────────────────────────────────────────────────────────────────────────
def _make_purchase_vouchers(ledger_names, n=5):
    """Generate `n` purchase vouchers each touching all the given ledgers
    (so the voucher walker would otherwise upgrade them to 'input')."""
    return [
        {
            "voucherTypeName": "Purchase",
            "ledgerEntries": [{"ledger": ln} for ln in ledger_names] + [
                {"ledger": "Some Vendor"},
            ],
        }
        for _ in range(n)
    ]


def _bs_ledger_xlsx(name, subhead, group_parent, head="Other Current Assets"):
    return {
        "bsOrPl": "B",
        "subhead": subhead,
        "groupParent": group_parent,
        "head": head,
        "closingBalance": 1000.0,
    }


def test_compute_pools_blocks_tds_payable_from_pretick():
    name = "Tds Payable - Contracts 2%"
    ledgers_xlsx = {
        name: _bs_ledger_xlsx(name, "Statutory Dues Payable",
                              "Duties & Taxes Payable",
                              head="Other Current Liabilities"),
    }
    vouchers = _make_purchase_vouchers([name], n=10)

    pools = compute_pools(ledgers_xlsx, [], vouchers)
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}

    assert name in rows, "TDS Payable should still appear in the universe"
    r = rows[name]
    # Despite 10 purchase vouchers, kind stays 'other' — usage upgrade blocked.
    assert r["kind"] == "other", f"kind upgraded despite block: {r}"
    assert r["kind_source"] != "usage"
    # Pre-tick must NOT fire.
    assert r["suggested"] is False


def test_compute_pools_blocks_tcs_receivable_from_pretick():
    name = "TCS Receivable"
    ledgers_xlsx = {
        name: _bs_ledger_xlsx(name, "Balance with Revenue Authorities", "Advance Taxes"),
    }
    vouchers = _make_purchase_vouchers([name], n=8)

    pools = compute_pools(ledgers_xlsx, [], vouchers)
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}
    r = rows[name]
    assert r["kind"] == "other"
    assert r["suggested"] is False


def test_compute_pools_blocks_bank_gst_from_pretick():
    name = "Bank GST"
    ledgers_xlsx = {
        name: _bs_ledger_xlsx(name, "Balance with Revenue Authorities", "Bank Accounts"),
    }
    vouchers = _make_purchase_vouchers([name], n=6)

    pools = compute_pools(ledgers_xlsx, [], vouchers)
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}
    r = rows[name]
    assert r["kind"] == "other"
    assert r["suggested"] is False


def test_compute_pools_keeps_genuine_input_ledger_pretick():
    """Sanity — Fix 1 must not regress real ITC ledgers."""
    name = "Input CGST"
    ledgers_xlsx = {
        name: _bs_ledger_xlsx(name, "Balance with Revenue Authorities", "GST Input Credit"),
    }
    pools = compute_pools(ledgers_xlsx, [], [])  # no vouchers needed
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}
    r = rows[name]
    # Name-side input signal — pre-tick fires.
    assert r["kind"] == "input"
    assert r["kind_source"] == "name"
    assert r["suggested"] is True


def test_compute_pools_block_does_not_affect_explicit_input_named_ledger():
    """A ledger explicitly named 'Input ...' is name-classified as input
    and bypasses the usage block entirely (the block only stops the
    `other -> input` upgrade)."""
    name = "Input TDS Recoverable"   # contrived but possible
    ledgers_xlsx = {
        name: _bs_ledger_xlsx(name, "Balance with Revenue Authorities", "Duties & Taxes Payable"),
    }
    pools = compute_pools(ledgers_xlsx, [], [])
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}
    r = rows[name]
    assert r["kind"] == "input"
    assert r["kind_source"] == "name"
    assert r["suggested"] is True


def test_compute_pools_blocks_full_user_reported_negative_list():
    """End-to-end check using the exact 9 ledgers the user marked Wrong
    in the Mapping Snapshot review."""
    cases = [
        ("TCS Receivable", "Balance with Revenue Authorities", "Advance Taxes"),
        ("TDS Form 16 A - 26 AS", "Balance with Revenue Authorities", "Advance Taxes"),
        ("Tds Payable - Commission & Brokerage", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("Tds Payable - Contracts 1%", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("Tds Payable - Contracts 2%", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("Tds Payable - Professional", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("TDS Payable - Purchase of Goods 194Q", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("TDS Payable -Comm & Brokerage 2%", "Statutory Dues Payable", "Duties & Taxes Payable"),
        ("Bank GST", "Balance with Revenue Authorities", "Bank Accounts"),
    ]
    ledgers_xlsx = {
        n: _bs_ledger_xlsx(
            n, sh, gp,
            head="Other Current Assets" if "Authorities" in sh else "Other Current Liabilities",
        )
        for n, sh, gp in cases
    }
    vouchers = _make_purchase_vouchers([n for n, _, _ in cases], n=10)

    pools = compute_pools(ledgers_xlsx, [], vouchers)
    rows = {r["name"]: r for r in pools["itc_ledgers_all_bs"]}
    wrongly_pretticked = [n for n, _, _ in cases if rows[n]["suggested"]]
    assert wrongly_pretticked == [], (
        f"These ledgers are still wrongly pre-ticked: {wrongly_pretticked}"
    )
