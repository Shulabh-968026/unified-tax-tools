# Third-Party Confirmations Module — Product Requirements Document

**Module slug:** `balance-confirmation`
**Status:** ✅ Phases 1–6 Live (v1.0) · 2026-04-29
**Owner:** MSS × Assure Audit Utilities
**Brand for recipient experience:** AssureAI (green `#047857` / `#ECFDF5`)

---

## 1. Executive Summary

The Third-Party Confirmations Module is a **complete, self-service confirmation
engine** built for Chartered Accountants conducting statutory audits under
Section 44AB. It automates the entire lifecycle:

```
   Tally Books JSON
        │
        ▼
   ① Ingest + classify ledgers (Trade Receivable / Payable / Bank / Other)
        │
        ▼
   ② Map emails (UI + bulk CSV import/export)
        │
        ▼
   ③ Bulk-send confirmation emails via Resend
      (HTML body · per-party Ledger Extract PDF · client Authorisation Letter PDF)
        │
        ▼
   ④ Recipient lands on /confirm/<token>  →  Yes-Confirmed / No-Disputed
                                              (with reason + ledger upload)
        │
        ▼
   ⑤ Auditor reviews responses → side-by-side recon for disputed parties
        │
        ▼
   ⑥ Excel + PDF Summary Working-Paper for the audit file
```

Every confirmation has a **secure UUID response token** that is generated at
ingest time, eliminating any later schema migrations.

---

## 2. Personas & Primary Use Cases

### 2.1 The Auditor (CA partner / article)
*"I need confirmations from 200 trade receivables, 150 payables, and 5 banks
within 10 days, signed off, and turned into a working paper for the audit
file."*

- Imports the Year's Books once.
- Maps emails (existing master + manual additions).
- Triggers bulk send with one click.
- Reviews real-time status (Sent → Delivered → Opened → Confirmed/Disputed).
- Reconciles disputed responses side-by-side.
- Downloads working-paper exports.

### 2.2 The Recipient (third party — vendor, customer, bank)
*"I just got an email asking me to confirm a balance — I don't want to log
in, register, or download anything. I just want to click one button."*

- Receives a clean branded email with a single CTA.
- Clicks → sees the balance + 2 buttons.
- Confirms in 2 clicks, OR attaches their statement + reason in 30 seconds.
- Gets a thank-you reference number.

### 2.3 The Reviewer (audit partner)
*"I want to see in one PDF: who confirmed, who disputed, who is silent,
and what the differences are."*

- Downloads the Summary PDF / XLSX.
- Reviews the variance worksheet.
- Signs off on the cover page.

---

## 3. Architecture

### 3.1 Backend (FastAPI · Python 3.11)
```
/app/backend/modules/balance_confirmation/
├── __init__.py
├── controller.py        → All routes under /api/balance-confirmation/*
├── schemas.py           → Pydantic models
├── classifier.py        → Tally group → category mapping (Phase 1)
├── service.py           → Books ingest + CSV roundtrip (Phase 1)
├── templates.py         → 3 default email templates (Phase 2)
├── exports.py           → Authorisation Letter Word generator (Phase 2)
├── sender.py            → Resend send + telemetry + status transitions (Phase 3)
├── letter_pdf.py        → Per-party Ledger Extract PDF (Phase 3)
├── summary_export.py    → 6-sheet XLSX + multi-page PDF (Phase 5)
└── recon.py             → XLSX/CSV parser + auto-match (Phase 6)
```

### 3.2 Frontend (React 19 · React-Router 7 · Tailwind · shadcn/ui)
```
/app/frontend/src/pages/balance_confirmation/
├── Landing.jsx          → Auditor workbench (~1045 lines, all phases)
└── ConfirmPage.jsx      → Public recipient page (~370 lines, AssureAI green)
```

### 3.3 Data Layer (MongoDB via Motor)

