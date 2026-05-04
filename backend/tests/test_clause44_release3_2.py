"""Release-3.2 tests — multi-signal heuristic, voucher-usage detection,
and ITC coverage diagnostic.

Background: Release 3.1 narrowed the ITC seeding to ledgers whose NAME
starts with ``Input``.  On the user's ``ABC_Textile_Mills`` JSON this
heuristic missed at least one valid input ledger (``SGST IN PUT`` —
note the embedded space) and would also miss any client that uses
bespoke ledger names (``Tax-Cr-Misc-A2``, ``GST Receivable 18%``, etc.).

3.2 makes detection naming-agnostic by combining three signals:
  1. Name pattern (existing, with whitespace-collapsing fix)
  2. parentGroup pattern (NEW — Tally users file under groups like
     ``INPUT CREDIT`` or ``Defrerred Input Credit`` regardless of leaf
     name)
  3. Voucher-usage scoring (NEW — ledgers that fire on purchase
     vouchers are auto-tagged as input even with cryptic names)

Plus a coverage diagnostic in the summary so the auditor can spot the
"low ITC coverage → wrong Col 3" failure mode at the report screen.
"""
from modules.clause44.service import (
    _classify_itc_kind,
    compute_voucher_usage_kinds,
    compute_suggestions,
    classify_vouchers,
)


# ─────────────────────────────────────────────────────────────────────
# 1. Multi-signal _classify_itc_kind
# ─────────────────────────────────────────────────────────────────────
class TestNameWhitespaceCollapse:
    def test_sgst_in_put_with_space(self):
        # The exact failing case from the user's ABC Textile Mills JSON.
        kind, src = _classify_itc_kind("SGST IN PUT", "", "")
        assert kind == "input"
        assert src == "name"

    def test_input_with_dash_underscore(self):
        for n in ["Input_CGST", "Input-CGST", "  Input   CGST  "]:
            assert _classify_itc_kind(n, "", "")[0] == "input"


class TestParentGroupSignal:
    def test_input_credit_group_catches_neutral_named_ledger(self):
        # Bespoke ledger name but parent group says INPUT CREDIT — Tally
        # convention.  Engine should still mark it as input via group.
        kind, src = _classify_itc_kind("Tax-Cr-Misc-A2", "", "INPUT CREDIT")
        assert kind == "input"
        assert src == "group"

    def test_output_credit_group_overrides(self):
        # Even a name without 'output' should be output-tagged if filed
        # under OUTPUT CREDIT group.
        kind, src = _classify_itc_kind("Tax-Cr-Misc-A2", "", "OUTPUT CREDIT")
        assert kind == "output"
        assert src == "group"

    def test_defrerred_input_credit_typo(self):
        # Real client typo from ABC Textile Mills — must still be caught.
        kind, src = _classify_itc_kind("Some Ledger", "", "Defrerred Input Credit")
        assert kind == "input"
        assert src == "group"


class TestSourcePriority:
    def test_name_beats_group(self):
        # If name is unambiguous, name wins (kind_source = 'name').
        kind, src = _classify_itc_kind("Input CGST", "", "Some Other Group")
        assert (kind, src) == ("input", "name")

    def test_output_anywhere_wins_over_input(self):
        # Defensive: if name says output but group says input, output wins.
        kind, src = _classify_itc_kind("Output CGST", "", "Input Credit")
        assert kind == "output"


# ─────────────────────────────────────────────────────────────────────
# 2. Voucher-usage classifier
# ─────────────────────────────────────────────────────────────────────
def _v(vtype, ledgers):
    return {
        "voucherTypeName": vtype,
        "ledgerEntries": [{"ledger": l} for l in ledgers],
    }


