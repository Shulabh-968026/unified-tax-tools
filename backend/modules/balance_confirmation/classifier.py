"""Tally group → Balance Confirmation category classifier.

Tally exports a `groups[]` master with `name` + `parentGroup`. We walk that
chain to determine if a ledger's parent group eventually rolls up into one of
Tally's reserved top-level groups: Sundry Debtors, Sundry Creditors, Bank
Accounts, or Bank OD A/c.

If the chain doesn't reach a reserved group (custom chart of accounts), we
fall back to keyword matching on the immediate parent group name (creditor /
debtor / bank). Anything still unmatched → "other" — surfaces to UI for the
user to manually re-classify.
"""
from __future__ import annotations
from typing import Any, Dict, List


# Tally reserved top-level groups → our category
TRADE_RECEIVABLE_RESERVED = {"sundry debtors"}
TRADE_PAYABLE_RESERVED    = {"sundry creditors"}
BANK_RESERVED             = {"bank accounts", "bank od a/c"}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def build_group_index(groups: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return {group_name_lower: parent_group_lower} for fast chain walking."""
    return {_norm(g.get("name")): _norm(g.get("parentGroup")) for g in (groups or [])}


def _root_chain(start: str, group_idx: Dict[str, str], max_depth: int = 12) -> List[str]:
    """Walk parent chain from `start` upward; return list of names lower-cased
    (start first). Stops at root (empty parent) or after max_depth to avoid
    accidental cycles in malformed data."""
    chain: List[str] = []
    cur = _norm(start)
    seen = set()
    for _ in range(max_depth):
        if not cur or cur in seen:
            break
        chain.append(cur)
        seen.add(cur)
        cur = group_idx.get(cur, "")
    return chain


def classify_ledger(parent_group: str, group_idx: Dict[str, str]) -> str:
    """Return one of: trade_receivable | trade_payable | bank | other.

    Walks the parent-group chain first (covers nested chart-of-account custom
    groups), then falls back to keyword matching.
    """
    chain = _root_chain(parent_group, group_idx)
    chain_set = set(chain)

    # 1. Reserved-group hit anywhere in the chain
    if chain_set & TRADE_RECEIVABLE_RESERVED:
        return "trade_receivable"
    if chain_set & TRADE_PAYABLE_RESERVED:
        return "trade_payable"
    if chain_set & BANK_RESERVED:
        return "bank"

    # 2. Keyword match on any link in the chain
    blob = " ".join(chain)
    if "creditor" in blob:
        return "trade_payable"
    if "debtor" in blob:
        return "trade_receivable"
    if "bank" in blob:
        return "bank"

    return "other"


def dr_cr_indicator(closing_balance: float) -> str:
    """Tally sign convention: + amount = Credit, - amount = Debit.
    Returns 'dr' / 'cr' / '' (zero balance)."""
    if not closing_balance:
        return ""
    return "dr" if closing_balance < 0 else "cr"
