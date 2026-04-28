"""Lightweight monthly aggregators for GST Recon.

Called during upload_batch to pre-extract just the totals needed for the
12-month Turnover & ITC summary, so we never need to keep raw file bodies
in Mongo. Each function tolerates malformed/partial input and returns a
flat dict of floats (or, for Books, a per-period dict).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict


def _f(v: Any) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _round_dict(d: Dict[str, float]) -> Dict[str, float]:
    return {k: round(v, 2) for k, v in d.items()}


# ----------------------------- GSTR-1 ----------------------------------------
def aggregate_gstr1(content: bytes) -> Dict[str, float]:
    """Sum outward taxable + tax across b2b/b2cs/b2cl/cdnr/exp sections.

    Returns: {taxable, igst, cgst, sgst, cess}
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    tot = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}

    # b2b: invoice → items
    for sup in (j.get("b2b") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cgst"]    += _f(d.get("camt"))
                tot["sgst"]    += _f(d.get("samt"))
                tot["cess"]    += _f(d.get("csamt"))
    # b2cl
    for sup in (j.get("b2cl") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cess"]    += _f(d.get("csamt"))
    # b2cs (rate-wise totals — no items)
    for it in (j.get("b2cs") or []):
        tot["taxable"] += _f(it.get("txval"))
        tot["igst"]    += _f(it.get("iamt"))
        tot["cgst"]    += _f(it.get("camt"))
        tot["sgst"]    += _f(it.get("samt"))
        tot["cess"]    += _f(it.get("csamt"))
    # cdnr (credit/debit notes — note type "C" subtracts, "D" adds)
    for sup in (j.get("cdnr") or []):
        for nt in (sup.get("nt") or []):
            sign = -1 if (nt.get("ntty") or "").upper() == "C" else 1
            for x in (nt.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += sign * _f(d.get("txval"))
                tot["igst"]    += sign * _f(d.get("iamt"))
                tot["cgst"]    += sign * _f(d.get("camt"))
                tot["sgst"]    += sign * _f(d.get("samt"))
                tot["cess"]    += sign * _f(d.get("csamt"))
    # exp (export with payment)
    for sup in (j.get("exp") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cess"]    += _f(d.get("csamt"))
    return _round_dict(tot)


# ----------------------------- GSTR-2B ---------------------------------------
def aggregate_gstr2b(content: bytes) -> Dict[str, float]:
    """Prefer itcsumm.itcavl.nonrevsup totals; fallback to docdata.b2b invoice sums.

    Returns: {taxable, igst, cgst, sgst, cess}
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    data = j.get("data") or j

    # 1) itcsumm path — gov format
    summ = ((data.get("itcsumm") or {}).get("itcavl") or {})
    nrs = summ.get("nonrevsup") or {}
    if isinstance(nrs, dict) and nrs:
        igst = cgst = sgst = cess = 0.0
        for v in nrs.values():
            if isinstance(v, dict):
                igst += _f(v.get("iamt"))
                cgst += _f(v.get("camt"))
                sgst += _f(v.get("samt"))
                cess += _f(v.get("csamt"))
        if igst or cgst or sgst or cess:
            return _round_dict({"taxable": 0.0, "igst": igst, "cgst": cgst, "sgst": sgst, "cess": cess})

    # 2) Fallback: walk docdata.b2b invoices
    tot = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
    for sup in ((data.get("docdata") or {}).get("b2b") or []):
        for inv in (sup.get("inv") or []):
            tot["taxable"] += _f(inv.get("txval"))
            tot["igst"]    += _f(inv.get("igst"))
            tot["cgst"]    += _f(inv.get("cgst"))
            tot["sgst"]    += _f(inv.get("sgst"))
            tot["cess"]    += _f(inv.get("cess"))
    return _round_dict(tot)


# ----------------------------- Books -----------------------------------------
def aggregate_books(content: bytes) -> Dict[str, Dict[str, float]]:
    """Group Tally vouchers by MMYYYY → outward/inward taxable + tax buckets.

    Heuristic — voucherTypeName classification:
      - "Sales" / "Service" / "Export" → outward
      - "Purchase" / "Expense"         → inward
    Tax separation by ledger name keywords:
      - "Output IGST/CGST/SGST" or "Input IGST/CGST/SGST" → respective tax bucket
      - everything else under that voucher's tax-prefix is treated as taxable value

    Returns: { "MMYYYY": {out_taxable, out_igst, out_cgst, out_sgst, out_cess,
                          in_taxable, in_igst, in_cgst, in_sgst, in_cess} }
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    out: Dict[str, Dict[str, float]] = {}
    OUT_NAMES = ("sales", "service", "export", "credit note (sales)", "debit note (sales)")
    IN_NAMES  = ("purchase", "expense", "credit note (purchase)", "debit note (purchase)")
    # Income/expense ledger keywords — used to distinguish taxable-value ledgers
    # from the counterparty (debtor/creditor) ledger inside a voucher.
    INCOME_LEDGER_KW = ("sales", "service", "income", "revenue", "export", "freight outward")
    EXPENSE_LEDGER_KW = ("purchase", "expense", "freight inward", "rent", "consum", "raw", "cogs", "salar")
    TAX_KW = ("igst", "cgst", "sgst", "cess")

    def _empty():
        return {
            "out_taxable": 0.0, "out_igst": 0.0, "out_cgst": 0.0, "out_sgst": 0.0, "out_cess": 0.0,
            "in_taxable":  0.0, "in_igst":  0.0, "in_cgst":  0.0, "in_sgst":  0.0, "in_cess":  0.0,
        }

    for v in (j.get("vouchers") or []):
        d = (v.get("date") or "")[:10]
        try:
            dt = datetime.fromisoformat(d).date() if d else None
        except Exception:
            dt = None
        if not dt:
            continue
        period = f"{dt.month:02d}{dt.year}"
        bucket = out.setdefault(period, _empty())

        vtn = (v.get("voucherTypeName") or "").lower()
        is_out = any(n in vtn for n in OUT_NAMES)
        is_in  = any(n in vtn for n in IN_NAMES)
        if not (is_out or is_in):
            continue
        prefix = "out" if is_out else "in"
        income_kw = INCOME_LEDGER_KW if is_out else EXPENSE_LEDGER_KW
        for le in (v.get("ledgerEntries") or []):
            ln = (le.get("ledgerName") or "").lower()
            amt = abs(_f(le.get("amount")))
            if "igst" in ln and ("output" in ln or "input" in ln):
                bucket[f"{prefix}_igst"] += amt
            elif "cgst" in ln and ("output" in ln or "input" in ln):
                bucket[f"{prefix}_cgst"] += amt
            elif "sgst" in ln and ("output" in ln or "input" in ln):
                bucket[f"{prefix}_sgst"] += amt
            elif "cess" in ln and ("output" in ln or "input" in ln):
                bucket[f"{prefix}_cess"] += amt
            elif any(k in ln for k in income_kw) and not any(t in ln for t in TAX_KW):
                # only true income/expense ledgers count as taxable value
                bucket[f"{prefix}_taxable"] += amt
    return {p: _round_dict(b) for p, b in out.items()}
