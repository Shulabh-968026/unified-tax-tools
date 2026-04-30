"""Tally Books JSON → Fixed Asset extraction service.

Responsibilities
----------------
1. **fa_groups_under(books)** — recursively walk the `groups` hierarchy under
   "Fixed Assets" / "Property, Plant and Equipment" → set of group names.
2. **fa_ledgers(books)** — list of FA ledgers, **excluding** ledgers whose name
   matches the depreciation pattern (auditor's spec: ignore Accumulated
   Depreciation ledgers entirely).
3. **fa_voucher_lines(books, ledger_names)** — for every voucher that touches
   any of the supplied ledger names, return one row per FA ledger entry, with
   sign-aware amount, narration, and the auditor-friendly Bill/Inv date logic
   (regex narration for "Bill Date" or "Inv Date" → fallback to accounting
   date; per spec).
4. **classify_voucher_line()** — returns one of: ``addition`` (debit to asset),
   ``credit`` (credit entry needing manual sale-vs-discount classification).

The parser keeps everything functional/synchronous; persistence happens in the
controller layer.
"""
from __future__ import annotations
import gzip
import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("fixed_assets.service")


# ============================ FY helpers =====================================
def fy_dates(fy: str) -> Tuple[str, str]:
    """'2024-25' → ('2024-04-01', '2025-03-31'). Returns ('', '') if malformed."""
    m = re.match(r"^\s*(\d{4})\s*-\s*(\d{2,4})\s*$", fy or "")
    if not m:
        return "", ""
    yr1 = int(m.group(1))
    yr2_raw = m.group(2)
    yr2 = int(yr2_raw) if len(yr2_raw) == 4 else 2000 + int(yr2_raw) if int(yr2_raw) < 80 else 1900 + int(yr2_raw)
    return f"{yr1:04d}-04-01", f"{yr2:04d}-03-31"


def half_rate_threshold(fy_end: str) -> str:
    """For FY ending YYYY-03-31 the 180-day cutoff is YYYY-1-10-03 (Oct 3 prior year)."""
    if not fy_end:
        return ""
    try:
        d = datetime.strptime(fy_end, "%Y-%m-%d").date()
    except ValueError:
        return ""
    # 180 days before FY end (Mar 31) ≈ Oct 3 of preceding year
    return f"{d.year - 1:04d}-10-03"


def is_more_than_180(put_to_use: str, fy_end: str) -> bool:
    """True ⇒ asset put to use ≥180 days before FY end ⇒ FULL depreciation rate.
    Defaults to True when input is missing (auditor can override later)."""
    if not put_to_use:
        return True
    try:
        ptu = datetime.strptime(put_to_use, "%Y-%m-%d").date()
        end = datetime.strptime(fy_end, "%Y-%m-%d").date()
    except ValueError:
        return True
    return (end - ptu).days >= 180


# ============================ Books ingest ===================================
DEPRECIATION_LEDGER_PATTERNS = [
    re.compile(r"\baccumulated\s+depreciation\b", re.I),
    re.compile(r"\bdepreciation\s+(reserve|provision)\b", re.I),
    re.compile(r"\bprovision\s+for\s+depreciation\b", re.I),
    re.compile(r"^\s*depreciation\b", re.I),       # leading "Depreciation - X"
]

FIXED_ASSET_GROUP_ROOTS = (
    "Fixed Assets",
    "Property, Plant and Equipment",
    "Property Plant and Equipment",
    "Property, Plant & Equipment",
)


# ============================ Auto-classification ===========================
# Heuristic mapping rules — checked in order. The first matching rule wins.
# Rules are intentionally narrow at the top (vehicles, computers) and
# fall through to "P&M generic" only after all the specific keys are tried.
_BLOCK_RULES: List[Tuple[str, re.Pattern]] = [
    ("15% Block – Vehicles",          re.compile(r"\b(vehicles?|motor\s*cars?|cars?|trucks?|lorries?|two\s*wheelers?|bikes?|scooters?)\b", re.I)),
    ("40% Block – Computers",         re.compile(r"\b(computers?|laptops?|desktops?|servers?|software|printers?|monitors?|cpus?)\b", re.I)),
    ("10% Block – Furniture",         re.compile(r"\b(furnitures?|fittings?|chairs?|tables?|cabinets?|desks?|sofas?|benches?|cupboards?)\b", re.I)),
    ("10% Block – Buildings",         re.compile(r"\b(buildings?|factory\s*sheds?|godowns?|office\s*premises?)\b", re.I)),
    ("15% Block – Plant & Machinery", re.compile(r"\b(plants?|machineries|machinery|machines?|office\s*equipments?|electricals?|equipments?|boilers?|tools?|generators?|pumps?|spreading|sewing|lab\s*test|cutting|stitching|ironing)\b", re.I)),
]


