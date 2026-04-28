"""Generic value/date parsing helpers used across modules (43B(h), etc.)."""
from __future__ import annotations

from datetime import datetime, date
from typing import Any, Optional

import pandas as pd


def norm_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return str(v).strip()


def to_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_date_iso(v: Any) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if not s:
        return None
    try:
        return pd.to_datetime(s).date().isoformat()
    except Exception:
        return None


def date_from_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


# ============================ GSTR-3B PDF Parser ============================
def parse_gstr3b_pdf(content: bytes) -> dict:
    """Extract GSTR-3B Table 3.1 (Outward supplies) and Table 4 (ITC) from a PDF.

    Returns dict:
      { "period": "012025", "gstin": "...",
        "table_3_1": {"a": {taxable_value, igst, cgst, sgst, cess}, "b":..., "c":..., "d":..., "e":...},
        "table_4": {
            "a_itc_available": {"igst":..,"cgst":..,"sgst":..,"cess":..},
            "b_itc_reversed":  {...},
            "c_net_itc":       {...},
        }
      }
    Never raises — returns partial with 'errors' list on failure.
    """
    import io, re, pdfplumber

    result = {"period": None, "gstin": None, "table_3_1": {}, "table_4": {}, "errors": []}

    def _num(v):
        if v is None:
            return 0.0
        s = str(v).replace(",", "").replace("₹", "").strip()
        # strip stray single letters (watermarks like "D", "E", "F", "I")
        s = re.sub(r"^[A-Za-z]\s*", "", s).strip()
        if s in ("", "-"):
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)

            # GSTIN
            m = re.search(r"(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][A-Z0-9])", text)
            if m:
                result["gstin"] = m.group(1)

            # Period (e.g. "Period January" + "Year 2024-25")
            m_p = re.search(r"Period\s+(\w+)", text)
            m_y = re.search(r"Year\s+(\d{4})-(\d{2})", text)
            if m_p and m_y:
                months = {"january":"01","february":"02","march":"03","april":"04","may":"05","june":"06",
                          "july":"07","august":"08","september":"09","october":"10","november":"11","december":"12"}
                mm = months.get(m_p.group(1).lower())
                y_start = int(m_y.group(1))
                if mm:
                    yr = str(y_start + (1 if int(mm) <= 3 else 0))
                    result["period"] = mm + yr

            # Walk tables
            all_tables = []
            for p in pdf.pages:
                all_tables.extend(p.extract_tables() or [])

            # Table 3.1: find table whose header row contains "Nature of Supplies" AND first data cell starts with "(a)"
            for t in all_tables:
                if not t or len(t) < 2:
                    continue
                header = " ".join((c or "") for c in t[0]).lower()
                if "nature of supplies" in header and "taxable" in header:
                    # Expect rows (a)..(e). Columns: label, taxable, igst, cgst, sgst, cess
                    for row in t[1:]:
                        if not row or not row[0]:
                            continue
                        label = row[0].strip().lower()
                        key = None
                        if label.startswith("(a)"): key = "a"
                        elif label.startswith("(b)"): key = "b"
                        elif label.startswith("(c"):  key = "c"
                        elif label.startswith("(d)"): key = "d"
                        elif label.startswith("(e)"): key = "e"
                        if key and len(row) >= 6:
                            result["table_3_1"][key] = {
                                "taxable_value": _num(row[1]),
                                "igst": _num(row[2]),
                                "cgst": _num(row[3]),
                                "sgst": _num(row[4]),
                                "cess": _num(row[5]),
                            }
                    if result["table_3_1"]:
                        break

            # Table 4: find rows with "ITC Available" / "Net ITC available" / "ITC Reversed"
            # Aggregate rows across all tables (since gov PDF splits Table 4 across pages)
            avail = {"igst":0.0,"cgst":0.0,"sgst":0.0,"cess":0.0}
            reversed_ = {"igst":0.0,"cgst":0.0,"sgst":0.0,"cess":0.0}
            net = None
            in_avail = False
            in_reversed = False
            for t in all_tables:
                if not t:
                    continue
                header = " ".join((c or "") for c in t[0]).lower()
                if not ("details" in header and "integrated tax" in header):
                    pass  # Table 4 header text — but section flags can still continue across tables
                for row in t:
                    if not row or not row[0]:
                        continue
                    label = (row[0] or "").strip().lower()
                    if "itc available" in label:
                        in_avail, in_reversed = True, False
                        continue
                    if "itc reversed" in label:
                        in_avail, in_reversed = False, True
                        continue
                    if "net itc available" in label and len(row) >= 5:
                        net = {"igst":_num(row[1]),"cgst":_num(row[2]),"sgst":_num(row[3]),"cess":_num(row[4])}
                        in_avail = in_reversed = False
                        continue
                    if "ineligible itc" in label:
                        in_avail = in_reversed = False
                        continue
                    if (in_avail or in_reversed) and re.match(r"^\(\d+\)", label) and len(row) >= 5:
                        bucket = avail if in_avail else reversed_
                        bucket["igst"] += _num(row[1])
                        bucket["cgst"] += _num(row[2])
                        bucket["sgst"] += _num(row[3])
                        bucket["cess"] += _num(row[4])

            if avail["igst"] or avail["cgst"] or avail["sgst"] or avail["cess"] or net:
                result["table_4"] = {
                    "a_itc_available": avail,
                    "b_itc_reversed": reversed_,
                    "c_net_itc": net or {
                        "igst": avail["igst"] - reversed_["igst"],
                        "cgst": avail["cgst"] - reversed_["cgst"],
                        "sgst": avail["sgst"] - reversed_["sgst"],
                        "cess": avail["cess"] - reversed_["cess"],
                    },
                }
    except Exception as e:
        result["errors"].append(f"{type(e).__name__}: {e}")
    return result