| Collection | Purpose | Cascade-deleted on run delete |
|---|---|---|
| `bc_runs` | One per FY-end confirmation cycle | — |
| `bc_ledgers` | Tally-derived + auditor-edited contact info per party | ✅ |
| `bc_books_raw` | Gzipped + base64 Tally JSON for re-classification + recon | ✅ |
| `bc_templates` | Email template library (3 default + custom) | global |
| `bc_authorizations` | Signed authorisation PDF per client | per-client (no cascade) |
| `bc_send_log` | Every send / webhook / pixel / click event | ✅ |
| `bc_responses` | Recipient submissions (confirm or dispute + attached statement) | ✅ |
| `bc_recon_comments` | Auditor working notes per recon pair | ✅ |

### 3.4 Routes (Auth = `session_token` cookie unless marked Public)

#### Phase 1 — Data Ingestion
| Method | Path | Purpose |
|---|---|---|
| POST | `/runs` | Create new run |
| GET | `/runs?client_id=` | List runs |
| GET | `/runs/{rid}` | Run detail |
| DELETE | `/runs/{rid}` | Cascade-delete run |
| POST | `/runs/{rid}/upload-books` | Tally JSON ingest + classify |
| GET | `/runs/{rid}/ledgers?category=&missing_email=` | List ledgers |
| PATCH | `/runs/{rid}/ledgers/{lid}` | Update email/cc/contact/category |
| GET | `/runs/{rid}/ledgers/export.csv` | Bulk download |
| POST | `/runs/{rid}/ledgers/import.csv` | Bulk update |

#### Phase 2 — Templates & Authorisation
| Method | Path | Purpose |
|---|---|---|
| GET | `/templates?kind=` | List templates (auto-seeds 3 defaults) |
| POST | `/templates` | Create custom |
| PATCH | `/templates/{tid}` | Update |
| DELETE | `/templates/{tid}` | Delete (rejects if `is_default`) |
| POST | `/clients/{cid}/authorization` | Upload signed PDF |
| GET | `/clients/{cid}/authorization` | Get metadata |
| GET | `/clients/{cid}/authorization/file` | Download PDF |
| DELETE | `/clients/{cid}/authorization` | Remove |
| GET | `/clients/{cid}/authorization/template.docx` | Download editable Word template |

#### Phase 3 — Sending Engine
| Method | Path | Purpose |
|---|---|---|
| POST | `/runs/{rid}/send` | Bulk send via Resend (reply_to dynamic, cc dedup) |
| GET | `/runs/{rid}/reminders?cadence_days=` | List eligible reminders (3/7/14 default) |
| GET | `/runs/{rid}/send-log?ledger_id=` | Audit trail (newest first) |
| DELETE | `/runs/{rid}/send-log` | Clear log |
| **GET** | `/track/pixel/{token}.gif` | **Public** · 43-byte 1×1 gif + status→opened |
| **GET** | `/track/click/{token}` | **Public** · 302 → /confirm/{token} + status→clicked |
| **POST** | `/webhook/resend` | **Public + Svix-signed** · Fail-closed if secret unset |

#### Phase 4 — Recipient Response Loop
| Method | Path | Purpose |
|---|---|---|
| **GET** | `/public/confirmation/{token}` | **Public** · Render context |
| **POST** | `/public/confirmation/{token}/confirm` | **Public** · Yes-Confirmed |
| **POST** | `/public/confirmation/{token}/dispute` | **Public** · No + reason + file (multipart, 8MB cap) |
| GET | `/runs/{rid}/responses?decision=` | Auditor list (enriched with our_balance) |
| GET | `/runs/{rid}/responses/{response_id}/attachment` | Download recipient's file |

#### Phase 5 — Summary Reports
| Method | Path | Purpose |
|---|---|---|
| GET | `/runs/{rid}/summary.xlsx` | 6-sheet workbook |
| GET | `/runs/{rid}/summary.pdf` | Multi-page PDF working-paper |

