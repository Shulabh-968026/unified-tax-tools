"""Service layer — Books JSON ingest + ledger CSV import/export."""
from __future__ import annotations
import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from modules.balance_confirmation.classifier import (
    build_group_index,
    classify_ledger,
    dr_cr_indicator,
)


# Email match: very permissive (CSV may be fed by humans).
def _norm_email(s: str) -> str:
    s = (s or "").strip()
    return s if "@" in s else ""


def _split_emails(s: str) -> List[str]:
    if not s:
        return []
    parts = [p.strip() for p in str(s).replace(";", ",").split(",")]
    return [p for p in parts if "@" in p]


def parse_books_json(content: bytes) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse Tally JSON → (company_block, groups[], ledgers[]).

    Raises ValueError on malformed JSON.
    """
    try:
        j = json.loads(content.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid Books JSON: {e.msg} at line {e.lineno}") from e
    if not isinstance(j, dict):
        raise ValueError("Books JSON must be an object at top level")
    return (j.get("company") or {}), (j.get("groups") or []), (j.get("ledgers") or [])


def build_ledger_records(run_id: str,
                         groups: List[Dict[str, Any]],
                         ledgers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify each Tally ledger and emit a flat record ready for Mongo insert.

    ALL ledgers are kept (including 'other' category) so the user can
    re-classify in the UI; we don't silently drop rows.
    """
    g_idx = build_group_index(groups)
    now = datetime.now(timezone.utc).isoformat()
    out: List[Dict[str, Any]] = []
    for L in ledgers or []:
        name = (L.get("name") or "").strip()
        if not name:
            continue
        parent = (L.get("parentGroup") or "").strip()
        category = classify_ledger(parent, g_idx)
        try:
            closing = float(L.get("closingBalance") or 0)
        except (TypeError, ValueError):
            closing = 0.0
        try:
            opening = float(L.get("openingBalance") or 0)
        except (TypeError, ValueError):
            opening = 0.0
        out.append({
            "ledger_id": str(uuid.uuid4()),
            "run_id": run_id,
            "name": name,
            "parent_group": parent,
            "category": category,
            "opening_balance": round(opening, 2),
            "closing_balance": round(closing, 2),
            "dr_cr": dr_cr_indicator(closing),
            "credit_period_days": int(L.get("creditPeriod") or 0),
            "gstin": (L.get("gstNumber") or L.get("gstin") or "").strip().upper(),
            "pan": (L.get("itPan") or L.get("pan") or "").strip().upper(),
            "address": _build_address(L),
            "phone": (L.get("phoneNumber") or L.get("phone") or "").strip(),
            "email": "",
            "cc_emails": [],
            "bcc_emails": [],
            "contact_name": "",
            "response_token": uuid.uuid4().hex,
            "confirmation_status": "not_sent",
            "last_modified": now,
        })
    return out


def _build_address(ledger: Dict[str, Any]) -> str:
    """Tally's ledger has scattered address fields — concatenate the obvious ones."""
    parts = []
    for k in ("addressLine1", "addressLine2", "addressLine3", "city", "state",
              "country", "pinCode"):
        v = (ledger.get(k) or "").strip() if isinstance(ledger.get(k), str) else ""
        if v:
            parts.append(v)
    if not parts:
        # Some exports nest under "address" array
        addr = ledger.get("address")
        if isinstance(addr, list):
            parts.extend([str(a).strip() for a in addr if a])
        elif isinstance(addr, str):
            parts.append(addr.strip())
    return ", ".join(parts)


def summarise_ledgers(ledgers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline counts + amounts per category for the Run summary card."""
    out: Dict[str, Any] = {
        "total": len(ledgers),
        "with_email": 0,
        "categories": {
            "trade_receivable": {"count": 0, "balance": 0.0, "with_email": 0},
            "trade_payable":    {"count": 0, "balance": 0.0, "with_email": 0},
            "bank":             {"count": 0, "balance": 0.0, "with_email": 0},
            "other":            {"count": 0, "balance": 0.0, "with_email": 0},
        },
    }
    for L in ledgers:
        cat = L.get("category") or "other"
        c = out["categories"].get(cat) or out["categories"]["other"]
        c["count"] += 1
        c["balance"] += abs(float(L.get("closing_balance") or 0))
        if L.get("email"):
            c["with_email"] += 1
            out["with_email"] += 1
    for c in out["categories"].values():
        c["balance"] = round(c["balance"], 2)
    return out


# ============================ CSV import / export =============================
EMAIL_CSV_COLUMNS = [
    "ledger_id", "name", "parent_group", "category",
    "closing_balance", "dr_cr",
    "email", "cc_emails", "bcc_emails", "contact_name",
    "phone", "gstin", "pan", "address",
]


def export_email_csv(ledgers: List[Dict[str, Any]]) -> bytes:
    """Export the editable Email Master as CSV bytes (UTF-8 + BOM for Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EMAIL_CSV_COLUMNS)
    for L in ledgers:
        ccs = L.get("cc_emails") or []
        if isinstance(ccs, list):
            ccs = "; ".join(ccs)
        bccs = L.get("bcc_emails") or []
        if isinstance(bccs, list):
            bccs = "; ".join(bccs)
        w.writerow([
            L.get("ledger_id", ""),
            L.get("name", ""),
            L.get("parent_group", ""),
            L.get("category", ""),
            f"{float(L.get('closing_balance') or 0):.2f}",
            (L.get("dr_cr") or "").upper(),
            L.get("email", ""),
            ccs,
            bccs,
            L.get("contact_name", ""),
            L.get("phone", ""),
            L.get("gstin", ""),
            L.get("pan", ""),
            L.get("address", ""),
        ])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def import_email_csv(content: bytes) -> List[Dict[str, Any]]:
    """Parse uploaded CSV → list of {ledger_id, email, cc_emails, bcc_emails,
    contact_name, phone, gstin, pan, address, category} updates. Other
    columns ignored.

    Matching priority: ledger_id (preferred) > exact name (fallback).
    """
    text = content.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    out: List[Dict[str, Any]] = []
    valid_categories = {"trade_receivable", "trade_payable", "bank", "other"}
    for row in rdr:
        rec: Dict[str, Any] = {}
        if row.get("ledger_id"):
            rec["ledger_id"] = row["ledger_id"].strip()
        if row.get("name"):
            rec["name"] = row["name"].strip()
        if "email" in row:
            rec["email"] = _norm_email(row.get("email", ""))
        if "cc_emails" in row:
            rec["cc_emails"] = _split_emails(row.get("cc_emails", ""))
        if "bcc_emails" in row:
            rec["bcc_emails"] = _split_emails(row.get("bcc_emails", ""))
        for k in ("contact_name", "phone", "gstin", "pan", "address"):
            if k in row:
                rec[k] = (row.get(k) or "").strip()
        if row.get("category"):
            cat = row["category"].strip().lower().replace(" ", "_")
            if cat in valid_categories:
                rec["category"] = cat
        if rec.get("ledger_id") or rec.get("name"):
            out.append(rec)
    return out


def fy_end_date(fy: str) -> str:
    """'2024-25' → '2025-03-31'."""
    fy = (fy or "").strip()
    try:
        if "-" in fy and len(fy) >= 7:
            start = int(fy.split("-")[0])
            return f"{start + 1:04d}-03-31"
    except (ValueError, IndexError):
        pass
    return ""
