"""Pydantic schemas for the Balance Confirmation module."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


CATEGORY = ("trade_receivable", "trade_payable", "bank", "other")
CATEGORY_LABEL = {
    "trade_receivable": "Trade Receivable",
    "trade_payable":    "Trade Payable",
    "bank":             "Bank",
    "other":            "Other",
}
DR_CR = ("dr", "cr")


class RunCreate(BaseModel):
    client_id: str
    fy: str
    name: Optional[str] = ""
    as_at_date: Optional[str] = ""  # YYYY-MM-DD; defaults to FY end on server


class RunOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    fy: str
    name: str = ""
    as_at_date: str = ""
    source_filename: str = ""
    status: str = "draft"
    summary: Optional[dict] = None
    created_at: str
    created_by_name: str = ""
    created_by_email: str = ""


class LedgerOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    ledger_id: str
    run_id: str
    name: str
    parent_group: str = ""
    head:    str = ""
    subhead: str = ""
    category: str
    opening_balance: float = 0.0
    closing_balance: float = 0.0
    dr_cr: str = ""
    email: str = ""
    cc_emails: List[str] = []
    bcc_emails: List[str] = []
    contact_name: str = ""
    address: str = ""
    address_line_1: str = ""
    address_line_2: str = ""
    city: str = ""
    pincode: str = ""
    phone: str = ""
    gstin: str = ""
    pan: str = ""
    response_token: str
    confirmation_status: str = "not_sent"  # not_sent|queued|sent|delivered|opened|confirmed|disputed|bounced
    last_modified: str = ""


class LedgerPatch(BaseModel):
    """Manual edits from the workbench UI — every field optional."""
    category: Optional[str] = None
    email: Optional[str] = None
    cc_emails: Optional[List[str]] = None
    bcc_emails: Optional[List[str]] = None
    contact_name: Optional[str] = None
    address: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    template_id: str
    kind: str  # customer | vendor | bank
    name: str
    subject: str
    html_body: str
    is_default: bool = False
    placeholders: List[str] = []
    created_at: str
    updated_at: str = ""


class TemplateUpsert(BaseModel):
    kind: str = Field(..., description="customer | vendor | bank")
    name: str
    subject: str
    html_body: str


class AuthorizationOut(BaseModel):
    client_id: str
    filename: str
    size: int
    uploaded_at: str
    uploaded_by_name: str = ""


# ============================ Phase 4 — Recipient response =================
class PublicConfirmationCtx(BaseModel):
    """Read-only context shown on /confirm/{token} (no auth)."""
    party_name: str
    contact_name: str = ""
    closing_balance: float = 0.0
    dr_cr: str = ""
    as_at_date: str = ""
    fy: str = ""
    client_name: str = ""
    client_gstin: str = ""
    auditor_firm: str = ""
    auditor_name: str = ""
    confirmation_status: str = "not_sent"
    submitted_response: Optional[Dict[str, Any]] = None


class PublicConfirmRequest(BaseModel):
    responder_name: str = ""
    responder_email: str = ""
    note: str = ""


class PublicDisputeRequest(BaseModel):
    responder_name: str = ""
    responder_email: str = ""
    their_balance: Optional[float] = None
    their_dr_cr: str = ""
    reason: str