def auto_classify_block(ledger_name: str, parent_group: str) -> str:
    """Heuristic block classifier. Returns `block_label` or empty string.
    Uses BOTH the ledger's name and its parent group so that ledgers like
    `Plant & Machinery GST 18%` (under group `Plant and Machineries`) match
    even when the rule keyword only appears in the parent group."""
    haystack = f"{ledger_name or ''} {parent_group or ''}"
    for block_label, pat in _BLOCK_RULES:
        if pat.search(haystack):
            return block_label
    return ""


def is_depreciation_ledger(name: str) -> bool:
    return any(p.search(name or "") for p in DEPRECIATION_LEDGER_PATTERNS)


def fa_group_names(books: Dict[str, Any]) -> Set[str]:
    """All group names that descend from any FA root. Includes the roots."""
    groups = books.get("groups") or []
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for g in groups:
        by_parent.setdefault(g.get("parentGroup") or "", []).append(g)

    out: Set[str] = set()
    stack = [r for r in FIXED_ASSET_GROUP_ROOTS]
    seen_roots = {g["name"] for g in groups
                  if g["name"] in FIXED_ASSET_GROUP_ROOTS}
    out.update(seen_roots)
    while stack:
        cur = stack.pop()
        for child in by_parent.get(cur, []):
            n = child["name"]
            if n not in out:
                out.add(n)
                stack.append(n)
    return out


