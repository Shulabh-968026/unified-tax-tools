"""Analytics payload for the Balance Confirmation Summary dashboard.

Single source of truth — consumed by:
    • GET /api/balance-confirmation/runs/{rid}/analytics   (JSON for UI)
    • build_summary_pdf()                                  (PDF mirror)

We expose six status buckets that match the audit narrative:
    confirmed    — recipient ticked "balance is correct"
    reconciled   — recipient disputed AND auditor has logged ≥1 recon comment
    disputed     — recipient disputed, reconciliation still pending
    in_flight    — queued / sent / delivered / opened / clicked  (awaiting)
    failed       — bounced / failed
    not_sent     — never dispatched (no email on file OR simply not yet sent)

Exposure  = sum of |closing_balance|.
Coverage (amount-weighted) = (confirmed_₹ + reconciled_₹) / category_total_₹
Coverage (count-weighted)  = (confirmed_n + reconciled_n) / category_total_n

We additionally expose `response_amt / response_n`  = confirmed + reconciled +
disputed — the true "response rate" before reconciliation work, matching the
auditor's initial risk-assessment view.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


CATEGORY_ORDER = [
    ("trade_receivable", "Receivables"),
    ("trade_payable",    "Payables"),
    ("bank",             "Banks"),
    ("unsecured_loans",  "Unsecured Loans"),
    ("other",            "Other"),
]

STATUS_ORDER = ["confirmed", "reconciled", "disputed",
                "in_flight", "failed", "not_sent"]

_IN_FLIGHT = {"queued", "sent", "delivered", "opened", "clicked"}
_FAILED    = {"bounced", "failed"}
_STALE_SENT_DAYS = 7


def _f(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_unsecured(parent_group: str) -> bool:
    pg = (parent_group or "").lower()
    return "unsecured" in pg and "loan" in pg


def _category_for(ledger: Dict[str, Any]) -> str:
    """Dashboard category (splits unsecured-loans out of 'other' / 'trade_payable')."""
    if _is_unsecured(ledger.get("parent_group", "")):
        return "unsecured_loans"
    cat = ledger.get("category") or "other"
    if cat in ("trade_receivable", "trade_payable", "bank"):
        return cat
    return "other"


def _status_bucket(ledger: Dict[str, Any], reconciled_ids: set) -> str:
    st = ledger.get("confirmation_status") or "not_sent"
    if st == "confirmed":
        return "confirmed"
    if st == "disputed":
        return "reconciled" if ledger.get("ledger_id") in reconciled_ids else "disputed"
    if st in _IN_FLIGHT:
        return "in_flight"
    if st in _FAILED:
        return "failed"
    return "not_sent"


def _empty_bucket() -> Dict[str, Any]:
    return {
        "count": 0,
        "amount": 0.0,
        "by_status": {k: {"count": 0, "amount": 0.0} for k in STATUS_ORDER},
    }


def _coverage(bucket: Dict[str, Any]) -> Dict[str, float]:
    by = bucket["by_status"]
    resp_n = by["confirmed"]["count"] + by["reconciled"]["count"] + by["disputed"]["count"]
    resp_a = by["confirmed"]["amount"] + by["reconciled"]["amount"] + by["disputed"]["amount"]
    audit_n = by["confirmed"]["count"] + by["reconciled"]["count"]
    audit_a = by["confirmed"]["amount"] + by["reconciled"]["amount"]
    tot_n = max(bucket["count"], 1)
    tot_a = bucket["amount"] if bucket["amount"] > 0.0001 else 1.0
    return {
        "response_count_pct":  round(resp_n  / tot_n * 100.0, 1),
        "response_amount_pct": round(resp_a  / tot_a * 100.0, 1),
        "audit_count_pct":     round(audit_n / tot_n * 100.0, 1),
        "audit_amount_pct":    round(audit_a / tot_a * 100.0, 1),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _reconciled_ledger_ids(responses: List[Dict[str, Any]],
                           comments: List[Dict[str, Any]]) -> set:
    """A disputed ledger counts as 'reconciled' once any auditor recon comment
    exists against its response (either a per-pair comment or a general one).
    We key on response_id → ledger_id."""
    resp_ids_with_comments = {
        (c.get("response_id") or "") for c in comments if c.get("response_id")
    }
    ids = set()
    for r in responses:
        if r.get("decision") == "disputed" and r.get("response_id") in resp_ids_with_comments:
            if r.get("ledger_id"):
                ids.add(r["ledger_id"])
    return ids


def _funnel(ledgers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """6-stage funnel — each stage with {count, amount}."""
    total_n = len(ledgers)
    total_a = sum(abs(_f(L.get("closing_balance"))) for L in ledgers)

    def agg(pred) -> Tuple[int, float]:
        n = 0
        a = 0.0
        for L in ledgers:
            if pred(L):
                n += 1
                a += abs(_f(L.get("closing_balance")))
        return n, a

    n_email, a_email = agg(lambda L: bool(L.get("email")))

    # "Dispatched" — any of: queued, sent, delivered, opened, clicked, confirmed, disputed, bounced, failed
    dispatched_states = {"queued", "sent", "delivered", "opened", "clicked",
                         "confirmed", "disputed", "bounced", "failed"}
    n_sent, a_sent = agg(lambda L: (L.get("confirmation_status") or "") in dispatched_states)

    delivered_states = dispatched_states - {"queued", "bounced", "failed"}
    n_del, a_del = agg(lambda L: (L.get("confirmation_status") or "") in delivered_states)

    opened_states = {"opened", "clicked", "confirmed", "disputed"}
    n_op, a_op = agg(lambda L: (L.get("confirmation_status") or "") in opened_states)

    responded_states = {"confirmed", "disputed"}
    n_resp, a_resp = agg(lambda L: (L.get("confirmation_status") or "") in responded_states)

    stages = [
        ("Identified",    total_n,  total_a),
        ("With email",    n_email,  a_email),
        ("Dispatched",    n_sent,   a_sent),
        ("Delivered",     n_del,    a_del),
        ("Opened",        n_op,     a_op),
        ("Responded",     n_resp,   a_resp),
    ]
    out = []
    for label, n, a in stages:
        out.append({
            "label": label,
            "count": n,
            "amount": round(a, 2),
            "count_pct":  round((n / total_n * 100.0) if total_n else 0.0, 1),
            "amount_pct": round((a / total_a * 100.0) if total_a > 0.0001 else 0.0, 1),
        })
    return out


def _top_disputed(responses: List[Dict[str, Any]],
                  ledger_by_id: Dict[str, Dict[str, Any]],
                  limit: int = 10) -> List[Dict[str, Any]]:
    rows = []
    for r in responses:
        if r.get("decision") != "disputed":
            continue
        L = ledger_by_id.get(r.get("ledger_id", "")) or {}
        our = abs(_f(L.get("closing_balance")))
        their = _f(r.get("their_balance")) if r.get("their_balance") is not None else None
        diff = None if their is None else round(their - our, 2)
        rows.append({
            "ledger_id":   r.get("ledger_id", ""),
            "party":       L.get("name", ""),
            "category":    _category_for(L),
            "our_amount":  round(our, 2),
            "our_dr_cr":   (L.get("dr_cr") or "").upper(),
            "their_amount": None if their is None else round(their, 2),
            "their_dr_cr": r.get("their_dr_cr") or "",
            "diff":        diff,
            "abs_diff":    0.0 if diff is None else abs(diff),
            "reason":      (r.get("reason") or "")[:220],
            "submitted_at": r.get("submitted_at", ""),
        })
    rows.sort(key=lambda x: x["abs_diff"], reverse=True)
    return rows[:limit]


def _top_unresponsive(ledgers: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    """Sent ≥ _STALE_SENT_DAYS ago, still in-flight (no response)."""
    cutoff = _now() - timedelta(days=_STALE_SENT_DAYS)
    rows = []
    for L in ledgers:
        st = L.get("confirmation_status") or ""
        if st not in _IN_FLIGHT:
            continue
        sent_at = _parse_iso(L.get("sent_at"))
        if not sent_at or sent_at > cutoff:
            continue
        days = (_now() - sent_at).days
        rows.append({
            "ledger_id": L.get("ledger_id", ""),
            "party":     L.get("name", ""),
            "category":  _category_for(L),
            "amount":    round(abs(_f(L.get("closing_balance"))), 2),
            "dr_cr":     (L.get("dr_cr") or "").upper(),
            "email":     L.get("email", ""),
            "status":    st,
            "sent_at":   L.get("sent_at", ""),
            "days_pending": days,
        })
    rows.sort(key=lambda x: x["amount"], reverse=True)
    return rows[:limit]


_SUBHEAD_RELEVANT_CATEGORIES = {
    "trade_receivable", "trade_payable", "bank", "unsecured_loans",
}


def _subhead_heatmap(ledgers: List[Dict[str, Any]],
                     reconciled_ids: set,
                     limit: int = 12) -> List[Dict[str, Any]]:
    """Coverage heatmap — only the audit-relevant heads. Subheads belonging to
    'other' ledgers (salaries, duties, taxes, etc.) are excluded because the
    balance-confirmation exercise doesn't apply to them."""
    groups: Dict[str, Dict[str, Any]] = {}
    for L in ledgers:
        cat = _category_for(L)
        if cat not in _SUBHEAD_RELEVANT_CATEGORIES:
            continue
        key = (L.get("parent_group") or "—").strip() or "—"
        g = groups.setdefault(key, {
            "parent_group": key,
            "category":     cat,
            "count": 0,
            "amount": 0.0,
            "audit_count": 0,
            "audit_amount": 0.0,
            "response_count": 0,
            "response_amount": 0.0,
        })
        amt = abs(_f(L.get("closing_balance")))
        g["count"]  += 1
        g["amount"] += amt
        st = _status_bucket(L, reconciled_ids)
        if st in ("confirmed", "reconciled"):
            g["audit_count"]    += 1
            g["audit_amount"]   += amt
            g["response_count"] += 1
            g["response_amount"] += amt
        elif st == "disputed":
            g["response_count"] += 1
            g["response_amount"] += amt
    rows = list(groups.values())
    for g in rows:
        tot_a = g["amount"] if g["amount"] > 0.0001 else 1.0
        tot_n = max(g["count"], 1)
        g["amount"]           = round(g["amount"], 2)
        g["audit_amount"]     = round(g["audit_amount"], 2)
        g["response_amount"]  = round(g["response_amount"], 2)
        g["audit_amount_pct"]    = round(g["audit_amount"]    / tot_a * 100.0, 1)
        g["response_amount_pct"] = round(g["response_amount"] / tot_a * 100.0, 1)
        g["audit_count_pct"]     = round(g["audit_count"]     / tot_n * 100.0, 1)
    rows.sort(key=lambda x: x["amount"], reverse=True)
    return rows[:limit]


