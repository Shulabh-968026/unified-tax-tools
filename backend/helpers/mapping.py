"""Ledger Mapping CSV/XLSX parser → classification rules for GST Recon.

The mapping file is the "Source of Truth" for classifying Tally ledgers into
Revenue / Output Tax / Input Tax buckets, per the BOOKS_DATA_EXTRACTION_LOGIC
spec. Keyword-only classification is fragile (e.g. "GST IGST SALES 5%" contains
both 'sales' and 'igst'), so we defer to the mapping's Head / Group Parent /
Ledger Name columns.

Columns expected (order-independent, case-normalised):
  Ledger Name | BS or PL | Group Parent | Map to Subhead | Head | Last Mapped Via
"""
from __future__ import annotations
import io
import re
from typing import Any, Dict, List, Set

import pandas as pd


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


def _lower(s: Any) -> str:
    return _norm(s).lower()


def parse_ledger_mapping(content: bytes) -> Dict[str, Any]:
    """Parse mapping XLSX/CSV → {rules, unmapped_candidates, columns, row_count}.

    rules = {
      "revenue":     set of ledger names (Sales / Other Income),
      "output_tax":  set of Output GST ledgers (3B liability source),
      "input_tax":   set of Input GST ledgers (2B / ITC source),
    }
    unmapped_candidates = list of ledger names the parser could not categorise —
    surfaces to the UI's "Pending Classification" list.
    """
    rules: Dict[str, Set[str]] = {"revenue": set(), "output_tax": set(), "input_tax": set()}
    unmapped: List[str] = []
    out: Dict[str, Any] = {"rules": rules, "unmapped_candidates": unmapped,
                           "columns": [], "row_count": 0, "error": None}

    # Read — auto-detect xlsx vs csv by sniffing the first bytes
    try:
        if content.startswith(b"PK"):
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str)
        else:
            df = pd.read_csv(io.BytesIO(content), dtype=str)
    except Exception as e:
        out["error"] = f"Cannot read mapping: {type(e).__name__}: {e}"
        return out

    df = df.fillna("")
    out["row_count"] = int(len(df))

    # Normalise column names
    col_map = {c: _lower(c) for c in df.columns}
    out["columns"] = list(df.columns)
    # Resolve our needed columns tolerantly
    def _find(*candidates: str) -> str:
        for orig, low in col_map.items():
            if low in candidates:
                return orig
        return ""

    col_ledger = _find("ledger name", "name", "ledger")
    col_head   = _find("head")
    col_group  = _find("group parent", "group", "parent group")
    col_sub    = _find("map to subhead", "subhead", "sub head")
    col_bs     = _find("bs or pl", "bs/pl", "bspl", "type")

    if not col_ledger or not col_head:
        out["error"] = "Mapping file missing required 'Ledger Name' or 'Head' columns"
        return out

    # Classification logic
    tax_kw_re = re.compile(r"\b(input|itc|igst|cgst|sgst|output)\b", re.IGNORECASE)
    output_name_re = re.compile(r"\boutput\b.*\b(igst|cgst|sgst|cess)\b", re.IGNORECASE)
    input_name_re  = re.compile(r"\b(input|itc)\b.*\b(igst|cgst|sgst|cess)\b", re.IGNORECASE)
    tax_letter_re  = re.compile(r"\b(igst|cgst|sgst|cess)\b", re.IGNORECASE)

    for _, row in df.iterrows():
        ledger = _norm(row[col_ledger])
        if not ledger:
            continue
        head = _lower(row[col_head])
        group = _lower(row[col_group]) if col_group else ""
        sub = _lower(row[col_sub]) if col_sub else ""

        # MUTUALLY-EXCLUSIVE classification (prevents double-counting tax amounts)
        # Precedence: Output Tax → Input Tax → Revenue
        #   Tax ledgers checked first because some Output/Input ledgers may also
        #   sit under a Sales/Purchase parent group.

        # C. Output Tax (GSTR-3B liability source)
        if group == "output credit" or (
            head == "other current liabilities" and output_name_re.search(ledger)
        ):
            rules["output_tax"].add(ledger)
            continue

        # B. ITC / Input Tax (GSTR-2B source)
        if group == "input credit" or (
            head == "other current assets"
            and ("balance with revenue" in sub or group in ("duties & taxes", "duties and taxes"))
            and (tax_kw_re.search(ledger) or tax_letter_re.search(ledger))
        ):
            rules["input_tax"].add(ledger)
            continue

        # A. Revenue / Outward Supply (Sales source)
        if head in ("revenue from operations", "other income"):
            rules["revenue"].add(ledger)
            continue

        # Not classified — if it looks tax-related, flag for manual review
        if tax_kw_re.search(ledger):
            unmapped.append(ledger)

    return out
