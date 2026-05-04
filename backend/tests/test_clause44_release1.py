"""Release-1 tests — ICAI-aligned cascade + 5-line reconciliation.

Covers:
 - Cascade ordering: RCM → Input A (exempt) → Import → Composition →
   Registered (with/without ITC inference) → URD.
 - De-duplication: a ledger tagged in Input A never double-counts via
   Input B (both feed Col 3 but line-by-line precedence rules).
 - Toggle: use_itc_inference=False zeroes out the Input B cohort.
 - ICAI 5-line recon: auto-categorisation + arrival ties to Col 2.
 - Auditor override via `exclusion_categories` moves a line between
   buckets without changing the arrival.
"""
from modules.clause44.service import (
    classify_vouchers, compute_recon_and_filter, categorise_exclusion,
)


def _party(name, reg, gstin="", country="India"):
    return {"name": name, "gstRegistrationType": reg, "partyGSTIN": gstin, "country": country}


def _voucher(vid, party, entries, vtype="Purchase", date="2023-04-01", vnum="1"):
    return {
        "voucherId": vid, "voucherTypeName": vtype, "date": date, "voucherNumber": vnum,
        "partyLedgerName": party["name"] if party else "",
        "ledgerEntries": entries,
    }


def _line(ledger, amount):
    # Convention: expense debit ≡ negative amount in Tally JSON.
    return {"ledger": ledger, "amount": -abs(amount), "isPartyLedger": "No"}


def _partyline(party, amount):
    return {"ledger": party["name"], "amount": abs(amount), "isPartyLedger": "Yes"}


def _party_lookup(*parties):
    return {p["name"]: p for p in parties}


class TestCascade:
    def _expenditure(self, *ledgers):
        return {l: {"reason": "test"} for l in ledgers}

    def test_registered_vendor_with_itc_ledger_lands_in_col5(self):
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        v = _voucher("v1", acme, [_line("Purchase", 1000), _line("Input IGST", 180), _partyline(acme, 1180)])
        res = classify_vouchers(
            [v], self._expenditure("Purchase"), {"Input IGST"}, _party_lookup(acme),
            use_itc_inference=True,
        )
        assert res["summary"]["col5"] == 1000
        assert res["summary"]["col3"] == 0

    def test_registered_vendor_without_itc_with_inference_goes_to_col3_input_b(self):
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        v = _voucher("v1", acme, [_line("Purchase", 1000), _partyline(acme, 1000)])
        res = classify_vouchers(
            [v], self._expenditure("Purchase"), set(), _party_lookup(acme),
            use_itc_inference=True,
        )
        assert res["summary"]["col3"] == 1000
        assert res["summary"]["col3_from_input_b"] == 1000
        assert res["summary"]["col3_from_input_a"] == 0
        assert res["summary"]["col5"] == 0

    def test_toggle_off_moves_registered_no_itc_to_col5(self):
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        v = _voucher("v1", acme, [_line("Purchase", 1000), _partyline(acme, 1000)])
        res = classify_vouchers(
            [v], self._expenditure("Purchase"), set(), _party_lookup(acme),
            use_itc_inference=False,
        )
        assert res["summary"]["col3"] == 0
        assert res["summary"]["col5"] == 1000

    def test_composition_always_col4(self):
        comp = _party("Comp Dealer", "Composition", "27AAAAC0000A1Z5")
        v = _voucher("v1", comp, [_line("Purchase", 500), _partyline(comp, 500)])
        res = classify_vouchers(
            [v], self._expenditure("Purchase"), set(), _party_lookup(comp),
            use_itc_inference=True,
        )
        assert res["summary"]["col4"] == 500

    def test_urd_goes_to_col7(self):
        urd = _party("Chai Stall", "Unregistered", "")
        v = _voucher("v1", urd, [_line("Refreshment", 100), _partyline(urd, 100)])
        res = classify_vouchers(
            [v], self._expenditure("Refreshment"), set(), _party_lookup(urd),
            use_itc_inference=True,
        )
        assert res["summary"]["col7"] == 100

    def test_rcm_voucher_type_auto_col7(self):
        # RCM vouchers bucketed to Col 7 per choice 4B — regardless of vendor status.
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        v = _voucher("v1", acme, [_line("Legal Fees", 2000), _partyline(acme, 2000)], vtype="Reverse Charge")
        res = classify_vouchers(
            [v], self._expenditure("Legal Fees"), {"Input IGST"}, _party_lookup(acme),
            use_itc_inference=True,
        )
        assert res["summary"]["col7"] == 2000
        assert res["summary"]["col5"] == 0
        assert res["summary"]["rcm_total"] == 2000
        assert res["summary"]["rcm_vouchers"] == 1
        assert res["transactions"][0]["is_rcm"] is True

    def test_foreign_supplier_goes_to_col7_with_import_flag(self):
        forex = _party("AWS Inc", "Regular", "", country="USA")
        v = _voucher("v1", forex, [_line("Cloud Hosting", 5000), _partyline(forex, 5000)])
        res = classify_vouchers(
            [v], self._expenditure("Cloud Hosting"), set(), _party_lookup(forex),
            use_itc_inference=True,
        )
        assert res["summary"]["col7"] == 5000
        assert res["summary"]["import_total"] == 5000
        assert res["transactions"][0]["is_import"] is True


