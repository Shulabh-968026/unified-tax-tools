"""Release-3.1 tests — ITC kind classification + smarter seeding.

User report: bulk of the value sat in Col 3 because the wizard auto-ticked
Output-side tax ledgers (Output CGST / Output SGST / Output IGST) under
the broader subhead-match seeding.  Output ledgers fire on sales
vouchers so they never appear on a purchase voucher → the ITC presence
check returned False everywhere → with inference ON, every registered-
vendor purchase swept into Col 3 via Input B.

Fix: pre-tick only ledgers whose name pattern says INPUT *and* whose
subhead matches the target list.  Output-kind ledgers stay un-ticked
even when the subhead would otherwise qualify.  Each ITC candidate now
carries a `kind` field ('input' | 'output' | 'other') so the UI can
warn the auditor.
"""
from modules.clause44.service import compute_suggestions, _classify_itc_kind


class TestKindClassifier:
    def test_input_prefixed_names(self):
        for n in ["Input CGST @ 9%", "Input SGST", "Input IGST 18%", "Input-Cess"]:
            assert _classify_itc_kind(n, "", "") == "input"

    def test_output_prefixed_names(self):
        for n in ["Output CGST @ 2.5%", "Output IGST 5%", "Output SGST", "Output-Cess"]:
            assert _classify_itc_kind(n, "", "") == "output"

    def test_alt_names(self):
        assert _classify_itc_kind("RCM Input IGST", "", "") == "input"
        assert _classify_itc_kind("ITC Input", "", "") == "input"
        assert _classify_itc_kind("RCM 18%", "", "") == "input"
        assert _classify_itc_kind("RCM Output 18%", "", "") == "output"

    def test_neutral_falls_back_to_other(self):
        assert _classify_itc_kind("Balance with GST Authorities", "", "") == "other"
        assert _classify_itc_kind("Statutory Dues Payable", "", "") == "other"


class TestSeedingHeuristic:
    def _xlsx(self, *rows):
        # rows = [(name, bsOrPl, subhead, groupParent), ...]
        return {n: {"name": n, "bsOrPl": bsp, "subhead": sh, "groupParent": gp,
                    "head": "", "closingBalance": 0}
                for n, bsp, sh, gp in rows}

    def test_input_with_target_subhead_is_pre_ticked(self):
        xlsx = self._xlsx(
            ("Input CGST @ 9%", "B", "Balance with Revenue Authorities", "Loans & Advances"),
        )
        s = compute_suggestions(xlsx, [])
        candidate = s["itc_candidates"][0]
        assert candidate["kind"] == "input"
        assert candidate["suggested"] is True

    def test_output_with_target_subhead_is_NOT_pre_ticked(self):
        # The bug case — Output ledger filed under Statutory Dues Payable
        # used to get auto-ticked.  Now it's classified output → un-ticked.
        xlsx = self._xlsx(
            ("Output CGST @ 2.5%", "B", "Statutory Dues Payable", "Current Liabilities"),
        )
        s = compute_suggestions(xlsx, [])
        candidate = s["itc_candidates"][0]
        assert candidate["kind"] == "output"
        assert candidate["suggested"] is False

    def test_other_with_target_subhead_is_NOT_pre_ticked(self):
        # Neutral "Balance with Revenue Authorities" stays present in the
        # candidate pool but un-ticked unless explicitly Input-prefixed.
        xlsx = self._xlsx(
            ("Balance with GST Authorities", "B", "Balance with Revenue Authorities", "Loans & Advances"),
        )
        s = compute_suggestions(xlsx, [])
        c = s["itc_candidates"][0]
        assert c["kind"] == "other"
        assert c["suggested"] is False

    def test_input_off_target_subhead_is_NOT_pre_ticked(self):
        # Input-named but filed in a non-target subhead — still candidate,
        # not pre-ticked (pre-tick requires both signals).
        xlsx = self._xlsx(
            ("Input IGST @ 18%", "B", "Misc Subhead", "Current Assets"),
        )
        s = compute_suggestions(xlsx, [])
        c = s["itc_candidates"][0]
        assert c["kind"] == "input"
        assert c["suggested"] is False  # subhead doesn't qualify

    def test_real_world_abc_textile_set(self):
        # The exact failure pattern from run_0ef0127bba5c — three Output
        # ledgers + one Input ledger filed under Statutory Dues Payable.
        xlsx = self._xlsx(
            ("Output CGST @ 2.5%", "B", "Statutory Dues Payable", "Current Liabilities"),
            ("Output SGST @ 2.5%", "B", "Statutory Dues Payable", "Current Liabilities"),
            ("Output IGST @ 5%",   "B", "Statutory Dues Payable", "Current Liabilities"),
            ("Input SGST @ 9%",    "B", "Statutory Dues Payable", "Current Liabilities"),
        )
        s = compute_suggestions(xlsx, [])
        cands = {c["name"]: c for c in s["itc_candidates"]}
        # Only the Input ledger gets pre-ticked
        suggested = [n for n, c in cands.items() if c["suggested"]]
        assert suggested == ["Input SGST @ 9%"]
        # All four are still in the pool
        assert len(cands) == 4
        # Output ledgers carry kind="output" so the UI can warn
        for out in ["Output CGST @ 2.5%", "Output SGST @ 2.5%", "Output IGST @ 5%"]:
            assert cands[out]["kind"] == "output"
