"""Clause 44 engine: XLSX parser + classification + reconciliation + consolidation merge."""
import io
import re
from typing import Dict, Any, List
import openpyxl
from fastapi import HTTPException

GST_KEYWORDS = ("gst", "input", "cgst", "sgst", "igst")
EXCLUSION_HINT_KEYWORDS = (
    "deprec", "salary", "salaries", "wages", "interest", "pf ", "epf",
    "esi", "provident", "bonus", "gratuity", "income tax", "tds",
    "drawing", "capital", "depreciation",
)

# ─────────────────────────────────────────────────────────────────────────
# ITC suggestion policy  (driven by the `Map to Subhead` column in the
# books XLSX — NOT by Group Parent or ledger-name keywords)
#
# • Ledgers whose subhead matches one of ITC_SUGGEST_SUBHEADS are shown
#   pre-selected on the ITC step.
# • Ledgers whose subhead matches one of ITC_POOL_EXCLUDE_SUBHEADS are
#   hidden from the ITC candidate pool altogether (trade payables /
#   receivables / fixed assets / cash / bank cannot be ITC ledgers).
# • Every other BS-side ledger is shown un-selected so the auditor can
#   search & tick any that the two-subhead heuristic misses.
# ─────────────────────────────────────────────────────────────────────────
ITC_SUGGEST_SUBHEADS = (
    "balance with revenue authorities",
    "statutory dues payable",
)
ITC_POOL_EXCLUDE_SUBHEADS = (
    "trade receivables",
    "trade payables",
    "sundry debtors",
    "sundry creditors",
    "creditors for expenses",
    "creditors for capital goods",
    "fixed assets",
    "cash in hand",
    "cash on hand",
    "cash and cash equivalents",
    "bank accounts",
    "bank balances",
    "bank od",
    "bank overdraft",
)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _subhead_matches(subhead: str, candidates: tuple) -> bool:
    """Case-insensitive + substring match. A ledger's subhead is considered
    a match if any candidate phrase appears inside the (normalised) subhead,
    OR the subhead is fully contained in the candidate (for pluralisation
    variants like 'Trade Payable' vs 'Trade Payables')."""
    s = _norm(subhead)
    if not s:
        return False
    for c in candidates:
        cn = _norm(c)
        if cn in s or s in cn:
            return True
    return False


def _fields_match(candidates: tuple, *fields: str) -> bool:
    """Match any of the given classification fields (subhead, groupParent,
    head) against the candidate list — used for the ITC exclude pool so
    granular Tally subheads like 'Buildings' / 'Furniture' still get caught
    by a Fixed-Assets rule on their parent group."""
    for f in fields:
        if _subhead_matches(f, candidates):
            return True
    return False

# Period validation: accepts 2023-24, 2023-2024, FY 2023-24, Q1 FY2023-24, H1 2023-24, etc.
PERIOD_REGEX = re.compile(
    r"^(?:(?:Q[1-4]|H[12])[\s-]?)?(?:FY[\s-]?)?\d{4}[-/]\d{2,4}$",
    re.IGNORECASE,
)


def is_valid_period(period: str) -> bool:
    if not period or len(period) > 30:
        return False
    return bool(PERIOD_REGEX.match(period.strip()))


def _is_gst_input_ledger(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in GST_KEYWORDS)


def _is_exclusion_hint(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in EXCLUSION_HINT_KEYWORDS)