class TestInputADeDupe:
    """Input A must win per-line over Input B — the same ledger tagged exempt
    cannot also contribute to the ITC-inference bucket."""

    def test_tagged_ledger_line_goes_col3_input_a_even_when_itc_inference_on(self):
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        # Two expense lines on one voucher: Petroleum (tagged exempt) + Services.
        v = _voucher("v1", acme, [
            _line("Petroleum Purchase", 600),
            _line("Services Fees", 400),
            _partyline(acme, 1000),
        ])
        expenditure = {"Petroleum Purchase": {}, "Services Fees": {}}
        res = classify_vouchers(
            [v], expenditure, set(), _party_lookup(acme),
            exempt_ledgers={"Petroleum Purchase"},
            use_itc_inference=True,
        )
        # Petroleum → Col 3 via Input A. Services → Col 3 via Input B.
        assert res["summary"]["col3"] == 1000
        assert res["summary"]["col3_from_input_a"] == 600
        assert res["summary"]["col3_from_input_b"] == 400
        # No line ended up double-counted.
        assert sum(t["amount"] for t in res["transactions"]) == 1000

    def test_tagged_ledger_remains_col3_when_inference_off(self):
        acme = _party("Acme Ltd", "Regular", "07AAAAA0000A1Z5")
        v = _voucher("v1", acme, [
            _line("Petroleum Purchase", 600),
            _line("Services Fees", 400),
            _partyline(acme, 1000),
        ])
        expenditure = {"Petroleum Purchase": {}, "Services Fees": {}}
        res = classify_vouchers(
            [v], expenditure, set(), _party_lookup(acme),
            exempt_ledgers={"Petroleum Purchase"},
            use_itc_inference=False,
        )
        # Petroleum → Col 3 (A). Services (registered, no ITC, toggle off) → Col 5.
        assert res["summary"]["col3"] == 600
        assert res["summary"]["col5"] == 400


class TestRecon:
    def test_auto_categoriser_routes_salary_to_sch3(self):
        assert categorise_exclusion("Salary Expenses", {}) == "sch3"

    def test_auto_categoriser_routes_depreciation_to_non_cash(self):
        assert categorise_exclusion("Depreciation on Plant", {}) == "non_cash"

    def test_auto_categoriser_routes_interest_to_money(self):
        assert categorise_exclusion("Interest on Bank OD", {}) == "money"

    def test_auto_categoriser_unknown_lands_other(self):
        assert categorise_exclusion("Mystery Ledger", {}) == "other"

    def test_5_line_recon_arithmetic_ties(self):
        # Build a small full-result and exclude two ledgers.  Under Release 3
        # the classifier routes excluded ledgers to Col 8 directly; the test
        # fixture mirrors that (Dep + Salary sit in by_ledger[x].col8).
        full = {
            "summary": {
                "col2_total": 1025, "col3": 300, "col4": 100, "col5": 400,
                "col6": 800, "col7": 100, "col8": 125, "reportable_total": 900,
            },
            "transactions": [
                {"voucher_id": "1", "ledger_name": "Purchase",  "bucket": "col5", "amount": 400, "party_name": "A"},
                {"voucher_id": "2", "ledger_name": "Purchase",  "bucket": "col3", "amount": 300, "party_name": "B"},
                {"voucher_id": "3", "ledger_name": "Purchase",  "bucket": "col4", "amount": 100, "party_name": "C"},
                {"voucher_id": "4", "ledger_name": "Purchase",  "bucket": "col7", "amount": 100, "party_name": ""},
                {"voucher_id": "5", "ledger_name": "Depreciation", "bucket": "col8", "amount": 50, "party_name": ""},
                {"voucher_id": "6", "ledger_name": "Salary Exp",   "bucket": "col8", "amount": 75, "party_name": ""},
            ],
            "by_ledger": {
                "Purchase":     {"col3": 300, "col4": 100, "col5": 400, "col7": 100, "col8": 0,   "total": 900},
                "Depreciation": {"col3": 0,   "col4": 0,   "col5": 0,   "col7": 0,   "col8": 50,  "total": 50},
                "Salary Exp":   {"col3": 0,   "col4": 0,   "col5": 0,   "col7": 0,   "col8": 75,  "total": 75},
            },
            "by_party": {},
        }
        out = compute_recon_and_filter(
            full, excluded_set={"Depreciation", "Salary Exp"},
            ledgers_xlsx={
                "Purchase": {"groupParent": "Purchase Accounts"},
                "Depreciation": {"groupParent": "Indirect Expenses"},
                "Salary Exp": {"groupParent": "Indirect Expenses"},
            },
            group_chains={"indirect expenses": "indirect expenses"},
            exclusion_categories={},
        )
        rc = out["recon"]
        # PL total = 900 + 50 + 75 (all non-fixed-asset) = 1025
        assert rc["pl_total"] == 1025
        assert rc["capex_total"] == 0
        # Dep auto-cats non_cash (50), Salary auto-cats sch3 (75)
        assert rc["non_cash_total"] == 50
        assert rc["sch3_total"] == 75
        # Col 8 total should equal the sum of sub-buckets
        assert rc["col8_total"] == 125
        # Reportable is surfaced from summary
        assert rc["reportable_total"] == 900

    def test_auditor_override_moves_line_between_buckets(self):
        full = {
            "summary": {
                "col2_total": 100, "col3": 0, "col4": 0, "col5": 0, "col6": 0,
                "col7": 0, "col8": 100, "reportable_total": 0,
            },
            "transactions": [
                {"voucher_id": "1", "ledger_name": "Mystery", "bucket": "col8", "amount": 100, "party_name": ""},
            ],
            "by_ledger": {"Mystery": {"col3": 0, "col4": 0, "col5": 0, "col7": 0, "col8": 100, "total": 100}},
            "by_party": {},
        }
        out = compute_recon_and_filter(
            full, excluded_set={"Mystery"},
            ledgers_xlsx={"Mystery": {"groupParent": "Misc"}},
            group_chains={},
            exclusion_categories={"Mystery": "non_cash"},
        )
        rc = out["recon"]
        assert rc["non_cash_total"] == 100
        assert rc["other_total"] == 0
