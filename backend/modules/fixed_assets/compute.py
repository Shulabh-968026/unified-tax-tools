"""IT Depreciation computation engine.

Pure functions — given Opening WDV per block + list of additions + list of
deletions, compute depreciation per block (with the 180-day half-rate rule,
short-term capital gain under Sec 50 when block goes negative).

Output shape lines up exactly with the user's sample IT Depreciation Schedule
Excel so the export module can render it without reshaping.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple


def adjusted_cost(addition: Dict[str, Any]) -> float:
    """Per the user's spec, the capitalised cost of an addition equals
    Invoice Cost adjusted for: Discount/Credits (−), Other Expenses (+),
    ITC Reversed (−), Interest Capitalised (+), Forex Fluctuations (+)."""
    return (
        float(addition.get("invoice_cost") or 0)
        - float(addition.get("discount_credits") or 0)
        + float(addition.get("other_expenses") or 0)
        - float(addition.get("itc_reversed") or 0)
        + float(addition.get("interest_capitalized") or 0)
        + float(addition.get("forex_fluctuations") or 0)
    )


def compute_block(*,
                  block_label: str,
                  rate: float,
                  opening_wdv: float,
                  additions: List[Dict[str, Any]],
                  deletions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute depreciation for a single block per the Sec 32 WDV method.

    Sales are deemed to first reduce the full-rate pool (Opening + Adds≥180);
    any excess then reduces the half-rate pool (Adds<180). When total sales
    exceed the entire block, depreciation is zero and the block records a
    Short-Term Capital Gain under Sec 50 equal to the excess.
    """
    rate_dec = float(rate or 0) / 100.0
    adds_full = sum(adjusted_cost(a) for a in additions if a.get("is_more_than_180", True))
    adds_half = sum(adjusted_cost(a) for a in additions if not a.get("is_more_than_180", True))
    sales = sum(float(d.get("sale_value") or 0) for d in deletions
                if (d.get("classification") or "") == "sale")

    block_wdv_before_dep = opening_wdv + adds_full + adds_half - sales

    stcg = 0.0
    if block_wdv_before_dep < 0:
        # Block extinguished — Sec 50 short-term capital gain
        stcg = -block_wdv_before_dep
        return {
            "block_label":        block_label,
            "rate":               rate,
            "opening_wdv":        opening_wdv,
            "adds_full":          adds_full,
            "adds_half":          adds_half,
            "deletions":          sales,
            "total_block":        opening_wdv + adds_full + adds_half,
            "dep_full":           0.0,
            "dep_half":           0.0,
            "depreciation":       0.0,
            "closing_wdv":        0.0,
            "stcg_sec50":         stcg,
            "block_extinguished": True,
        }

    # Allocate sales: first against full-rate pool, remainder against half-rate
    full_pool = opening_wdv + adds_full
    sales_against_full = min(sales, full_pool)
    sales_remainder = sales - sales_against_full
    eligible_full = max(0.0, full_pool - sales_against_full)
    eligible_half = max(0.0, adds_half - sales_remainder)

    dep_full = eligible_full * rate_dec
    dep_half = eligible_half * (rate_dec / 2.0)
    depreciation = dep_full + dep_half
    closing_wdv = block_wdv_before_dep - depreciation

    return {
        "block_label":        block_label,
        "rate":               rate,
        "opening_wdv":        opening_wdv,
        "adds_full":          adds_full,
        "adds_half":          adds_half,
        "deletions":          sales,
        "total_block":        block_wdv_before_dep,
        "dep_full":           dep_full,
        "dep_half":           dep_half,
        "depreciation":       depreciation,
        "closing_wdv":        closing_wdv,
        "stcg_sec50":         0.0,
        "block_extinguished": False,
    }


def compute_run(*,
                openings: List[Dict[str, Any]],
                blocks_meta: Dict[str, float],
                additions: List[Dict[str, Any]],
                deletions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Run the per-block computation across every block_label that has any
    activity (opening, additions or deletions) and return the rows + grand
    totals for the cover sheet."""
    # Index inputs by block_label
    by_block: Dict[str, Dict[str, Any]] = {}

    def _bucket(bl: str) -> Dict[str, Any]:
        if bl not in by_block:
            by_block[bl] = {"opening_wdv": 0.0, "adds": [], "dels": []}
        return by_block[bl]

    for o in openings:
        bl = o.get("block_label") or ""
        if bl:
            _bucket(bl)["opening_wdv"] = float(o.get("opening_wdv") or 0)
    for a in additions:
        bl = a.get("block_label") or ""
        if bl:
            _bucket(bl)["adds"].append(a)
    for d in deletions:
        bl = d.get("block_label") or ""
        if bl and (d.get("classification") or "") == "sale":
            _bucket(bl)["dels"].append(d)

    rows: List[Dict[str, Any]] = []
    for bl, payload in by_block.items():
        rate = blocks_meta.get(bl, 0.0)
        rows.append(compute_block(
            block_label=bl, rate=rate,
            opening_wdv=payload["opening_wdv"],
            additions=payload["adds"],
            deletions=payload["dels"],
        ))

    # Drop blocks where every numeric is zero — they add visual noise to
    # the on-screen schedule and the Excel/PDF export without conveying
    # any audit information. (Kept inputs intact for the reconciliation
    # workings.)
    def _all_zero(r: Dict[str, Any]) -> bool:
        return all(
            float(r.get(k) or 0) == 0 for k in
            ("opening_wdv", "adds_full", "adds_half", "deletions",
             "depreciation", "closing_wdv", "stcg_sec50")
        )
    rows = [r for r in rows if not _all_zero(r)]
    rows.sort(key=lambda r: (-(r["rate"] or 0), r["block_label"]))

    totals = {
        "opening_wdv":   sum(r["opening_wdv"] for r in rows),
        "adds_full":     sum(r["adds_full"] for r in rows),
        "adds_half":     sum(r["adds_half"] for r in rows),
        "deletions":     sum(r["deletions"] for r in rows),
        "total_block":   sum(r["total_block"] for r in rows),
        "depreciation":  sum(r["depreciation"] for r in rows),
        "closing_wdv":   sum(r["closing_wdv"] for r in rows),
        "stcg_sec50":    sum(r["stcg_sec50"] for r in rows),
    }
    return rows, totals
