# MSS × Assure — Audit Utilities (Merged)

## Problem Statement
Merge two existing Emergent projects into ONE:
- **Clause 44 Form 3CD Tool** (master) — already has a 9-utility catalog; Clause 44 is the only live utility.
- **Section 43B(H) MSME Disallowance Tool** — standalone app with year-end ingest, MSME profile editor, payments ingest, FIFO compute, and Excel export.

Keep Clause 44 as the base project and port 43B(h) in. Shared DB, shared auth, shared clients collection. Backend restructured into controller / service / dao / schemas + core + helpers. Same UI stack preserved (shadcn/ui + Tailwind + sonner). MUI migration deferred to later phases.

## Stack
- Frontend: React 19 + react-router-dom 7 + shadcn/ui + Tailwind + sonner + lucide-react + @phosphor-icons/react
- Backend: FastAPI + motor (MongoDB async) + pandas + rapidfuzz + xlsxwriter
- Auth: Emergent-managed Google OAuth (existing Clause 44 flow applies to both utilities)

## Architecture (after merge)
### Backend (`/app/backend`)
```
server.py                 # slim app factory, mounts all routers under /api
core/
  db.py                   # Mongo singleton, ensure_indexes, ensure_super_admin
helpers/
  email.py                # Resend invite email
  parsers.py              # norm_str / to_float / parse_date_iso / date_from_iso
modules/
  auth/controller.py      # /auth/*  (get_current_user + OAuth session)
  admin/controller.py     # /admin/*
  clients/controller.py   # /clients/*  (shared across utilities)
  clause44/
    controller.py         # /runs/*
    service.py            # 3CD engine (parse + classify + recon)
    exports.py            # Excel export
  msme43bh/
    controller.py         # /msme/*
    service.py            # parse_yearend_excel, parse_payments_json, compute_disallowance
    dao.py                # msme_sessions collection access
    schemas.py            # SessionCreate/Out, ProfileRow, ProfilesUpdate
    exports.py            # Profile template + audit workbook
```

### Frontend (`/app/frontend/src`)
```
App.js                    # routes
pages/
  (Clause 44 pages kept intact: Login, ClientList, ClientUtilities, ClientHome, Dashboard, Consolidated, AdminUsers, ...)
  msme43bh/
    Landing.jsx           # FY picker + past runs
    SessionDashboard.jsx  # 4 tabs: Year-End | MSME Profile | Payments | Results
components/
  msme43bh/
    YearEndUpload.jsx, ProfilesEditor.jsx, PaymentsUpload.jsx, ResultsView.jsx, Footer.jsx
lib/
  api.js                  # shared http client (auth cookie)
  msme-api.js             # /msme-prefixed axios-like wrapper + INR formatters
  utilities.jsx           # flipped msme-43bh to status="active"
```

### MongoDB collections
- `clients`          — shared (Clause 44 schema: client_id, file_number, name, type, divisions)
- `runs`             — Clause 44 audit runs
- `msme_sessions`    — 43B(h) sessions (new)
- `users`, `user_sessions`, `invitations` — auth

## Routes
- `/dashboard` → clients list
- `/dashboard/clients/:clientId` → utilities catalog
- `/dashboard/clients/:clientId/utilities/clause-44` → Clause 44 tool (existing)
- `/dashboard/clients/:clientId/utilities/msme-43bh` → 43B(h) landing (NEW)
- `/dashboard/clients/:clientId/utilities/msme-43bh/sessions/:sid` → 43B(h) workbench (NEW)

## Phase 1 status (2026-01-27)
- [x] Cloned both source repos
- [x] Clause 44 set as base; pod `.env` preserved
- [x] Backend restructured into core/helpers/modules/{auth,admin,clients,clause44,msme43bh}
- [x] MSME module split into controller/service/dao/schemas/exports (clean DDD)
- [x] Auth-aware routes — 43B(h) now protected by Emergent Google OAuth
- [x] Frontend routes + utility card wired for 43B(h)
- [x] `utilities.jsx` → 43BH MSME Disallowance marked `status="active"`
- [x] Frontend compiles clean; backend boots clean; endpoints return expected auth 401s
- [x] Whitelisted `shulabh@transformautomations.com` as admin (invitations collection)
- [x] 43B(h) Results table polish (2026-04-27)
      • Amount & Disallowance right-justified
      • All columns sortable (click header, chevron indicator)
      • Reason column shrunk to ~12% width, wraps naturally
      • Column widths via `<colgroup>`; denser fonts on mono columns
      • Sticky table header on scroll
- [x] Bug fix: removed duplicate "FIFO Forced" in Statutory Due Date cell
      (backend `due_date_basis` now says "Voucher Date + 45 days"; pill badge is the sole "FIFO Forced" marker)
- [ ] End-to-end testing with real login + upload flow (user to verify / to be done after more changes)