def fa_ledgers(books: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Asset ledgers under FA groups, MINUS depreciation ledgers (per spec)."""
    fa_groups = fa_group_names(books)
    out: List[Dict[str, Any]] = []
    for led in books.get("ledgers") or []:
        if led.get("parentGroup") not in fa_groups:
            continue
        if is_depreciation_ledger(led.get("name") or ""):
            continue
        out.append({
            "name":              led["name"],
            "parent_group":      led.get("parentGroup") or "",
            "opening_balance":   float(led.get("openingBalance") or 0),
            "closing_balance":   float(led.get("closingBalance") or 0),
            "is_gst_applicable": str(led.get("isGSTApplicable") or "").lower() in ("yes", "true", "1"),
        })
    return out


# ============================ Invoice date detection ========================
# Per user spec: regex narration for "Bill Date" or "Inv Date" first, else
# fall back to the voucher accounting date. Do NOT use Tally's `dueDates`
# (those represent payment due-dates, NOT bill dates).
_INV_DATE_PATTERNS = [
    re.compile(
        r"(?:bill|inv(?:oice)?)\.?\s*(?:date|dt|no\s*&\s*dt)\s*[:\-]?\s*"
        r"(\d{1,2}[-/.\s]\d{1,2}[-/.\s]\d{2,4}|"
        r"\d{4}[-/.\s]\d{1,2}[-/.\s]\d{1,2})",
        re.I,
    ),
]

# Invoice/Bill number — captured from narration on a best-effort basis.
# Stops at a date keyword, "for ", "nos", punctuation or end of segment.
_INV_NO_PATTERN = re.compile(
    r"\b(?:bill|inv(?:oice)?)\.?\s*(?:no\.?|num\.?|#)?\s*[:\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-/.\s]{0,40}?)"
    r"(?=\s*(?:dt\b|date\b|dat\b|for\b|nos\b|qty\b|@|,|;|\.\s|$))",
    re.I,
)
_INV_NO_TAIL_STRIP = re.compile(r"\s*(?:dt|date|dat|for|nos|qty|@).*$", re.I)


def detect_invoice_no(narration: str) -> str:
    if not narration:
        return ""
    m = _INV_NO_PATTERN.search(narration)
    if not m:
        return ""
    raw = _INV_NO_TAIL_STRIP.sub("", m.group(1)).strip(" ,.;:-/")
    return raw[:30]


def _normalise_date(token: str) -> str:
    """Best-effort dd/mm/yyyy → YYYY-MM-DD. Returns '' if not parseable."""
    s = re.sub(r"[\s./]", "-", token.strip())
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def detect_invoice_date(narration: str) -> Tuple[str, str]:
    """Returns (date_iso, source) where source ∈ {'narration', ''}."""
    if not narration:
        return "", ""
    for p in _INV_DATE_PATTERNS:
        m = p.search(narration)
        if m:
            iso = _normalise_date(m.group(1))
            if iso:
                return iso, "narration"
    return "", ""


# ============================ Voucher line classification ===================
def fa_voucher_lines(books: Dict[str, Any],
                     fa_ledger_names: Set[str]) -> List[Dict[str, Any]]:
    """Yield one row per FA-ledger entry inside FA-touching vouchers.

    Sign convention (Tally JSON): negative `amount` ⇒ Debit, positive ⇒ Credit.
    """
    out: List[Dict[str, Any]] = []
    for v in books.get("vouchers") or []:
        entries = v.get("ledgerEntries") or []
        if not any((e.get("ledger") in fa_ledger_names) for e in entries):
            continue

        narration = v.get("narration") or ""
        inv_date_iso, inv_src = detect_invoice_date(narration)
        acc_date = v.get("date") or ""

        # Identify counter-party: prefer the explicit party ledger row
        party = ""
        for e in entries:
            if e.get("isPartyLedger") in ("Yes", True):
                party = e.get("ledger") or ""
                break
        party = party or v.get("partyLedgerName") or ""

        for e in entries:
            ledger = e.get("ledger") or ""
            if ledger not in fa_ledger_names:
                continue
            amt_raw = float(e.get("amount") or 0)
            # Asset Dr (purchase) shows as negative in Tally JSON;
            # asset Cr (sale/discount/return) shows as positive.
            is_debit = amt_raw < 0
            magnitude = abs(amt_raw)
            row = {
                "voucher_id":            v.get("voucherId") or "",
                "voucher_no":            v.get("voucherNumber") or "",
                "voucher_type":          v.get("voucherTypeName") or "",
                "accounting_date":       acc_date,
                "invoice_date":          inv_date_iso or acc_date,
                "invoice_date_source":   inv_src or ("accounting_fallback" if not inv_date_iso else inv_src),
                "ledger_name":           ledger,
                "amount":                magnitude,
                "is_debit":              is_debit,
                "narration":             narration,
                "party_name":            party,
                "particulars":           narration,
            }
            out.append(row)
    return out


def stage_addition_rows(lines: List[Dict[str, Any]],
                        ledger_id_by_name: Dict[str, str],
                        run_id: str,
                        fy_end: str) -> List[Dict[str, Any]]:
    """Convert debit lines → addition records. PTU defaults to invoice_date."""
    out: List[Dict[str, Any]] = []
    for r in lines:
        if not r["is_debit"]:
            continue
        ptu = r["invoice_date"] or r["accounting_date"]
        out.append({
            "run_id":               run_id,
            "fa_ledger_id":         ledger_id_by_name.get(r["ledger_name"], ""),
            "block_label":          "",
            "voucher_id":           r["voucher_id"],
            "voucher_no":           r["voucher_no"],
            "voucher_type":         r["voucher_type"],
            "accounting_date":      r["accounting_date"],
            "invoice_date":         r["invoice_date"],
            "invoice_date_source":  r["invoice_date_source"],
            "invoice_no":           detect_invoice_no(r.get("narration", "")),
            "put_to_use_date":      ptu,
            "party_name":           r["party_name"],
            "particulars":          r["particulars"],
            "description":          r["particulars"],
            "invoice_cost":         r["amount"],
            "discount_credits":     0.0,
            "other_expenses":       0.0,
            "itc_reversed":         0.0,
            "interest_capitalized": 0.0,
            "forex_fluctuations":   0.0,
            "is_more_than_180":     is_more_than_180(ptu, fy_end),
            "half_rate":            not is_more_than_180(ptu, fy_end),
            "reviewed":             False,
            "source":               "addition",
            "parent_addition_id":   "",
            "linked_as":            "",
            "notes":                "",
        })
    return out


def stage_credit_rows(lines: List[Dict[str, Any]],
                      ledger_id_by_name: Dict[str, str],
                      run_id: str) -> List[Dict[str, Any]]:
    """Convert credit lines → unclassified credit records (sale vs discount?)."""
    out: List[Dict[str, Any]] = []
    for r in lines:
        if r["is_debit"]:
            continue
        out.append({
            "run_id":          run_id,
            "fa_ledger_id":    ledger_id_by_name.get(r["ledger_name"], ""),
            "voucher_id":      r["voucher_id"],
            "voucher_no":      r["voucher_no"],
            "voucher_type":    r["voucher_type"],
            "accounting_date": r["accounting_date"],
            "party_name":      r["party_name"],
            "particulars":     r["particulars"],
            "amount":          r["amount"],
            "classification":  "pending",
            "sale_value":      None,
            "sale_date":       r["accounting_date"],   # default (auditor edits)
            "buyer_name":      r["party_name"],        # default (auditor edits)
        })
    return out


# ============================ Books JSON parsing helper ====================
def parse_books_json(content_bytes: bytes) -> Dict[str, Any]:
    """Parse Tally Books JSON (raw or gzip-compressed)."""
    raw = content_bytes
    if len(raw) >= 2 and raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig", errors="replace").strip()
    return json.loads(text)
