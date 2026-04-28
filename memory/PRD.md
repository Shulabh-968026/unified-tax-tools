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
- [x] GST Recon Phase C — GSTR-3B PDF parser complete (2026-04-28)
      • Installed `pdfplumber` and froze to `requirements.txt`
      • New function `helpers/parsers.py::parse_gstr3b_pdf(bytes)` → `{period, gstin, table_3_1:{a..e:{taxable_value,igst,cgst,sgst,cess}}, table_4:{a_itc_available, b_itc_reversed, c_net_itc}, errors}`
      • Extracts GSTIN + period from header text; Table 3.1 by header-match then row-prefix `(a)..(e)`; Table 4 by walking rows across the page split, flagging "ITC Available" vs "ITC Reversed" sections and capturing `Net ITC Available` directly
      • Handles stray watermark letters (D/E/F/I) in numeric cells and `-` placeholders
      • Verified against user's real sample (GSTR3B_33AAEFA5684J1ZC_012025.pdf): Outward ₹8.69L + IGST ₹43,454.65, RCM ₹13k + CGST/SGST ₹1,170 each, Net ITC CGST/SGST ₹21,204.58 each — all match the PDF exactly
- [x] GST Recon Phase C.2 — parsers wired into upload pipeline (2026-04-28)
      • Fixed SyntaxError in `controller.py` (stale leftover code at L175-180)
      • New `modules/gst_recon/aggregators.py` with `aggregate_gstr1`, `aggregate_gstr2b`, `aggregate_books`
      • `upload_batch` now persists per-file aggregates: `r1_outward`, `r2b_itc`, `books_per_month`, plus existing `table_3_1`/`table_4` for 3B PDFs
      • Books aggregator excludes party (debtor/creditor) ledgers from taxable-value buckets to avoid double-counting
- [x] GST Recon Phase C.3 — Pandas-style 12-month aggregation engine (2026-04-28)
      • New `service.py::build_summary(run_doc)` produces 12 rows (Apr→Mar) + annual totals with 9 numeric columns + 4 variance columns (R1−R3B outward, R2B−R3B ITC, Books−R1 outward, Books−R2B ITC)
      • New endpoint `POST /api/gst-recon/runs/{rid}/summary` — computes + persists summary; transitions run.status to "summarized"
      • RunOut/FileBucketItem schemas extended with `extra="allow"` + explicit `summary` field so all C.2/C.3 fields survive `response_model` filtering
      • Frontend: Summary panel in `pages/gst_recon/Landing.jsx` — two reconciliation tables (Outward + ITC) with sticky header, alternating rows, amber variance highlighting (green when |variance| < 1, amber otherwise), annual totals row
      • Fixed latent bug: missing `useState` for `validation` / `setValidation` in Landing.jsx (would have crashed on upload)
      • Tests: 12 unit tests in `tests/test_gst_recon_phase_c3.py` + 14 e2e tests in `tests/test_gst_recon_phase_c_e2e.py` — 48/48 passing including 22 prior regression
- [x] GST Recon Phase D — voucher-level matching with rapidfuzz (2026-04-28)
      • New collection `gst_recon_invoices` (indexed on run_id+source+period) — invoice records persisted on upload, dropped on run delete
      • New extractors in `aggregators.py`: `extract_books_invoices`, `extract_gstr1_invoices`, `extract_gstr2b_invoices` — emit flat per-invoice records {period, direction, party_gstin, invoice_no, date, taxable, igst, cgst, sgst, cess, total}
      • Books extractor only emits B2B vouchers (party GSTIN required) — B2C skipped since portal won't have them under b2b
      • New `service.py::match_invoices(books, portal)` — two-pass matching: (1) exact on (party_gstin, normalised invoice no); (2) rapidfuzz fuzz.ratio ≥85 on inv-no within same gstin. Tolerances: value=max(₹1, 0.5%); date=same calendar day after ISO normalisation
      • Returns 5 categories: matched / value_mismatch / date_mismatch / missing_in_books / missing_in_portal + counts
      • New endpoint `POST /api/gst-recon/runs/{rid}/match?period=MMYYYY&direction=outward|inward`
      • Cascade delete of invoices on run delete
      • 16 unit tests in `tests/test_gst_recon_phase_d.py` — all passing
