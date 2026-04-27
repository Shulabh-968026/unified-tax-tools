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
- [ ] Start the next module (user to specify which utility)
- [ ] Migrate 43B(h) pages from shadcn → MUI + react-toastify (preserve current look)
- [ ] Migrate Clause 44 pages from shadcn → MUI
- [ ] Replace sonner with react-toastify (once MUI migration happens)
- [ ] Run the testing sub-agent once the next round of changes is in

## Phase 3 / future utilities (status="soon" in `utilities.jsx`)
GST Turnover Recon · TDS Disallowance & Recon · TDS Clause 34 — 3CD · AIS/TIS/26AS Recon · Fixed Assets · Balance Confirmation · GST Refund Clause 31

## Deferred
- MUI rewrite (user confirmed Option A — defer to Phase 2)
- End-to-end browser testing of MSME upload + compute flow (requires real Excel/JSON fixtures and an authenticated session)
