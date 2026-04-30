# MSS × Assure — Audit Utilities (Merged)

## Fixed Assets — Phase 1A/B/C/E live (2026-04-30)
- [x] **Module skeleton** at `/app/backend/modules/fixed_assets/` (controller / schemas / service / legal_master) + router prefix `/api/fixed-assets/*` wired in `server.py`
- [x] **Legal master seeded** from shipped `data/it_depreciation_legal_master.xlsx` — 143 rows across 15 distinct `block_label`s (Buildings 5/10/40, Furniture 10, P&M 15/30/40, Vehicles 15/30/40/45, Computers 40, Renewable Energy 40, Ships 20, Intangibles 25). `seed_legal_master()` is idempotent; admin-only `/legal-master/reseed` for law-change refreshes.
- [x] **Run CRUD** — `POST /runs` (with auto multi-FY linkage via `rolled_from_run_id` when prior run exists), `GET /runs?client_id=`, `GET /runs/{rid}`, `DELETE /runs/{rid}` cascades to ledgers/additions/credits/block-opening/books-raw.
- [x] **Books JSON ingest** — `POST /runs/{rid}/ingest-books`:
      • Recursively walks Tally `groups` under "Fixed Assets" / "Property, Plant and Equipment" → 7 standard auditor groups detected on Velav sample (COMPUTER, Electrical Equipments, Furniture & Fittings, Office Equipments, Plant and Machineries, Vehicle, root)
      • **Excludes** `Accumulated Depreciation - *` ledgers (regex `accumulated\s+depreciation` etc.) — per spec, never circle-back to the depreciation ledger
      • Sign convention: Tally `amount < 0` ⇒ asset Dr (Addition), `amount > 0` ⇒ asset Cr (pending Sale-vs-Discount classification)
      • **Bill / Invoice date** narration regex (per user spec): `(bill|inv(?:oice)?)\.?\s*(?:date|dt|no\s*&\s*dt)\s*[:\-]?\s*<dd-mm-yyyy|yyyy-mm-dd>` → fallback to voucher accounting date. Tested: `"Bill Date 12/06/2024 - …"` → `2024-06-12`. (`dueDates[]` deliberately ignored — user clarified those are payment due-dates, not bill dates.)
      • Stages every voucher line into `fa_additions` (with PTU defaulting to invoice_date, half_rate auto-flagged via 180-day rule from `fy_end`) and `fa_credits` (status=pending, sale_value blank for auditor entry).
      • Smoke test on Velav 2024-25 books: **21 FA ledgers detected (down from 27 — 6 Accumulated Depreciation excluded)** · 101 additions · 4 credits · ingest takes ~600ms.
- [x] **Ledger Workbench** — `GET /runs/{rid}/ledgers`, `POST /runs/{rid}/ledgers/{lid}/classify`. Classification validates the legal_master row exists & block_label matches; cascades the chosen `block_label` to all staged additions for that ledger.
- [x] **180-day rule helper** — `is_more_than_180(put_to_use, fy_end)` ≥180 days ⇒ full rate, else half rate. Pytest sanity: 4/4 cases pass (Apr/Sep ≥180, Oct/Jan <180).
- [x] **MongoDB hygiene** — every response excludes `_id`; `RUNS.insert_one` followed by `doc.pop("_id", None)` to satisfy Pydantic serialization.
- [x] **Frontend Landing** at `/dashboard/clients/:clientId/utilities/fixed-assets[/runs/:rid]` (`/app/frontend/src/pages/fixed_assets/Landing.jsx`):
      • Two-state UX (mirrors Balance Confirmation): no-rid → Runs list with **New Run** button + "Rolled forward" badge for multi-FY linkage; in-rid → 5-cell stats strip (FA Ledgers / Pending / Confirmed / Additions / Credits) + Books drop-zone + Classification Workbench table
      • **Classify modal** — block dropdown (15 active block_labels with rate badge), legal-entry dropdown lazy-loaded per block, optional auditor note. "Strict Care" enforced — submit disabled until both block and legal entry chosen
      • Live status chips (Pending / Auto-Suggested / Confirmed / Skipped) — counts auto-refresh after every classify
- [x] **Utility tile** flipped from `soon` → `active` in `/app/frontend/src/lib/utilities.jsx`