def parse_ledger_xlsx(content: bytes) -> Dict[str, Dict[str, Any]]:
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}
    header = [str(h or "").strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    needed = ["Ledger Name", "BS or PL"]
    for n in needed:
        if n not in idx:
            raise HTTPException(status_code=400, detail=f"Excel missing column: {n}")
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows[1:]:
        name = (r[idx["Ledger Name"]] or "")
        if isinstance(name, str):
            name = name.replace("_x000D_", "").replace("\r", "").strip()
        if not name:
            continue

        def col(c):
            i = idx.get(c, -1)
            if i < 0:
                return None
            return r[i]

        rec = {
            "name": name,
            "openingBalance": col("Opening Balance (Dr)/Cr"),
            "totalDebit": col("Total Debit"),
            "totalCredit": col("Total Credit"),
            "closingBalance": col("Closing Balance (Dr)/Cr"),
            "bsOrPl": (r[idx["BS or PL"]] or "").strip() if r[idx["BS or PL"]] else "",
            "groupParent": ((col("Group Parent") or "")).strip() if col("Group Parent") else "",
            "subhead": ((col("Map to Subhead") or "")).strip() if col("Map to Subhead") else "",
            "head": ((col("Head") or "")).strip() if col("Head") else "",
        }
        out[name] = rec
    return out


def build_group_chain(groups: List[Dict[str, Any]]) -> Dict[str, str]:
    by_name = {g.get("name", ""): g for g in groups}
    cache: Dict[str, str] = {}

    def chain(name: str, depth: int = 0) -> str:
        if not name or depth > 20:
            return ""
        if name in cache:
            return cache[name]
        g = by_name.get(name)
        parent = (g or {}).get("parentGroup", "") if g else ""
        c = (parent + " > " + chain(parent, depth + 1)) if parent else ""
        full = (name + (" > " + c if c else "")).lower()
        cache[name] = full
        return full

    return {n: chain(n) for n in by_name}


def is_capex_ledger(ledger: Dict[str, Any], group_chains: Dict[str, str]) -> bool:
    pg = ledger.get("parentGroup", "") or ""
    chain = group_chains.get(pg, pg.lower())
    return "fixed asset" in chain


def compute_suggestions(ledgers_xlsx: Dict[str, Dict[str, Any]], ledgers_json: List[Dict[str, Any]]):
    """Build the two pools the Mapping screen needs.

    ITC candidate pool  — every BS-side ledger except those whose subhead is
    in `ITC_POOL_EXCLUDE_SUBHEADS` (trade payables/receivables/fixed assets/
    cash/bank).  Within this pool, `suggested=True` is set only for ledgers
    whose subhead matches one of `ITC_SUGGEST_SUBHEADS` (Balance with
    Revenue Authorities / Statutory Dues Payable).  Everything else is
    shown un-ticked but searchable.

    Expenditure-exclusion pool — every P&L ledger, with `suggested=True`
    for those whose NAME hints at non-supply items (salaries, PF, interest,
    depreciation, etc.).
    """
    itc_candidates = []
    for name, rec in ledgers_xlsx.items():
        if rec.get("bsOrPl") != "B":
            continue
        subhead = rec.get("subhead", "") or ""
        group_parent = rec.get("groupParent", "") or ""
        head = rec.get("head", "") or ""
        # Exclude check walks subhead + groupParent + head so Tally's
        # granular subheads (Buildings, Furniture, etc.) still get caught
        # by the Fixed-Assets rule on their parent group.
        if _fields_match(ITC_POOL_EXCLUDE_SUBHEADS, subhead, group_parent, head):
            continue
        itc_candidates.append({
            "name": name,
            "groupParent": group_parent,
            "subhead": subhead,
            "closingBalance": rec.get("closingBalance"),
            # Pre-selection is still strictly driven by the two target subheads
            # — group-parent ambiguity must not auto-select an ITC ledger.
            "suggested": _subhead_matches(subhead, ITC_SUGGEST_SUBHEADS),
        })

    pl_ledgers = []
    for name, rec in ledgers_xlsx.items():
        if rec.get("bsOrPl") != "P":
            continue
        pl_ledgers.append({
            "name": name,
            "groupParent": rec.get("groupParent", ""),
            "subhead": rec.get("subhead", ""),
            "closingBalance": rec.get("closingBalance"),
            "suggested": _is_exclusion_hint(name),
        })

    return {"itc_candidates": itc_candidates, "pl_ledgers": pl_ledgers}


def determine_expenditure_ledgers(
    ledgers_xlsx: Dict[str, Dict[str, Any]],
    ledgers_json: List[Dict[str, Any]],
    group_chains: Dict[str, str],
    excluded: set,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name, rec in ledgers_xlsx.items():
        if name in excluded:
            continue
        try:
            cb_val = float(rec.get("closingBalance") or 0)
        except (TypeError, ValueError):
            cb_val = 0.0
        if rec.get("bsOrPl") == "P" and cb_val < 0:
            out[name] = {"reason": "P&L ledger with debit closing balance (Expenditure)"}

    for ledger in ledgers_json:
        name = ledger.get("name", "")
        if not name or name in excluded:
            continue
        if is_capex_ledger(ledger, group_chains):
            out[name] = {"reason": "Capital Expenditure (Fixed Assets group)"}

    return out


def classify_vouchers(
    vouchers: List[Dict[str, Any]],
    expenditure_ledgers: Dict[str, Dict[str, Any]],
    itc_ledgers: set,
    party_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    txns: List[Dict[str, Any]] = []
    by_ledger: Dict[str, Dict[str, float]] = {}
    by_party: Dict[str, Dict[str, Any]] = {}

    for v in vouchers:
        entries = v.get("ledgerEntries", []) or []
        exp_lines = []
        for e in entries:
            lname = e.get("ledger", "")
            try:
                amt = float(e.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if lname in expenditure_ledgers and amt < 0:
                exp_lines.append((lname, abs(amt)))
        if not exp_lines:
            continue

        itc_hits = [e.get("ledger", "") for e in entries if e.get("ledger", "") in itc_ledgers]
        party_name = v.get("partyLedgerName", "") or ""
        party = party_lookup.get(party_name, {})
        party_gstin = (party.get("partyGSTIN") or "").strip()
        party_reg = (party.get("gstRegistrationType") or "").strip()

        if itc_hits:
            bucket = "col5"
            reason = f"ITC ledger '{itc_hits[0]}' present in voucher"
        elif party_reg.lower() == "composition":
            bucket = "col4"
            reason = f"Party '{party_name}' is Composition dealer"
        elif party_gstin and party_reg.lower() not in ("unregistered", "consumer"):
            bucket = "col3"
            reason = f"Party '{party_name}' is registered (GSTIN: {party_gstin}) — Exempt supply"
        else:
            bucket = "col7"
            if not party_name:
                reason = "No party ledger associated — Unregistered"
            elif not party_gstin:
                reason = f"Party '{party_name}' has no GSTIN — Unregistered"
            else:
                reason = f"Party '{party_name}' marked as {party_reg or 'Unregistered'}"

        # Party-wise bucket key — empty party name collapses to "— Cash / No Party —"
        p_key = party_name or "— Cash / No Party —"

        for lname, amt in exp_lines:
            txns.append({
                "voucher_id": v.get("voucherId", ""),
                "date": v.get("date", ""),
                "voucher_number": v.get("voucherNumber", ""),
                "voucher_type": v.get("voucherTypeName", ""),
                "ledger_name": lname,
                "party_name": party_name,
                "party_gstin": party_gstin,
                "party_reg": party_reg,
                "amount": amt,
                "bucket": bucket,
                "reason": reason,
            })
            row = by_ledger.setdefault(lname, {"col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0})
            row[bucket] += amt
            row["total"] += amt

            prow = by_party.setdefault(p_key, {
                "col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0,
                "party_gstin": party_gstin, "party_reg": party_reg, "vouchers": 0,
            })
            prow[bucket] += amt
            prow["total"] += amt
            # Most-recent GSTIN / reg type wins — values are tied to party master
            if party_gstin:
                prow["party_gstin"] = party_gstin
            if party_reg:
                prow["party_reg"] = party_reg

        # Count each voucher once per party (done after the loop so we don't
        # inflate the count by # of expense lines on the voucher).
        if p_key in by_party:
            by_party[p_key]["vouchers"] += 1

    col3 = sum(t["amount"] for t in txns if t["bucket"] == "col3")
    col4 = sum(t["amount"] for t in txns if t["bucket"] == "col4")
    col5 = sum(t["amount"] for t in txns if t["bucket"] == "col5")
    col7 = sum(t["amount"] for t in txns if t["bucket"] == "col7")
    summary = {
        "col2_total": col3 + col4 + col5 + col7,
        "col3": col3, "col4": col4, "col5": col5,
        "col6": col3 + col4 + col5, "col7": col7,
    }
    return {"summary": summary, "transactions": txns, "by_ledger": by_ledger, "by_party": by_party}


def compute_recon_and_filter(full_result: Dict[str, Any], excluded_set: set) -> Dict[str, Any]:
    full_by_ledger: Dict[str, Dict[str, float]] = full_result["by_ledger"]
    full_txns: List[Dict[str, Any]] = full_result["transactions"]

    filtered_by_ledger = {l: v for l, v in full_by_ledger.items() if l not in excluded_set}
    filtered_txns = [t for t in full_txns if t["ledger_name"] not in excluded_set]

    # Re-build by_party from the filtered transactions so excluded-ledger
    # amounts don't leak into the party breakup.
    filtered_by_party: Dict[str, Dict[str, Any]] = {}
    voucher_seen: Dict[str, set] = {}
    for t in filtered_txns:
        p_key = t.get("party_name") or "— Cash / No Party —"
        row = filtered_by_party.setdefault(p_key, {
            "col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0,
            "party_gstin": t.get("party_gstin", "") or "",
            "party_reg": t.get("party_reg", "") or "",
            "vouchers": 0,
        })
        row[t["bucket"]] += t["amount"]
        row["total"] += t["amount"]
        if t.get("party_gstin"):
            row["party_gstin"] = t["party_gstin"]
        if t.get("party_reg"):
            row["party_reg"] = t["party_reg"]
        seen = voucher_seen.setdefault(p_key, set())
        if t.get("voucher_id") and t["voucher_id"] not in seen:
            seen.add(t["voucher_id"])
            row["vouchers"] += 1

    col3 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col3")
    col4 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col4")
    col5 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col5")
    col7 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col7")
    summary = {
        "col2_total": col3 + col4 + col5 + col7,
        "col3": col3, "col4": col4, "col5": col5,
        "col6": col3 + col4 + col5, "col7": col7,
    }
    total_books = sum((v.get("total", 0) or 0) for v in full_by_ledger.values())
    excluded_lines = []
    for l in sorted(excluded_set):
        if l in full_by_ledger:
            amt = full_by_ledger[l].get("total", 0) or 0
            if amt:
                excluded_lines.append({"name": l, "amount": amt})
    excluded_total = sum(line["amount"] for line in excluded_lines)
    return {
        "summary": summary,
        "by_ledger": filtered_by_ledger,
        "by_party": filtered_by_party,
        "transactions": filtered_txns,
        "recon": {
            "total_books": total_books,
            "excluded_lines": excluded_lines,
            "excluded_total": excluded_total,
            "balance": total_books - excluded_total,
        },
    }


def merge_runs_for_consolidation(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"col2_total": 0.0, "col3": 0.0, "col4": 0.0, "col5": 0.0, "col6": 0.0, "col7": 0.0}
    by_ledger: Dict[str, Dict[str, float]] = {}
    by_party: Dict[str, Dict[str, Any]] = {}
    transactions: List[Dict[str, Any]] = []
    excluded_acc: Dict[str, float] = {}
    total_books = 0.0
    division_summaries: List[Dict[str, Any]] = []

    for r in runs:
        s = r.get("summary") or {}
        for k in summary:
            summary[k] += float(s.get(k) or 0)
        for lname, vals in (r.get("by_ledger") or {}).items():
            row = by_ledger.setdefault(lname, {"col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0})
            for k, v in vals.items():
                row[k] = (row.get(k, 0.0) or 0.0) + float(v or 0)
        for pname, vals in (r.get("by_party") or {}).items():
            row = by_party.setdefault(pname, {
                "col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0,
                "party_gstin": vals.get("party_gstin", "") or "",
                "party_reg": vals.get("party_reg", "") or "",
                "vouchers": 0,
            })
            for k in ("col3", "col4", "col5", "col7", "total"):
                row[k] = (row.get(k, 0.0) or 0.0) + float(vals.get(k) or 0)
            row["vouchers"] += int(vals.get("vouchers") or 0)
            if vals.get("party_gstin"):
                row["party_gstin"] = vals["party_gstin"]
            if vals.get("party_reg"):
                row["party_reg"] = vals["party_reg"]
        for t in (r.get("transactions") or []):
            tt = dict(t)
            tt["division_name"] = r.get("division_name") or "—"
            transactions.append(tt)
        recon = r.get("recon") or {}
        total_books += float(recon.get("total_books") or 0)
        for line in recon.get("excluded_lines") or []:
            excluded_acc[line["name"]] = excluded_acc.get(line["name"], 0.0) + float(line.get("amount") or 0)
        division_summaries.append({
            "division_id": r.get("division_id"),
            "division_name": r.get("division_name") or "—",
            "run_id": r.get("run_id"),
            "summary": s,
        })

    excluded_lines = [{"name": n, "amount": amt} for n, amt in sorted(excluded_acc.items())]
    excluded_total = sum(line["amount"] for line in excluded_lines)
    return {
        "summary": summary,
        "by_ledger": by_ledger,
        "by_party": by_party,
        "transactions": transactions,
        "recon": {
            "total_books": total_books,
            "excluded_lines": excluded_lines,
            "excluded_total": excluded_total,
            "balance": total_books - excluded_total,
        },
        "division_summaries": division_summaries,
    }
