"""Financial Statement Designer — Phase 1 scaffolding.

Tally books JSON → Schedule III Balance Sheet / P&L / Cash Flow / Notes
→ designer-style PDF (Classic or Boardroom).

This package is intentionally isolated from Fixed Assets / Clause 44 /
MSME 43B(h) / GST Recon / Balance Confirmation — no shared state or
imports. It owns its own Mongo collections (fs_runs, fs_uploads) and
its own FastAPI router.
"""
