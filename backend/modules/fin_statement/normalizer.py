"""Financial Statement JSON normalizer.

Accepts the pre-aggregated Schedule III FinalStatement JSON emitted by
the client's accounting platform (envelope: ``{"message": {...}}``) and
returns a flat, renderable dict for the PDF templates.

Zero DB dependency — pure function, trivially unit-testable.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


def _fmt_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _flatten_tree(
    nodes: List[Dict[str, Any]],
    depth: int = 0,
    out: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Walk a BS/P&L tree (``account`` / ``children`` / ``note_number``) and
    emit flat rows with an ``indent`` level, preserving order."""
    if out is None:
        out = []
    for n in nodes or []:
        out.append({
            "label":    str(n.get("account") or n.get("row_header") or ""),
            "note":     n.get("note_number") or "",
            "current":  _fmt_float(n.get("total", 0)),
            "previous": _fmt_float(n.get("previous_total", 0)),
            "indent":   depth,
            "is_header": bool(n.get("children")) and depth == 0,
            "is_subtotal": bool(n.get("children")) and depth > 0,
        })
        kids = n.get("children") or []
        if kids:
            _flatten_tree(kids, depth + 1, out)
    return out


def _flatten_cashflow(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten cash-flow `report_data` rows. They're already sequenced so we
    just project out the fields we need."""
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        amts = r.get("amounts") or {}
        # Amounts are keyed by FY string e.g. "2024-2025". We pick the
        # latest FY as "current", second-latest as "previous".
        fys = sorted([k for k in amts.keys() if k], reverse=True)
        cy_key = fys[0] if fys else None
        py_key = fys[1] if len(fys) > 1 else None
        out.append({
            "serial":   r.get("serial_number") or r.get("serial_number_constant") or "",
            "label":    r.get("row_header") or "",
            "current":  _fmt_float(amts.get(cy_key)) if cy_key else 0.0,
            "previous": _fmt_float(amts.get(py_key)) if py_key else 0.0,
            "indent":   int(r.get("indentation_level") or 0),
            "is_header":    bool(r.get("header_bold")),
            "header_underline": bool(r.get("header_underline")),
            "is_bold":      bool(r.get("value_bold")),
            "row_id":   r.get("row_id") or "",
            "blank_below": bool(r.get("blank_row_bottom")),
            "line_top":    r.get("value_line_top") or "NONE",
            "line_below":  r.get("value_line_below") or "NONE",
        })
    return out


def _notes_with_details(
    notes: List[Dict[str, Any]],
    details: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Group detail rows under their parent note so each note block
    carries its own sub-ledger breakdown."""
    by_note: Dict[int, List[Dict[str, Any]]] = {}
    for d in details or []:
        nn = d.get("note_number")
        if nn is None:
            continue
        try:
            nn = int(nn)
        except (TypeError, ValueError):
            continue
        by_note.setdefault(nn, []).append(d)

    out: List[Dict[str, Any]] = []
    for n in notes or []:
        nn = n.get("note_number")
        try:
            nn_int = int(nn) if nn not in (None, "") else None
        except (TypeError, ValueError):
            nn_int = None
        # Flatten the detail rows under this note, same tree shape
        detail_rows = _flatten_tree(by_note.get(nn_int, [])) if nn_int else []
        out.append({
            "note":     nn_int,
            "title":    str(n.get("account") or ""),
            "current":  _fmt_float(n.get("total", 0)),
            "previous": _fmt_float(n.get("previous_total", 0)),
            "details":  detail_rows,
            "children": _flatten_tree(n.get("children") or []),
        })
    return out


def _flatten_fa(fa: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the Fixed Assets / PPE schedule as a renderable block."""
    if not fa:
        return {}
    subheads = fa.get("subheads") or []
    total = fa.get("total") or {}
    prev_subheads = fa.get("previous_year_subheads") or []
    prev_total = fa.get("previous_total") or {}
    fields = ("opening_cost", "additions", "deletions", "closing_cost",
              "opening_depreciation", "depreciation_for_year",
              "depreciation_withdrawn", "closing_depreciation",
              "closing_written_down_value")

    def row(x):
        return {
            "label": x.get("display_subhead_name") or x.get("subhead_name") or "",
            **{f: _fmt_float(x.get(f, 0)) for f in fields},
        }
    return {
        "subheads":      [row(s) for s in subheads],
        "total":         {f: _fmt_float(total.get(f, 0)) for f in fields},
        "prev_subheads": [row(s) for s in prev_subheads],
        "prev_total":    {f: _fmt_float(prev_total.get(f, 0)) for f in fields},
    }


def _format_address(addr: Dict[str, Any]) -> str:
    """Flatten the nested client_address into a single one-line string."""
    if not isinstance(addr, dict):
        return ""
    # Prefer the `office` node, fall back to whatever first node exists
    node = addr.get("office") or next(
        (v for v in addr.values() if isinstance(v, dict)), {}
    )
    parts = [
        node.get("door_no"),
        node.get("residence_name"),
        node.get("street"),
        node.get("locality"),
        node.get("city"),
        node.get("pincode"),
    ]
    return ", ".join([str(p).strip() for p in parts if p and str(p).strip()])


def normalize_final_statement(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a FinalStatement JSON envelope.

    Input may be either the envelope ``{"message": {...}}`` or the inner
    dict directly.
    """
    if not isinstance(raw, dict):
        raise ValueError("JSON must be an object")
    msg = raw.get("message") if "message" in raw else raw
    if not isinstance(msg, dict):
        raise ValueError("`message` must be an object")
    if "balance_sheet_report" not in msg or "profit_or_loss_report" not in msg:
        raise ValueError(
            "This does not look like a FinalStatement JSON — expected "
            "`message.balance_sheet_report` and `message.profit_or_loss_report`."
        )

    signatory = (msg.get("signatory_details") or [{}])[0]
    cfs_rows = (msg.get("cash_flow_report") or {}).get("report_data") or []

    return {
        "company": {
            "name":    msg.get("client_name", "").strip(),
            "address": _format_address(msg.get("client_address") or {}),
        },
        "period": {
            "current_start":  msg.get("current_period_start_date", ""),
            "current_end":    msg.get("current_period_end_date", ""),
            "previous_start": msg.get("previous_period_start_date", ""),
            "previous_end":   msg.get("previous_period_end_date", ""),
            "fy_current":     _fy_label(msg.get("current_period_start_date", "")),
            "fy_previous":    _fy_label(msg.get("previous_period_start_date", "")),
        },
        "balance_sheet": _flatten_tree(msg.get("balance_sheet_report") or []),
        "profit_loss":   _flatten_tree(msg.get("profit_or_loss_report") or []),
        "cash_flow":     _flatten_cashflow(cfs_rows),
        "notes":         _notes_with_details(
            msg.get("notes_report") or [],
            msg.get("details_report") or [],
        ),
        "fixed_asset":   _flatten_fa(msg.get("fixed_asset_report") or {}),
        "ageing":        msg.get("ageing_report") or {},
        "signatory": {
            "firm_name":           signatory.get("signatory_firm_name", ""),
            "firm_registration":   signatory.get("firm_registration_number", ""),
            "firm_text":           signatory.get("firmText", ""),
            "client_text":         signatory.get("clientText", ""),
            "place":               signatory.get("place", ""),
            "date":                signatory.get("reportDate", ""),
            "membership_number":   signatory.get("membership_number", ""),
            "title":               signatory.get("title", ""),
            "text_on_top":         signatory.get("textOnTop", ""),
            "udin":                signatory.get("udin", ""),
            "signatories_client":  signatory.get("signatories_client", ""),
            "auth_roles":          signatory.get("authorized_signatory_role", []) or [],
        },
        "counts": {
            "notes":   len(msg.get("notes_report") or []),
            "details": len(msg.get("details_report") or []),
        },
    }


def _fy_label(iso_or_text_start: str) -> str:
    """Derive 'YYYY-YY' label from a start-date string like '01 April 2024'
    or '2024-04-01'."""
    if not iso_or_text_start:
        return ""
    s = str(iso_or_text_start)
    # Try ISO
    import re
    m = re.search(r"(\d{4})", s)
    if not m:
        return s
    y = int(m.group(1))
    return f"{y}-{str(y + 1)[2:]}"


__all__ = ["normalize_final_statement"]
