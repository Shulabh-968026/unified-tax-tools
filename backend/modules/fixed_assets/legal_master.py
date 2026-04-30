"""Income-tax depreciation legal master loader.

The XLSX shipped at `data/it_depreciation_legal_master.xlsx` is the
authoritative reference for the 13 standard IT depreciation block_labels and
their 144 underlying legal entries (Income-tax Appendix I). It is read-only
from the auditor's perspective — admin alone may re-seed when the law changes.

Public surface
--------------
* `seed_legal_master(force=False)` — idempotent loader. Adds rows once, skips
  existing on subsequent calls (or wipes & re-inserts when `force=True`).
* `get_block_labels_active()` — distinct active block_label values.
* `get_practical_groups_active()` — practical_group → block_label mapping.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

import openpyxl

from core.db import db

log = logging.getLogger("fixed_assets.legal_master")

LEGAL_MASTER_COLLECTION = db.fa_legal_master

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data",
                          "it_depreciation_legal_master.xlsx")


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("true", "1", "yes", "y")


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _to_int(v: Any, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _read_master_xlsx() -> List[Dict[str, Any]]:
    """Parse the shipped XLSX into a list of dicts, one per row."""
    if not os.path.exists(_DATA_PATH):
        raise FileNotFoundError(f"Legal master XLSX missing at {_DATA_PATH}")
    wb = openpyxl.load_workbook(_DATA_PATH, data_only=True, read_only=True)
    ws = wb.active
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h or "").strip() for h in row]
            continue
        if not any(c is not None and c != "" for c in row):
            continue
        d = {headers[j]: row[j] for j in range(len(headers))}
        rows.append(d)
    wb.close()

    out: List[Dict[str, Any]] = []
    for d in rows:
        rate = _to_float(d.get("depreciation_rate"))
        out.append({
            "row_id":                       _to_int(d.get("row_id")),
            "appendix_part":                str(d.get("appendix_part") or "").strip(),
            "asset_type":                   str(d.get("asset_type") or "").strip(),
            "main_section_code":            str(d.get("main_section_code") or "").strip(),
            "main_section_name":            str(d.get("main_section_name") or "").strip(),
            "entry_code":                   str(d.get("entry_code") or "").strip(),
            "entry_level_1":                str(d.get("entry_level_1") or "").strip(),
            "entry_level_2":                str(d.get("entry_level_2") or "").strip(),
            "entry_level_3":                str(d.get("entry_level_3") or "").strip(),
            "entry_level_4":                str(d.get("entry_level_4") or "").strip(),
            "legal_entry_text":             str(d.get("legal_entry_text") or "").strip(),
            "practical_group":              str(d.get("practical_group") or "").strip(),
            "block_rate_group":             str(d.get("block_rate_group") or "").strip(),
            "block_label":                  str(d.get("block_label") or "").strip(),
            "depreciation_rate":            rate,
            "rate_unit":                    str(d.get("rate_unit") or "%").strip(),
            "conditional_flag":             _to_bool(d.get("conditional_flag")),
            "condition_summary":            str(d.get("condition_summary") or "").strip(),
            "current_applicability_status": str(d.get("current_applicability_status") or "").strip(),
            "ui_display_name":              str(d.get("ui_display_name") or "").strip(),
            "sort_order":                   _to_int(d.get("sort_order")),
            "is_active":                    _to_bool(d.get("is_active")),
            "source_reference":             str(d.get("source_reference") or "").strip(),
        })
    return out


async def seed_legal_master(force: bool = False) -> int:
    """Idempotent seed of the IT depreciation legal master.

    Returns the number of rows present after seeding.
    """
    existing = await LEGAL_MASTER_COLLECTION.count_documents({})
    if existing and not force:
        return existing

    rows = _read_master_xlsx()
    if not rows:
        log.warning("Legal master file produced no rows")
        return existing

    if force:
        await LEGAL_MASTER_COLLECTION.delete_many({})
    await LEGAL_MASTER_COLLECTION.insert_many(rows)
    log.info(f"Legal master seeded: {len(rows)} rows (force={force})")
    return await LEGAL_MASTER_COLLECTION.count_documents({})


async def list_legal_master(*, active_only: bool = True,
                            block_label: Optional[str] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if active_only:
        q["is_active"] = True
    if block_label:
        q["block_label"] = block_label
    rows = await LEGAL_MASTER_COLLECTION.find(q, {"_id": 0}) \
        .sort([("sort_order", 1), ("row_id", 1)]) \
        .to_list(500)
    return rows


async def get_block_labels_active() -> List[Dict[str, Any]]:
    """Return distinct active block_labels with their canonical rate.

    Output shape: [{block_label, rate, practical_group, count}]
    """
    pipeline = [
        {"$match": {"is_active": True, "block_label": {"$ne": ""}}},
        {"$group": {
            "_id": "$block_label",
            "rate": {"$first": "$depreciation_rate"},
            "practical_group": {"$first": "$practical_group"},
            "block_rate_group": {"$first": "$block_rate_group"},
            "sort_order": {"$min": "$sort_order"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"sort_order": 1, "_id": 1}},
        {"$project": {
            "_id": 0,
            "block_label": "$_id",
            "rate": 1,
            "practical_group": 1,
            "block_rate_group": 1,
            "count": 1,
        }},
    ]
    return await LEGAL_MASTER_COLLECTION.aggregate(pipeline).to_list(50)