### Pending — same module
- [ ] Phase 1D — `POST /runs/{rid}/ingest-prior-3cd` (parse `FORM3CA.F3CA.Form3cdDeprAllw[]` → opening WDV by rate; cross-validate against optional Excel upload; expose `/exceptions` workflow)
- [ ] Phase 1F — Additions table UI: editable PTU dates (with [Copy Acc Date] / [Copy Inv Date] buttons), 5 adjustment columns, drag-drop from Invoice Cost into adjustment columns, auto-recompute half_rate as PTU edits
- [ ] Phase 1F — Credit-classification modal: Sale (sale_value, sale_date, buyer_name auto from voucher) vs Discount (transfer to discount_credits column on the matching addition)
- [ ] Phase 1G — Computation engine `POST /runs/{rid}/compute` and the multi-sheet Excel export matching the user's "Sample IT Depreciation Schedule" (Block Summary in the exact 14-column layout · Additions Register · Deletions Register · Reconciliation · Workings)
- [ ] Phase 1H — Multi-FY continuity ("roll forward closing WDV" UI button)

## Domain switch — Resend sender flipped (2026-04-29)
- [x] **Resend domain `assureai.in` verified** (DKIM + SPF + MX all green in Resend dashboard, region: ap-northeast-1 / Tokyo)
- [x] `.env` updated: `RESEND_SENDER_EMAIL=notifications@assureai.in`, `RESEND_SENDER_NAME="AssureAI Audit Confirmations"` (fallback only)
- [x] **Dynamic From-name per send** — `sender.send_one()` accepts optional `from_name` arg; bulk_send computes `f"Confirmation of Balance — M/s {client.name}"` per ledger so recipients see the auditee's name in their inbox header
- [x] **Subject template upgraded** — all 3 default templates (customer / vendor / bank) now use `Confirmation of Balance — M/s {{client_name}} as on {{as_at_date}}`; `_ensure_default_templates()` auto-upgrades legacy default-subjects on first /templates GET (preserves any user-customised subjects)
- [x] Live smoke test to dhans75@gmail.com — Resend message ID `6b022c38-…` accepted ✅; pytest 1/1 passing
- [ ] **(Pending user action)** Resend Webhooks → Edit existing webhook → swap preview URL for production URL once deployed (signing secret stays the same)

## Balance Confirmation — Phase 4 live (2026-04-29)
- [x] **Public recipient response loop** — no auth needed, accessed via the `/track/click/{token}` 302 redirect from the email
- [x] New routes (public unless noted):
      • `GET  /api/balance-confirmation/public/confirmation/{token}` — context for the AssureAI-green landing page (party_name, balance, dr_cr, client, auditor, status); never echoes file bytes
      • `POST /api/balance-confirmation/public/confirmation/{token}/confirm` — JSON body, flips ledger.confirmation_status → `confirmed` (terminal)
      • `POST /api/balance-confirmation/public/confirmation/{token}/dispute` — multipart/form-data with `Form(...)` annotations on every scalar (testing agent caught & fixed the missing-Form bug); reason required (400 if empty), file optional, 8MB cap with **early Content-Length pre-check** so we don't buffer DoS payloads. Status flips → `disputed` (terminal). Idempotent re-submit replaces the response doc but ledger stays terminal.
      • `GET  /api/balance-confirmation/runs/{rid}/responses?decision=` — auditor-side, enriches each row with ledger_name + our_balance + our_dr_cr; auth-gated
      • `GET  /api/balance-confirmation/runs/{rid}/responses/{response_id}/attachment` — streams the recipient's uploaded statement; **filename sanitised** for Content-Disposition; auth-gated
