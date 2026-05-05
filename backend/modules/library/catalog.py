"""Client Library — the central per-engagement file store.

Every uploaded source file (Tally JSON, Ledger Map XLSX, prior-year 3CD
JSON, ITR JSON, GST returns, bank statements, etc.) lives in the
`client_files` collection.  Modules pin to specific file *versions*
rather than embedding the data, so:

  • A single re-upload of Books JSON instantly invalidates every dependent
    module's last run (they all flip to "outdated").
  • An auditor's previously-pinned run still has access to the exact byte
    sequence it computed against — pinned versions are protected from
    hard-delete.
  • Storage cost no longer scales with N modules × N runs.

This module owns three concerns:
  1. Catalogue — which file-types exist + which modules depend on them.
  2. Lifecycle — upload (creates a new version), soft-delete, restore,
     hard-prune (after 30-day grace).
  3. Outdated detection — for a given (client, period, division), does
     each module's last run pin to the latest version of every file-type
     it depends on?
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# File-type catalogue.  When we onboard a new file-type, add it here AND
# add it to MODULE_DEPENDENCIES below if any module reads it.  Every
# entry must have a stable `key` (used in URLs, DB), a human label, and
# a list of accepted MIME types / extensions.
# ---------------------------------------------------------------------------
FILE_TYPE_CATALOG: list[dict] = [
    {
        "key": "books_json",
        "label": "Books of Accounts (Tally JSON)",
        "ext": [".json"],
        "kind": "primary",
        "description": "Daybook + ledgers + groups + parties exported from Tally for the FY.",
    },
    {
        "key": "ledger_mapping_xlsx",
        "label": "Ledger Mapping (BS/PL classification)",
        "ext": [".xlsx"],
        "kind": "primary",
        "description": "Per-ledger BS-or-P&L tag, subhead, group parent, head, closing balance.",
    },
    {
        "key": "form_3cd_prior_json",
        "label": "Form 3CD — Prior Year",
        "ext": [".json"],
        "kind": "secondary",
        "description": "Last year's filed 3CD JSON (used for comparatives).",
    },
    {
        "key": "itr_prior_json",
        "label": "Income Tax Return — Prior Year",
        "ext": [".json"],
        "kind": "secondary",
        "description": "Last year's filed ITR JSON.",
    },
    {
        "key": "form_26as_json",
        "label": "Form 26AS",
        "ext": [".json", ".pdf"],
        "kind": "secondary",
        "description": "TDS credits, advance tax, refunds — for AIS/TIS recon.",
    },
    {
        "key": "ais_json",
        "label": "AIS — Annual Information Statement",
        "ext": [".json"],
        "kind": "secondary",
        "description": "AIS pulled from the income-tax portal.",
    },
    {
        "key": "tis_json",
        "label": "TIS — Taxpayer Information Summary",
        "ext": [".json"],
        "kind": "secondary",
        "description": "TIS pulled from the income-tax portal.",
    },
    {
        "key": "gstr_1_json",
        "label": "GSTR-1 (consolidated)",
        "ext": [".json"],
        "kind": "secondary",
        "description": "Outward supplies as filed for the FY (all months merged).",
    },
    {
        "key": "gstr_3b_json",
        "label": "GSTR-3B (consolidated)",
        "ext": [".json"],
        "kind": "secondary",
        "description": "Self-assessed liability + ITC as filed for the FY.",
    },
    {
        "key": "fa_register_xlsx",
        "label": "Fixed Assets Register (Prior Year closing)",
        "ext": [".xlsx"],
        "kind": "secondary",
        "description": "Opening WDV per block, useful-life overrides, asset-class tags.",
    },
    {
        "key": "it_depreciation_opening_wdv_xlsx",
        "label": "IT Depreciation — Opening WDV",
        "ext": [".xlsx"],
        "kind": "secondary",
        "description": "Per-block opening WDV (sub-block resolution) for IT Depreciation working.  Auto-generated template covers every active legal-master block.",
    },
    {
        "key": "party_master_xlsx",
        "label": "Party Master",
        "ext": [".xlsx"],
        "kind": "secondary",
        "description": "Vendor / customer master with email, GSTIN, MSME flag.",
    },
    {
        "key": "msme43bh_creditor_report_xlsx",
        "label": "AssureAI MSME 43B(h) Creditor Report",
        "ext": [".xlsx"],
        "kind": "secondary",
        "description": "Creditor-level disallowance computation produced by the 43B(h) Disallowance module — auto-saved here on each compute.  Auditors can also drop in an externally-prepared version.",
    },
]

FILE_TYPE_KEYS = {ft["key"] for ft in FILE_TYPE_CATALOG}
FILE_TYPE_BY_KEY = {ft["key"]: ft for ft in FILE_TYPE_CATALOG}

# File-types that the engine can pre-populate from data already in the
# Library.  See `modules.library.templates` for generators.
FILE_TYPES_WITH_TEMPLATES = {
    "party_master_xlsx",
    "fa_register_xlsx",
    "it_depreciation_opening_wdv_xlsx",
}


# ---------------------------------------------------------------------------
# Module → required file-types graph.  Drives the "Data outdated" badge
# computation in `compute_module_status`.
# ---------------------------------------------------------------------------
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "clause44":             ["books_json", "ledger_mapping_xlsx"],
    "msme43bh":             ["books_json", "party_master_xlsx"],
    "fixed_assets":         ["books_json", "fa_register_xlsx"],
    "balance_confirmation": ["books_json", "party_master_xlsx"],
    "gst_recon":            ["books_json", "gstr_1_json", "gstr_3b_json"],
    "fin_statement":        ["books_json"],
}


# ---------------------------------------------------------------------------
# Action-log enum (used by Balance Confirmation and any future module
# with external side-effects).  Defined here so the schema is owned by
# one place.
# ---------------------------------------------------------------------------
ACTION_TYPES = [
    # Phase 1 — request initiation
    "request_sent",
    "request_resent",
    # Phase 2 — email lifecycle (Resend webhook)
    "email_delivered",
    "email_bounced",
    "email_opened",
    "link_clicked",
    # Phase 3 — vendor response
    "vendor_responded_online",
    "vendor_responded_offline",
    # Phase 4 — auditor follow-up & closure
    "reminder_sent",
    "phone_call_logged",
    "auditor_override",
    "marked_non_responder",
    "disagreement_resolved",
    "balance_finalized",
]