## Phase 2 backlog (pick up tomorrow)
- [x] GST Turnover Recon — Phase A scaffold (2026-04-28)
      • Backend: `modules/gst_recon/{controller,service,schemas}.py` with filename categorizer + 12-month grid builder
      • Routes: POST/GET/DELETE `/api/gst-recon/runs`, POST `/api/gst-recon/runs/{rid}/files` (batch upload + categorize)
      • Mongo: new `gst_recon_runs` collection
      • Frontend: `pages/gst_recon/Landing.jsx` — multi-file dropzone + 5-bucket counters + 12-month coverage grid + "Run Reconciliation" CTA (disabled until complete)
      • Route: `/dashboard/clients/:clientId/utilities/gst-recon`
      • `utilities.jsx` → `gst-turnover-recon` flipped to `status="active"`
      • `ClientUtilities.jsx` navigates to it
      • Smoke-tested: sample filenames (`33AAEFA5684J1ZC_GSTR1_April_2024-2025_0.json`, `returns_R2B_..._042024.json`, `GSTR3B_..._042024.pdf`) correctly classified + mapped to Apr 2024 row
- [x] GST Recon Phase A scaffold complete (see above)
- [x] Client model extended with optional `gstin` field (2026-04-28)
      • Backend: `ClientCreate` / `ClientUpdate` now accept `gstin` with regex `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$` (server-side 422 on invalid)
      • `_public()` includes `gstin` in response; stored upper-cased & trimmed, `None` when blank
      • Frontend: `CreateClientDialog` has new GSTIN input (optional, 15-char, uppercased, client-side regex) with hint text
      • `ClientUtilities` page header now shows `GSTIN · <value>` chip when set
- [x] GST Recon Phase B — Pre-flight validation gates complete (2026-04-28)
      • Backend: new `modules/gst_recon/validation.py` with `inspect_file()` + `validate_run()`
      • Upload endpoint now inspects each file: extracts GSTIN + return period from content (GSTR-1 `gstin`/`fp`, GSTR-2B `data.gstin`/`rtnprd`, PDF `%PDF` header), captures Books `booksFromDate`/`booksToDate`
      • New route `POST /api/gst-recon/runs/{rid}/validate` → `{ok, errors[], warnings[], summary}`
      • 4 gates enforced: (1) client GSTIN present, (2) file integrity (JSON parse, PDF `%PDF` header), (3) GSTIN match — every GSTR file's GSTIN must equal `clients.gstin`, (4) FY alignment — Books dates must cover the FY range, (5) completeness — mapping present + every month has R1/R2B/R3B
      • Frontend: new "Run Pre-flight Check" button (enabled once coverage is full); "Run Reconciliation" button is now hard-gated on `validation.ok === true`
      • Validation panel lists all blockers in red + warnings in amber, plus a mono-font summary line
      • Smoke-tested end-to-end with user's real sample files: client `33AAEFA5684J1ZC`, 5 files uploaded (GSTR-1, GSTR-2B, GSTR-3B, Books, Mapping) → 0 integrity failures, 0 GSTIN mismatches, only the expected coverage-gap error
- [ ] GST Recon Phase C — GSTR-3B PDF parser (Table 3.1 turnover + Table 4 ITC) in `helpers/parsers.py`, Pandas 12-month aggregation, Summary UI
- [ ] GST Recon Phase D — Voucher-level rapidfuzz matching + drill-down UI with amber/red highlighting
- [ ] GST Recon Phase E — Testing sub-agent
- [ ] Migrate 43B(h) pages from shadcn → MUI + react-toastify (preserve current look)
- [ ] Migrate Clause 44 pages from shadcn → MUI
- [ ] Replace sonner with react-toastify (once MUI migration happens)

### Real-sample file formats (captured from user's uploads — for Phase B/C)
- **Books JSON** (Tally export): top-level `company.booksFromDate / booksToDate`, `vouchers[]` with `voucherTypeName`, `date`, `voucherNumber`, `partyGSTIN`, `consigneeGSTIN`, `ledgerEntries[]` (tax amounts are in per-ledger entries like "Input CGST @ 2.5%", "Output IGST @ 5%"). No top-level `clientGstin` → infer via `consigneeGSTIN` on sales or match against `clients.gstin`.
- **GSTR-1 JSON**: `gstin`, `fp` (MMYYYY), `b2b[]` → each item has `ctin` (counterparty) + `inv[]` with `inum`, `idt` (DD-MM-YYYY), `val`, `itms[].itm_det.{txval,camt,samt,iamt,csamt,rt}`.
- **GSTR-2B JSON**: `data.docdata.b2b[]` → `ctin`, `trdnm`, `supfildt`, `supprd`, `inv[]` with `inum`, `dt`, `val`, `txval`, `cgst`, `sgst`, `igst`, `cess`, `itcavl`, `imsStatus`. Also `data.itcsumm.itcavl.nonrevsup.b2b` for ITC totals.
- **GSTR-3B PDF**: needs `pdfplumber` (not yet installed) to extract Table 3.1 (Outward supplies) and Table 4 (ITC).
- **Ledger Mapping**: XLSX (not CSV as originally spec'd). Exact column names to be confirmed from the sample during Phase B.

## Phase 3 / future utilities (status="soon" in `utilities.jsx`)
GST Turnover Recon · TDS Disallowance & Recon · TDS Clause 34 — 3CD · AIS/TIS/26AS Recon · Fixed Assets · Balance Confirmation · GST Refund Clause 31

## Deferred
- MUI rewrite (user confirmed Option A — defer to Phase 2)
- End-to-end browser testing of MSME upload + compute flow (requires real Excel/JSON fixtures and an authenticated session)
