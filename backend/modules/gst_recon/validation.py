"""Phase B pre-flight validation for GST Turnover Recon.

Light-weight content inspection — parse just enough of each uploaded file to
extract GSTIN, return period, and an integrity flag. Keeps Mongo payloads small.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from modules.gst_recon.service import _extract_gstin, _extract_period

GSTIN_IN_FILE_RE = re.compile(r"(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][A-Z0-9])")
GSTR3B_HEADER_RE = re.compile(rb"(?i)(gstr[-\s_]*3b|form\s*gstr[-\s]*3b|rtnprd|return\s+period)")
FP_RE = re.compile(r'"fp"\s*:\s*"(\d{6})"')


def inspect_file(filename: str, bucket: str, content: bytes) -> Dict[str, Any]:
    """Return content-level metadata: gstin, period, integrity_ok, parse_error, books_from/to."""
    out: Dict[str, Any] = {"integrity_ok": False, "parse_error": None, "gstin": None, "period": None}
    try:
        if bucket in ("gstr1", "gstr2b", "books"):
            try:
                j = json.loads(content.decode("utf-8", errors="replace"))
            except Exception as e:
                out["parse_error"] = f"Not a valid JSON: {e.__class__.__name__}"
                return out
            out["integrity_ok"] = True
            if bucket == "gstr1":
                out["gstin"] = j.get("gstin") or _extract_gstin(filename)
                out["period"] = j.get("fp") or _extract_period(filename)
            elif bucket == "gstr2b":
                # Case-insensitive lookups — GSTN uses camelCase in older files
                from modules.gst_recon.aggregators import _ci_get
                data = _ci_get(j, "data") or j
                out["gstin"] = _ci_get(data, "gstin") or _extract_gstin(filename)
                out["period"] = _ci_get(data, "rtnprd") or _ci_get(data, "retPeriod") or _extract_period(filename)
            else:  # books
                company = j.get("company") or {}
                out["books_from"] = company.get("booksFromDate") or j.get("booksFromDate")
                out["books_to"] = company.get("booksToDate") or j.get("booksToDate")
                out["gstin"] = (company.get("gstin") or company.get("GSTIN")
                                or _extract_gstin(json.dumps(j)[:2000]))
        elif bucket == "gstr3b":
            # PDF header sniff only — deep content parse happens in Phase C (pdfplumber).
            head = content[:8]
            if not head.startswith(b"%PDF"):
                out["parse_error"] = "Not a PDF (missing %PDF header)"
                return out
            out["integrity_ok"] = True
            # Full table extraction (Phase C.2)
            from helpers.parsers import parse_gstr3b_pdf
            parsed = parse_gstr3b_pdf(content)
            out["gstin"] = parsed.get("gstin") or _extract_gstin(filename)
            out["period"] = parsed.get("period") or _extract_period(filename)
            out["table_3_1"] = parsed.get("table_3_1") or {}
            out["table_4"] = parsed.get("table_4") or {}
            if parsed.get("errors"):
                # Don't hard-fail integrity — surface as warning text
                out["parse_error"] = "; ".join(parsed["errors"])
                out["integrity_ok"] = bool(out["table_3_1"] or out["table_4"])
        elif bucket == "mapping":
            # CSV or XLSX — byte-level size check only for Phase B
            if len(content) < 20:
                out["parse_error"] = "Mapping file is empty"
                return out
            out["integrity_ok"] = True
        elif bucket == "unknown":
            out["parse_error"] = "File not recognised (check filename)"
    except Exception as e:
        out["parse_error"] = str(e)
    return out


def _fy_range(fy: str) -> Tuple[date, date]:
    """'2024-25' -> (2024-04-01, 2025-03-31)."""
    start = int(fy.split("-")[0])
    return date(start, 4, 1), date(start + 1, 3, 31)


def validate_run(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return dict: ok, errors[], warnings[], months[], summary."""
    errors: List[str] = []
    warnings: List[str] = []

    client_gstin = (doc.get("client_gstin") or "").upper().strip()
    fy = doc.get("fy", "")
    files = doc.get("files", [])

    # Gate 1: client has a GSTIN
    if not client_gstin:
        errors.append("Client does not have a GSTIN set. Add GSTIN on the client before running GST Recon.")

    # Gate 2: integrity per file + gstin mismatch
    bad_integrity: List[str] = []
    mismatched: List[str] = []
    for f in files:
        if f.get("parse_error"):
            bad_integrity.append(f"{f['filename']}: {f['parse_error']}")
        fg = (f.get("gstin") or "").upper()
        if client_gstin and fg and f["bucket"] in ("gstr1", "gstr2b", "gstr3b") and fg != client_gstin:
            mismatched.append(f"{f['filename']} has GSTIN {fg}")
    if bad_integrity:
        errors.append("File integrity failures: " + "; ".join(bad_integrity))
    if mismatched:
        errors.append(f"GSTIN mismatch against client {client_gstin}: " + "; ".join(mismatched))

    # Gate 3: FY alignment (Books)
    books = next((f for f in files if f["bucket"] == "books"), None)
    if not books:
        errors.append("Books of Accounts JSON is missing.")
    else:
        bf = (books.get("books_from") or "")[:10]
        bt = (books.get("books_to") or "")[:10]
        fy_start, fy_end = _fy_range(fy) if fy else (None, None)
        try:
            bfd = date.fromisoformat(bf) if bf else None
            btd = date.fromisoformat(bt) if bt else None
            if not bfd or not btd:
                errors.append("Books JSON missing booksFromDate/booksToDate.")
            elif fy_start and (bfd > fy_start or btd < fy_end):
                errors.append(f"Books dates ({bf} to {bt}) do not cover FY {fy} ({fy_start} to {fy_end}).")
        except Exception:
            warnings.append(f"Could not parse Books dates: {bf} / {bt}")

    # Gate 4: completeness — ledger mapping + all 12 months × 3 returns
    if not any(f["bucket"] == "mapping" for f in files):
        errors.append("Ledger Mapping file is missing.")
    missing_months: List[str] = []
    for m in doc.get("months", []):
        gaps = [g for g in ("gstr1", "gstr2b", "gstr3b") if not m.get(g)]
        if gaps:
            missing_months.append(f"{m['month_label']} ({'/'.join(g.upper() for g in gaps)})")
    if missing_months:
        errors.append(f"Month coverage gaps: {', '.join(missing_months)}")

    total_gst_files = sum(1 for f in files if f["bucket"] in ("gstr1", "gstr2b", "gstr3b"))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "total_files": len(files),
            "gst_files": total_gst_files,
            "has_books": any(f["bucket"] == "books" for f in files),
            "has_mapping": any(f["bucket"] == "mapping" for f in files),
            "client_gstin": client_gstin,
            "mismatched_gstins": len(mismatched),
            "integrity_failures": len(bad_integrity),
        },
    }
