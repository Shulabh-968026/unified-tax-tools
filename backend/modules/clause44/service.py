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
# ICAI 5-line recon auto-categoriser (Para 79.4).  Each excluded ledger
# the auditor ticks is bucketed into one of four ICAI exclusion classes so
# the recon presents as ICAI prescribes:
#     Total P&L expenditure
#   + Capex additions                            → capex_addback
#   − Non-cash charges                            → non_cash
#   − Schedule III items                          → sch3
#   − Transactions in money / securities          → money
#   − Other exclusions (auditor-driven)           → other
#
# The auditor can override the auto-category per line on the recon screen.
# ─────────────────────────────────────────────────────────────────────────
RECON_BUCKETS = ("capex_addback", "non_cash", "sch3", "money", "other")
_NON_CASH_HINTS = ("deprec", "amortis", "provision for", "fair value", "mtm", "impairment", "write off", "write-off")
_SCH3_HINTS = (
    "salary", "salaries", "wages", "pf ", "epf", "esi", "provident",
    "bonus", "gratuity", "drawing", "dividend declared",
    "sale of land", "sale of building",
)
_MONEY_HINTS = (
    "interest on", "interest paid", "tds ", "tds-", "income tax",
    "invest", "mutual fund", "securities", "share purchase", "share buyback",
    "discount on issue", "bank charges",
)


