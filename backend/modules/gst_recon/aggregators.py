"""Lightweight monthly aggregators + invoice extractors for GST Recon.

CRITICAL: This module handles Tally JSON (not a generic books format). Key
quirks:
  • ledger entries use key `"ledger"` (NOT `"ledgerName"`)
  • voucher party uses `"partyLedgerName"` (NOT `"partyName"`)
  • sign convention: positive amount = Credit, negative amount = Debit
    (so a Sales voucher has party Dr=-ve, Sales Cr=+ve, Output Tax Cr=+ve)

Ledger classification is driven by the Ledger Mapping XLSX (source of truth).
Use helpers.mapping.parse_ledger_mapping to build the `rules` dict, then pass
it to aggregate_books / extract_books_invoices.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


def _f(v: Any) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _round_dict(d: Dict[str, float]) -> Dict[str, float]:
    return {k: round(v, 2) for k, v in d.items()}


# ============================ GSTR-1 =========================================
def aggregate_gstr1(content: bytes) -> Dict[str, float]:
    """Sum outward taxable + tax across b2b/b2cs/b2cl/cdnr/exp sections.
    Returns {taxable, igst, cgst, sgst, cess}."""
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    tot = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}

    for sup in (j.get("b2b") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cgst"]    += _f(d.get("camt"))
                tot["sgst"]    += _f(d.get("samt"))
                tot["cess"]    += _f(d.get("csamt"))
    for sup in (j.get("b2cl") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cess"]    += _f(d.get("csamt"))
    for it in (j.get("b2cs") or []):
        tot["taxable"] += _f(it.get("txval"))
        tot["igst"]    += _f(it.get("iamt"))
        tot["cgst"]    += _f(it.get("camt"))
        tot["sgst"]    += _f(it.get("samt"))
        tot["cess"]    += _f(it.get("csamt"))
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
    for sup in (j.get("exp") or []):
        for inv in (sup.get("inv") or []):
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                tot["taxable"] += _f(d.get("txval"))
                tot["igst"]    += _f(d.get("iamt"))
                tot["cess"]    += _f(d.get("csamt"))
    return _round_dict(tot)


# ============================ GSTR-2B ========================================
def aggregate_gstr2b(content: bytes) -> Dict[str, float]:
    """Prefer itcsumm.itcavl.nonrevsup totals; fallback to docdata.b2b invoice sums."""
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    data = j.get("data") or j
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

    tot = {"taxable": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
    for sup in ((data.get("docdata") or {}).get("b2b") or []):
        for inv in (sup.get("inv") or []):
            tot["taxable"] += _f(inv.get("txval"))
            tot["igst"]    += _f(inv.get("igst"))
            tot["cgst"]    += _f(inv.get("cgst"))
            tot["sgst"]    += _f(inv.get("sgst"))
            tot["cess"]    += _f(inv.get("cess"))
    return _round_dict(tot)


# ============================ Books (mapping-driven) =========================
_OUT_VTYPES = ("sales", "credit note")            # credit note (sales) reverses sales
_IN_VTYPES  = ("purchase", "debit note", "reverse charges")  # reverse charges = inward RCM


def _tax_letter_bucket(lname_lower: str) -> Optional[str]:
    """Return 'igst' | 'cgst' | 'sgst' | 'cess' or None based on ledger name."""
    if "igst" in lname_lower: return "igst"
    if "cgst" in lname_lower: return "cgst"
    if "sgst" in lname_lower: return "sgst"
    if "cess" in lname_lower: return "cess"
    return None


def _empty_bucket() -> Dict[str, float]:
    return {
        "out_taxable": 0.0, "out_igst": 0.0, "out_cgst": 0.0, "out_sgst": 0.0, "out_cess": 0.0,
        "in_taxable":  0.0, "in_igst":  0.0, "in_cgst":  0.0, "in_sgst":  0.0, "in_cess":  0.0,
    }


def aggregate_books(content: bytes, rules: Optional[Dict[str, Set[str]]] = None) -> Dict[str, Dict[str, float]]:
    """Group Tally vouchers by MMYYYY → outward/inward totals.

    Uses mapping-driven classification when `rules` is provided (from
    helpers.mapping.parse_ledger_mapping). Returns empty dict if no rules and
    no legacy keyword fallback matches.

    Voucher type gates:
      • Sales / Credit Note → outward leg
      • Purchase / Debit Note / Reverse Charges → inward leg
      • Receipt / Payment / Contra / Journal → skipped (no revenue or tax ledger)

    Returns { "MMYYYY": {out_taxable, out_igst, out_cgst, out_sgst, out_cess,
                         in_taxable, in_igst, in_cgst, in_sgst, in_cess} }
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    out: Dict[str, Dict[str, float]] = {}
    rev = (rules or {}).get("revenue") or set()
    out_tax = (rules or {}).get("output_tax") or set()
    in_tax = (rules or {}).get("input_tax") or set()

    for v in (j.get("vouchers") or []):
        d = (v.get("date") or "")[:10]
        try:
            dt = datetime.fromisoformat(d).date() if d else None
        except Exception:
            dt = None
        if not dt:
            continue
        vtn = (v.get("voucherTypeName") or "").lower()
        is_outward = any(n in vtn for n in _OUT_VTYPES)
        is_inward  = any(n in vtn for n in _IN_VTYPES) and "credit note" not in vtn  # credit note → outward
        if not (is_outward or is_inward):
            continue
        period = f"{dt.month:02d}{dt.year}"

        # OUTWARD
        if is_outward:
            # Gate: at least one revenue OR output-tax ledger entry in voucher
            entries = v.get("ledgerEntries") or []
            if not any((le.get("ledger") or "") in rev or (le.get("ledger") or "") in out_tax for le in entries):
                continue
            bucket = out.setdefault(period, _empty_bucket())
            # Sign for outward: sales credit (+ve) contributes +; credit-note reverses (-ve → +abs subtract)
            sign = -1 if "credit note" in vtn else 1
            for le in entries:
                lname = le.get("ledger") or ""
                amt = _f(le.get("amount"))
                # Revenue: credit = positive amount (for Sales). For Credit Note, revenue is debit = -ve.
                if lname in rev:
                    # Take positive credit only; if voucher is credit-note, flip.
                    if amt > 0:
                        bucket["out_taxable"] += sign * amt
                    elif amt < 0 and "credit note" in vtn:
                        bucket["out_taxable"] += abs(amt) * sign  # = -abs, net reduction
                elif lname in out_tax:
                    tb = _tax_letter_bucket(lname.lower())
                    if tb:
                        key = f"out_{tb}"
                        if amt > 0:
                            bucket[key] += sign * amt
                        elif amt < 0 and "credit note" in vtn:
                            bucket[key] += abs(amt) * sign
            continue

        # INWARD
        if is_inward:
            entries = v.get("ledgerEntries") or []
            if not any((le.get("ledger") or "") in in_tax for le in entries):
                continue
            bucket = out.setdefault(period, _empty_bucket())
            sign = -1 if "debit note" in vtn else 1  # debit note → reverses purchase
            tax_total = 0.0
            for le in entries:
                lname = le.get("ledger") or ""
                amt = _f(le.get("amount"))
                if lname in in_tax:
                    tb = _tax_letter_bucket(lname.lower())
                    if tb:
                        # Input tax is a debit = negative amount → take abs
                        val = abs(amt) * sign
                        bucket[f"in_{tb}"] += val
                        tax_total += val
            # Purchase taxable value: infer from party ledger credit minus tax total
            # (party is creditor; Cr entry is +ve amount in Tally)
            party_cr = 0.0
            for le in entries:
                if le.get("isPartyLedger") == "Yes":
                    a = _f(le.get("amount"))
                    if a > 0:
                        party_cr += a
            taxable_est = max(0.0, (party_cr * sign) - tax_total)
            bucket["in_taxable"] += taxable_est

    return {p: _round_dict(b) for p, b in out.items()}


