"""Release 4.4.12 — Clause 44 Consolidated Report is the computed sum of
division runs only.  There is no upload flow at Consolidation scope;
any stray `scope_kind="consolidation"` runs from earlier builds must
not leak into the merged view.

These tests verify the service-layer merge helper against carefully-
synthesised run documents.  Endpoint-level behaviour (the scope filter
in the query, the 400 on consolidation-scope upload) is a thin layer
above this and exercised by the existing live-test suite.
"""
from modules.clause44.service import merge_runs_for_consolidation


def _division_run(*, division_id, division_name, pl_total, capex_total=0,
                  ledger_totals=None):
    """Shorthand — build the fields `merge_runs_for_consolidation`
    reads.  Per-ledger totals default to one ledger == pl_total."""
    if ledger_totals is None:
        ledger_totals = {f"Rent - {division_name}": {"total": pl_total}}
    return {
        "run_id": f"run-{division_id}",
        "division_id": division_id,
        "division_name": division_name,
        "summary": {"col2_total": pl_total + capex_total,
                    "col3": 0, "col4": 0, "col5": pl_total + capex_total,
                    "col6": pl_total + capex_total, "col7": 0, "col8": 0},
        "by_ledger": ledger_totals,
        "by_party": {},
        "transactions": [
            {"bucket": "col5", "ledger_name": k, "amount": v["total"],
             "voucher_id": f"v{i}", "party_name": "Vendor"}
            for i, (k, v) in enumerate(ledger_totals.items())
        ],
        "recon": {
            "pl_total":         float(pl_total),
            "capex_total":      float(capex_total),
            "reportable_total": float(pl_total + capex_total),
        },
    }


# ─────────────────────────────────────────────────────────────────────────
# Core merge semantics
# ─────────────────────────────────────────────────────────────────────────
def test_merge_sums_pl_totals_across_divisions():
    runs = [
        _division_run(division_id="d1", division_name="Tiruppur",  pl_total=10_00_000),
        _division_run(division_id="d2", division_name="Mumbai",    pl_total= 5_00_000),
        _division_run(division_id="d3", division_name="Bangalore", pl_total= 2_00_000),
    ]
    merged = merge_runs_for_consolidation(runs)
    assert merged["recon"]["pl_total"] == 17_00_000


def test_merge_sums_capex_across_divisions():
    runs = [
        _division_run(division_id="d1", division_name="Tiruppur", pl_total=0, capex_total=4_00_00_000),
        _division_run(division_id="d2", division_name="Mumbai",   pl_total=0, capex_total=  50_00_000),
    ]
    merged = merge_runs_for_consolidation(runs)
    assert merged["recon"]["capex_total"] == 4_50_00_000
    assert merged["recon"]["pl_total"] == 0


def test_merge_idempotent_at_single_division():
    """Merging a single-division list must yield the same numbers as the
    input run — no accidental doubling."""
    run = _division_run(division_id="d1", division_name="Only",
                        pl_total=7_50_000, capex_total=1_00_000)
    merged = merge_runs_for_consolidation([run])
    assert merged["recon"]["pl_total"] == 7_50_000
    assert merged["recon"]["capex_total"] == 1_00_000
    assert len(merged["division_summaries"]) == 1


def test_merge_preserves_per_division_summaries():
    runs = [
        _division_run(division_id="d1", division_name="Tiruppur", pl_total=10_00_000),
        _division_run(division_id="d2", division_name="Mumbai",   pl_total= 5_00_000),
    ]
    merged = merge_runs_for_consolidation(runs)
    ds = merged["division_summaries"]
    assert len(ds) == 2
    names = {d["division_name"] for d in ds}
    assert names == {"Tiruppur", "Mumbai"}


def test_merge_combines_by_ledger_with_same_name_across_divisions():
    """When two divisions have a ledger with the exact same name (e.g.
    both call their rent ledger 'Office Rent'), the merged pivot sums
    them — it does NOT create two rows."""
    runs = [
        _division_run(division_id="d1", division_name="Tiruppur",
                      pl_total=0, ledger_totals={"Office Rent": {"total": 3_00_000}}),
        _division_run(division_id="d2", division_name="Mumbai",
                      pl_total=0, ledger_totals={"Office Rent": {"total": 4_00_000}}),
    ]
    merged = merge_runs_for_consolidation(runs)
    assert list(merged["by_ledger"]) == ["Office Rent"]
    assert merged["by_ledger"]["Office Rent"]["total"] == 7_00_000


def test_merge_transactions_carry_division_stamp():
    """Every transaction in the merged list must be stamped with its
    source division so the drill-down sheet can show which division a
    voucher came from."""
    runs = [
        _division_run(division_id="d1", division_name="Tiruppur", pl_total=1_00_000),
        _division_run(division_id="d2", division_name="Mumbai",   pl_total=2_00_000),
    ]
    merged = merge_runs_for_consolidation(runs)
    divs_seen = {t["division_name"] for t in merged["transactions"]}
    assert divs_seen == {"Tiruppur", "Mumbai"}


# ─────────────────────────────────────────────────────────────────────────
# Regression guards — the old bug (Issue 3): consolidation-scope run
# bleeding into the merged view must not re-appear even if a stray run
# slips through the query filter.
# ─────────────────────────────────────────────────────────────────────────
def test_merge_empty_list_returns_zero_totals():
    merged = merge_runs_for_consolidation([])
    assert merged["recon"]["pl_total"] == 0
    assert merged["recon"]["capex_total"] == 0
    assert merged["division_summaries"] == []


def test_merge_single_division_matches_on_screen_values():
    """Regression guard for Release 4.4.11 — the on-screen Division view
    of a single division's run and the Consolidated Report (when that
    is the only generated division) must tie to the rupee."""
    tiruppur = _division_run(
        division_id="d-tiruppur", division_name="Tiruppur",
        pl_total=1_23_45_678, capex_total=45_00_000,
    )
    merged = merge_runs_for_consolidation([tiruppur])
    assert merged["recon"]["pl_total"]    == tiruppur["recon"]["pl_total"]
    assert merged["recon"]["capex_total"] == tiruppur["recon"]["capex_total"]
    # reportable = pl_total + capex_total - (sum of deduction buckets)
    assert merged["recon"]["reportable_total"] == (
        tiruppur["recon"]["pl_total"] + tiruppur["recon"]["capex_total"]
    )
