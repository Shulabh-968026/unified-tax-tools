"""Financial Statement JSON normalizer.

Accepts the pre-aggregated Schedule III FinalStatement JSON emitted by
the client's accounting platform (envelope: ``{"message": {...}}``) and
returns a flat, renderable dict for the PDF templates.

Zero DB dependency — pure function, trivially unit-testable.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional


# --------------------------- helpers -----------------------------------
def _fmt_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII", "XIII", "XIV", "XV"]
_LETTERS = list("abcdefghijklmnopqrstuvwxyz")


def _prefix_for(indent: int, counter: int) -> str:
    """Return the numbering prefix for a given indent level (0 = Roman,
    1 = Arabic, 2 = 'a.', 3 = 'A.')."""
    if indent <= 0:
        return _ROMAN[counter - 1] if 0 < counter <= len(_ROMAN) else str(counter)
    if indent == 1:
        return str(counter)
    if indent == 2:
        ltr = _LETTERS[counter - 1] if 0 < counter <= 26 else str(counter)
        return f"{ltr}."
    if indent == 3:
        ltr = _LETTERS[counter - 1].upper() if 0 < counter <= 26 else str(counter)
        return f"{ltr}."
    return ""


def _render_tree(
    nodes: List[Dict[str, Any]],
    depth: int = 0,
    parent_counters: Optional[Dict[int, int]] = None,
    parent_is_root: bool = False,
    running_root_counter: Optional[List[int]] = None,
    running_sub_counter: Optional[List[int]] = None,
    out: Optional[List[Dict[str, Any]]] = None,
    add_subtotals: bool = True,
) -> List[Dict[str, Any]]:
    """Walk a BS/P&L tree and emit flat rows with numbering prefixes,
    indentation and optional subtotal markers.

    Returns a list of dicts with:
      label, note, current, previous, indent, kind, prefix
    Where ``kind`` is one of: 'header' (indent-0 with children),
    'subhead' (intermediate indent with children), 'leaf', 'subtotal'
    (emitted after closing a subhead's group), 'total' (emitted after
    closing a root header's group).
    """
    if out is None:
        out = []
    if running_root_counter is None:
        running_root_counter = [0]  # mutable int
    if running_sub_counter is None:
        running_sub_counter = [0]
    local_counter = 0  # counter within this parent scope
    for n in nodes or []:
        local_counter += 1
        has_kids = bool(n.get("children"))
        label = str(n.get("account") or "").strip()
        cur = _fmt_float(n.get("total", 0))
        prev = _fmt_float(n.get("previous_total", 0))
        note = n.get("note_number") or ""
        if depth == 0:
            running_root_counter[0] += 1
            counter = running_root_counter[0]
            prefix = _prefix_for(0, counter)
            kind = "header" if has_kids else "root_line"
        elif depth == 1:
            running_sub_counter[0] += 1
            counter = running_sub_counter[0]
            prefix = _prefix_for(1, counter)
            kind = "subhead" if has_kids else "leaf"
        else:
            counter = local_counter
            prefix = _prefix_for(depth, counter)
            kind = "subhead" if has_kids else "leaf"

        out.append({
            "label":    label,
            "note":     note,
            "current":  cur,
            "previous": prev,
            "indent":   depth,
            "kind":     kind,
            "prefix":   prefix,
        })
        if has_kids:
            # Recurse with reset sub counter when we enter a new indent-1
            if depth == 0:
                running_sub_counter[0] = 0
            _render_tree(
                n["children"], depth + 1,
                parent_counters=parent_counters,
                parent_is_root=(depth == 0),
                running_root_counter=running_root_counter,
                running_sub_counter=running_sub_counter,
                out=out,
                add_subtotals=add_subtotals,
            )
            if add_subtotals:
                if depth == 1:
                    # Emit "Total(N)" subtotal for this closed subhead
                    out.append({
                        "label":    f"Total({counter})",
                        "note":     "",
                        "current":  cur,
                        "previous": prev,
                        "indent":   1,
                        "kind":     "subtotal",
                        "prefix":   "",
                    })
                elif depth == 0:
                    # Emit "TOTAL (X)" for closed root section
                    out.append({
                        "label":    f"TOTAL ({prefix})",
                        "note":     "",
                        "current":  cur,
                        "previous": prev,
                        "indent":   0,
                        "kind":     "total",
                        "prefix":   "",
                    })
            if depth == 0:
                running_sub_counter[0] = 0  # reset for next root
    return out


def _flatten_cashflow(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten cash-flow `report_data` — already sequenced in source, just
    project the fields we need for rendering."""
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        amts = r.get("amounts") or {}
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


def _flatten_tree_simple(nodes, depth=0, out=None):
    if out is None:
        out = []
    for n in nodes or []:
        out.append({
            "label":    str(n.get("account") or ""),
            "current":  _fmt_float(n.get("total", 0)),
            "previous": _fmt_float(n.get("previous_total", 0)),
            "indent":   depth,
            "has_children": bool(n.get("children")),
        })
        if n.get("children"):
            _flatten_tree_simple(n["children"], depth + 1, out)
    return out


def _walk_note_titles(
    rows: List[Dict[str, Any]],
    parent_label: str = "",
    out: Optional[Dict[int, Dict[str, str]]] = None,
) -> Dict[int, Dict[str, str]]:
    """Walk a BS/P&L tree and emit a {note_number: {leaf, parent}} map.

    The leaf label is the source-of-truth title for that note (the JSON's
    ``notes_report.account`` sometimes wrongly carries the parent group
    label, e.g. note 1 shows up as "Shareholders' Funds" instead of
    "Share Capital")."""
    if out is None:
        out = {}
    for r in rows or []:
        nn = r.get("note_number")
        try:
            nn = int(nn) if nn not in (None, "") else None
        except (TypeError, ValueError):
            nn = None
        if nn:
            out[nn] = {"leaf": str(r.get("account") or ""),
                       "parent": parent_label}
        if r.get("children"):
            _walk_note_titles(r["children"], r.get("account", ""), out)
    return out


def _notes_with_details(
    notes: List[Dict[str, Any]],
    details: List[Dict[str, Any]],
    fa: Optional[Dict[str, Any]] = None,
    title_map: Optional[Dict[int, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Build the Notes-to-Financial-Statements block.

    Title-resolution rules (kept aligned with the reference final-statement
    style):
      • Use the BS/P&L tree leaf label as the canonical title (the JSON's
        ``notes_report.account`` is unreliable for some wrapper notes —
        e.g. Note 1 shows up as "Shareholders' Funds" instead of "Share
        Capital").
      • Sub-items come from ``notes_report.children`` (lettered a./b./c.).
        When a wrapper note carries a single child whose label matches the
        canonical title, drop one level and surface its grandchildren.
      • When ``children`` is empty but ``notes_report.account`` differs
        from the title, the account itself becomes a single sub-item
        (e.g. Note 6 "Other Current Liabilities" → "a. Statutory Dues
        Payable").
      • Synthesize Note 8 (PPE) — it isn't in ``notes_report``, lives in
        ``fixed_asset_report``.
    """
    title_map = title_map or {}
    out: List[Dict[str, Any]] = []
    have_note_8 = False

    for n in notes or []:
        nn = n.get("note_number")
        try:
            nn_int = int(nn) if nn not in (None, "") else None
        except (TypeError, ValueError):
            nn_int = None
        if nn_int == 8:
            have_note_8 = True

        canonical_title = (
            (title_map.get(nn_int) or {}).get("leaf")
            or str(n.get("account") or "")
        )

        # Decide sub-items
        children = n.get("children") or []
        unwrapped = False
        # Capture the row used as source-of-truth for the note total —
        # falls back to the parent unless we drill into a wrapper child.
        eff_row = n
        # Wrapper case: 1 child whose label == canonical_title → drill in
        if (len(children) == 1
                and str(children[0].get("account") or "").strip().lower()
                == canonical_title.strip().lower()):
            eff_row = children[0]
            children = eff_row.get("children") or []
            unwrapped = True

        subitems: List[Dict[str, Any]] = []
        for i, c in enumerate(children):
            letter = _LETTERS[i] if i < len(_LETTERS) else str(i + 1)
            subitems.append({
                "prefix":   f"{letter}.",
                "label":    str(c.get("account") or ""),
                "current":  _fmt_float(c.get("total", 0)),
                "previous": _fmt_float(c.get("previous_total", 0)),
                "indent":   0,
                "detail_number": c.get("detail_number") or (i + 1),
            })

        # Fallback: if no children AND we didn't already unwrap (which
        # signals a special note like Note 1 Share Capital where the
        # source data doesn't carry a/b/c lines), and the JSON's account
        # differs from the canonical title, treat the account as the
        # single 'a.' sub-item (matches the reference for notes 6/7/10/12
        # etc.).
        # Skip the fallback for Note 8 — it's the PPE matrix block which
        # is rendered separately.
        if not subitems and not unwrapped and nn_int != 8:
            jsn_acc = str(n.get("account") or "").strip()
            if jsn_acc and jsn_acc.lower() != canonical_title.strip().lower():
                subitems.append({
                    "prefix":   "a.",
                    "label":    jsn_acc,
                    "current":  _fmt_float(n.get("total", 0)),
                    "previous": _fmt_float(n.get("previous_total", 0)),
                    "indent":   0,
                    "detail_number": 1,
                })

        # Note 8 in notes_report is the P&L Depreciation note. The
        # reference renders Note 8 as the PPE schedule (BS leaf). Force
        # the PPE values + clear sub-items so the renderer attaches its
        # special matrix block.
        if nn_int == 8 and fa and (fa.get("subheads") or fa.get("total")):
            ppe_total = _fmt_float((fa.get("total") or {}).get("closing_written_down_value", 0))
            ppe_prev = _fmt_float((fa.get("prev_total") or {}).get("closing_written_down_value", 0))
            out.append({
                "note":     8,
                "title":    canonical_title or "Property, Plant and Equipment",
                "current":  ppe_total,
                "previous": ppe_prev,
                "subitems": [],
            })
            continue

        out.append({
            "note":     nn_int,
            "title":    canonical_title,
            "current":  _fmt_float(eff_row.get("total", 0)),
            "previous": _fmt_float(eff_row.get("previous_total", 0)),
            "subitems": subitems,
        })

    if not have_note_8 and fa and (fa.get("subheads") or fa.get("total")):
        ppe_total = _fmt_float((fa.get("total") or {}).get("closing_written_down_value", 0))
        ppe_prev = _fmt_float((fa.get("prev_total") or {}).get("closing_written_down_value", 0))
        synth = {
            "note":     8,
            "title":    (title_map.get(8) or {}).get("leaf", "Property, Plant and Equipment"),
            "current":  ppe_total,
            "previous": ppe_prev,
            "subitems": [],
        }
        idx = next(
            (i for i, r in enumerate(out)
             if r.get("note") is not None and r["note"] > 8),
            len(out),
        )
        out.insert(idx, synth)
    return out


def _details_sections(
    details: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the "Details to Financial Statements" section.

    Each row in ``details_report`` represents a lettered sub-item under a
    parent note (e.g. "3 (a) Term Loans from Banks") with its underlying
    ledger-level leaves.  The output is flat — caller loops through and
    renders ``N (letter)`` headers followed by the leaf rows.
    """
    out: List[Dict[str, Any]] = []
    for d in details or []:
        nn = d.get("note_number")
        dn = d.get("detail_number")
        try:
            nn_int = int(nn) if nn not in (None, "") else None
        except (TypeError, ValueError):
            nn_int = None
        try:
            dn_int = int(dn) if dn not in (None, "") else 1
        except (TypeError, ValueError):
            dn_int = 1
        letter = _LETTERS[dn_int - 1] if 0 < dn_int <= len(_LETTERS) else str(dn_int)
        leaves = []
        for c in d.get("children") or []:
            leaves.append({
                "label":    str(c.get("account") or ""),
                "current":  _fmt_float(c.get("total", 0)),
                "previous": _fmt_float(c.get("previous_total", 0)),
            })
        out.append({
            "note":     nn_int,
            "detail":   dn_int,
            "ref":      f"{nn_int} ({letter})" if nn_int is not None else f"({letter})",
            "title":    str(d.get("account") or ""),
            "current":  _fmt_float(d.get("total", 0)),
            "previous": _fmt_float(d.get("previous_total", 0)),
            "leaves":   leaves,
        })
    return out


def _normalize_ageing(ageing: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten the ageing_report per FY and per category into renderable
    rows. Output: {'trade payables': {fy: {rows, buckets}}, ...}."""
    out: Dict[str, Any] = {}
    bucket_keys = ("not_due", "less_than_a_year", "one_to_two_years",
                   "two_to_three_years", "more_than_three_years", "total")
    for fy, cats in (ageing or {}).items():
        if not isinstance(cats, dict):
            continue
        for cat, blk in cats.items():
            if not isinstance(blk, dict):
                continue
            rows = []
            for r in blk.get("rows", []) or []:
                if not isinstance(r, dict):
                    continue
                rows.append({
                    "label": r.get("row_header", ""),
                    "type":  r.get("row_type", "value_row"),
                    **{k: _fmt_float(r.get(k, 0)) for k in bucket_keys},
                })
            if rows:
                out.setdefault(cat, {})[fy] = {
                    "rows":   rows,
                    "header": (blk.get("meta_data") or {}).get(
                        "amount_group_header",
                        "Outstanding for the following periods from the due date for payment",
                    ),
                }
    return out


def _flatten_fa(fa: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the PPE schedule as a renderable block."""
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
    if not isinstance(addr, dict):
        return ""
    node = addr.get("office") or next(
        (v for v in addr.values() if isinstance(v, dict)), {}
    )
    parts = [
        node.get("door_no"), node.get("residence_name"),
        node.get("street"), node.get("locality"),
        node.get("city"), node.get("pincode"),
    ]
    return ", ".join([str(p).strip() for p in parts if p and str(p).strip()])


def _short_city(addr: Dict[str, Any]) -> str:
    """Return just the city/state line for the page header — the reference
    PDF shows e.g. 'NALLUR , TIRUPUR' not the full address."""
    if not isinstance(addr, dict):
        return ""
    node = addr.get("office") or next(
        (v for v in addr.values() if isinstance(v, dict)), {}
    )
    return str(node.get("city") or "").strip()


def _fy_label(iso_or_text_start: str) -> str:
    if not iso_or_text_start:
        return ""
    m = re.search(r"(\d{4})", str(iso_or_text_start))
    if not m:
        return str(iso_or_text_start)
    y = int(m.group(1))
    return f"{y}-{str(y + 1)[2:]}"


def _end_ddmmyyyy(iso_or_text_end: str) -> str:
    """Return DD/MM/YYYY from a date string like '31 March 2025' or
    '2025-03-31'."""
    s = str(iso_or_text_end or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    # Text form like '31 March 2025'
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s, re.I)
    if m:
        mm = months.get(m.group(2).lower(), "")
        if mm:
            return f"{int(m.group(1)):02d}/{mm}/{m.group(3)}"
    return s


def _long_end_date(iso_or_text_end: str) -> str:
    """Return 'DD Month YYYY' with ordinal suffix, e.g. '31st March 2025'."""
    s = str(iso_or_text_end or "").strip()
    if not s:
        return ""
    months_n = {
        "01": "January", "02": "February", "03": "March", "04": "April",
        "05": "May", "06": "June", "07": "July", "08": "August",
        "09": "September", "10": "October", "11": "November", "12": "December",
    }
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        day = int(m.group(3))
        mname = months_n.get(m.group(2), "")
        year = m.group(1)
    else:
        mt = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s, re.I)
        if not mt:
            return s
        day = int(mt.group(1))
        mname = mt.group(2).capitalize()
        year = mt.group(3)
    suffix = "th"
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {mname} {year}"


def _signatory(raw_sig: Dict[str, Any], client_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enrich the signatory block with CIN (from client record) and a
    clean directors list."""
    sig = raw_sig or {}
    roles = sig.get("authorized_signatory_role") or []
    directors = []
    for r in roles:
        directors.append({
            "name": r.get("autho_name") or "",
            "role": r.get("autho_role") or "Director",
            "din":  r.get("din") or "",
        })
    # Display report date as DD-MM-YYYY if ISO
    raw_date = sig.get("reportDate", "") or ""
    disp_date = raw_date
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(raw_date))
    if m:
        disp_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return {
        "firm_name":           sig.get("signatory_firm_name", ""),
        "firm_registration":   sig.get("firm_registration_number", ""),
        "firm_text":           sig.get("firmText", "") or "For " + (sig.get("signatory_firm_name") or ""),
        "client_text":         sig.get("clientText", ""),
        "partner_name":        sig.get("signatories_client", ""),  # signing partner
        "partner_title":       sig.get("title", "Partner"),
        "membership_number":   sig.get("membership_number", ""),
        "place":               sig.get("place", ""),
        "date":                disp_date,
        "udin":                sig.get("udin", ""),
        "text_on_top":         sig.get("textOnTop", "Subject to our report of even date"),
        "directors":           directors,
        "cin":                 (client_record or {}).get("cin", ""),
    }


def normalize_final_statement(
    raw: Dict[str, Any],
    client_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize a FinalStatement JSON envelope."""
    if not isinstance(raw, dict):
        raise ValueError("JSON must be an object")
    msg = raw.get("message") if "message" in raw else raw
    if not isinstance(msg, dict):
        raise ValueError("`message` must be an object")
    if "balance_sheet_report" not in msg or "profit_or_loss_report" not in msg:
        raise ValueError(
            "This does not look like a FinalStatement JSON — expected "
            "`message.balance_sheet_report` and `message.profit_or_loss_report`.")

    signatory = (msg.get("signatory_details") or [{}])[0]
    cfs_rows = (msg.get("cash_flow_report") or {}).get("report_data") or []
    # Build note title map. P&L first, then BS — BS leaf labels take
    # precedence so that note 8 (shared by PPE & Depreciation) resolves
    # to "Property, Plant and Equipment" (the canonical BS title).
    title_map = _walk_note_titles(msg.get("profit_or_loss_report") or [])
    title_map.update(_walk_note_titles(msg.get("balance_sheet_report") or []))

    return {
        "company": {
            "name":    msg.get("client_name", "").strip(),
            "address": _format_address(msg.get("client_address") or {}),
            "city":    _short_city(msg.get("client_address") or {}),
            "cin":     (client_record or {}).get("cin", ""),
        },
        "period": {
            "current_start":  msg.get("current_period_start_date", ""),
            "current_end":    msg.get("current_period_end_date", ""),
            "previous_start": msg.get("previous_period_start_date", ""),
            "previous_end":   msg.get("previous_period_end_date", ""),
            "fy_current":     _fy_label(msg.get("current_period_start_date", "")),
            "fy_previous":    _fy_label(msg.get("previous_period_start_date", "")),
            "current_end_short":  _end_ddmmyyyy(msg.get("current_period_end_date", "")),
            "previous_end_short": _end_ddmmyyyy(msg.get("previous_period_end_date", "")),
            "current_end_long":   _long_end_date(msg.get("current_period_end_date", "")),
        },
        "balance_sheet": _render_tree(msg.get("balance_sheet_report") or []),
        "profit_loss":   _render_tree(msg.get("profit_or_loss_report") or []),
        "cash_flow":     _flatten_cashflow(cfs_rows),
        "notes":         _notes_with_details(
            msg.get("notes_report") or [],
            msg.get("details_report") or [],
            fa=_flatten_fa(msg.get("fixed_asset_report") or {}),
            title_map=title_map,
        ),
        "details":       _details_sections(msg.get("details_report") or []),
        "ageing":        _normalize_ageing(msg.get("ageing_report") or {}),
        "fixed_asset":   _flatten_fa(msg.get("fixed_asset_report") or {}),
        "signatory":     _signatory(signatory, client_record),
        "counts": {
            "notes":   len(msg.get("notes_report") or []),
            "details": len(msg.get("details_report") or []),
        },
    }


__all__ = ["normalize_final_statement"]