- [x] New collection `bc_responses` — schema locked: `{response_id, run_id, ledger_id, response_token, decision: confirmed|disputed, responder_name/email, their_balance/dr_cr, reason, note, responder_ip, user_agent, submitted_at, uploaded_filename/size/content_b64}`
- [x] `bc_responses` cascade-deletes on run delete (verified)
- [x] Frontend `pages/balance_confirmation/ConfirmPage.jsx` (~370 lines): public route `/confirm/:token` outside ProtectedRoute, AssureAI green header (#047857), balance card with ₹ + Dr/Cr indicator + plain-language hint, two-button choose state (Yes / No), confirm form (name/email/note), dispute form (name/email/their balance + Dr-Cr/reason*/file upload), thank-you screen with reference id + UTC timestamp, friendly "Link Invalid or Expired" error state. Uses raw `axios` (NOT the http alias) so no auth cookie ever leaks.
- [x] Frontend `Landing.jsx` Responses drawer (`data-testid='bc-responses-drawer'`, width capped at min(95vw, 720px) for parity with Send Log) — decision filter, side-by-side our-vs-their balance card, reason text, attachment download routed through auth-gated endpoint
- [x] **Tests**: 57/57 backend pytest GREEN (28 P1+2 + 14 P3 + 15 P4 in `test_balance_confirmation_phase4.py`); frontend Playwright regression GREEN (test_reports/iteration_8.json)

## Balance Confirmation — Phases 5 + 6 live (2026-04-29) — module COMPLETE
- [x] **Phase 5 — Confirmation Summary Report exports**
      • `GET /api/balance-confirmation/runs/{rid}/summary.xlsx` — 6-sheet workbook (openpyxl): **Cover** (KPI table + status banner) · **Sent Tracker** (15 cols per ledger with every status timestamp + send_attempts) · **Status Timeline** (every send_log event chrono) · **Variances** (disputed responses with our vs their + diff + reason) · **Confirmed** (clean sign-off list) · **Notes** (blank for auditor's manual entry)
      • `GET /api/balance-confirmation/runs/{rid}/summary.pdf` — multi-page reportlab PDF: cover + 4 KPI cards (confirmed / disputed / in-flight / failed) + status banner; optional Variances + Confirmed pages; Sign-off block
      • `kpi_buckets()` helper buckets every ledger into one of {confirmed, disputed, in_flight, failed, no_action, no_email}
      • Frontend: 'Summary XLSX' (emerald) + 'Summary PDF' (rose) buttons in run-header, only visible after books ingest
- [x] **Phase 6 — Side-by-side reconciliation**
      • `recon.py` — heuristic column detector (Date/Voucher Type/Voucher #/Particulars/Debit/Credit/Balance/Amount); XLSX + CSV parsers (CSV sniffs `,`/`;`/`\t`/`|` delimiters, handles dd-mm-yyyy + dd/mm/yyyy + ISO + parentheses-as-negative); single-Amount-column auto-split (positive=Cr, negative=Dr)
      • `auto_match()` — greedy amount-only matcher with sign-insensitive comparison (our credit ↔ their debit) and configurable tolerance (default ₹1)
      • `GET /api/balance-confirmation/runs/{rid}/responses/{response_id}/recon?tolerance=` — fetches our books from cached Tally JSON, parses recipient's attachment, returns side-by-side pairs `{status: match|ours_only|theirs_only, our, theirs, diff}` + counts
      • Comments CRUD: `POST /recon/comments`, `GET /recon/comments`, `DELETE /recon/comments/{cid}` (collection `bc_recon_comments`, cascade on run delete)
      • Frontend `ReconModal` (~155 lines): 5-cell metric strip (our balance · their balance · auto-matched · ours/theirs only · tolerance ₹ control), two-pane diff table with row pairs, reconciliation notes section (real-time author + timestamp)
- [x] PDF cover — fixed reportlab Color → hex conversion (was using `hexval()[2:]` which returns `0xRRGGBB`; now uses `int(red*255)` etc → `#RRGGBB`).
- [x] Tests: **77 passed + 1 skipped** across all 4 phases (skipped covers the text-only-dispute branch — easy seed when needed). New `test_balance_confirmation_phase5_6.py` (21 cases).
- [x] Cascade complete: `delete_run` cleans up bc_runs + bc_ledgers + bc_books_raw + bc_send_log + bc_responses + bc_recon_comments.
- [x] Catalog tile is `status="active"` — module fully shipped.

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
- [x] **GST Recon — Click-to-drill from Party-wise → MatchDrawer (whole-year)** (2026-04-28)
      • New endpoint `POST /api/gst-recon/runs/{rid}/match-party?party_gstin=&direction=&relaxed=` — runs the same 3-pass matching engine across **all 12 months** of vouchers for a single supplier.
      • Frontend: clicking a row in `Annual Party-wise Comparison` opens MatchDrawer in `mode=party` with header `<Party Name> · all months` and subtitle `<GSTIN> · Books ↔ <portal>`.
      • Sticky Relaxed Fuzzy state preserved across drawer open/close.
      • **Verified end-to-end on real Allman Knitwear FY24-25 data**: clicking Sanjeev Stiching Centre Tirupur row → drawer mounts, returns `Missing in Portal: 313` — matches backend curl exactly.
      • Backend tests: 43/43 unit tests (phase_c3 + phase_d + excel_export) passing.
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
- [x] GST Recon Phase E completion — full testing-agent regression PASSED (2026-04-28 / iteration_5.json)
      • Backend: 75/75 pre-existing GST Recon tests + 13/13 new Phase E live tests = **88/88 GREEN**
      • New `tests/test_gst_recon_phase_e_live.py` covers `/match-party` (auth gate, 404 unknown run, 400 bad direction, 422 missing param, inward/outward 200 with correct shape), partywise read shape, multi-sheet xlsx download, and client GSTIN regex on POST/PATCH
      • Frontend: Recon Landing mounts cleanly (iter4 'Illegal constructor' regression resolved); Past Runs/Resume, validation gates, Pending Classification, 12-Month coverage grid, Reconciliation Health, tab switcher, 29-row Annual Party-wise table, click-to-drill drawer with `mode=party` (header `Sanjeev Stiching · all months`, 313 missing-in-portal verified), Relaxed Fuzzy sticky, Audit Working-Paper download — all verified
      • Cosmetic findings: `pytest.ini asyncio_mode` warning; `/api/clients` has no DELETE (archive only) — both optional follow-ups
- [x] GST Recon — Signature-ready PDF working-paper (2026-04-29)
      • New `modules/gst_recon/pdf_export.py` (reportlab 4.4) builds a 5-page A4 PDF: Cover/Health (KPI cards + status banner) → 12-Month Outward + ITC tables → Annual Party-wise Outward (top-15) → Annual Party-wise Inward/ITC (top-15) → Sign-off block
      • New endpoint `GET /api/gst-recon/runs/{rid}/working-paper.pdf` (auth-gated, 404 on unknown run, auto-builds summary if missing)
      • Variances above ₹1 lakh → red, above ₹1 → amber (matches Dashboard cards)
      • Footer on every page: `GST Recon Working-Paper · FY · Run · Page N · MSS × Assure`
      • Frontend: new rose-bordered "Working-Paper PDF" button (`data-testid="download-pdf-btn"`) next to the green "Audit Working-Paper" XLSX button
      • Verified end-to-end on real Allman Knitwear FY24-25 (5 pages, 12KB, all monies, 15 month-issues flagged, top-15 parties listed)
      • `requirements.txt` updated with `reportlab==4.4.10`
- [x] DB cleanup (2026-04-29) — deleted 16 unwanted clients (TEST_*, PeriodTest, Dup1, ArchiveMe, MultiDedup, TEST_smoke_curl, TEST_QA_Client_Updated) + 9 orphaned Clause-44 runs; **Allman Knitwear + ABC Textile Mills only** remain with all their legitimate runs/sessions/invoices intact
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
TDS Disallowance & Recon · TDS Clause 34 — 3CD · AIS/TIS/26AS Recon · Fixed Assets · GST Refund Clause 31

## Balance Confirmation (Phase 1+2 live · 2026-04-29)
- [x] Backend module `modules/balance_confirmation/` (controller / service / classifier / templates / exports / schemas)
- [x] 18 routes under `/api/balance-confirmation/*` — Runs CRUD, Books JSON ingest, Ledger workbench (list/patch/csv export+import), Templates CRUD (default seed = 3 rows: customer / vendor / bank in AssureAI green #047857), Authorisation Letter upload/download/template
- [x] Mongo collections: `bc_runs`, `bc_ledgers`, `bc_templates`, `bc_authorizations`, `bc_books_raw` (gzipped Tally JSON kept for future re-classification)
- [x] **UUID `response_token` baked into every ledger at ingest** — Phase 4 recipient response loop will need zero schema migration
- [x] Tally classifier walks `groups[]` parent chain; reserved groups (Sundry Debtors → Trade Receivable, Sundry Creditors → Trade Payable, Bank Accounts / Bank OD A/c → Bank) + keyword fallback. Verified on Allman: 195 ledgers → 58 receivable / 46 payable / 2 bank / 89 other.
- [x] Word `.docx` Authorisation Letter template generator (python-docx 1.2) — client signs on letterhead, scans as PDF, re-uploads. PDF auto-attached to confirmations in Phase 3.
- [x] Frontend `pages/balance_confirmation/Landing.jsx` (~560 lines): Past Runs sidebar, books dropzone, summary cards, ledger workbench (tabs / search / missing-email filter / CSV roundtrip / inline edit), Email Templates drawer, Authorisation drawer
- [x] Route `/dashboard/clients/:cid/utilities/balance-confirmation` (also `/runs/:rid` deep link) wired in App.js
- [x] `utilities.jsx` tile flipped `status="active"` (was "soon" → "in_progress" → "active")
- [x] Tests: 28/28 in `tests/test_balance_confirmation.py` (Run CRUD + Books ingest + Ledgers + CSV + Templates + Authorization + Cascade delete)
- [x] Dependency added: `python-docx==1.2.0` (for Word template)

## Balance Confirmation — Phase 3 live (2026-04-29)
- [x] Backend `modules/balance_confirmation/sender.py` — Resend send engine: `render_template` (placeholder substitution), `build_email_context`, `inject_tracking` (rewrites the response link → click-tracker URL + appends 1×1 transparent pixel), `send_one` wraps the synchronous Resend SDK in `asyncio.to_thread`, `can_transition` (terminal-status guard for confirmed/disputed)
- [x] Backend `modules/balance_confirmation/letter_pdf.py` — per-party Ledger Extract PDF (reportlab): walks Tally `vouchers[]`, finds every entry touching the party, produces a 7-column statement (Date / Voucher Type / Voucher # / Narration / Debit / Credit / Running Balance) with Opening + Closing rows
- [x] New routes (auth-gated unless noted):
      • `POST /api/balance-confirmation/runs/{rid}/send` — bulk-send via Resend with attachments [Ledger Extract + signed Authorization PDF], `reply_to` = current user's email, `cc` = universal payload.cc + per-ledger ledger.cc_emails (deduped). Per-recipient try-loop; isolated failures.
      • `GET  /api/balance-confirmation/runs/{rid}/reminders?cadence_days=` — eligible list (default 3 → 7 → 14 days; never re-reminds within window)
      • `GET  /api/balance-confirmation/runs/{rid}/send-log` — full audit trail (newest first) + `?ledger_id=` filter
      • `DELETE /api/balance-confirmation/runs/{rid}/send-log` — clear log for a run
      • `GET  /api/balance-confirmation/track/pixel/{token}.gif` — **public**, returns 43-byte transparent gif + flips status to `opened`
      • `GET  /api/balance-confirmation/track/click/{token}` — **public**, 302 → `/confirm/{token}` + flips status to `clicked`
      • `POST /api/balance-confirmation/webhook/resend` — **public** but Svix-signature gated. Fail-closed if `RESEND_WEBHOOK_SECRET` unset (503). Maps `email.sent / delivered / opened / clicked / bounced / complained` → ledger.status with terminal-state protection.
- [x] Mongo collection `bc_send_log` — every send / webhook event / pixel hit / click logged; cascade-deleted on run delete
- [x] Frontend Phase 3 additions in `Landing.jsx` (~770 lines now): bulk-action bar (selected count, Send Selected, Send Reminder, Send All in View), per-row checkbox + select-all (auto-disabled on rows with no email), Universal Cc input, Status chip column with 10 states, Send Log drawer
- [x] Env additions: `RESEND_API_KEY` (re_***), `RESEND_SENDER_EMAIL=onboarding@resend.dev`, `RESEND_SENDER_NAME=MSS x Assure Audit Utilities`, `RESEND_WEBHOOK_SECRET` (whsec_***)
- [x] Live verification: real send to delivered@resend.dev returned a Resend message id, Resend webhook fired (svix-signed), pixel + click flipped status correctly. **42/42 backend tests pass** (28 Phase 1+2 + 14 Phase 3 in `test_balance_confirmation_phase3.py`); frontend smoke confirms all 7 new test-ids present.
- [x] Dependencies added: `resend==2.29.0`, `svix==1.92.2`

## Deferred
- MUI rewrite (user confirmed Option A — defer to Phase 2)
- End-to-end browser testing of MSME upload + compute flow (requires real Excel/JSON fixtures and an authenticated session)