# ============================ Phase D: invoice-level extractors ==============
def extract_books_invoices(content: bytes, rules: Optional[Dict[str, Set[str]]] = None) -> List[Dict[str, Any]]:
    """Return every B2B (party-GSTIN-bearing) sales/purchase voucher as a flat record.

    Requires `rules` dict for accurate tax extraction. Falls back to a blank
    rule-set (emitting records with zero tax amounts) if None.
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return []
    rev = (rules or {}).get("revenue") or set()
    out_tax = (rules or {}).get("output_tax") or set()
    in_tax = (rules or {}).get("input_tax") or set()
    out: List[Dict[str, Any]] = []
    for v in (j.get("vouchers") or []):
        d = (v.get("date") or "")[:10]
        try:
            dt = datetime.fromisoformat(d).date() if d else None
        except Exception:
            dt = None
        if not dt:
            continue
        vtn = (v.get("voucherTypeName") or "").lower()
        is_outward = any(n in vtn for n in _OUT_VTYPES)
        is_inward  = any(n in vtn for n in _IN_VTYPES) and "credit note" not in vtn
        if not (is_outward or is_inward):
            continue
        party_gstin = (v.get("partyGSTIN") or v.get("consigneeGSTIN") or "").upper().strip()
        if not party_gstin:
            continue  # B2C — skip
        party_name = v.get("partyLedgerName") or ""

        entries = v.get("ledgerEntries") or []
        taxable = igst = cgst = sgst = cess = 0.0
        if is_outward:
            for le in entries:
                lname = le.get("ledger") or ""
                amt = _f(le.get("amount"))
                if lname in rev and amt > 0:
                    taxable += amt
                elif lname in out_tax and amt > 0:
                    tb = _tax_letter_bucket(lname.lower())
                    if tb == "igst": igst += amt
                    elif tb == "cgst": cgst += amt
                    elif tb == "sgst": sgst += amt
                    elif tb == "cess": cess += amt
        else:
            tax_total = 0.0
            for le in entries:
                lname = le.get("ledger") or ""
                amt = _f(le.get("amount"))
                if lname in in_tax:
                    tb = _tax_letter_bucket(lname.lower())
                    val = abs(amt)
                    if tb == "igst": igst += val; tax_total += val
                    elif tb == "cgst": cgst += val; tax_total += val
                    elif tb == "sgst": sgst += val; tax_total += val
                    elif tb == "cess": cess += val; tax_total += val
            # Taxable = party-ledger credit minus tax
            party_cr = sum(_f(le.get("amount")) for le in entries
                           if le.get("isPartyLedger") == "Yes" and _f(le.get("amount")) > 0)
            taxable = max(0.0, party_cr - tax_total)

        total = round(taxable + igst + cgst + sgst + cess, 2)
        direction = "outward" if is_outward else "inward"
        out.append({
            "period": f"{dt.month:02d}{dt.year}",
            "direction": direction,
            "party_gstin": party_gstin,
            "party_name": party_name,
            "voucher_no": (v.get("voucherNumber") or "").strip(),
            "voucher_type": v.get("voucherTypeName") or "",
            "date": dt.isoformat(),
            "taxable": round(taxable, 2),
            "igst": round(igst, 2),
            "cgst": round(cgst, 2),
            "sgst": round(sgst, 2),
            "cess": round(cess, 2),
            "total": total,
        })
    return out


def extract_gstr1_invoices(content: bytes, default_period: str = "") -> List[Dict[str, Any]]:
    """Walk GSTR-1 b2b → each invoice as a flat record."""
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return []
    fp = j.get("fp") or default_period or ""
    out: List[Dict[str, Any]] = []
    for sup in (j.get("b2b") or []):
        ctin = (sup.get("ctin") or "").upper().strip()
        trdnm = sup.get("trdnm") or ""
        for inv in (sup.get("inv") or []):
            taxable = igst = cgst = sgst = cess = 0.0
            for x in (inv.get("itms") or []):
                d = x.get("itm_det") or {}
                taxable += _f(d.get("txval"))
                igst    += _f(d.get("iamt"))
                cgst    += _f(d.get("camt"))
                sgst    += _f(d.get("samt"))
                cess    += _f(d.get("csamt"))
            total = round(_f(inv.get("val")) or (taxable + igst + cgst + sgst + cess), 2)
            out.append({
                "period": fp,
                "direction": "outward",
                "party_gstin": ctin,
                "party_name": trdnm,
                "invoice_no": (inv.get("inum") or "").strip(),
                "date": inv.get("idt") or "",
                "taxable": round(taxable, 2),
                "igst": round(igst, 2),
                "cgst": round(cgst, 2),
                "sgst": round(sgst, 2),
                "cess": round(cess, 2),
                "total": total,
            })
    return out


def extract_gstr2b_invoices(content: bytes, default_period: str = "") -> List[Dict[str, Any]]:
    """Walk GSTR-2B docdata.b2b → each invoice as a flat record."""
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except Exception:
        return []
    data = j.get("data") or j
    fp = data.get("rtnprd") or default_period or ""
    out: List[Dict[str, Any]] = []
    for sup in ((data.get("docdata") or {}).get("b2b") or []):
        ctin = (sup.get("ctin") or "").upper().strip()
        trdnm = sup.get("trdnm") or ""
        for inv in (sup.get("inv") or []):
            out.append({
                "period": fp,
                "direction": "inward",
                "party_gstin": ctin,
                "party_name": trdnm,
                "invoice_no": (inv.get("inum") or "").strip(),
                "date": inv.get("dt") or "",
                "taxable": round(_f(inv.get("txval")), 2),
                "igst": round(_f(inv.get("igst")), 2),
                "cgst": round(_f(inv.get("cgst")), 2),
                "sgst": round(_f(inv.get("sgst")), 2),
                "cess": round(_f(inv.get("cess")), 2),
                "total": round(_f(inv.get("val")), 2),
            })
    return out