def build_analytics(*, run: Dict[str, Any],
                    client: Dict[str, Any],
                    ledgers: List[Dict[str, Any]],
                    responses: List[Dict[str, Any]],
                    comments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble the full dashboard payload."""
    reconciled_ids = _reconciled_ledger_ids(responses, comments)

    # Roll-ups
    by_cat: Dict[str, Dict[str, Any]] = {k: _empty_bucket() for k, _ in CATEGORY_ORDER}
    overall = _empty_bucket()

    for L in ledgers:
        cat = _category_for(L)
        amt = abs(_f(L.get("closing_balance")))
        st  = _status_bucket(L, reconciled_ids)

        for b in (by_cat[cat], overall):
            b["count"]  += 1
            b["amount"] += amt
            b["by_status"][st]["count"]  += 1
            b["by_status"][st]["amount"] += amt

    # Round amounts; compute coverage
    def _finalize(b: Dict[str, Any]):
        b["amount"] = round(b["amount"], 2)
        for s in b["by_status"].values():
            s["amount"] = round(s["amount"], 2)
        b["coverage"] = _coverage(b)
        return b

    overall = _finalize(overall)
    categories = []
    for key, label in CATEGORY_ORDER:
        b = _finalize(by_cat[key])
        b["key"]   = key
        b["label"] = label
        categories.append(b)

    ledger_by_id = {L["ledger_id"]: L for L in ledgers if L.get("ledger_id")}

    return {
        "generated_at": _now().isoformat(),
        "run": {
            "id":          run.get("id", ""),
            "fy":          run.get("fy", ""),
            "as_at_date":  run.get("as_at_date", ""),
            "name":        run.get("name", ""),
            "created_by":  run.get("created_by_name", ""),
        },
        "client": {
            "name":  client.get("name", ""),
            "gstin": client.get("gstin", ""),
        },
        "overall":     overall,
        "categories":  categories,
        "funnel":      _funnel(ledgers),
        "top_disputed":    _top_disputed(responses, ledger_by_id),
        "top_unresponsive": _top_unresponsive(ledgers),
        "subheads":    _subhead_heatmap(ledgers, reconciled_ids),
        "reconciled_count": len(reconciled_ids),
    }
