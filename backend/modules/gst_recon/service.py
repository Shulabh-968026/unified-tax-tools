"""GST Turnover Reconciliation — Phase A: filename categorizer + batch helpers.

Phase B (next session) adds: GSTIN/FY pre-flight gates, GSTR-3B PDF parser,
pandas aggregation (turnover & ITC), rapidfuzz voucher-level matching.
"""
from __future__ import annotations
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

# Filename recognition — tolerant to the real sample names we received:
#   33AAEFA5684J1ZC_GSTR1_April_2024-2025_0.json
#   returns_R2B_33AAEFA5684J1ZC_012025.json
#   GSTR3B_33AAEFA5684J1ZC_012025.pdf
#   Allman_Knit_Wear_IT_24-25_01042024-31032025-165633.json
#   A_519_2024_2025_v10_ledger_mapping.xlsx
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][A-Z0-9])\b")
PERIOD_MMYYYY_RE = re.compile(r"(?<!\d)(0[1-9]|1[0-2])(\d{4})(?!\d)")
MONTH_NAME_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)",
    re.IGNORECASE,
)
MONTH_NAMES = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

def _extract_period(fname: str) -> Optional[str]:
    """Return MMYYYY or None. Tries explicit 012025 first, else MonthName + 4-digit year."""
    m = PERIOD_MMYYYY_RE.search(fname)
    if m:
        return m.group(1) + m.group(2)
    mn = MONTH_NAME_RE.search(fname)
    if mn:
        mm = MONTH_NAMES[mn.group(1).lower()]
        # Year heuristic: pick the first 4-digit 20xx in the filename
        y = re.search(r"(20\d{2})", fname)
        if y:
            return mm + y.group(1)
    return None


def _extract_gstin(fname: str) -> Optional[str]:
    m = GSTIN_RE.search(fname.upper())
    return m.group(1) if m else None


def categorize_file(filename: str, size: int = 0) -> Dict[str, Any]:
    """Sort a single uploaded filename into a bucket + optional period + GSTIN."""
    lower = filename.lower()
    bucket = "unknown"
    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""

    if re.search(r"gstr[\s_-]?3b|_r3b|gstr3b", lower) and ext == "pdf":
        bucket = "gstr3b"
    elif re.search(r"gstr[\s_-]?2b|_r2b|returns_r2b", lower) and ext == "json":
        bucket = "gstr2b"
    elif re.search(r"gstr[\s_-]?1|_r1_", lower) and ext == "json":
        bucket = "gstr1"
    elif "ledger_mapping" in lower or "ledger-mapping" in lower or re.search(r"mapping.*\.(csv|xlsx|xls)$", lower):
        bucket = "mapping"
    elif ext == "json":
        # Fallback: Books JSON (tally-style tends to have long date-range in filename)
        if re.search(r"\d{8}-\d{8}", lower) or re.search(r"\d{2}[-_]\d{2}", lower):
            bucket = "books"

    return {
        "filename": filename,
        "bucket": bucket,
        "period": _extract_period(filename) if bucket in ("gstr1", "gstr2b", "gstr3b") else None,
        "gstin": _extract_gstin(filename),
        "size": size,
    }


