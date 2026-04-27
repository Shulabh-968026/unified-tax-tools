"""Business logic for the 43B(h) MSME Disallowance utility.

Handles Excel/JSON parsing of year-end ageing & Tally payment vouchers and the
Section 43B(h) disallowance computation (exemption -> statutory due date ->
FIFO payment match -> status).
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from rapidfuzz import fuzz, process

from helpers.parsers import norm_str, to_float, parse_date_iso, date_from_iso

STATUTORY_DAYS = 45
FUZZY_THRESHOLD = 85


# ============================ Excel / JSON parsing ============================
def parse_yearend_excel(content: bytes) -> List[Dict[str, Any]]:
    """Parse the Year-End MSME Ageing Excel file into bill dicts."""
    bio = io.BytesIO(content)
    xl = pd.ExcelFile(bio)
    sheet = xl.sheet_names[0]
    df = pd.read_excel(bio, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]
    cols = {c.lower(): c for c in df.columns}

    def col(name: str) -> Optional[str]:
        return cols.get(name.lower())

    bills: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        ledger = norm_str(row.get(col("Ledger Name"), ""))
        if not ledger:
            continue
        bills.append({
            "id": str(uuid.uuid4()),
            "ledger_name": ledger,
            "is_msme": bool(row.get(col("Is MSME"), True)) if col("Is MSME") else True,
            "analysis_type": norm_str(row.get(col("Analysis Type"), "")),
            "voucher_no": norm_str(row.get(col("Voucher No"), "")),
            "voucher_date": parse_date_iso(row.get(col("Voucher Date"))),
            "bill_amount": to_float(row.get(col("Bill Amount"))),
            "due_date": parse_date_iso(row.get(col("Due Date"))),
            "gt_45_days": to_float(row.get(col("> 45 Days"))),
            "overdue_at_year_end": to_float(row.get(col("Overdue at Year End"))),
        })
    return bills


def parse_payments_json(content: bytes) -> List[Dict[str, Any]]:
    """Parse Tally-style JSON; extract Payment vouchers per ledger."""
    data = json.loads(content)
    out: List[Dict[str, Any]] = []
    vouchers = data.get("vouchers", []) if isinstance(data, dict) else []
    for v in vouchers:
        if v.get("voucherTypeName") != "Payment":
            continue
        pay_date = parse_date_iso(v.get("date"))
        for entry in v.get("ledgerEntries", []) or []:
            if entry.get("isPartyLedger") != "Yes":
                continue
            amt = to_float(entry.get("amount"))
            if amt >= 0:
                continue
            ledger = norm_str(entry.get("ledger"))
            if not ledger:
                continue
            out.append({
                "id": str(uuid.uuid4()),
                "ledger_name": ledger,
                "payment_date": pay_date,
                "amount": abs(amt),
                "voucher_number": norm_str(v.get("voucherNumber")),
                "narration": norm_str(v.get("narration")),
            })
    return out


def parse_profiles_excel(content: bytes) -> List[Dict[str, Any]]:
    df = pd.read_excel(io.BytesIO(content))
    df.columns = [str(c).strip() for c in df.columns]
    cols = {c.lower(): c for c in df.columns}

    def col(name: str) -> Optional[str]:
        return cols.get(name.lower())

    profiles: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        ledger_col = col("Creditor Name") or col("Ledger Name")
        ledger = norm_str(row.get(ledger_col)) if ledger_col else ""
        if not ledger:
            continue
        cap_col = col("Capital goods Creditor / Fund Creditor") or col("Capital Goods")
        profiles.append({
            "ledger_name": ledger,
            "msme_number": norm_str(row.get(col("MSME Number"))) if col("MSME Number") else "",
            "sector": norm_str(row.get(col("Sector"))) if col("Sector") else "",
            "msme_type": norm_str(row.get(col("MSME Type"))) if col("MSME Type") else "",
            "capital_goods": norm_str(row.get(cap_col)) if cap_col else "",
        })
    return profiles


# ============================ Computation Engine ============================
def compute_disallowance(
    bills: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    payments: List[Dict[str, Any]],
    force_fifo: bool = False,
) -> Dict[str, Any]:
    """Apply Section 43B(h) rules: Exemption -> Due Date -> FIFO match -> Status."""
    profile_by_name = {p["ledger_name"].strip().lower(): p for p in profiles}
    profile_keys = list(profile_by_name.keys())

    def find_profile(ledger: str) -> Optional[Dict[str, Any]]:
        key = ledger.strip().lower()
        if key in profile_by_name:
            return profile_by_name[key]
        if profile_keys:
            m = process.extractOne(key, profile_keys, scorer=fuzz.token_set_ratio)
            if m and m[1] >= FUZZY_THRESHOLD:
                return profile_by_name[m[0]]
        return None

    bill_ledgers = sorted({b["ledger_name"] for b in bills})
    bill_lower_to_orig = {b.lower(): b for b in bill_ledgers}
    bill_keys = list(bill_lower_to_orig.keys())

    payments_by_bill_ledger: Dict[str, List[Dict[str, Any]]] = {b: [] for b in bill_ledgers}
    for p in payments:
        pl_lower = p["ledger_name"].strip().lower()
        if pl_lower in bill_lower_to_orig:
            payments_by_bill_ledger[bill_lower_to_orig[pl_lower]].append(p)
            continue
        if not bill_keys:
            continue
        m = process.extractOne(pl_lower, bill_keys, scorer=fuzz.token_set_ratio)
        if m and m[1] >= FUZZY_THRESHOLD:
            payments_by_bill_ledger[bill_lower_to_orig[m[0]]].append(p)

    for k in payments_by_bill_ledger:
        payments_by_bill_ledger[k].sort(key=lambda x: x["payment_date"] or "9999-12-31")

    bills_sorted = sorted(bills, key=lambda b: (b["ledger_name"], b["voucher_date"] or "9999-12-31"))
    ledger_groups: Dict[str, List[Dict[str, Any]]] = {}
    for b in bills_sorted:
        ledger_groups.setdefault(b["ledger_name"], []).append(b)

    audit_rows: List[Dict[str, Any]] = []
    for ledger, ledger_bills in ledger_groups.items():
        profile = find_profile(ledger)
        sector = (profile or {}).get("sector") or ""
        msme_type = (profile or {}).get("msme_type") or ""
        capital_goods = (profile or {}).get("capital_goods") or ""
        is_exempt = sector == "Trading" or msme_type == "Medium" or capital_goods == "Yes"

        ledger_payments = list(payments_by_bill_ledger.get(ledger, []))
        bill_clear_info: Dict[str, Dict[str, Any]] = {}
        pay_idx = 0
        pay_remaining = ledger_payments[pay_idx]["amount"] if ledger_payments else 0.0

        for b in ledger_bills:
            need = b["bill_amount"]
            applied_payments: List[Dict[str, Any]] = []
            while need > 0.001 and pay_idx < len(ledger_payments):
                if pay_remaining <= 0.001:
                    pay_idx += 1
                    if pay_idx >= len(ledger_payments):
                        break
                    pay_remaining = ledger_payments[pay_idx]["amount"]
                    continue
                applied = min(need, pay_remaining)
                applied_payments.append({
                    "payment_date": ledger_payments[pay_idx]["payment_date"],
                    "amount": applied,
                    "voucher_number": ledger_payments[pay_idx].get("voucher_number"),
                })
                need -= applied
                pay_remaining -= applied
            fully_paid = need <= 0.001
            clear_date = applied_payments[-1]["payment_date"] if (fully_paid and applied_payments) else None
            bill_clear_info[b["id"]] = {
                "fully_paid": fully_paid,
                "clear_date": clear_date,
                "applied_payments": applied_payments,
                "remaining_unpaid": max(0.0, need),
            }

        for b in ledger_bills:
            info = bill_clear_info.get(b["id"], {"fully_paid": False, "clear_date": None, "applied_payments": [], "remaining_unpaid": b["bill_amount"]})

            fifo_forced = False
            if force_fifo:
                vd = date_from_iso(b["voucher_date"])
                stat_due = (vd + timedelta(days=STATUTORY_DAYS)).isoformat() if vd else None
                due_basis = "Voucher Date + 45 days"
                fifo_forced = b["analysis_type"] != "FIFO" and bool(b["due_date"])
            elif b["analysis_type"] == "FIFO":
                vd = date_from_iso(b["voucher_date"])
                stat_due = (vd + timedelta(days=STATUTORY_DAYS)).isoformat() if vd else None
                due_basis = "FIFO + 45 days"
            else:
                if b["due_date"]:
                    stat_due = b["due_date"]
                    due_basis = "Source Due Date"
                else:
                    vd = date_from_iso(b["voucher_date"])
                    stat_due = (vd + timedelta(days=STATUTORY_DAYS)).isoformat() if vd else None
                    due_basis = "Fallback +45 days"

            stat_due_d = date_from_iso(stat_due)
            clear_d = date_from_iso(info["clear_date"])
            payment_date = info["clear_date"]

            delay_days = (clear_d - stat_due_d).days if (clear_d and stat_due_d) else None
            year_end_flagged = (b["gt_45_days"] > 0) or (b["overdue_at_year_end"] > 0)

            if is_exempt:
                status = "Exempt"
                disallowance = 0.0
                reason = f"Excluded: Sector={sector or '-'}, Type={msme_type or '-'}, CapitalGoods={capital_goods or '-'}"
            else:
                if year_end_flagged and not info["fully_paid"]:
                    status, disallowance = "Disallowed", b["bill_amount"]
                    reason = "Already overdue at year-end and unpaid in subsequent FY"
                elif not info["fully_paid"]:
                    status, disallowance = "Disallowed", b["bill_amount"]
                    reason = "Bill remains unpaid in subsequent FY records"
                elif clear_d and stat_due_d and clear_d > stat_due_d:
                    status, disallowance = "Disallowed", b["bill_amount"]
                    reason = f"Paid {delay_days} day(s) after statutory due date"
                else:
                    status, disallowance = "Allowed", 0.0
                    reason = "Paid within statutory limit"

            audit_rows.append({
                "id": b["id"],
                "ledger_name": ledger,
                "voucher_no": b["voucher_no"],
                "voucher_date": b["voucher_date"],
                "bill_amount": round(b["bill_amount"], 2),
                "analysis_type": b["analysis_type"],
                "source_due_date": b["due_date"],
                "statutory_due_date": stat_due,
                "due_date_basis": due_basis,
                "payment_date": payment_date,
                "delay_days": delay_days,
                "status": status,
                "disallowance": round(disallowance, 2),
                "reason": reason,
                "year_end_flag": "> 45 Days" if b["gt_45_days"] > 0 else ("Overdue at Year End" if b["overdue_at_year_end"] > 0 else ""),
                "fully_paid": info["fully_paid"],
                "remaining_unpaid": round(info["remaining_unpaid"], 2),
                "applied_payments": info["applied_payments"],
                "sector": sector,
                "msme_type": msme_type,
                "capital_goods": capital_goods,
                "fifo_forced": fifo_forced,
            })

    summary = {
        "total_outstanding": round(sum(r["bill_amount"] for r in audit_rows), 2),
        "total_exempt": round(sum(r["bill_amount"] for r in audit_rows if r["status"] == "Exempt"), 2),
        "total_allowed": round(sum(r["bill_amount"] for r in audit_rows if r["status"] == "Allowed"), 2),
        "final_disallowance": round(sum(r["disallowance"] for r in audit_rows), 2),
        "bill_count": len(audit_rows),
        "disallowed_count": sum(1 for r in audit_rows if r["status"] == "Disallowed"),
        "allowed_count": sum(1 for r in audit_rows if r["status"] == "Allowed"),
        "exempt_count": sum(1 for r in audit_rows if r["status"] == "Exempt"),
        "fifo_forced_count": sum(1 for r in audit_rows if r.get("fifo_forced")),
        "force_fifo": bool(force_fifo),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"summary": summary, "audit_rows": audit_rows}


def session_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "client_id": doc.get("client_id"),
        "name": doc.get("name"),
        "fy": doc.get("fy"),
        "scope": doc.get("scope") or "Single scope",
        "source_filename": doc.get("source_filename") or "",
        "payments_filename": doc.get("payments_filename") or "",
        "generated_by": doc.get("generated_by") or "S Dhananjayan",
        "created_at": doc.get("created_at", ""),
        "has_yearend": bool(doc.get("yearend_bills")),
        "has_profiles": bool(doc.get("profiles")),
        "has_payments": bool(doc.get("payments")),
        "has_results": bool(doc.get("results")),
        "yearend_count": len(doc.get("yearend_bills") or []),
        "profile_count": len(doc.get("profiles") or []),
        "payment_count": len(doc.get("payments") or []),
    }
