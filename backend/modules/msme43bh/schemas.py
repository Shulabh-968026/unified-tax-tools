"""Pydantic schemas for the 43B(h) MSME Disallowance utility."""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel

SECTOR_OPTIONS = ["Manufacturing", "Services", "Trading"]
MSME_TYPE_OPTIONS = ["Micro", "Small", "Medium"]


class SessionCreate(BaseModel):
    name: Optional[str] = None
    fy: Optional[str] = None
    client_id: Optional[str] = None
    # Phase C.1 — scope (defaults to consolidation when absent).
    scope_kind: Optional[str] = None
    division_ids: Optional[List[str]] = None
    gstin_group_id: Optional[str] = None


class SessionOut(BaseModel):
    id: str
    client_id: Optional[str] = None
    name: Optional[str] = None
    fy: Optional[str] = None
    scope: Optional[str] = "Single scope"
    source_filename: Optional[str] = ""
    payments_filename: Optional[str] = ""
    generated_by: Optional[str] = "S Dhananjayan"
    created_at: str
    has_yearend: bool = False
    has_profiles: bool = False
    has_payments: bool = False
    has_results: bool = False
    yearend_count: int = 0
    profile_count: int = 0
    payment_count: int = 0


class ProfileRow(BaseModel):
    ledger_name: str
    msme_number: Optional[str] = None
    sector: Optional[str] = None
    msme_type: Optional[str] = None
    capital_goods: Optional[str] = None


class ProfilesUpdate(BaseModel):
    profiles: List[ProfileRow]
