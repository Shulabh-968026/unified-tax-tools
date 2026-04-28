"""Pydantic schemas for the GST Turnover & ITC Reconciliation utility."""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    client_id: str
    fy: str  # e.g. "2024-25"
    name: Optional[str] = None


class FileBucketItem(BaseModel):
    """File entry on a run. Phase C extras (r1_outward, r2b_itc, books_per_month,
    table_3_1, table_4, integrity_ok, parse_error, books_from/to) flow through
    via `extra=allow` so they survive the response_model filter."""
    model_config = ConfigDict(extra="allow")

    filename: str
    bucket: str        # "gstr1" | "gstr2b" | "gstr3b" | "books" | "mapping" | "unknown"
    period: Optional[str] = None   # "MMYYYY" for monthly files
    gstin: Optional[str] = None
    size: int = 0


class MonthStatus(BaseModel):
    period: str        # "MMYYYY" (e.g. "042024")
    month_label: str   # "Apr 2024"
    gstr1: bool = False
    gstr2b: bool = False
    gstr3b: bool = False


class RunOut(BaseModel):
    # extra='allow' so mapping_rules / mapping_unmapped_ledgers / mapping_row_count /
    # mapping_filename / created_by survive the GET /runs/{rid} response filter.
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    fy: str
    name: Optional[str] = None
    created_at: str
    status: str = "draft"
    files: List[FileBucketItem] = []
    months: List[MonthStatus] = []
    has_books: bool = False
    has_mapping: bool = False
    validation: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