def build_month_grid(fy: str, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For FY '2024-25' return 12 rows Apr-2024..Mar-2025 with per-return presence flags."""
    try:
        start_year = int(fy.split("-")[0])
    except Exception:
        start_year = date.today().year
    months: List[Tuple[str, str]] = []  # (MMYYYY, label)
    for i in range(12):
        m = ((3 + i) % 12) + 1  # Apr=4 ... Mar=3
        y = start_year if i < 9 else start_year + 1
        months.append((f"{m:02d}{y}", f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m-1]} {y}"))

    period_map = {p: {"gstr1": False, "gstr2b": False, "gstr3b": False} for p, _ in months}
    for f in files:
        p = f.get("period")
        b = f.get("bucket")
        if p in period_map and b in ("gstr1", "gstr2b", "gstr3b"):
            period_map[p][b] = True

    return [
        {"period": p, "month_label": label, **period_map[p]}
        for p, label in months
    ]


# ============================ Phase C.3: 12-month Summary =====================
_SUM_KEYS = (
    "books_outward_taxable", "books_outward_tax", "books_itc_total",
    "r1_outward_taxable", "r1_outward_tax",
    "r2b_itc_total",
    "r3b_outward_taxable", "r3b_outward_tax", "r3b_itc_total",
    "var_r1_vs_r3b_outward", "var_r2b_vs_r3b_itc",
    "var_books_vs_r1_outward", "var_books_vs_r2b_itc",
)


def build_summary(run_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Stitch per-file aggregates into a 12-month Turnover & ITC table.

    Pulls:
      • Books:   from books_file["books_per_month"][period]
      • GSTR-1:  from gstr1_file["r1_outward"]
      • GSTR-2B: from gstr2b_file["r2b_itc"]
      • GSTR-3B: from gstr3b_file["table_3_1"] (rows a/b/c → outward) and table_4.c_net_itc

    Variance columns:
      • R1 vs R3B (outward taxable) — must reconcile per GSTR-9 line 7
      • R2B vs R3B (ITC total) — must reconcile per GSTR-9C
      • Books vs R1 (outward taxable) — Tally vs portal
      • Books vs R2B (ITC total)

    Returns: {fy, rows: [12], totals: {…}}
    """
    files = run_doc.get("files", [])
    fy = run_doc.get("fy", "")
    months = run_doc.get("months", [])

    by_period: Dict[str, Dict[str, Any]] = {
        m["period"]: {"period": m["period"], "month_label": m["month_label"]}
        for m in months
    }

    # Books — single file, per-month dict
    books_file = next((f for f in files if f.get("bucket") == "books"), None)
    books_agg: Dict[str, Dict[str, float]] = (books_file or {}).get("books_per_month") or {}
    for p, row in by_period.items():
        b = books_agg.get(p, {})
        row["books_outward_taxable"] = b.get("out_taxable", 0.0)
        row["books_outward_tax"] = round(
            b.get("out_igst", 0.0) + b.get("out_cgst", 0.0)
            + b.get("out_sgst", 0.0) + b.get("out_cess", 0.0), 2,
        )
        row["books_itc_total"] = round(
            b.get("in_igst", 0.0) + b.get("in_cgst", 0.0)
            + b.get("in_sgst", 0.0) + b.get("in_cess", 0.0), 2,
        )

    # GSTR-1
    for f in files:
        if f.get("bucket") != "gstr1":
            continue
        p = f.get("period")
        if p not in by_period:
            continue
        a = f.get("r1_outward") or {}
        by_period[p]["r1_outward_taxable"] = a.get("taxable", 0.0)
        by_period[p]["r1_outward_tax"] = round(
            a.get("igst", 0.0) + a.get("cgst", 0.0)
            + a.get("sgst", 0.0) + a.get("cess", 0.0), 2,
        )

    # GSTR-2B
    for f in files:
        if f.get("bucket") != "gstr2b":
            continue
        p = f.get("period")
        if p not in by_period:
            continue
        a = f.get("r2b_itc") or {}
        by_period[p]["r2b_itc_total"] = round(
            a.get("igst", 0.0) + a.get("cgst", 0.0)
            + a.get("sgst", 0.0) + a.get("cess", 0.0), 2,
        )

    # GSTR-3B — rows (a) outward taxable, (b) zero-rated, (c) other outward
    # Excludes (d) inward RCM and (e) non-GST since they're not part of turnover.
    for f in files:
        if f.get("bucket") != "gstr3b":
            continue
        p = f.get("period")
        if p not in by_period:
            continue
        t31 = f.get("table_3_1") or {}
        out_tax = sum((t31.get(k) or {}).get("taxable_value", 0.0) for k in ("a", "b", "c"))
        out_tax_amt = sum(
            (t31.get(k) or {}).get("igst", 0.0)
            + (t31.get(k) or {}).get("cgst", 0.0)
            + (t31.get(k) or {}).get("sgst", 0.0)
            + (t31.get(k) or {}).get("cess", 0.0)
            for k in ("a", "b", "c")
        )
        by_period[p]["r3b_outward_taxable"] = round(out_tax, 2)
        by_period[p]["r3b_outward_tax"] = round(out_tax_amt, 2)
        net = (f.get("table_4") or {}).get("c_net_itc") or {}
        by_period[p]["r3b_itc_total"] = round(
            net.get("igst", 0.0) + net.get("cgst", 0.0)
            + net.get("sgst", 0.0) + net.get("cess", 0.0), 2,
        )

    # Zero-fill + variance columns + ordered rows
    rows: List[Dict[str, Any]] = []
    for m in months:
        r = by_period[m["period"]]
        for k in _SUM_KEYS:
            r.setdefault(k, 0.0)
        r["var_r1_vs_r3b_outward"] = round(r["r1_outward_taxable"] - r["r3b_outward_taxable"], 2)
        r["var_r2b_vs_r3b_itc"] = round(r["r2b_itc_total"] - r["r3b_itc_total"], 2)
        r["var_books_vs_r1_outward"] = round(r["books_outward_taxable"] - r["r1_outward_taxable"], 2)
        r["var_books_vs_r2b_itc"] = round(r["books_itc_total"] - r["r2b_itc_total"], 2)
        rows.append(r)

    totals = {k: round(sum(r[k] for r in rows), 2) for k in _SUM_KEYS}
    return {"fy": fy, "rows": rows, "totals": totals}


# ============================ Phase D: voucher-level matching =================
import re as _re

_INV_NORM_RE = _re.compile(r"[^A-Z0-9]")


def _norm_inv_no(s: Optional[str]) -> str:
    """Normalise an invoice / voucher number for matching: uppercase, strip non-alnum."""
    if not s:
        return ""
    return _INV_NORM_RE.sub("", str(s).upper())


def _to_iso_date(d: Optional[str]) -> Optional[str]:
    """Tolerate '2024-04-01' (ISO) or '01-04-2024' (DD-MM-YYYY) → YYYY-MM-DD; else None."""
    if not d:
        return None
    s = str(d).strip()[:10]
    if _re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if _re.match(r"^\d{2}-\d{2}-\d{4}$", s):
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    if _re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    return None


def _classify_pair(b: Dict[str, Any], p: Dict[str, Any], fuzzy_score: Optional[int] = None) -> Tuple[str, Dict[str, Any]]:
    """Decide whether a books↔portal pair is matched, value_mismatch, or date_mismatch.

    Tolerances:
      • Value: max(₹1, 0.5%) of the larger side
      • Date: must be the exact same calendar day (after ISO normalisation); only flagged
        when both sides have parseable dates
    """
    b_total = float(b.get("total", 0) or 0)
    p_total = float(p.get("total", 0) or 0)
    diff = round(b_total - p_total, 2)
    tol = max(1.0, 0.005 * max(abs(b_total), abs(p_total)))
    b_date = _to_iso_date(b.get("date"))
    p_date = _to_iso_date(p.get("date"))
    pair: Dict[str, Any] = {
        "books": {k: v for k, v in b.items() if not k.startswith("_")},
        "portal": {k: v for k, v in p.items() if not k.startswith("_")},
        "value_diff": diff,
        "books_date": b_date,
        "portal_date": p_date,
    }
    if fuzzy_score is not None:
        pair["fuzzy_score"] = fuzzy_score
    if abs(diff) > tol:
        return "value_mismatch", pair
    if b_date and p_date and b_date != p_date:
        return "date_mismatch", pair
    return "matched", pair


def match_invoices(books: List[Dict[str, Any]], portal: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Two-pass matching: (1) exact party_gstin + normalised invoice no, (2) rapidfuzz ≥85.

    Returns dict with `matched`, `value_mismatch`, `date_mismatch`,
    `missing_in_books` (portal-only), `missing_in_portal` (books-only), and `counts`.
    """
    from rapidfuzz import fuzz, process

    # Normalise once
    for b in books:
        b["_norm"] = _norm_inv_no(b.get("voucher_no") or b.get("invoice_no"))
    for p in portal:
        p["_norm"] = _norm_inv_no(p.get("invoice_no") or p.get("voucher_no"))

    n_b, n_p = len(books), len(portal)
    used_b = [False] * n_b
    used_p = [False] * n_p
    matched: List[Dict[str, Any]] = []
    value_mm: List[Dict[str, Any]] = []
    date_mm: List[Dict[str, Any]] = []

    # Pass 1: exact match on (gstin, normalised inv no)
    p_idx: Dict[Tuple[str, str], List[int]] = {}
    for j, p in enumerate(portal):
        p_idx.setdefault((p.get("party_gstin", ""), p["_norm"]), []).append(j)

    for i, b in enumerate(books):
        key = (b.get("party_gstin", ""), b["_norm"])
        for j in p_idx.get(key, []):
            if not used_p[j]:
                used_b[i] = True
                used_p[j] = True
                cat, pair = _classify_pair(b, portal[j])
                {"matched": matched, "value_mismatch": value_mm, "date_mismatch": date_mm}[cat].append(pair)
                break

    # Pass 2: fuzzy on inv-no within same gstin (only unmatched on both sides)
    by_gstin: Dict[str, List[int]] = {}
    for j, p in enumerate(portal):
        if used_p[j]:
            continue
        by_gstin.setdefault(p.get("party_gstin", ""), []).append(j)

    for i, b in enumerate(books):
        if used_b[i]:
            continue
        gstin = b.get("party_gstin", "")
        cand_idxs = [j for j in by_gstin.get(gstin, []) if not used_p[j]]
        if not cand_idxs or not b["_norm"]:
            continue
        choices = {j: portal[j]["_norm"] for j in cand_idxs if portal[j]["_norm"]}
        if not choices:
            continue
        best = process.extractOne(b["_norm"], choices, scorer=fuzz.ratio, score_cutoff=85)
        if best:
            _, score, j = best
            used_b[i] = True
            used_p[j] = True
            cat, pair = _classify_pair(b, portal[j], fuzzy_score=int(score))
            {"matched": matched, "value_mismatch": value_mm, "date_mismatch": date_mm}[cat].append(pair)

    # Sweep remainders
    missing_in_portal = [{k: v for k, v in b.items() if not k.startswith("_")}
                         for i, b in enumerate(books) if not used_b[i]]
    missing_in_books = [{k: v for k, v in p.items() if not k.startswith("_")}
                        for j, p in enumerate(portal) if not used_p[j]]

    return {
        "matched": matched,
        "value_mismatch": value_mm,
        "date_mismatch": date_mm,
        "missing_in_books": missing_in_books,
        "missing_in_portal": missing_in_portal,
        "counts": {
            "matched": len(matched),
            "value_mismatch": len(value_mm),
            "date_mismatch": len(date_mm),
            "missing_in_books": len(missing_in_books),
            "missing_in_portal": len(missing_in_portal),
        },
    }
