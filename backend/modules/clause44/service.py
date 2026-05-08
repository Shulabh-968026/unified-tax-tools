"""Clause 44 engine: XLSX parser + classification + reconciliation + consolidation merge."""
import io
import re
from typing import Dict, Any, List
import openpyxl
from fastapi import HTTPException

GST_KEYWORDS = ("gst", "input", "cgst", "sgst", "igst")

# Release 4.4.4 — Penal / statutory interest is a Sch III no-supply
# (Col 8 exclusion).  Pure financing interest / discount on loans /
# deposits / advances is an *exempt* supply (Col 3 / Input A) per
# Schedule III + GST Exemption Notification 12/2017-CT entry 27, NOT
# an exclusion.  We split the universe accordingly.
_PENAL_INTEREST_PATTERNS = (
    "interest on income tax", "interest on advance tax",
    "interest on tds", "interest on tcs",
    "interest on gst", "interest on cgst", "interest on sgst",
    "interest on igst", "interest on professional tax",
    "interest on service tax", "interest u/s ",
    "penal interest", "penalty", "late fee", "late fees",
    "interest on late",
)

EXCLUSION_HINT_KEYWORDS = (
    "deprec", "salary", "salaries", "wages", "pf ", "epf",
    "esi", "provident", "bonus", "gratuity", "income tax", "tds",
    "drawing", "depreciation",
    # `capital` was too greedy ("Working Capital Loan", "Capital Goods
    # Repairs") — narrowed to proprietor-style capital accounts only.
    "capital a/c", "capital account",
    *_PENAL_INTEREST_PATTERNS,
)


def _is_interest_or_discount_on_loans(name: str) -> bool:
    """True when the ledger name reads like financing interest / discount
    on loans / deposits / advances (i.e. exempt supply per Sch III).
    Excludes penal-interest patterns explicitly so Income-Tax / TDS /
    GST penalties don't leak into Input A.
    """
    n = (name or "").lower()
    if any(p in n for p in _PENAL_INTEREST_PATTERNS):
        return False
    if "interest" in n:
        return True
    # Discount-on-loans patterns (bill-discounting, LC-discounting, etc.).
    return any(k in n for k in (
        "bill discount", "discount on bill", "discount on loan",
        "lc discount", "discount on advance",
    ))

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


_INPUT_SYNONYMS_NAME = ("itc", "cenvat", "input tax credit")


# ─────────────────────────────────────────────────────────────────────────
# Release 4.4.6 — Voucher-usage NEGATIVE list.  These patterns identify
# BS-side ledgers that *do* touch purchase vouchers (TDS withheld on
# contractor / professional bills, TCS collected on sales, advance-tax
# clearings, bank-charge GST, statutory provisions) but are NOT input
# tax credit.  When a ledger matches one of these, the voucher-usage
# upgrade `other → input` is suppressed so it stays at `kind="other"`
# and is never auto-pre-ticked.
#
# The block applies ONLY to the usage upgrade — name-based "input" /
# "output" detection still wins.  So a ledger called `Input TDS Cr`
# (rare but possible) would still be tagged input via the name signal.
# ─────────────────────────────────────────────────────────────────────────
_USAGE_BLOCK_NAME_PATTERNS = (
    "tds", "tcs", "advance tax", "income tax", "professional tax",
    "late fee", "late fees", "penalty", "penal interest",
    "interest on",
)
_USAGE_BLOCK_GROUP_PATTERNS = (
    "bank accounts", "bank account",
    "advance taxes", "advance tax",
    "provisions",
)


def _is_blocked_from_usage_upgrade(name: str, group_parent: str) -> bool:
    """True when a ledger should NOT be upgraded to ``input`` via voucher-
    usage inference even if it appears on ≥ N purchase vouchers.

    Implements the auditor-curated negative list (Bucket A from the
    Mapping Snapshot review): TDS / TCS / Advance-Tax / Bank-charge GST
    / penal-interest ledgers naturally touch purchase vouchers but are
    statutory deductions, not ITC.

    Detection layers:
      1. Name contains a TDS / TCS / advance-tax / penal-interest token.
      2. Name matches the bank-charge-GST shape: contains "bank" AND
         (one of "gst", "charge", "charges").
      3. Group parent is a withholding-tax / bank / provisions bucket.
    """
    n = (name or "").lower()
    g = (group_parent or "").lower()
    if any(p in n for p in _USAGE_BLOCK_NAME_PATTERNS):
        return True
    if "bank" in n and any(k in n for k in ("gst", "charge", "charges")):
        return True
    if any(p in g for p in _USAGE_BLOCK_GROUP_PATTERNS):
        return True
    return False