def categorise_exclusion(name: str, rec: Dict[str, Any] | None = None, group_chains: Dict[str, str] | None = None) -> str:
    """Auto-suggest the ICAI recon bucket for an excluded ledger.  The
    caller (UI) presents this as the default and lets the auditor override.
    """
    rec = rec or {}
    n = (name or "").lower()
    group_parent = (rec.get("groupParent") or rec.get("parentGroup") or "").lower()
    chain = (group_chains or {}).get(group_parent, group_parent) if group_chains else ""
    # Fixed Assets in the excluded list is rare after Slice 6A (we stop
    # suggesting it), but handle it defensively.
    if "fixed asset" in chain or "fixed asset" in group_parent:
        return "capex_addback"
    if any(h in n for h in _NON_CASH_HINTS):
        return "non_cash"
    if any(h in n for h in _SCH3_HINTS):
        return "sch3"
    if any(h in n for h in _MONEY_HINTS):
        return "money"
    return "other"

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
    *,
    exempt_ledgers: set | None = None,
    use_itc_inference: bool = True,
) -> Dict[str, Any]:
    """Classify each expense line into Col 3/4/5/7.

    Cascade (per ICAI, adapted to the JSON we actually have):
      0. `voucherTypeName == "Reverse Charge"`              → Col 7 (RCM flag)
      1. **Input A** — line's ledger is in `exempt_ledgers`  → Col 3
      2. Foreign supplier (party country set & not India)   → Col 7 (import flag)
      3. Party reg type == "composition"                    → Col 4
      4. Party reg type == "regular" AND has GSTIN
         · **Input B** — if `use_itc_inference` and voucher
           carries NO ITC-ledger entry, classify as Col 3
           (presumed exempt supply on a registered vendor)
         · Otherwise                                        → Col 5
      5. Everything else (URD / consumer / blank reg)       → Col 7

    Input A takes precedence over Input B — a ledger tagged as exempt
    will always be Col 3 regardless of vendor ITC behaviour, and the same
    voucher can never be counted twice in Col 3 because classification is
    per-expense-line: once line X is set via Input A, it's final for that
    line only.
    """
    exempt_ledgers = exempt_ledgers or set()

    txns: List[Dict[str, Any]] = []
    by_ledger: Dict[str, Dict[str, float]] = {}
    by_party: Dict[str, Dict[str, Any]] = {}
    # Per-line Col 3 attribution tallies for the disclaimer footer.
    col3_source_totals = {"input_a": 0.0, "input_b": 0.0}

    for v in vouchers:
        entries = v.get("ledgerEntries", []) or []
        exp_lines: List[tuple] = []
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

        vtype = (v.get("voucherTypeName") or "").strip().lower()
        is_rcm = vtype == "reverse charge"
        has_itc = any((e.get("ledger", "") or "") in itc_ledgers for e in entries)
        party_name = v.get("partyLedgerName", "") or ""
        party = party_lookup.get(party_name, {})
        party_gstin = (party.get("partyGSTIN") or "").strip()
        party_reg = ((party.get("gstRegistrationType") or "")).strip().lower()
        party_country = (party.get("country") or "").strip().lower()
        is_import = bool(party_country) and party_country != "india"

        # Per-line classification (Input A wins line-by-line).
        for lname, amt in exp_lines:
            bucket, reason, col3_src = _classify_single_line(
                lname, party_name, party_reg, party_gstin,
                is_rcm=is_rcm, is_import=is_import, has_itc=has_itc,
                exempt_ledgers=exempt_ledgers,
                use_itc_inference=use_itc_inference,
                party_country=party_country,
            )

            if bucket == "col3":
                col3_source_totals[col3_src] = col3_source_totals.get(col3_src, 0.0) + amt

            txns.append({
                "voucher_id": v.get("voucherId", ""),
                "date": v.get("date", ""),
                "voucher_number": v.get("voucherNumber", ""),
                "voucher_type": v.get("voucherTypeName", ""),
                "ledger_name": lname,
                "party_name": party_name,
                "party_gstin": party_gstin,
                "party_reg": party_reg,
                "party_country": party_country,
                "amount": amt,
                "bucket": bucket,
                "reason": reason,
                "is_rcm": is_rcm,
                "is_import": is_import,
                "has_itc_ledger": has_itc,
                "col3_source": col3_src if bucket == "col3" else "",
            })
            row = by_ledger.setdefault(lname, {"col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0})
            row[bucket] += amt
            row["total"] += amt

            # "— Cash / No Party —" synthetic bucket for empty party names.
            p_key = party_name or "— Cash / No Party —"
            prow = by_party.setdefault(p_key, {
                "col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "total": 0.0,
                "party_gstin": party_gstin, "party_reg": party_reg, "vouchers": 0,
            })
            prow[bucket] += amt
            prow["total"] += amt
            if party_gstin:
                prow["party_gstin"] = party_gstin
            if party_reg:
                prow["party_reg"] = party_reg

        # Count each voucher once per party (done after the loop so we
        # don't inflate the count by # of expense lines on the voucher).
        p_key = party_name or "— Cash / No Party —"
        if p_key in by_party:
            by_party[p_key]["vouchers"] += 1

    col3 = sum(t["amount"] for t in txns if t["bucket"] == "col3")
    col4 = sum(t["amount"] for t in txns if t["bucket"] == "col4")
    col5 = sum(t["amount"] for t in txns if t["bucket"] == "col5")
    col7 = sum(t["amount"] for t in txns if t["bucket"] == "col7")
    rcm_total = sum(t["amount"] for t in txns if t.get("is_rcm"))
    import_total = sum(t["amount"] for t in txns if t.get("is_import"))
    summary = {
        "col2_total": col3 + col4 + col5 + col7,
        "col3": col3, "col4": col4, "col5": col5,
        "col6": col3 + col4 + col5, "col7": col7,
        # Memo counters for the report header / disclaimer
        "rcm_total": rcm_total,
        "rcm_vouchers": sum(1 for t in txns if t.get("is_rcm")),
        "import_total": import_total,
        "col3_from_input_a": col3_source_totals.get("input_a", 0.0),
        "col3_from_input_b": col3_source_totals.get("input_b", 0.0),
    }
    return {"summary": summary, "transactions": txns, "by_ledger": by_ledger, "by_party": by_party}


def _classify_single_line(
    lname: str, party_name: str, party_reg: str, party_gstin: str,
    *, is_rcm: bool, is_import: bool, has_itc: bool,
    exempt_ledgers: set, use_itc_inference: bool,
    party_country: str = "",
) -> tuple:
    """Return (bucket, reason, col3_source).  col3_source is 'input_a' |
    'input_b' | '' (non-Col-3 lines)."""
    # 0) RCM — bucketed to Col 7 per team choice (ICAI silent; CAs typically
    # disclose RCM separately).
    if is_rcm:
        return "col7", "RCM voucher — supplier typically unregistered", ""
    # 1) Input A — ledger explicitly tagged as exempt-supply purchase.
    if lname in exempt_ledgers:
        return "col3", f"Ledger '{lname}' tagged as exempt-supply purchase (Input A)", "input_a"
    # 2) Foreign supplier — import.
    if is_import:
        country_label = party_country.title() if party_country else "non-India"
        return (
            "col7",
            f"Foreign supplier '{party_name}' ({country_label}) — import, no Indian GSTIN",
            "",
        )
    # 3) Composition.
    if party_reg == "composition":
        return "col4", f"Party '{party_name}' is Composition dealer", ""
    # 4) Registered vendor.
    if party_reg == "regular" and party_gstin:
        if use_itc_inference and not has_itc:
            return (
                "col3",
                f"Registered vendor '{party_name}' (GSTIN {party_gstin}) "
                f"but no ITC ledger on voucher — presumed exempt supply (Input B, ITC inference)",
                "input_b",
            )
        return "col5", f"Party '{party_name}' is Regular (GSTIN: {party_gstin})", ""
    # 5) URD / Consumer / blank.
    if not party_name:
        return "col7", "No party ledger associated — treated as Unregistered", ""
    return "col7", f"Party '{party_name}' — {party_reg or 'unregistered / no GSTIN'}", ""


def compute_recon_and_filter(
    full_result: Dict[str, Any],
    excluded_set: set,
    *,
    ledgers_xlsx: Dict[str, Dict[str, Any]] | None = None,
    group_chains: Dict[str, str] | None = None,
    exclusion_categories: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Produce the ICAI 5-line recon + filter transactions/by_ledger/by_party.

    Recon math follows Para 79.4::

        Total P&L expenditure
      + Capex additions                      (items in Fixed Assets group)
      − Non-cash charges                     (depreciation, provisions)
      − Schedule III items                   (salary, dividend, land sale…)
      − Money / Securities                   (interest, TDS, investments)
      − Other exclusions                     (residual auditor tick)
      = Reportable expenditure (Col 2)

    `ledgers_xlsx` + `group_chains` feed the auto-categoriser.
    `exclusion_categories` is the auditor's per-line override map
    (ledger name → bucket); missing entries fall back to the
    auto-category.
    """
    ledgers_xlsx = ledgers_xlsx or {}
    group_chains = group_chains or {}
    exclusion_categories = exclusion_categories or {}

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

    # Summary — rebuilt from filtered transactions
    col3 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col3")
    col4 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col4")
    col5 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col5")
    col7 = sum(t["amount"] for t in filtered_txns if t["bucket"] == "col7")
    rcm_total = sum(t["amount"] for t in filtered_txns if t.get("is_rcm"))
    import_total = sum(t["amount"] for t in filtered_txns if t.get("is_import"))
    col3_a = sum(t["amount"] for t in filtered_txns if t.get("col3_source") == "input_a")
    col3_b = sum(t["amount"] for t in filtered_txns if t.get("col3_source") == "input_b")
    summary = {
        "col2_total": col3 + col4 + col5 + col7,
        "col3": col3, "col4": col4, "col5": col5,
        "col6": col3 + col4 + col5, "col7": col7,
        "rcm_total": rcm_total,
        "rcm_vouchers": sum(1 for t in filtered_txns if t.get("is_rcm")),
        "import_total": import_total,
        "col3_from_input_a": col3_a,
        "col3_from_input_b": col3_b,
    }

    # ── ICAI 5-line recon ──────────────────────────────────────────────
    # Split total books (= all classified expenditure before exclusions)
    # into P&L expenditure vs Capex based on ledger group chain.
    pl_total = 0.0
    capex_total = 0.0
    for lname, vals in full_by_ledger.items():
        total = float(vals.get("total", 0) or 0)
        rec = ledgers_xlsx.get(lname, {}) or {}
        group_parent = (rec.get("groupParent") or "").lower()
        chain = group_chains.get(group_parent, group_parent).lower()
        if "fixed asset" in chain or "fixed asset" in group_parent:
            capex_total += total
        else:
            pl_total += total

    # Bucket each excluded ledger using per-line override (auditor) with
    # auto-category fallback. `bucket_lines` groups the line detail by
    # bucket for the UI.
    bucket_lines: Dict[str, List[Dict[str, Any]]] = {b: [] for b in RECON_BUCKETS}
    for l in sorted(excluded_set):
        if l not in full_by_ledger:
            continue
        amt = float(full_by_ledger[l].get("total", 0) or 0)
        if not amt:
            continue
        bucket = exclusion_categories.get(l)
        if bucket not in RECON_BUCKETS:
            bucket = categorise_exclusion(l, ledgers_xlsx.get(l, {}), group_chains)
        bucket_lines[bucket].append({"name": l, "amount": amt, "bucket": bucket})

    bucket_totals = {b: sum(x["amount"] for x in bucket_lines[b]) for b in RECON_BUCKETS}
    # Capex add-back: any excluded FA lines *plus* the capex already inside
    # `capex_total` isn't double-counted — the auditor excluding a FA
    # ledger just moves it from "reportable" into the "+" side of the
    # recon as an explicit add-back.
    subtracted = bucket_totals["non_cash"] + bucket_totals["sch3"] + bucket_totals["money"] + bucket_totals["other"]
    reportable = pl_total + capex_total - subtracted

    # Flat list for backwards-compatibility (old UI / exports).
    excluded_lines_flat = [
        {"name": x["name"], "amount": x["amount"], "bucket": x["bucket"]}
        for bucket in RECON_BUCKETS
        for x in bucket_lines[bucket]
    ]
    excluded_total = sum(x["amount"] for x in excluded_lines_flat)

    return {
        "summary": summary,
        "by_ledger": filtered_by_ledger,
        "by_party": filtered_by_party,
        "transactions": filtered_txns,
        "recon": {
            # ICAI 5-line
            "pl_total": pl_total,
            "capex_total": capex_total,
            "capex_addback_total": bucket_totals["capex_addback"],
            "non_cash_total": bucket_totals["non_cash"],
            "sch3_total": bucket_totals["sch3"],
            "money_total": bucket_totals["money"],
            "other_total": bucket_totals["other"],
            "reportable_total": reportable,
            # Per-bucket line detail (for the recon table UI)
            "non_cash_lines": bucket_lines["non_cash"],
            "sch3_lines": bucket_lines["sch3"],
            "money_lines": bucket_lines["money"],
            "other_lines": bucket_lines["other"],
            "capex_addback_lines": bucket_lines["capex_addback"],
            # Legacy keys kept for backwards-compat with older pages /
            # Excel exports that still read them.
            "total_books": pl_total + capex_total,
            "excluded_lines": excluded_lines_flat,
            "excluded_total": excluded_total,
            "balance": reportable,
        },
    }


def merge_runs_for_consolidation(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"col2_total": 0.0, "col3": 0.0, "col4": 0.0, "col5": 0.0, "col6": 0.0, "col7": 0.0}
    by_ledger: Dict[str, Dict[str, float]] = {}
    by_party: Dict[str, Dict[str, Any]] = {}
    transactions: List[Dict[str, Any]] = []
    excluded_acc: Dict[str, float] = {}
    excluded_bucket: Dict[str, str] = {}
    total_books = 0.0
    pl_total = 0.0
    capex_total = 0.0
    bucket_sums = {"non_cash": 0.0, "sch3": 0.0, "money": 0.0, "other": 0.0, "capex_addback": 0.0}
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
            nm = line["name"]
            excluded_acc[nm] = excluded_acc.get(nm, 0.0) + float(line.get("amount") or 0)
            if line.get("bucket"):
                excluded_bucket[nm] = line["bucket"]
        pl_total += float(recon.get("pl_total") or 0)
        capex_total += float(recon.get("capex_total") or 0)
        for b in ("non_cash", "sch3", "money", "other", "capex_addback"):
            bucket_sums[b] += float(recon.get(f"{b}_total") or 0)
        division_summaries.append({
            "division_id": r.get("division_id"),
            "division_name": r.get("division_name") or "—",
            "run_id": r.get("run_id"),
            "summary": s,
        })

    excluded_lines = [
        {"name": n, "amount": amt, "bucket": excluded_bucket.get(n, "other")}
        for n, amt in sorted(excluded_acc.items())
    ]
    excluded_total = sum(line["amount"] for line in excluded_lines)
    reportable = pl_total + capex_total - (bucket_sums["non_cash"] + bucket_sums["sch3"] + bucket_sums["money"] + bucket_sums["other"])
    return {
        "summary": summary,
        "by_ledger": by_ledger,
        "by_party": by_party,
        "transactions": transactions,
        "recon": {
            "pl_total": pl_total,
            "capex_total": capex_total,
            "non_cash_total": bucket_sums["non_cash"],
            "sch3_total": bucket_sums["sch3"],
            "money_total": bucket_sums["money"],
            "other_total": bucket_sums["other"],
            "capex_addback_total": bucket_sums["capex_addback"],
            "reportable_total": reportable,
            # Legacy keys retained for the old Excel recon template
            "total_books": total_books,
            "excluded_lines": excluded_lines,
            "excluded_total": excluded_total,
            "balance": total_books - excluded_total,
        },
        "division_summaries": division_summaries,
    }
