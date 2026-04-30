"""Pydantic schemas — Fixed Assets / IT Depreciation module."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# ============================ Runs ===========================================
class FaRunCreate(BaseModel):
    client_id: str
    fy: str               # e.g. "2024-25"
    name: Optional[str] = ""
    fy_start: Optional[str] = ""  # YYYY-MM-DD; auto-derived from FY when missing
    fy_end: Optional[str] = ""    # YYYY-MM-DD


class FaRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    fy: str
    fy_start: str = ""
    fy_end: str = ""
    name: str = ""
    status: str = "draft"   # draft | classified | computed | finalized
    source_filename: str = ""
    summary: Optional[Dict[str, Any]] = None
    created_at: str
    created_by_name: str = ""
    created_by_email: str = ""
    rolled_from_run_id: str = ""  # multi-FY continuity


# ============================ Legal Master ==================================
class LegalMasterRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    row_id: int
    block_label: str
    ui_display_name: str
    legal_entry_text: str = ""
    practical_group: str = ""
    block_rate_group: str = ""
    depreciation_rate: float
    rate_unit: str = ""
    asset_type: str = ""
    main_section_name: str = ""
    appendix_part: str = ""
    current_applicability_status: str = ""
    sort_order: int = 0
    is_active: bool = True


# ============================ FA Ledger (post-classification) ================
CLASSIFICATION_STATUS = ("pending", "auto_suggested", "confirmed", "skipped")


class FaLedgerOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    fa_ledger_id: str
    run_id: str
    name: str
    parent_group: str = ""
    opening_balance: float = 0.0
    closing_balance: float = 0.0
    addition_count: int = 0
    deletion_count: int = 0
    block_label: str = ""
    legal_master_row_id: Optional[int] = None
    classification_status: str = "pending"  # pending | auto_suggested | confirmed | skipped
    classification_note: str = ""
    last_modified: str = ""


class FaLedgerClassifyRequest(BaseModel):
    block_label: str
    legal_master_row_id: int
    note: Optional[str] = ""
    confirm: bool = True


# ============================ Additions / Deletions =========================
class FaAdditionOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    addition_id: str
    run_id: str
    fa_ledger_id: str
    block_label: str = ""
    voucher_id: str = ""
    voucher_no: str = ""
    voucher_type: str = ""
    accounting_date: str = ""
    invoice_date: str = ""
    invoice_date_source: str = ""  # narration | accounting_fallback
    put_to_use_date: str = ""
    party_name: str = ""
    particulars: str = ""
    invoice_cost: float = 0.0
    discount_credits: float = 0.0
    other_expenses: float = 0.0
    itc_reversed: float = 0.0
    interest_capitalized: float = 0.0
    forex_fluctuations: float = 0.0
    half_rate: bool = False
    is_more_than_180: bool = True
    notes: str = ""


class FaAdditionPatch(BaseModel):
    invoice_date: Optional[str] = None
    invoice_no: Optional[str] = None
    put_to_use_date: Optional[str] = None
    description: Optional[str] = None
    party_name: Optional[str] = None
    voucher_no: Optional[str] = None
    invoice_cost: Optional[float] = None
    discount_credits: Optional[float] = None
    other_expenses: Optional[float] = None
    itc_reversed: Optional[float] = None
    interest_capitalized: Optional[float] = None
    forex_fluctuations: Optional[float] = None
    block_label: Optional[str] = None
    notes: Optional[str] = None
    reviewed: Optional[bool] = None


class FaAdditionLink(BaseModel):
    parent_addition_id: str
    linked_as: str       # one of ADJ_FIELDS


class FaCreditEntryOut(BaseModel):
    """A credit entry pending classification as Sale or Discount."""
    model_config = ConfigDict(extra="allow")
    credit_id: str
    run_id: str
    fa_ledger_id: str
    voucher_id: str = ""
    voucher_no: str = ""
    voucher_type: str = ""
    accounting_date: str = ""
    party_name: str = ""
    particulars: str = ""
    amount: float = 0.0
    classification: str = "pending"  # pending | sale | discount
    sale_value: Optional[float] = None
    sale_date: str = ""
    buyer_name: str = ""


class FaCreditClassifyRequest(BaseModel):
    classification: str  # 'sale' | 'discount'
    sale_value: Optional[float] = None
    sale_date: Optional[str] = None
    buyer_name: Optional[str] = None
    note: Optional[str] = None


# ============================ Block Opening (3CD or Excel) ==================
class FaBlockOpeningOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    block_label: str
    rate: float
    opening_wdv: float = 0.0
    source: str = "manual"        # manual | prior_3cd | prior_run
    source_ref: str = ""
    description: str = ""


class FaOpeningExceptionOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    exception_id: str
    block_label: str
    rate: float
    opening_excel: float = 0.0
    closing_3cd: float = 0.0
    diff: float = 0.0
    status: str = "open"          # open | reconciled
    reconcile_note: str = ""