class TestVoucherUsage:
    def test_purchase_dominant_marks_input(self):
        cands = [{"name": "Mystery Tax Ledger"}]
        vchs = [_v("Purchase", ["Mystery Tax Ledger", "Vendor X"])] * 5
        out = compute_voucher_usage_kinds(cands, vchs)
        assert out["Mystery Tax Ledger"]["usage_kind"] == "input"
        assert out["Mystery Tax Ledger"]["n_purchase"] == 5

    def test_sales_dominant_marks_output(self):
        cands = [{"name": "Mystery Tax Ledger"}]
        vchs = [_v("Sales", ["Mystery Tax Ledger", "Customer Y"])] * 5
        out = compute_voucher_usage_kinds(cands, vchs)
        assert out["Mystery Tax Ledger"]["usage_kind"] == "output"

    def test_mixed_usage_returns_neutral(self):
        cands = [{"name": "Mixed Ledger"}]
        vchs = [_v("Purchase", ["Mixed Ledger"])] * 3 + [_v("Sales", ["Mixed Ledger"])] * 3
        out = compute_voucher_usage_kinds(cands, vchs)
        assert out["Mixed Ledger"]["usage_kind"] == "neutral"

    def test_unused_ledger_returns_neutral(self):
        cands = [{"name": "Dormant"}]
        vchs = [_v("Purchase", ["Some Other Ledger"])]
        out = compute_voucher_usage_kinds(cands, vchs)
        assert out["Dormant"]["usage_kind"] == "neutral"
        assert out["Dormant"]["n_voucher"] == 0

    def test_below_threshold_returns_neutral(self):
        cands = [{"name": "Sparse"}]
        vchs = [_v("Purchase", ["Sparse"])] * 2  # below default min=3
        out = compute_voucher_usage_kinds(cands, vchs)
        assert out["Sparse"]["usage_kind"] == "neutral"


# ─────────────────────────────────────────────────────────────────────
# 3. compute_suggestions integration
# ─────────────────────────────────────────────────────────────────────
def _xlsx(*rows):
    return {n: {"name": n, "bsOrPl": "B", "subhead": sh, "groupParent": gp,
                "head": "", "closingBalance": 0}
            for n, sh, gp in rows}


class TestSuggestionsIntegration:
    def test_usage_promotes_other_to_input_and_pre_ticks(self):
        xlsx = _xlsx(
            ("Tax-Cr-Misc-A2", "Misc", "Misc Group"),
        )
        vchs = [_v("Purchase", ["Tax-Cr-Misc-A2"])] * 5
        s = compute_suggestions(xlsx, [], vchs)
        c = s["itc_candidates"][0]
        assert c["kind"] == "input"
        assert c["kind_source"] == "usage"
        assert c["usage_kind"] == "input"
        assert c["suggested"] is True   # auto-pre-tick via usage signal

    def test_name_input_with_no_subhead_match_now_pre_ticks_via_usage(self):
        # Real-world: 'SGST IN PUT' name says input, parent INPUT CREDIT,
        # books-XLSX subhead might not be 'Balance with Revenue
        # Authorities' — should still pre-tick if vouchers back it up.
        xlsx = _xlsx(
            ("SGST IN PUT", "Misc Subhead", "INPUT CREDIT"),
        )
        vchs = [_v("Purchase", ["SGST IN PUT"])] * 5
        s = compute_suggestions(xlsx, [], vchs)
        c = s["itc_candidates"][0]
        assert c["kind"] == "input"
        assert c["suggested"] is True

    def test_output_named_with_purchase_usage_stays_output(self):
        # Defensive — usage signal must NOT override an explicit Output name.
        xlsx = _xlsx(("Output CGST @ 2.5%", "Misc", "OUTPUT CREDIT"))
        vchs = [_v("Purchase", ["Output CGST @ 2.5%"])] * 5
        s = compute_suggestions(xlsx, [], vchs)
        c = s["itc_candidates"][0]
        assert c["kind"] == "output"
        assert c["suggested"] is False

    def test_no_vouchers_falls_back_to_legacy_subhead_path(self):
        # Backward compat: when caller doesn't pass vouchers, behaviour
        # matches the Release 3.1 subhead-only seed.
        xlsx = _xlsx(("Input CGST", "Balance with Revenue Authorities", "Loans & Advances"))
        s = compute_suggestions(xlsx, [], None)
        c = s["itc_candidates"][0]
        assert c["kind"] == "input"
        assert c["suggested"] is True
        assert c["usage_kind"] is None

    def test_real_abc_textile_pattern(self):
        # Recreates the user's ABC Textile Mills failure: 'SGST IN PUT'
        # now correctly ticks as input.
        xlsx = _xlsx(
            ("Input CGST @ 9%",            "Misc", "INPUT CREDIT"),
            ("SGST IN PUT",                "Misc", "INPUT CREDIT"),
            ("CGST Deferred Input Credit", "Misc", "Defrerred Input Credit"),
            ("Output CGST @ 2.5%",         "Misc", "OUTPUT CREDIT"),
        )
        # Heavy purchase usage on input ledgers, sales on output.
        vchs = (
            [_v("Purchase", ["Input CGST @ 9%", "SGST IN PUT", "CGST Deferred Input Credit"])] * 5
            + [_v("Sales", ["Output CGST @ 2.5%"])] * 5
        )
        s = compute_suggestions(xlsx, [], vchs)
        cands = {c["name"]: c for c in s["itc_candidates"]}
        suggested = sorted(n for n, c in cands.items() if c["suggested"])
        assert suggested == [
            "CGST Deferred Input Credit",
            "Input CGST @ 9%",
            "SGST IN PUT",
        ]
        assert cands["Output CGST @ 2.5%"]["kind"] == "output"
        assert cands["Output CGST @ 2.5%"]["suggested"] is False


