"""Pydantic schemas for the GST Turnover & ITC Reconciliation utility."""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class RunCreate(BaseModel):
    client_id: str
    fy: str  # e.g. "2024-25"
    name: Optional[str] = None


class FileBucketItem(BaseModel):
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