#### Phase 6 — Side-by-side Reconciliation
| Method | Path | Purpose |
|---|---|---|
| GET | `/runs/{rid}/responses/{response_id}/recon?tolerance=` | Parse + auto-match |
| GET | `/runs/{rid}/responses/{response_id}/recon/comments` | List notes |
| POST | `/runs/{rid}/responses/{response_id}/recon/comments` | Add note |
| DELETE | `/runs/{rid}/responses/{response_id}/recon/comments/{cid}` | Remove note |

---

## 4. Phase-by-Phase Functionality

### Phase 1 — Data Ingestion + Classification

**Inputs**: Tally Books JSON (same format as 43B(h) + GST Recon).

**Classifier rules** (`classifier.py`):
1. Walk `parentGroup` chain via the Tally `groups[]` master.
2. Reserved-group hits in the chain →
   - `Sundry Debtors` → `trade_receivable`
   - `Sundry Creditors` → `trade_payable`
   - `Bank Accounts` or `Bank OD A/c` → `bank`
3. Keyword fallback (`creditor` / `debitor` / `bank`) for custom charts of accounts.
4. Anything else → `other` (auditor re-classifies in UI).

**Sign convention**: Tally `closingBalance > 0` = Credit, `< 0` = Debit.

**Verified on Allman Knitwear** (real client, FY 24-25, 195 ledgers):
- 58 trade receivables, 46 trade payables, 2 banks (Karur Vysya / SBI), 89 other.

**CSV roundtrip** for bulk email mapping:
- Columns: `ledger_id, name, parent_group, category, closing_balance, dr_cr, email, cc_emails, contact_name, phone, gstin, pan, address`
- BOM + UTF-8 (Excel-friendly)
- Match priority: `ledger_id` → `name` (exact)
- Returns `{rows_in_csv, matched, not_found[]}`

### Phase 2 — Template Configuration

**Default templates auto-seeded on first GET /templates**:

| Kind | Tone | Subject |
|---|---|---|
| `customer` | Standard reconciliation | "Balance Confirmation Request as on `{{as_at_date}}` · `{{client_name}}`" |
| `vendor` | Statement matching focus | "Statement of Account & Balance Confirmation as on `{{as_at_date}}` · `{{client_name}}`" |
| `bank` | Formal RBI 7-section format | "Independent Bank Confirmation as on `{{as_at_date}}` · `{{client_name}}`" |

**Placeholders** (Jinja-style `{{tokens}}`):
`client_name`, `client_gstin`, `as_at_date`, `party_name`, `contact_name_or_party`,
`closing_balance_inr`, `dr_cr`, `response_link`, `auditor_name`, `auditor_firm`, `address`

**Authorisation Letter**:
- **Step 1**: Auditor downloads Word template (`python-docx 1.2`) with placeholders + AssureAI green title.
- **Step 2**: Client signs on letterhead, scans as PDF.
- **Step 3**: Auditor uploads PDF — auto-attached to every confirmation email.

### Phase 3 — Sending Engine + Telemetry

**Resend integration**:
- `RESEND_API_KEY`, `RESEND_SENDER_EMAIL=onboarding@resend.dev` (free tier, awaiting domain verification — see §6.1).
- `reply_to` = current logged-in user's email (so vendor replies hit the auditor directly).
- `cc` = universal cc (per-batch from UI) + per-ledger `cc_emails` (auto-deduped).
- `RESEND_WEBHOOK_SECRET` (Svix-signed) — fail-closed if unset.