# ─────────────────────────────────────────────────────────────────────
# 4. Coverage diagnostic in classify_vouchers summary
# ─────────────────────────────────────────────────────────────────────
class TestCoverageDiagnostic:
    def _setup(self, with_itc=True):
        # 4 vouchers with regular-registered party.
        # `with_itc=True` puts ITC ledger on the voucher; False omits it.
        v_with = {
            "voucherTypeName": "Purchase",
            "partyLedgerName": "Vendor A",
            "ledgerEntries": [
                {"ledger": "Purchases", "amount": -1000},
                {"ledger": "Input CGST", "amount": 90},
            ],
        }
        v_without = {
            "voucherTypeName": "Purchase",
            "partyLedgerName": "Vendor A",
            "ledgerEntries": [
                {"ledger": "Purchases", "amount": -1000},
            ],
        }
        vouchers = [v_with if with_itc else v_without for _ in range(4)]
        exp = {"Purchases": {"reason": ""}}
        itc = {"Input CGST"} if with_itc else set()
        party_lookup = {"Vendor A": {"gstRegistrationType": "regular", "partyGSTIN": "29ABCDE1234F1Z5", "country": "India"}}
        return vouchers, exp, itc, party_lookup

    def test_coverage_full(self):
        vchs, exp, itc, pl = self._setup(with_itc=True)
        result = classify_vouchers(vchs, exp, itc, pl)
        s = result["summary"]
        assert s["itc_coverage_eligible"] == 4
        assert s["itc_coverage_with_itc"] == 4
        assert s["itc_coverage_pct"] == 100.0

    def test_coverage_zero_triggers_advisory(self):
        vchs, exp, itc, pl = self._setup(with_itc=False)
        result = classify_vouchers(vchs, exp, itc, pl)
        s = result["summary"]
        assert s["itc_coverage_eligible"] == 4
        assert s["itc_coverage_with_itc"] == 0
        assert s["itc_coverage_pct"] == 0.0

    def test_no_eligible_vouchers_returns_none(self):
        # Only RCM / unregistered vouchers — no eligible denominator.
        v = {
            "voucherTypeName": "Reverse Charge",
            "partyLedgerName": "Vendor B",
            "ledgerEntries": [{"ledger": "Purchases", "amount": -500}],
        }
        result = classify_vouchers([v], {"Purchases": {"reason": ""}}, set(), {})
        s = result["summary"]
        assert s["itc_coverage_eligible"] == 0
        assert s["itc_coverage_pct"] is None