def _alnum_lower(s: str) -> str:
    """Collapse a string to lowercase alphanumerics only.  Lets us match
    `IN PUT`, `In-Put`, `IN_PUT` etc. as `input` — real-world Tally data
    has all of these variants depending on who keyed in the ledger name.
    """
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _classify_itc_kind(name: str, subhead: str, group_parent: str) -> tuple:
    """Tag an ITC candidate by *name signal* as 'input' (typical Col 5
    marker), 'output' (sales-side — should NOT drive Col 5 inference) or
    'other' (neutral, awaits voucher-usage inference downstream).

    Returns ``(kind, source)`` where ``source`` records *why* the
    classifier landed where it did so the UI can show a provenance chip:
        - ``"name"``   → the ledger name itself contained the marker
        - ``"group"``  → the parent group name contained the marker
        - ``"subhead"``→ the books-XLSX subhead contained the marker
        - ``""``       → no name-based signal (kind = 'other')

    Multi-signal upgrade (Release 3.2):
      * Whitespace-collapsed comparison so `SGST IN PUT` is recognised.
      * `parentGroup` and `subhead` are checked alongside the name —
        Tally users very commonly file ITC ledgers under groups like
        ``INPUT CREDIT`` or ``Defrerred Input Credit`` regardless of how
        the leaf ledger is named.
      * `output` always wins when present anywhere — sales-side ledgers
        must never be auto-treated as ITC markers.
    """
    n = _alnum_lower(name)
    g = _alnum_lower(group_parent)
    s = _alnum_lower(subhead)

    # 1) Output wins unambiguously if present in ANY of the three signals.
    if "output" in n:
        return "output", "name"
    if "output" in g:
        return "output", "group"
    if "output" in s:
        return "output", "subhead"

    # 2) Input — direct token match
    if "input" in n:
        return "input", "name"
    # 3) Input — alt-name on ledger
    if any(k.replace(" ", "") in n for k in _INPUT_SYNONYMS_NAME):
        return "input", "name"
    # 4) Input — group / subhead signal
    if "input" in g or "rcminput" in g:
        return "input", "group"
    if "input" in s or "rcminput" in s:
        return "input", "subhead"

    return "other", ""


def compute_voucher_usage_kinds(
    candidates: List[Dict[str, Any]],
    vouchers: List[Dict[str, Any]],
    *,
    min_appearances: int = 3,
    dominance_ratio: float = 3.0,
) -> Dict[str, Dict[str, Any]]:
    """**Voucher-usage classifier (Release 3.2 / option B).**

    Walks every voucher and tallies, per ledger:
      - ``n_purchase``  : appearances on Purchase / Debit Note / Journal-
        purchase vouchers (the universe where ITC is *availed*)
      - ``n_sales``     : appearances on Sales / Credit Note vouchers
        (the universe where Output tax fires)
      - ``n_voucher``   : total vouchers touched

    Scores each ledger:
      - 'input'  if ``n_purchase ≥ min_appearances`` and dominant over
        sales by ``dominance_ratio``.
      - 'output' if ``n_sales ≥ min_appearances`` and dominant over
        purchases by ``dominance_ratio``.
      - 'neutral' otherwise (mixed or dormant — let the name signal lead).

    This is naming-agnostic: even a ledger called ``Tax-Cr-Misc-A2`` will
    be auto-flagged ``input`` if it consistently fires on purchase
    vouchers.  Critical for large datasets with bespoke client naming.
    """
    cand_names = {c["name"] for c in candidates}
    counters: Dict[str, Dict[str, int]] = {
        n: {"n_purchase": 0, "n_sales": 0, "n_voucher": 0}
        for n in cand_names
    }
    PURCHASE_TYPES = ("purchase", "debit note", "purchase order")
    SALES_TYPES = ("sales", "credit note")

    for v in vouchers:
        vtype = (v.get("voucherTypeName") or "").strip().lower()
        is_purchase = any(k in vtype for k in PURCHASE_TYPES) and "credit note" not in vtype
        is_sales = any(k in vtype for k in SALES_TYPES) and "debit note" not in vtype
        seen_in_voucher: set = set()
        for e in v.get("ledgerEntries", []) or []:
            lname = e.get("ledger", "")
            if lname not in cand_names:
                continue
            seen_in_voucher.add(lname)
        for lname in seen_in_voucher:
            c = counters[lname]
            c["n_voucher"] += 1
            if is_purchase:
                c["n_purchase"] += 1
            elif is_sales:
                c["n_sales"] += 1

    out: Dict[str, Dict[str, Any]] = {}
    for name, c in counters.items():
        np_, ns = c["n_purchase"], c["n_sales"]
        kind = "neutral"
        if np_ >= min_appearances and np_ >= dominance_ratio * max(ns, 1):
            kind = "input"
        elif ns >= min_appearances and ns >= dominance_ratio * max(np_, 1):
            kind = "output"
        out[name] = {**c, "usage_kind": kind}
    return out