- [x] **GST Recon — Iter6 polish: ITC bug fix + sticky relaxed + simpler partywise** (2026-04-28)
      • **P1**: Relaxed Fuzzy state lifted from MatchDrawer to SummaryPanel — toggle now persists across drawer open/close/navigation within the same run.
      • **P2** (BUG): Annual Party-wise Inward (ITC) sheet was showing **bill values** instead of **ITC amounts** (e.g. Sunayana Textiles showed ₹5,00,416 instead of correct ITC ₹23,829.32). Root cause: frontend and Excel were displaying `*_total` (bill) keys regardless of direction. Fix: direction-aware columns — inward shows `*_tax` (ITC = igst+cgst+sgst+cess), outward shows `*_taxable` (turnover). Verified: total Books ITC ₹4,55,935.12 vs R2B ITC ₹76,411.78 matches monthly ITC totals exactly.
      • **P3**: GSTR-3B columns removed from Annual Party-wise on both UI and Excel — R3B is monthly-only, not party-resolvable, so showing it added noise. Sheets now have a clean **5 columns**: Party GSTIN | Party Name | Books (ITC/Taxable) | Portal (ITC/Taxable) | Books − Portal.
      • **Tests**: 74/74 GST Recon tests still passing.
      • **Party Name column**: added next to GSTIN in both Voucher sheets (Outward + Inward) in the audit Excel and in the on-screen Match Drawer pair tabs. Source field: Tally `partyLedgerName` for books, GSTR-1/2B `trdnm` for portal records.
      • **Relaxed Fuzzy mode**: new third-pass matching when toggle is ON in the drawer header — auto-matches residual unmatched vouchers if `(party_gstin, period, total)` are equal within ₹1 / 0.5% tolerance, even when bill numbers and dates differ entirely. Picks closest |date diff| when multiple candidates remain. Marked with `relaxed_match: true` in response so the UI shows "Relaxed" tag in the match column. **Verified on real Apr-2024 data**: strict mode matched=0, relaxed mode matched=4 extra pairs (e.g. Sunayana ₹14,406, Sneha ₹3,23,883). New endpoint param: `&relaxed=true` on `/match` and `/export.xlsx`.
      • **Annual Party-wise table**: new endpoint `GET /api/gst-recon/runs/{rid}/partywise?direction=inward|outward` aggregates voucher records by party_gstin across all 12 months. Returns rows with party name, books_total, portal_total, diff_total. Sorted by largest variance first.
      • **Frontend tab switcher** on Summary panel: "Annual Party-wise" (now default tab) | "12-Month Reconciliation" (the prior tables). Direction selector for partywise view.
      • **Excel workbook expanded to 8 sheets**: Dashboard | Annual Party-wise (Outward) | Annual Party-wise (Inward) | 12-Month Summary | Outward Vouchers | Inward Vouchers | Pending Classification | Run Metadata.
      • **Tests**: 74/74 passing — 3 new relaxed-fuzzy unit tests + 1 new partywise sheet test.
      • **BUG**: Despite earlier 2B fix, real GSTR-2B JSON files for Apr-May 2024 still showed 0.00. **Root causes** (TWO issues):
        1. User's actual 2B files use `igst/cgst/sgst/cess` keys (NOT the GSTN-spec `iamt/camt/samt/csamt`)
        2. Invoice tax breakdown sits inside `inv.items[]` array, not at invoice level
      • **FIX**: New `_itc_pick(node)` helper accepts BOTH key namings. `_sum_itc_dict` reads totals at the `nonrevsup` parent level (which equal sum of children) instead of double-counting. Invoice extractor sums `items[]` array when invoice-level tax fields are absent.
      • **Verified with user's real Apr/May 2024 2B JSONs**: Apr ITC = ₹31,553.92, May ITC = ₹44,857.86 (matches GSTR-3B Net values exactly). Was 0.00 before fix.
      • **NEW: `GET /api/gst-recon/runs/{rid}/export.xlsx`** — multi-sheet audit working-paper:
        - Sheet 1: Dashboard with 4 KPI cards + traffic-light coloring + status banner
        - Sheet 2: 12-Month Summary (Outward + ITC blocks with Annual totals)
        - Sheet 3: Outward Vouchers (every Books↔GSTR-1 match, categorised by status)
        - Sheet 4: Inward Vouchers (every Books↔GSTR-2B match)
        - Sheet 5: Pending Classification (unmapped ledgers)
        - Sheet 6: Run Metadata + uploaded files list
      • Frontend: new "Audit Working-Paper" download button next to Run Reconciliation (enabled once summary computed)
      • **Tests**: 70/70 passing — 3 new 2B real-format tests + 6 new Excel export tests
      • **BUG**: GSTR-2B values showed 0.00 for Apr-Sep 2024 but worked Oct-Mar (user's screenshot). **Root cause**: GSTN's 2B JSON format changed mid-year — older files use camelCase (`itcSumm.itcAvl.nonRevSup`) while newer use lowercase (`itcsumm.itcavl.nonrevsup`). Parser was lowercase-only.
      • **FIX**: All 2B JSON key lookups now case-insensitive (`_ci_get` / `_ci_path` helpers). Tolerates 4 variants: v1 camelCase, v2 lowercase, v3 itcavl-without-nonrevsup wrapper, v4 docdata.b2b invoice-level fallback. Same fix applied to `validation.py::inspect_file` for period / gstin extraction.
      • **Data cleanup**: deleted 19 test clients + 6 Allman trial runs + cascading invoice + books_raw collections. DB now has only Allman Knitwear + ABC Textile Mills with their legitimate data intact.
      • **Summary Dashboard**: new `DashboardCards` component above the 12-month tables showing 4 cards (Books-vs-R1, R1-vs-R3B, Books-vs-R2B, R2B-vs-R3B) with variance amount, % of base, months-flagged count, and colour coding (green=ok, amber=warn, red=danger >₹1L variance). Dashboard header strip shows "ALL RECONCILED" or "N MONTH-ISSUES FLAGGED" banner with overall severity.
      • **Tests**: 62/62 passing — 2 new tests cover GSTR-2B camelCase + itcavl-without-nonrevsup variants.
      • **BUG**: Books figures always showing 0.00 — two root causes: (a) Tally JSON uses `ledger` key not `ledgerName`; voucher party uses `partyLedgerName` not `partyName`; (b) keyword-based classification mis-rejects ledger names like `GST IGST SALES 5%` (has both 'sales' AND 'igst')
      • **FIX**: Ledger Mapping XLSX is now the **source of truth**. New `helpers/mapping.py::parse_ledger_mapping` parses the mapping and returns mutually-exclusive {revenue, output_tax, input_tax} sets. Classification precedence: Output Tax → Input Tax → Revenue (prevents double-counting).
      • Rules (refined from user's spec + actual mapping): revenue = `Head ∈ {Revenue from Operations, Other Income}`; output_tax = `Group Parent="Output Credit"` OR `Head="Other Current Liabilities" + /output.*(igst|cgst|sgst|cess)/`; input_tax = `Group Parent="Input Credit"` OR `Head="Other Current Assets" + (GroupParent="Duties & Taxes" OR Subhead contains "Balance with Revenue") + name contains Input/ITC/GST-letter`
      • `aggregators.py::aggregate_books` + `extract_books_invoices` rewritten to take `rules` parameter; Tally sign convention respected (+ve = Credit, -ve = Debit); party ledger excluded via `isPartyLedger` flag
      • Books raw content stored gzipped+base64 in new `gst_recon_books_raw` collection. Auto re-aggregation on either ordering: Books→Mapping and Mapping→Books
      • Upload response exposes `mapping_unmapped_ledgers` + `books_reprocessed` flag
      • Cascade delete extended to `gst_recon_books_raw`
      • **Verified with real user data**: Books outward total = ₹1,38,33,365.96 matches GSTR-1 total from user's screenshot exactly (was 0.00 before fix)
      • **BUG**: Past runs were not listed — unlike 43BH / Clause44. **FIX**: new `PastRunsPanel` component on Landing page shows all runs for the client with Resume/Delete/New Run buttons + status pills (draft/summarised/complete) + coverage counter. Tally → resumable state (months, buckets, summary, unmapped).
      • **UX**: New "Pending Classification" warning strip surfaces unmapped ledger names from the mapping as pills
      • **Tests**: 60/60 passing (12 C.3 unit + 16 D unit + 17 C e2e + 17 D e2e — e2e suites regenerated with synthetic openpyxl mapping fixture; new helper `tests/_gst_recon_helpers.py`)
      • **Fixed mid-iteration**: missing `History` import in Landing.jsx caused "Illegal constructor" runtime error (React instantiated `window.History` DOM interface)
      • GSTR-1 column in Outward summary table and GSTR-2B column in ITC summary table now clickable
      • New `MatchDrawer` slides in from right with 5 colour-coded tabs (matched/value-mismatch/date-mismatch/missing-in-books/missing-in-portal) + count badges
      • Pair-tabs show: Party GSTIN, Books #, Portal #, Books Total, Portal Total, Δ, Books Date, Portal Date, Fuzzy Score (when fuzzy-matched)
      • Missing-tabs show: Party GSTIN, Party Name, Inv #, Date, Taxable, IGST, CGST, SGST, Total
      • Backdrop + close button + ESC support
- [ ] GST Recon Phase E completion — full testing-agent run + Excel export of voucher-level reconciliation as a working-paper
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
