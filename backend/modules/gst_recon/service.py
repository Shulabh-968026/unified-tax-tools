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
