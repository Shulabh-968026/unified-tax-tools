"""
Fixed Assets — Summary MIS service.

Aggregates everything the auditor needs to "look at one screen" before
signing off on the working-paper:

  * KPI strip (Opening · Adds · Depn · Closing)
  * Counts: ledgers, additions, discounts, sales, merged-into-parents,
    bills-attached, half-rate pool, etc.
  * Audit-risk flags (missing PTU, PTU > FY end, missing party, un-reviewed,
    discount-pending, zero/negative invoice cost)
  * Block-wise breakdown
  * Top 10 additions by capitalised value
  * Top 5 suppliers by capitalised value
  * Adjustment-column usage (how many adds touched Other Exp / ITC Rev / etc)
  * Quarterly distribution of additions
  * OCR coverage (uploads pending, total chunks, applied)

Pure-data — no DB writes. Intentionally split out from controller.py so
the endpoint stays a thin call-site.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from modules.fixed_assets.compute import adjusted_cost


# ---- helpers -----------------------------------------------------------
def _flag(count: int, value: float) -> Dict[str, Any]:
    return {"count": int(count), "value": round(float(value), 2)}


def _quarter(iso_date: str, fy_start: str, fy_end: str) -> Optional[str]:
    """Map an ISO-formatted date string to Q1/Q2/Q3/Q4 within the FY."""
    try:
        d = datetime.strptime((iso_date or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    try:
        s = datetime.strptime((fy_start or "")[:10], "%Y-%m-%d").date()
        e = datetime.strptime((fy_end or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if d < s or d > e:
        return None
    months = (d.year - s.year) * 12 + (d.month - s.month)
    if months < 3:
        return "Q1"
    if months < 6:
        return "Q2"
    if months < 9:
        return "Q3"
    return "Q4"


# ---- main builder ------------------------------------------------------
def build_summary(
    *,
    run: Dict[str, Any],
    ledgers: List[Dict[str, Any]],
    additions: List[Dict[str, Any]],
    credits: List[Dict[str, Any]],
    blocks_meta: Dict[str, float],
    compute_rows: List[Dict[str, Any]],
    compute_totals: Dict[str, float],
    attached_addition_ids: set,
    pending_uploads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """All stats are derived; nothing is persisted."""
    fy_end = run.get("fy_end") or ""
    fy_start = run.get("fy_start") or ""

    # ------------ Bucket A — MIS counts & values ------------
    additions_active = [a for a in additions if not a.get("parent_addition_id")]
    additions_merged = [a for a in additions if a.get("parent_addition_id")]
    discount_credits = [c for c in credits
                        if (c.get("classification") or "").lower() == "discount"]
    discounts_merged = [c for c in discount_credits if c.get("parent_addition_id")]
    sales = [c for c in credits if (c.get("classification") or "").lower() == "sale"]
    pending_credits = [c for c in credits
                       if (c.get("classification") or "").lower() == "pending"]

    # OCR attachment coverage
    bills_attached = sum(1 for a in additions if a.get("addition_id") in attached_addition_ids)
    bills_attached_value = sum(
        adjusted_cost(a) for a in additions
        if a.get("addition_id") in attached_addition_ids
        and not a.get("parent_addition_id")
    )
    bills_unattached = len(additions_active) - bills_attached
    coverage_pct = (
        round(100.0 * bills_attached / len(additions_active), 1)
        if additions_active else 0.0
    )

    half_rate_pool = [a for a in additions_active if not a.get("is_more_than_180", True)]
    half_rate_value = sum(adjusted_cost(a) for a in half_rate_pool)

    merged_value = sum(float(a.get("invoice_cost") or 0) for a in additions_merged)
    merged_disc_value = sum(abs(float(c.get("amount") or 0)) for c in discounts_merged)

    counts = {
        "ledgers":               len(ledgers),
        "ledgers_classified":    sum(1 for L in ledgers if L.get("block_label")),
        "additions":             _flag(len(additions_active),
                                       sum(adjusted_cost(a) for a in additions_active)),
        "additions_merged":      _flag(len(additions_merged), merged_value),
        "discounts":             _flag(len(discount_credits),
                                       sum(abs(float(c.get("amount") or 0)) for c in discount_credits)),
        "discounts_merged":      _flag(len(discounts_merged), merged_disc_value),
        "sales":                 _flag(len(sales),
                                       sum(float(c.get("sale_value") or c.get("amount") or 0) for c in sales)),
        "bills_attached":        _flag(bills_attached, bills_attached_value),
        "bills_unattached":      _flag(bills_unattached, 0.0),  # value computed below
        "coverage_pct":          coverage_pct,
        "half_rate_pool":        _flag(len(half_rate_pool), half_rate_value),
    }
    counts["bills_unattached"]["value"] = round(
        sum(adjusted_cost(a) for a in additions_active) - bills_attached_value, 2,
    )

    # ------------ Bucket B — Audit-risk flags ------------
    missing_ptu      = [a for a in additions_active if not (a.get("put_to_use_date") or "").strip()]
    missing_party    = [a for a in additions_active if not (a.get("party_name") or "").strip()]
    unreviewed       = [a for a in additions_active if not a.get("reviewed", False)]
    zero_neg_cost    = [a for a in additions_active if float(a.get("invoice_cost") or 0) <= 0]

    ptu_after_fy = []
    if fy_end:
        for a in additions_active:
            ptu = (a.get("put_to_use_date") or "").strip()
            if ptu and ptu > fy_end:
                ptu_after_fy.append(a)

    audit_flags = {
        "missing_ptu":           _flag(len(missing_ptu),
                                       sum(adjusted_cost(a) for a in missing_ptu)),
        "ptu_after_fy_end":      _flag(len(ptu_after_fy),
                                       sum(adjusted_cost(a) for a in ptu_after_fy)),
        "missing_party":         _flag(len(missing_party),
                                       sum(adjusted_cost(a) for a in missing_party)),
        "unreviewed":            _flag(len(unreviewed),
                                       sum(adjusted_cost(a) for a in unreviewed)),
        "discount_pending":      _flag(len(pending_credits),
                                       sum(abs(float(c.get("amount") or 0)) for c in pending_credits)),
        "zero_or_negative_cost": _flag(len(zero_neg_cost),
                                       sum(float(a.get("invoice_cost") or 0) for a in zero_neg_cost)),
    }
    open_flags = sum(1 for v in audit_flags.values() if v["count"] > 0)

    # ------------ Bucket C — Insight cuts ------------

    # Block-wise breakdown — count + capitalised value of additions per block,
    # joined with the compute row for depreciation + closing.
    by_block_cnt: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for a in additions_active:
        bl = a.get("block_label") or "(Unclassified)"
        c, v = by_block_cnt[bl]
        by_block_cnt[bl] = (c + 1, v + adjusted_cost(a))
    cmpx = {r["block_label"]: r for r in compute_rows}
    blocks: List[Dict[str, Any]] = []
    seen = set()
    for bl, (cnt, val) in by_block_cnt.items():
        cr = cmpx.get(bl, {})
        blocks.append({
            "block_label":      bl,
            "rate":             float(blocks_meta.get(bl) or cr.get("rate") or 0),
            "additions_count":  cnt,
            "additions_value":  round(val, 2),
            "depreciation":     round(float(cr.get("depreciation") or 0), 2),
            "closing_wdv":      round(float(cr.get("closing_wdv") or 0), 2),
        })
        seen.add(bl)
    # Surface compute-only blocks (eg blocks with opening but no current adds)
    for r in compute_rows:
        if r["block_label"] in seen:
            continue
        blocks.append({
            "block_label":      r["block_label"],
            "rate":             float(r.get("rate") or 0),
            "additions_count":  0,
            "additions_value":  0.0,
            "depreciation":     round(float(r.get("depreciation") or 0), 2),
            "closing_wdv":      round(float(r.get("closing_wdv") or 0), 2),
        })
    blocks.sort(key=lambda b: -b["rate"])

    # Top 10 additions by capitalised value
    top_additions = sorted(
        additions_active, key=lambda a: -adjusted_cost(a),
    )[:10]
    top_additions_payload = [{
        "addition_id":      a["addition_id"],
        "description":      (a.get("description") or a.get("particulars") or ""),
        "party_name":       a.get("party_name") or "",
        "block_label":      a.get("block_label") or "",
        "put_to_use_date":  a.get("put_to_use_date") or "",
        "capitalised_cost": round(adjusted_cost(a), 2),
        "is_more_than_180": bool(a.get("is_more_than_180", True)),
    } for a in top_additions]

    # Top 5 suppliers by capitalised value
    by_party: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for a in additions_active:
        p = (a.get("party_name") or "").strip() or "(unknown)"
        c, v = by_party[p]
        by_party[p] = (c + 1, v + adjusted_cost(a))
    top_suppliers = sorted(
        ({"party": p, "count": c, "value": round(v, 2)}
         for p, (c, v) in by_party.items()),
        key=lambda x: -x["value"],
    )[:5]

    # Adjustment-column usage — how many additions touched each + ₹ totals
    adj_keys = (
        ("other_expenses",       "Other Expenses",      False),
        ("itc_reversed",         "ITC Reversed",        False),
        ("interest_capitalized", "Interest Capitalised", False),
        ("forex_fluctuations",   "Forex Fluctuations",  False),
        ("discount_credits",     "Discounts / Credits", True),
    )
    adjustments = []
    for key, label, is_negative in adj_keys:
        touched = [a for a in additions_active if float(a.get(key) or 0) > 0]
        total = sum(float(a.get(key) or 0) for a in touched)
        adjustments.append({
            "key":              key,
            "label":            label,
            "count":            len(touched),
            "value":            round(total, 2),
            "reduces_cost":     is_negative,
        })

    # Quarterly distribution of capitalised additions (PTU date or invoice date)
    q_buckets: Dict[str, List[float]] = {q: [0, 0.0] for q in ("Q1", "Q2", "Q3", "Q4")}
    q_buckets["Outside FY"] = [0, 0.0]
    for a in additions_active:
        d = (a.get("put_to_use_date") or a.get("invoice_date") or "")
        q = _quarter(d, fy_start, fy_end) or "Outside FY"
        q_buckets[q][0] += 1
        q_buckets[q][1] += adjusted_cost(a)
    quarterly = [
        {"quarter": q, "count": int(c), "value": round(v, 2)}
        for q, (c, v) in q_buckets.items()
        if (c, v) != (0, 0.0) or q != "Outside FY"
    ]

    # ------------ OCR coverage ------------
    pend_total_chunks   = sum(len(u.get("chunks") or []) for u in pending_uploads)
    pend_applied_chunks = sum(len(u.get("applied_chunk_indexes") or []) for u in pending_uploads)
    ocr = {
        "uploads_pending":          len([u for u in pending_uploads if u.get("status") not in ("completed",)]),
        "uploads_total":            len(pending_uploads),
        "chunks_total":             pend_total_chunks,
        "chunks_applied":           pend_applied_chunks,
        "chunks_remaining":         max(0, pend_total_chunks - pend_applied_chunks),
    }

    # ------------ KPI strip ------------
    kpis = {
        "opening_wdv":   round(float(compute_totals.get("opening_wdv") or 0), 2),
        "adds_full":     round(float(compute_totals.get("adds_full") or 0), 2),
        "adds_half":     round(float(compute_totals.get("adds_half") or 0), 2),
        "deletions":     round(float(compute_totals.get("deletions") or 0), 2),
        "depreciation":  round(float(compute_totals.get("depreciation") or 0), 2),
        "closing_wdv":   round(float(compute_totals.get("closing_wdv") or 0), 2),
    }

    return {
        "run_id":           run.get("id"),
        "client_name":      run.get("client_name") or run.get("name") or "",
        "fy_label":         run.get("fy_label") or run.get("fy") or "",
        "fy_start":         fy_start,
        "fy_end":           fy_end,
        "kpis":             kpis,
        "validation":       run.get("prior_3cd_validation"),
        "counts":           counts,
        "audit_flags":      audit_flags,
        "open_flag_count":  open_flags,
        "blocks":           blocks,
        "top_additions":    top_additions_payload,
        "top_suppliers":    top_suppliers,
        "adjustments":      adjustments,
        "quarterly":        quarterly,
        "ocr":              ocr,
    }


__all__ = ["build_summary"]