def compute_suggestions(
    ledgers_xlsx: Dict[str, Dict[str, Any]],
    ledgers_json: List[Dict[str, Any]],
    vouchers: List[Dict[str, Any]] | None = None,
):
    """Build the two pools the Mapping screen needs.

    ITC candidate pool  — every BS-side ledger except those whose subhead is
    in `ITC_POOL_EXCLUDE_SUBHEADS` (trade payables/receivables/fixed assets/
    cash/bank).  Each candidate carries:
      * ``kind``         ∈ {input, output, other} — final merged signal.
      * ``kind_source``  ∈ {name, group, subhead, usage, ""} — provenance
        chip for the UI ("why did the engine think this was input?").
      * ``name_kind``    — what the *name* heuristic alone said.
      * ``usage_kind``   — what voucher-walking inferred (input/output/
        neutral) — only present when ``vouchers`` is supplied.
      * ``n_purchase`` / ``n_sales`` / ``n_voucher`` — usage telemetry the
        UI can render as a "fires on N purchase vouchers" chip.

    Pre-selection rule (`suggested=True`) — fires when the merged kind is
    ``"input"`` AND any one of these holds:
      (a) the books-XLSX subhead matches one of ``ITC_SUGGEST_SUBHEADS``
          (legacy strict path), OR
      (b) voucher-usage tagged this ledger as input — even on bespoke
          client naming the engine still auto-detects when the ledger is
          actually used on purchase vouchers.

    Output ledgers stay in the candidate pool but are never pre-ticked.
    """
    # Build the candidate skeleton — **union** of XLSX-mapped ledgers and
    # JSON-only ledgers (Release 3.2 / fix-up).  The XLSX may not have a
    # row for every BS-side ledger Tally exported (the user maps only
    # what they care about), but ITC ledgers can lurk in the JSON-only
    # set.  We therefore iterate every JSON ledger marked ``bsOrPnl=='B'``
    # and merge the XLSX record on top when present, so the candidate
    # carries the auditor's subhead mapping but is *never gated* on it.
    skeleton = []
    seen: set = set()

    def _admit(name, subhead, group_parent, head):
        """Decide if a BS-side ledger belongs in the ITC candidate pool.

        Default: filter out trade payables / receivables / fixed assets /
        cash / bank (they can never be ITC ledgers).

        **Override** (Release 3.2 fix-up): when the *name* or *parent
        group* clearly signals input/output (e.g. ``INPUT CREDIT`` parent
        group, ``Input CGST`` name pattern, ``OUTPUT CREDIT`` group), we
        keep the ledger even if the auditor mis-mapped its subhead to
        ``Sundry Debtors`` / ``Trade Receivables`` in the books XLSX.
        Real-world books frequently have this mis-mapping because Tally
        files Input/Output GST ledgers under generic 'Trade ...' heads.
        """
        nk, src = _classify_itc_kind(name, subhead, group_parent)
        # Strong signal from name OR group → always admit.
        if nk in ("input", "output") and src in ("name", "group"):
            return True, nk, src
        # No strong signal → defer to the legacy exclude filter.
        if _fields_match(ITC_POOL_EXCLUDE_SUBHEADS, subhead, group_parent, head):
            return False, nk, src
        return True, nk, src

    # 1. Start from the JSON ledgers (authoritative on what exists).
    for jl in (ledgers_json or []):
        name = jl.get("name", "")
        if not name or name in seen:
            continue
        bs_json = (jl.get("bsOrPnl") or "").strip().upper()
        if bs_json not in ("B", "P", ""):
            bs_json = ""
        rec = ledgers_xlsx.get(name) or {}
        bs_xlsx = (rec.get("bsOrPl") or "").strip().upper()
        bsorpl = bs_xlsx or bs_json
        if bsorpl != "B":
            continue
        subhead = (rec.get("subhead") or "") or ""
        group_parent = (rec.get("groupParent") or "") or jl.get("parentGroup", "") or ""
        head = (rec.get("head") or "") or ""
        admit, name_kind, kind_source = _admit(name, subhead, group_parent, head)
        if not admit:
            continue
        skeleton.append({
            "name": name,
            "groupParent": group_parent,
            "subhead": subhead,
            "head": head,
            "closingBalance": rec.get("closingBalance") if rec else jl.get("closingBalance"),
            "name_kind": name_kind,
            "kind_source": kind_source,
        })
        seen.add(name)
    # 2. Then catch any XLSX-only ledgers that didn't appear in the JSON.
    for name, rec in ledgers_xlsx.items():
        if name in seen or rec.get("bsOrPl") != "B":
            continue
        subhead = rec.get("subhead", "") or ""
        group_parent = rec.get("groupParent", "") or ""
        head = rec.get("head", "") or ""
        admit, name_kind, kind_source = _admit(name, subhead, group_parent, head)
        if not admit:
            continue
        skeleton.append({
            "name": name,
            "groupParent": group_parent,
            "subhead": subhead,
            "head": head,
            "closingBalance": rec.get("closingBalance"),
            "name_kind": name_kind,
            "kind_source": kind_source,
        })
        seen.add(name)

    # Voucher-usage detection (option B) — only if vouchers were passed.
    usage_map: Dict[str, Dict[str, Any]] = {}
    if vouchers:
        usage_map = compute_voucher_usage_kinds(skeleton, vouchers)

    itc_candidates = []
    for c in skeleton:
        usage = usage_map.get(c["name"], {})
        usage_kind = usage.get("usage_kind", "neutral")
        n_purchase = usage.get("n_purchase", 0)
        n_sales = usage.get("n_sales", 0)
        n_voucher = usage.get("n_voucher", 0)

        # Merge name-kind with usage-kind.
        # Rule: name signal is authoritative when it's not 'other'; the
        # usage signal only fires for 'other'-named ledgers (the "unknown"
        # bucket where naming gives us nothing).  This keeps Output-named
        # ledgers from ever being upgraded to Input via voucher counts.
        kind = c["name_kind"]
        kind_source = c["kind_source"]
        # Release 4.4.6 — block usage upgrade for TDS / TCS / advance-tax
        # / bank-charge GST patterns (auditor-curated negative list).
        usage_blocked = (
            c["name_kind"] == "other"
            and _is_blocked_from_usage_upgrade(c["name"], c["groupParent"])
        )
        if kind == "other" and usage_kind in ("input", "output") and not usage_blocked:
            kind = usage_kind
            kind_source = "usage"

        # Conflict flag: name says 'input' but vouchers don't back it up
        # AND the ledger never appeared on a purchase voucher.  We still
        # honour the name (auditor sees the chip), but expose the conflict
        # so the UI can show a soft "looks unused on purchases" advisory.
        usage_conflict = (
            c["name_kind"] == "input"
            and n_voucher > 0
            and n_purchase == 0
            and n_sales > 0
        )

        # Pre-tick: legacy subhead match OR voucher-usage match.
        suggested = (
            kind == "input"
            and (
                _subhead_matches(c["subhead"], ITC_SUGGEST_SUBHEADS)
                or usage_kind == "input"
            )
        )

        itc_candidates.append({
            "name": c["name"],
            "groupParent": c["groupParent"],
            "subhead": c["subhead"],
            "closingBalance": c["closingBalance"],
            "kind": kind,
            "kind_source": kind_source,
            "name_kind": c["name_kind"],
            "usage_kind": usage_kind if vouchers else None,
            "n_purchase": n_purchase,
            "n_sales": n_sales,
            "n_voucher": n_voucher,
            "usage_conflict": usage_conflict,
            "suggested": suggested,
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


# ─────────────────────────────────────────────────────────────────────────
# Release 4.4 — Three-pool model.  Replaces the heuristic-gated candidate
# pools with structural rules derived from the AssureAI ledger-mapping
# Head + Subhead taxonomy (auditor-curated, reliable — never reads Tally
# Group Parent which varies wildly across clients / firms).
#
# Pool 1 · Exempt Purchases  — bsOrPl = 'P'
#                              AND head ∉ {Revenue from Operations, Other Income}
# Pool 2 · ITC Ledgers       — bsOrPl = 'B' AND subhead ∈ ITC_SUBHEAD_DEFAULTS
#                              ("Show all BS-side ledgers" toggle on the UI
#                               flips this to bsOrPl = 'B' only)
# Pool 3 · Exclusions        — head ∉ {Revenue from Operations, Other Income}
#                              AND ( bsOrPl = 'P' OR
#                                    (bsOrPl = 'B' AND head ∈ FA_HEADS) )
# ─────────────────────────────────────────────────────────────────────────
_REVENUE_HEADS_EXCLUDE = {"revenue from operations", "other income"}
_FA_HEADS = {"property, plant and equipment", "intangible fixed assets"}
# Schedule III subheads where Input / Output GST naturally lands.  Hard-
# coded for now — Release 4.5 will surface this as a per-firm config.
ITC_SUBHEAD_DEFAULTS = (
    "balance with revenue authorities",   # Input GST credit
    "statutory dues payable",             # Output GST liability (auditors
                                           # sometimes mark these as ITC
                                           # markers for cross-checking)
)


def _norm(s: str) -> str:
    """Normalise a free-form mapping value for case-insensitive comparison."""
    return (s or "").strip().lower()


def _is_exempt_hint(name: str) -> bool:
    """Best-guess pre-tick for the Exempt Purchases pool — flags ledgers
    whose name strongly suggests an exempt-supply purchase: petroleum,
    alcohol, tobacco, life-insurance premium, **plus financing
    interest / discount on loans / deposits / advances** (exempt supply
    per GST Notification 12/2017-CT entry 27 — see ICAI Para 79.13).

    Penal interest on tax dues is excluded explicitly via
    `_is_interest_or_discount_on_loans`.
    """
    n = (name or "").lower()
    EXEMPT_HINTS = (
        "petrol", "diesel", "alcoh", "liquor", "spirit", "tobacco",
        "life insurance", "insurance premium",
    )
    if any(h in n for h in EXEMPT_HINTS):
        return True
    return _is_interest_or_discount_on_loans(name)


def compute_pools(
    ledgers_xlsx: Dict[str, Dict[str, Any]],
    ledgers_json: List[Dict[str, Any]],
    vouchers: List[Dict[str, Any]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build the three independent ledger pools the Clause 44 stepper
    consumes.  Each row carries: ``name, subhead, group_parent, head,
    closing_balance, suggested``.  The ITC pool (and the
    ``itc_ledgers_all_bs`` companion array used by the "Show all BS-side"
    toggle) additionally carry the name/group/voucher-usage classifier
    so the existing kind-tinted UI keeps working.

    Pre-tick (``suggested=True``) preserves the existing heuristics —
    ``_is_exclusion_hint`` for exclusions (plus FA heads auto-tick),
    ``_is_exempt_hint`` for exempt purchases, name/group/subhead/voucher
    -usage merge for ITC.

    All comparisons are case- and whitespace-insensitive.
    """
    # Index every ledger by name — XLSX-mapped + JSON-only, XLSX wins when
    # both have data.  Surfaces every ledger Tally exported even when the
    # auditor mapped only a subset.
    universe: Dict[str, Dict[str, Any]] = {}

    def _row(name, rec, jl):
        return {
            "name": name,
            "subhead": (rec or {}).get("subhead", "") or "",
            "group_parent": (rec or {}).get("groupParent", "") or (jl or {}).get("parentGroup", "") or "",
            "head": (rec or {}).get("head", "") or "",
            "closing_balance": (rec or {}).get("closingBalance") if rec else (jl or {}).get("closingBalance"),
            "bs_or_pl": ((rec or {}).get("bsOrPl") or (jl or {}).get("bsOrPnl") or "").strip().upper(),
        }

    for jl in (ledgers_json or []):
        name = jl.get("name", "")
        if not name:
            continue
        rec = ledgers_xlsx.get(name)
        universe[name] = _row(name, rec, jl)

    for name, rec in ledgers_xlsx.items():
        if name not in universe:
            universe[name] = _row(name, rec, None)

    # --- Pool 1 · Exempt Purchases --------------------------------------
    exempt_ledgers = []
    for r in universe.values():
        if r["bs_or_pl"] != "P":
            continue
        if _norm(r["head"]) in _REVENUE_HEADS_EXCLUDE:
            continue
        exempt_ledgers.append({
            "name": r["name"],
            "subhead": r["subhead"],
            "group_parent": r["group_parent"],
            "head": r["head"],
            "closing_balance": r["closing_balance"],
            "suggested": _is_exempt_hint(r["name"]),
        })

    # --- Pool 2 · ITC Ledgers -------------------------------------------
    # Build the full BS-side skeleton first; we'll partition it into the
    # default-view (subhead-gated) and the all-BS view downstream.
    bs_skeleton = [r for r in universe.values() if r["bs_or_pl"] == "B"]

    # Voucher-usage detection — preserves naming-agnostic auto-detection.
    usage_map: Dict[str, Dict[str, Any]] = {}
    if vouchers:
        usage_map = compute_voucher_usage_kinds(
            [{"name": r["name"]} for r in bs_skeleton], vouchers,
        )

    def _enrich_itc(r: Dict[str, Any]) -> Dict[str, Any]:
        name_kind, kind_source = _classify_itc_kind(
            r["name"], r["subhead"], r["group_parent"],
        )
        usage = usage_map.get(r["name"], {})
        usage_kind = usage.get("usage_kind", "neutral")
        n_purchase = usage.get("n_purchase", 0)
        n_sales = usage.get("n_sales", 0)
        n_voucher = usage.get("n_voucher", 0)
        kind = name_kind
        ksource = kind_source
        # Release 4.4.6 — block the usage `other → input` upgrade for
        # TDS / TCS / Advance-Tax / Bank-charge GST patterns.  These
        # ledgers do appear on purchase vouchers (TDS deducted on
        # contractor bills, etc.) but they aren't ITC.  Name-side input
        # signals still win, so a ledger explicitly named "Input ..."
        # is unaffected.
        usage_blocked = (
            name_kind == "other"
            and _is_blocked_from_usage_upgrade(r["name"], r["group_parent"])
        )
        if kind == "other" and usage_kind in ("input", "output") and not usage_blocked:
            kind, ksource = usage_kind, "usage"
        usage_conflict = (
            name_kind == "input"
            and n_voucher > 0 and n_purchase == 0 and n_sales > 0
        )
        in_default_view = _norm(r["subhead"]) in ITC_SUBHEAD_DEFAULTS
        # Pre-tick fires only inside the default-view subheads — auditors
        # in expanded mode still get name/usage chips for visual scanning
        # but no auto-tick (avoids surprise when toggling back).
        suggested = (
            in_default_view and kind == "input" and (
                _subhead_matches(r["subhead"], ITC_SUGGEST_SUBHEADS)
                or usage_kind == "input"
            )
        )
        return {
            "name": r["name"],
            "subhead": r["subhead"],
            "group_parent": r["group_parent"],
            "head": r["head"],
            "closing_balance": r["closing_balance"],
            "suggested": suggested,
            # Membership flag — true if this row is in the focused default
            # view (subhead-gated).  False = only visible when "Show all
            # BS-side ledgers" toggle is on.
            "in_default_view": in_default_view,
            # ITC enrichments
            "kind": kind,
            "kind_source": ksource,
            "name_kind": name_kind,
            "usage_kind": usage_kind if vouchers else None,
            "n_purchase": n_purchase,
            "n_sales": n_sales,
            "n_voucher": n_voucher,
            "usage_conflict": usage_conflict,
        }

    itc_ledgers_all_bs = [_enrich_itc(r) for r in bs_skeleton]
    itc_ledgers = [r for r in itc_ledgers_all_bs if r["in_default_view"]]

    # --- Pool 3 · Exclusions --------------------------------------------
    exclusion_ledgers = []
    for r in universe.values():
        head_norm = _norm(r["head"])
        if head_norm in _REVENUE_HEADS_EXCLUDE:
            continue
        is_capex = (r["bs_or_pl"] == "B" and head_norm in _FA_HEADS)
        if r["bs_or_pl"] != "P" and not is_capex:
            continue
        # Auto-tick rule (Release 4.4.5): keyword match for genuine Sch III
        # / non-cash / money exclusions only.  Capex (FA + Intangibles) is
        # NEVER auto-ticked — it's reportable in Col 2 and only flows
        # through the recon's `capex_addback` bucket if the auditor
        # explicitly opts it in.  The badge below tells the auditor what
        # each tick does.
        suggested = (not is_capex) and _is_exclusion_hint(r["name"])
        exclusion_ledgers.append({
            "name": r["name"],
            "subhead": r["subhead"],
            "group_parent": r["group_parent"],
            "head": r["head"],
            "closing_balance": r["closing_balance"],
            "suggested": suggested,
            # `recon_role` tells the UI whether ticking this row will
            # SUBTRACT it from P&L (most exclusions) or ADD IT BACK to
            # P&L (capex — Col 2 already includes capex purchases).
            "recon_role": "addback" if is_capex else "subtract",
        })

    return {
        "exempt_ledgers": exempt_ledgers,
        "itc_ledgers": itc_ledgers,
        "itc_ledgers_all_bs": itc_ledgers_all_bs,
        "exclusion_ledgers": exclusion_ledgers,
    }


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
    excluded_ledgers: set | None = None,
    use_itc_inference: bool = True,
) -> Dict[str, Any]:
    """Classify each expense line into Col 3/4/5/7/8.

    Cascade (per ICAI, adapted to the JSON we actually have):
      0. Ledger in `excluded_ledgers`                      → **Col 8**
         (auditor-elected exclusion, wins over everything)
      1. `voucherTypeName == "Reverse Charge"`              → Col 7 (RCM)
      2. **Input A** — line's ledger in `exempt_ledgers`   → Col 3
      3. Foreign supplier (non-India country)              → Col 7 (import)
      4. Party reg type == "composition"                   → Col 4
      5. Party reg type == "regular" + GSTIN
         · **Input B** — `use_itc_inference` ON & no ITC
           ledger on voucher → Col 3
         · Otherwise                                        → Col 5
      6. Else (URD / consumer / blank)                     → Col 7

    **Important — what changed in Release 3:** the auditor-excluded
    ledgers are now classified to **Col 8** (not filtered out).  Col 2 in
    Clause 44 is the *gross* total expenditure per books (per ICAI Para
    79.4); Col 3–7 report only the portion that is not Sch III / non-cash
    / money / money-securities; the residual is Col 8.
    """
    exempt_ledgers = exempt_ledgers or set()
    excluded_ledgers = excluded_ledgers or set()

    txns: List[Dict[str, Any]] = []
    by_ledger: Dict[str, Dict[str, float]] = {}
    by_party: Dict[str, Dict[str, Any]] = {}
    col3_source_totals = {"input_a": 0.0, "input_b": 0.0}
    # Coverage diagnostic (Release 3.2 / option C) — if registered-vendor
    # vouchers don't carry an ITC ledger entry, the auditor probably hasn't
    # tagged all their input ledgers.  We surface this in the summary so
    # the UI can show a yellow advisory banner on the Report screen.
    cov_eligible = 0   # vouchers from regular-registered party with GSTIN
    cov_with_itc = 0   # of those, how many had any selected ITC ledger

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

        # Coverage diagnostic — count vouchers where ITC *should* exist:
        # registered-regular vendor with GSTIN, India-domestic, non-RCM.
        if (
            party_reg == "regular"
            and party_gstin
            and not is_rcm
            and not is_import
        ):
            cov_eligible += 1
            if has_itc:
                cov_with_itc += 1

        for lname, amt in exp_lines:
            bucket, reason, col3_src = _classify_single_line(
                lname, party_name, party_reg, party_gstin,
                is_rcm=is_rcm, is_import=is_import, has_itc=has_itc,
                exempt_ledgers=exempt_ledgers,
                excluded_ledgers=excluded_ledgers,
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
            row = by_ledger.setdefault(lname, {"col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "col8": 0.0, "total": 0.0})
            row[bucket] += amt
            row["total"] += amt

            p_key = party_name or "— Cash / No Party —"
            prow = by_party.setdefault(p_key, {
                "col3": 0.0, "col4": 0.0, "col5": 0.0, "col7": 0.0, "col8": 0.0, "total": 0.0,
                "party_gstin": party_gstin, "party_reg": party_reg, "vouchers": 0,
            })
            prow[bucket] += amt
            prow["total"] += amt
            if party_gstin:
                prow["party_gstin"] = party_gstin
            if party_reg:
                prow["party_reg"] = party_reg

        p_key = party_name or "— Cash / No Party —"
        if p_key in by_party:
            by_party[p_key]["vouchers"] += 1

    col3 = sum(t["amount"] for t in txns if t["bucket"] == "col3")
    col4 = sum(t["amount"] for t in txns if t["bucket"] == "col4")
    col5 = sum(t["amount"] for t in txns if t["bucket"] == "col5")
    col7 = sum(t["amount"] for t in txns if t["bucket"] == "col7")
    col8 = sum(t["amount"] for t in txns if t["bucket"] == "col8")
    rcm_total = sum(t["amount"] for t in txns if t.get("is_rcm"))
    import_total = sum(t["amount"] for t in txns if t.get("is_import"))
    summary = {
        # Col 2 is the GROSS total per books (includes Col 8).  Per ICAI
        # Para 79.4 the Clause 44 Col 2 headline is the assessee's total
        # expenditure for the year; Cols 3-7 are the reportable split and
        # Col 8 is the excluded residual.
        "col2_total": col3 + col4 + col5 + col7 + col8,
        "col3": col3, "col4": col4, "col5": col5,
        "col6": col3 + col4 + col5, "col7": col7, "col8": col8,
        "reportable_total": col3 + col4 + col5 + col7,  # Col 6 + Col 7
        "rcm_total": rcm_total,
        "rcm_vouchers": sum(1 for t in txns if t.get("is_rcm")),
        "import_total": import_total,
        "col3_from_input_a": col3_source_totals.get("input_a", 0.0),
        "col3_from_input_b": col3_source_totals.get("input_b", 0.0),
        # Coverage diagnostic — auditor advisory.
        "itc_coverage_eligible": cov_eligible,
        "itc_coverage_with_itc": cov_with_itc,
        "itc_coverage_pct": (
            round(100.0 * cov_with_itc / cov_eligible, 1) if cov_eligible else None
        ),
    }
    return {"summary": summary, "transactions": txns, "by_ledger": by_ledger, "by_party": by_party}


def _classify_single_line(
    lname: str, party_name: str, party_reg: str, party_gstin: str,
    *, is_rcm: bool, is_import: bool, has_itc: bool,
    exempt_ledgers: set, excluded_ledgers: set, use_itc_inference: bool,
    party_country: str = "",
) -> tuple:
    """Return (bucket, reason, col3_source).  col3_source is 'input_a' |
    'input_b' | '' (non-Col-3 lines)."""
    # 0) Excluded — auditor has explicitly ticked this ledger as not
    # reportable under Clause 44.  Land in Col 8 regardless of vendor
    # status; the ICAI recon sub-buckets (Non-cash / Sch III / Money /
    # Other / Capex add-back) apply at the recon screen via the
    # auto-categoriser.
    if lname in excluded_ledgers:
        return "col8", f"Ledger '{lname}' excluded from Col 3-7 reporting (Col 8)", ""
    # 1) RCM
    if is_rcm:
        return "col7", "RCM voucher — supplier typically unregistered", ""
    # 2) Input A
    if lname in exempt_ledgers:
        return "col3", f"Ledger '{lname}' tagged as exempt-supply purchase (Input A)", "input_a"
    # 3) Foreign supplier
    if is_import:
        country_label = party_country.title() if party_country else "non-India"
        return (
            "col7",
            f"Foreign supplier '{party_name}' ({country_label}) — import, no Indian GSTIN",
            "",
        )
    # 4) Composition
    if party_reg == "composition":
        return "col4", f"Party '{party_name}' is Composition dealer", ""
    # 5) Registered
    if party_reg == "regular" and party_gstin:
        if use_itc_inference and not has_itc:
            return (
                "col3",
                f"Registered vendor '{party_name}' (GSTIN {party_gstin}) "
                f"but no ITC ledger on voucher — presumed exempt supply (Input B, ITC inference)",
                "input_b",
            )
        return "col5", f"Party '{party_name}' is Regular (GSTIN: {party_gstin})", ""
    # 6) URD / Consumer / blank
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
    """Attach the ICAI 5-line recon to the classification result.

    **Release 3 change:** this function no longer *filters* transactions
    (excluded ledgers are now classified to Col 8 inside
    `classify_vouchers`).  It only computes the recon layout so the UI
    can present it per ICAI Para 79.4.

    The recon still shows:

        Total P&L expenditure (Col 2, including excluded)
        + Capex additions (memo — already in Col 2)
        − Non-cash charges                     \\
        − Schedule III items                    |  Σ = Col 8
        − Money / Securities                    |
        − Other exclusions                      /
        = Reportable expenditure (Col 6 + Col 7)

    Auto-categorisation of each excluded ledger into its ICAI sub-bucket
    is done via `categorise_exclusion`; auditor can override per line
    through `exclusion_categories`.
    """
    ledgers_xlsx = ledgers_xlsx or {}
    group_chains = group_chains or {}
    exclusion_categories = exclusion_categories or {}

    by_ledger: Dict[str, Dict[str, float]] = full_result["by_ledger"]
    summary: Dict[str, Any] = full_result["summary"]

    # Split the gross Col 2 into P&L vs capex based on ledger group chain
    # — capex is a memo line in the ICAI recon (already inside Col 2).
    pl_total = 0.0
    capex_total = 0.0
    for lname, vals in by_ledger.items():
        total = float(vals.get("total", 0) or 0)
        rec = ledgers_xlsx.get(lname, {}) or {}
        group_parent = (rec.get("groupParent") or "").lower()
        chain = group_chains.get(group_parent, group_parent).lower()
        if "fixed asset" in chain or "fixed asset" in group_parent:
            capex_total += total
        else:
            pl_total += total

    # Bucket the excluded ledgers into ICAI sub-buckets for the recon +
    # for the new Col 8 Excel sheet.  Each excluded ledger's Col 8 amount
    # is the total on its row in `by_ledger` (post-Release 3 these rows
    # live entirely in Col 8).
    bucket_lines: Dict[str, List[Dict[str, Any]]] = {b: [] for b in RECON_BUCKETS}
    for l in sorted(excluded_set):
        if l not in by_ledger:
            continue
        amt = float(by_ledger[l].get("col8", 0) or 0)
        if not amt:
            continue
        bucket = exclusion_categories.get(l)
        if bucket not in RECON_BUCKETS:
            bucket = categorise_exclusion(l, ledgers_xlsx.get(l, {}), group_chains)
        bucket_lines[bucket].append({"name": l, "amount": amt, "bucket": bucket})

    bucket_totals = {b: sum(x["amount"] for x in bucket_lines[b]) for b in RECON_BUCKETS}
    col8_total = float(summary.get("col8", 0) or 0)
    reportable = float(summary.get("reportable_total", 0) or 0)

    excluded_lines_flat = [
        {"name": x["name"], "amount": x["amount"], "bucket": x["bucket"]}
        for bucket in RECON_BUCKETS
        for x in bucket_lines[bucket]
    ]

    return {
        "summary": summary,
        "by_ledger": by_ledger,
        "by_party": full_result["by_party"],
        "transactions": full_result["transactions"],
        "recon": {
            # ICAI Para 79.4 presentation
            "pl_total": pl_total,
            "capex_total": capex_total,
            "capex_addback_total": bucket_totals["capex_addback"],
            "non_cash_total": bucket_totals["non_cash"],
            "sch3_total": bucket_totals["sch3"],
            "money_total": bucket_totals["money"],
            "other_total": bucket_totals["other"],
            "col8_total": col8_total,
            "reportable_total": reportable,
            # Per-bucket line detail (recon table + Col 8 Excel sheet)
            "non_cash_lines": bucket_lines["non_cash"],
            "sch3_lines": bucket_lines["sch3"],
            "money_lines": bucket_lines["money"],
            "other_lines": bucket_lines["other"],
            "capex_addback_lines": bucket_lines["capex_addback"],
            # Legacy keys retained for exports/code still referencing them
            "total_books": pl_total + capex_total,
            "excluded_lines": excluded_lines_flat,
            "excluded_total": col8_total,
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