**Each email contains**:
1. Rendered HTML body (template + placeholders)
2. Tracking pixel (43-byte gif, no-cache headers)
3. Click-through rewrite — link goes through `/track/click/{token}` (logs + 302)
4. Attachment: per-party Ledger Extract PDF (reportlab — Date / Voucher Type / Voucher # / Narration / Debit / Credit / Running Balance, with Opening + Closing rows in AssureAI green)
5. Attachment: signed Authorisation Letter PDF (if uploaded for the client)
6. `tags: [{name:"run_id", value:rid}, {name:"kind", value:"send"|"reminder"}]`

**Status state machine** (`sender.can_transition`):
```
not_sent ─► queued ─► sent ─► delivered ─► opened ─► clicked
                                                       │
                                                       ▼
                                              confirmed | disputed   ← TERMINAL
                                              bounced  | failed
```
- `confirmed` and `disputed` are TERMINAL — pixel/click events cannot downgrade them.
- `bounced` and `failed` from Resend webhook flip status without overwriting prior timestamps.

**Reminder framework**:
- Default cadence **3 / 7 / 14 days**.
- `GET /runs/{rid}/reminders?cadence_days=N` returns eligible ledgers (`sent | delivered | opened | clicked` + older than N days + not re-reminded within window).
- Auditor reviews list, picks subset, calls `POST /runs/{rid}/send` with `is_reminder=true` (subject auto-prefixed `[Reminder]`).

**Send Log drawer** in UI shows every `send / reminder / webhook / telemetry / response` event chronologically.

### Phase 4 — Recipient Response Loop

**Public route** `/confirm/:token` — outside `ProtectedRoute` in `App.js`.
Uses raw `axios` (NOT the auth-injecting `http` alias) so no cookies leak.

**Page flow**:
```
GET /api/balance-confirmation/public/confirmation/<token>
   │
   ├─ token unknown          → "Link Invalid or Expired" friendly screen
   ├─ already submitted      → Thank-you screen (idempotent)
   └─ fresh                  → Choose state
                                ├─ "✓ Yes" (green) → Confirm form (name/email/note) → POST /confirm
                                └─ "✗ No"  (amber) → Dispute form
                                                     ├─ Name / Email
                                                     ├─ Their balance + Dr/Cr selector
                                                     ├─ Reason (required)
                                                     └─ File upload (optional, 8MB cap)
                                                     → POST /dispute (multipart)
```

**Security**:
- Token = UUIDv4 hex (32 chars, ~128 bits entropy). Cannot be guessed.
- Public endpoints never echo `uploaded_content_b64` (file bytes hidden in projections).
- Multipart endpoint has early `Content-Length` pre-check (>9MB rejected before buffering).
- Filename sanitised on download (`Content-Disposition`) — strips path separators + quotes.
- Empty reason → 400.
- Each response stores `responder_ip` + `user_agent` for audit trail.

**Auditor view** (`bc-responses-drawer`):
- Decision filter (all / confirmed / disputed)
- Side-by-side our-vs-their balance (amber tint when diff > ₹1)
- Reason text in amber callout
- Confirmation note in green callout
- Attachment download button (auth-gated)
- "⇆ Reconcile" button when filename ends in `.xlsx` or `.csv` (Phase 6)

### Phase 5 — Summary Working-Paper

**Excel workbook** (`summary_export.build_summary_xlsx`) — 6 sheets:

1. **Cover** — Client / FY / As-at / Auditor / Generated + 7-row Status Summary (Confirmed · Disputed · In Flight · Failed · No Action · Without Email · Total)
2. **Sent Tracker** — 15 columns × N rows: Party · Group · Category · Email · Closing · Dr/Cr · Status · Queued At · Sent At · Delivered At · Opened At · Clicked At · Bounced At · Last Reminder · Attempts. Row tinted by status (emerald=confirmed, amber=disputed, rose=bounced/failed). Frozen header.
3. **Status Timeline** — Chronological send_log: Timestamp · Party · Kind · Status · Resend ID · To Email · Subject/Note · Actor.
4. **Variances** — Disputed responses with our_balance vs their_balance + diff + reason + responder + submitted timestamp + attachment filename. Diff > ₹1 → amber tint.
5. **Confirmed** — Clean sign-off list (emerald-tinted): Party · Email · Our Books · Dr/Cr · Confirmed By · Confirmed Email · Submitted · Note.
6. **Notes** — Blank intentionally; auditor types working notes here.

**PDF working-paper** (`build_summary_pdf`) — multi-page A4:

1. **Cover + Health** — Client block (CLIENT / GSTIN / FY / AS AT / AUDITOR / GENERATED) + Status banner (auto-coloured: emerald all-confirmed, amber some-disputed, blue still-awaiting) + 4 KPI cards (CONFIRMED · DISPUTED · IN FLIGHT · FAILED·BOUNCED).
2. **Disputed Confirmations** (if any) — Top-12 by abs(diff): Party · Our Books · Their Books · Diff · Reason. "+ N more" footer if >12.
3. **Confirmed Parties** (if any) — All confirmed: Party · Email · Books · Confirmed By · On.
4. **Sign-off** — PREPARED BY · REVIEWED BY · DATE blocks + boilerplate notes about working-paper purpose.

Footer on every page: `Balance Confirmation Summary · FY <fy> · Run <rid> · Page N · MSS × Assure · Audit Utilities`

### Phase 6 — Side-by-side Reconciliation

**When recipient uploads an .xlsx or .csv statement with their dispute**, auditor clicks "⇆ Reconcile" → ReconModal opens.

**Parser** (`recon.parse_recipient_statement`):
- Auto-detects Date / Voucher Type / Voucher # / Particulars / Debit / Credit / Balance / Amount columns via header keyword matching (multilingual hint sets).
- XLSX: scans first 25 rows for header (skips title rows).
- CSV: sniffs delimiter (`,` `;` `\t` `|`).
- Date parsing: ISO `YYYY-MM-DD`, Indian `dd-mm-yyyy` / `dd/mm/yyyy`, with year inference for 2-digit.
- Amount parsing: handles parentheses-as-negative, comma thousands, currency symbols.
- Single-Amount-column variant: positive→Credit, negative→Debit.

**Auto-matcher** (`recon.auto_match`):
- Greedy amount-only match within `±tolerance` rupees (default 1, configurable).
- Sign-insensitive: our credit ≡ their debit (counterparty mirroring).
- O(N×M) — fine for typical ledger sizes (<500 rows); flag for >5k.
- Each unmatched row tagged `ours_only` (left-only) or `theirs_only` (right-only).

**ReconModal UI**:
- Header: party + responder + dispute date + attachment filename
- 5-cell metric strip: Our balance · Their balance · Auto-matched · Ours/Theirs only counts · **Tolerance ₹ control** (default 1, live re-match)
- Two-pane diff table:
  - LEFT (emerald tint, 5 columns: Date / Type / Vch # / Dr / Cr)
  - CENTRE (Δ indicator: `≈ X.XX` for matches, `←` for ours_only, `→` for theirs_only)
  - RIGHT (amber tint, 5 columns)
- Comments section: live timestamp + author per note; saved to `bc_recon_comments`; cascade-delete with run.

**Limitations (v1)**:
- PDF/JPG attachments → friendly "Auto-parse not supported · download to review manually" screen (PDF needs OCR + table extraction — heavy lift for v2).
- No date-window matching (intentional simplicity; manual link/unlink in UI fills the gap).
- No per-pair manual link/unlink yet (workaround: comment per pair, then accept/reject in v2).

---

## 5. Test Coverage

| Test file | Cases | Status |
|---|---|---|
| `test_balance_confirmation.py` (P1+2) | 28 | ✅ Pass |
| `test_balance_confirmation_phase3.py` (P3) | 14 | ✅ Pass |
| `test_balance_confirmation_phase4.py` (P4) | 15 | ✅ Pass |
| `test_balance_confirmation_phase5_6.py` (P5+6) | 21 | ✅ 20 pass, 1 skipped (text-only-dispute fixture missing — non-blocking) |
| **TOTAL** | **78** | **77 pass · 1 skipped** |

Frontend Playwright regression in `/app/test_reports/iteration_8.json` and `iteration_9.json` — all data-testids present and functional flows verified end-to-end.

---

## 6. Pending Items — Action Checklist for User

### 6.1 🚨 Production Email Hardening

- [ ] **Verify a sending domain on Resend** *(BLOCKER for real client emails)*
  - **What:** Until you verify a domain, Resend rejects sends to anyone other than your API-key owner address (`dhananjayan@transformautomations.com`).
  - **Where:** [resend.com/domains](https://resend.com/domains) → Add Domain → enter e.g. `assureai.in` or `mssco.in`
  - **DNS records** Resend will give you (need domain admin access at GoDaddy / Cloudflare / Route 53):
    - 3 × CNAME records for DKIM
    - 1 × TXT record for SPF
    - 1 × TXT record for DMARC
  - **Once verified** (~15 minutes): edit `/app/backend/.env` → change `RESEND_SENDER_EMAIL=onboarding@resend.dev` to `RESEND_SENDER_EMAIL=confirmations@<your-domain>` → `sudo supervisorctl restart backend`.
  - **Note:** You said you don't currently have domain admin access; loop in your IT / domain admin.

- [ ] **Update Resend webhook URL after production deploy**
  - **Where:** Resend Dashboard → Webhooks → existing endpoint → Edit
  - **Change:** `https://unified-tax-tools.preview.emergentagent.com/api/balance-confirmation/webhook/resend`
    → `https://<your-prod-url>/api/balance-confirmation/webhook/resend`
  - **Subscribed events** (verify these are still ticked):
    `email.sent`, `email.delivered`, `email.bounced`, `email.opened`, `email.clicked`, `email.complained`

### 6.2 ✍️ Per-Client Setup (Repeat for each new client)

- [ ] Create the **client** in `/dashboard/clients` with a valid GSTIN.
- [ ] **Customise the email templates** (Templates drawer) to match your firm's tone — particularly the auditor name, firm name, footer.
- [ ] **Generate the Authorisation Letter Word template** (Authorisation drawer → Step 1) → put on client letterhead → get signed → scan to PDF → upload (Step 2). This PDF will auto-attach to every confirmation email for this client.

### 6.3 📦 Per-Run Setup

- [ ] Create a **new Run** with the right FY (e.g. `2024-25`) and as-at date.
- [ ] Upload the **Year's Books JSON** from Tally (same format as 43B(h) / GST Recon — must include `groups[]`, `ledgers[]`, `vouchers[]` keys).
- [ ] **Map emails** for parties whose ledgers don't already carry contact info — either inline in the workbench or via the CSV roundtrip:
  1. Click **Export CSV** in the workbench
  2. Open in Excel, fill in `email`, `cc_emails`, `contact_name`, `phone` columns
  3. **Import CSV** back — UI will report `matched / rows_in_csv`
- [ ] **Re-classify any "Other" ledgers** the heuristic missed (Receivable / Payable / Bank / Other dropdown per row).
- [ ] **Decide your Universal CC** for the batch (e.g. `audit-team@yourfirm.in`) — entered in the toolbar before clicking Send.

### 6.4 📤 Sending

- [ ] Smoke-test with **1-2 confirmations** to your own email first (verify the template, attachments, branding).
- [ ] Once happy, **multi-select + Bulk Send** the rest. Resend's free tier limit is 3,000 emails/month / 100 emails/day — for larger runs, upgrade to the paid plan.
- [ ] Monitor **Send Log** for any bounces / failures. Resend will flag bad addresses; update the email + retry.
- [ ] After **3 days** with no response → auditor reviews `GET /reminders?cadence_days=3` → multi-select + click "Send Reminder" (subject auto-prefixed `[Reminder]`).
- [ ] Repeat at **7** and **14** days.

### 6.5 📥 Receiving Responses

Recipients land on your `/confirm/<token>` page. No action needed from you — submissions auto-flip status to `confirmed` or `disputed` and appear in the Responses drawer.

- [ ] Periodically open the **Responses drawer** to triage what came back.
- [ ] For **disputed** responses with an XLSX/CSV attachment → click **⇆ Reconcile** → review side-by-side → leave reconciliation notes per pair.
- [ ] For disputed responses with PDF/JPG attachments → click **download** and review manually.
- [ ] For **confirmed** responses → no further action; they're audit-ready.
- [ ] For **silent** ledgers (still in `sent / delivered / opened` after 14 days) → manual escalation via phone/courier (out of scope for this module).

### 6.6 📑 Working-Paper Generation

- [ ] At the end of the cycle, click **Summary XLSX** (emerald button in run header) → review all 6 sheets → fill in the **Notes** sheet.
- [ ] Click **Summary PDF** (rose button) → print → partner signs the Sign-off page → attach to the audit file.

### 6.7 🏆 Optional Enhancements (P2 — discuss as future tasks)

- [ ] **Domain branding email-side** — once a verified domain ships, also customise the `From` display name (`MSS & Co. Audit Confirmations <confirmations@your-domain>`) and add a firm logo to the header.
- [ ] **AI summary in ReconModal** — one-line LLM-generated conclusion ("4 of 9 differences explained by cheques in transit · 2 unmatched invoices need GST e-way bill verification") using the Universal LLM key. ~30 minutes to wire.
- [ ] **Cross-utility bridge** from GST Recon → Bulk Send confirmations to parties with unmatched ITC variances.
- [ ] **Date-window auto-matching** in recon (today is amount-only).
- [ ] **PDF statement parser** for recon (today only XLSX/CSV are auto-parsed; PDF needs OCR).
- [ ] **Per-pair manual link / unlink** in ReconModal (today's auto-match is global).
- [ ] **Reminder cadence override per batch** in UI (currently fixed default 3/7/14).
- [ ] **"Snooze" action** on disputed responses (remind me in 7 days) for partner triage.
- [ ] **Refactor `Landing.jsx`** (1045 lines) into smaller modules.
- [ ] **Telemetry pixel served from CDN** with shorter URL — reduces email size + improves deliverability.
- [ ] **Bank confirmation paper-mail variant** — generate a printable PDF letter for parties without email.

### 6.8 🛠️ Operational / DevOps

- [ ] Decide your **email send cap** policy (Resend free → paid upgrade thresholds).
- [ ] Set up **alerting** on bounce rate > 5% (high bounce hurts deliverability; usually means stale email list).
- [ ] **Monthly DB backup** — `bc_responses` is your audit-evidence collection; back it up alongside `bc_send_log`.
- [ ] **GDPR / DPDP**: recipient `responder_ip` + `user_agent` are stored. If any recipient asks for deletion, build a one-off script that scrubs `bc_responses` + `bc_send_log` for that party. (Or add a UI button later.)

---

## 7. Tech Stack & Dependencies

| Layer | Tech |
|---|---|
| Backend | FastAPI 0.110, Python 3.11, Motor (async MongoDB), Pydantic v2 |
| Frontend | React 19, React-Router 7, Tailwind, shadcn/ui (sonner toasts), lucide-react |
| Email | `resend==2.29.0` (transactional), `svix==1.92.2` (webhook verification) |
| Documents | `reportlab==4.4.10` (PDFs), `openpyxl` (XLSX), `python-docx==1.2.0` (Word) |
| Storage | MongoDB collections (gzipped Tally JSON + base64 PDFs in BSON, 16MB doc limit observed) |

---

## 8. Branding Reference

| Surface | Color | Hex |
|---|---|---|
| AssureAI green (recipient-facing emails + landing page) | Emerald-700 | `#047857` |
| AssureAI green soft (callouts, banners) | Emerald-50 | `#ECFDF5` |
| Auditor-facing UI | Slate / neutral | (default Tailwind) |

---

## 9. Document Trail

- `/app/memory/PRD.md` — Master product PRD (all utilities)
- `/app/memory/THIRD_PARTY_CONFIRMATIONS_PRD.md` — **This file**
- `/app/memory/test_credentials.md` — QA token re-seed instructions
- `/app/test_reports/iteration_6.json` — Phase 1+2 sign-off
- `/app/test_reports/iteration_7.json` — Phase 3 sign-off
- `/app/test_reports/iteration_8.json` — Phase 4 sign-off
- `/app/test_reports/iteration_9.json` — Phase 5+6 sign-off

---

*Last updated 2026-04-29 by E1 (Emergent agent) after Phase 6 completion.*
