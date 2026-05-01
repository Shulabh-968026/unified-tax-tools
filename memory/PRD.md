# MSS × Assure — Audit Utilities (Merged)

## Fixed Assets — Discount/Credit row merge into a parent asset (2026-05-01 AM-2)

User screenshot showed that rose-tinted **Discount/Credit rows** in the Additions tab had no 🔗 Merge button, so an auditor couldn't net a debit-note/discount off against a specific asset purchase. Now they can.

### Backend (`controller.py`)
- `_unlink_addition()` branches on `aid.startswith("discount-")` — for discount aids it looks up the credit doc, decrements the parent's `<linked_as>` column by `abs(credit.amount)`, and clears `parent_addition_id` + `linked_as` on the credit (linkage is persisted on `fa_credits`, not `fa_additions`).
- `link_addition()` has a dedicated discount-credit branch: validates the credit exists and is classified as `discount`, resolves the credit's block via `fa_ledgers`, enforces same-block coherence with the parent, and persists the linkage on the credit doc. Re-fetches the parent **after** the idempotent `_unlink_addition` call so re-linking the same credit no longer double-counts (also fixed for the regular-addition branch).
- `classify_credit()` auto-unlinks before transitioning out of `discount` (sale or pending), so the parent's adjustment column doesn't keep a stale value after reclassification.
- `GET /runs/{rid}/additions` and the xlsx export now propagate `parent_addition_id` + `linked_as` from the credit doc onto the synthetic `discount-<credit_id>` row, so the UI's existing `MergedRow` component renders it as a compact "↳ Merged" strip without changes.
- `_gather_compute_inputs()` skips discount credits with `parent_addition_id` to avoid double-subtract — the magnitude is already netted into the parent's `discount_credits` (or other) column at link time.

### Frontend
- `AdditionRow.jsx` — link button now renders on locked discount rows too (rose hover, distinct tooltip).
- `MergeModal.jsx` — when `child.source==='discount_credit'`: header reads "Net discount / credit", a rose-tinted hint banner appears, and `linked_as` defaults to `discount_credits` (instead of `other_expenses`).

### Tests
- New `tests/test_fixed_assets_discount_merge.py` — 9/9 GREEN: link routes magnitude into chosen column, idempotent re-link does NOT double, switching `linked_as` moves cleanly between columns, unlink restores parent + clears credit, compute totals are invariant under link/unlink (₹6,226,269.16 baseline preserved), self-link rejected (400), unknown parent (404), bogus column (400), reclassify discount→sale auto-clears the linkage.
- Frontend (Playwright iteration_12) — 4/4 acceptance points GREEN: link button visible on discount rows, modal opens with new header + Discounts/Credits pre-selected, merge writes "↳ Merged · ₹7,582.00 · as Discounts/Credits" strip, unlink reverts cleanly. Final cleanup + compute re-baselined.

## Fixed Assets — One-click bulk attach + GST-aware matcher (2026-05-01 AM-1)

Three closely-linked changes that together turn the OCR pipeline from "review every chunk" into "trust + verify".

### #1 — GST-aware matcher (the real unlock)
Watching the user's video revealed the matcher's blind spot: **Tally books fixed assets NET of input GST** (the GST goes to a separate ITC ledger), but Gemini extracts the **gross** total from the invoice. So `invoice_cost = ₹63,600` and `total_value = ₹75,048` with a 18% GST gap that pass-2 was rejecting.

The matcher now compares against BOTH `total_value` AND `taxable_value` (the OCR already extracts the taxable line). If either matches the addition's `invoice_cost` within tolerance — same row wins. Tested on `COMPUTER_GST_18.pdf`: was 0 / 9 auto-matches → now **8 / 9 high-confidence**, with the 9th genuinely having no Tally row.

### #2 — Confidence tiers
Every match now carries `confidence: "high" | "medium" | "low"` instead of just a score:
| Trigger | Confidence |
|---|---|
| Exact normalised invoice number match | high |
| Total/taxable within ±₹1 + GSTIN match | high |
| Total/taxable within ±₹1 + party fuzzy ≥85 | high |
| Total/taxable within ±0.5% + party ≥80 | medium |
| Fuzzy invoice number (≥85) + party ≥70 | low |

Inline backfill on every read (`_infer_confidence_from_method`) means chunks stored before this change still get the new UI. The matcher returns `best_high` first, falls back to `best_medium` only if pass-3 fuzzy doesn't beat it.

### #3 — One-click apply (two trigger points)
**Backend** — `POST /runs/{rid}/apply-all-high-confidence` sweeps every `done` pending upload, attaches every chunk with `confidence: "high"` (skipping already-applied), overwrites each target row's description, and returns `{total_attached, total_descriptions, uploads_processed, per_upload: [...]}`. Single transaction, single HTTP call.

`GET /runs/{rid}/invoice-inbox` now also returns `total_high_conf_pending` at the top level + `high_conf_pending` per row for badge rendering.

**Frontend — two trigger points:**
1. **Inside the modal** (when reviewing one PDF) — emerald banner above the chunk list: `⚡ N high-confidence matches found — pre-selected with description overwrite` and `[⚡ Apply all N]` button. Confirm dialog before commit.
2. **On the inbox panel** (sweep all pending uploads) — `[⚡ Auto-apply N]` button next to the refresh icon, only visible when `total_high_conf_pending > 0`. Confirm dialog: *"Across X inbox uploads: Y high-confidence matches will be attached and Y asset descriptions overwritten."*

Per-chunk confidence pills (`★ High` emerald, `medium` amber, `low` slate) render inside each chunk card so the auditor can always see which matches were trusted.

### End-to-end verified
- Backend smoke: upload `COMPUTER_GST_18.pdf` → 8 high-conf matches detected → sweep returns `{total_attached: 8, total_descriptions: 8}` → 8 rows now carry audit-grade descriptions like "Dell Monitor", "HP LaserJet Pro", "Processor i3 12th Gen, Motherboard, RAM, SSD, HDD, Monitor".
- Frontend Playwright (Resume + sweep): inbox sweep button shows `Auto-apply 8`, modal banner shows `[⚡ Apply all 8]`, 8/9 chunks carry the green `★ High` confidence pill.
- Backend lint clean. Frontend lint clean.

## Fixed Assets — Inbox + Multi-PDF + Ledger-aware OCR (2026-04-30 PM-6)

Four user-driven changes shipped together; all backend smoke-tested + frontend Playwright-verified.

### #1 · Ledger-aware target dropdown (P1)
- New Gemini prompt extracts `detected_ledger_name` from the OCR'd ledger pages (e.g. "Computer GST 18%", "Plant & Machinery GST 12%").
- New `detect_fa_ledger_id()` in `invoice_ocr.py` fuzzy-matches that against the run's `fa_ledgers.name` (token-set + partial-ratio, ≥85 confidence threshold).
- The Split-Preview modal carries a new ledger-filter strip with `BookMarked` icon: defaults to the auto-detected ledger (★ marker), but the auditor can pick a different ledger or `All ledgers (N)` to bypass entirely.
- When a chunk's auto-match falls outside the active ledger filter, the chunk header surfaces a small amber `Match is in another ledger — pick from current filter or switch to "All ledgers"` hint instead of silently failing.

### #2 · Replaced redundant block dropdown with always-visible ledger filter (P0)
- `AdditionsToolbar.jsx`: removed the redundant block dropdown (the chips strip above already carries that). Replaced with a permanent ledger filter: `All ledgers (N) / <ledger> · <count> rows`. Always visible (even with 1 ledger) so the auditor can see exactly what's in the active block.

### #3 · Default columns slimmed (P0)
- `additions/utils.js`: `Supplier · Voucher No · Invoice No · Inv Date` are now `default: false`. Auditors who rely on them flip them via the gear icon. Bumped LS key to `fa.additions.colVis.v2` so existing users get the new defaults on next visit.

### #4 · Persistent inbox + multi-PDF upload (P2)
**Backend — Mongo-backed pending uploads** (replaces the in-memory `_PENDING_UPLOADS` dict):
- New collection `fa_pending_invoice_uploads` — `{upload_id, run_id, client_id, filename, pdf_size, status, error?, page_classifications, ledger_pages, detected_ledger_name?, detected_fa_ledger_id?, single_invoice, summary, chunks: [{chunk_index, page_range, pdf_size, extraction, match, applied, applied_addition_id?, applied_at?}], created_at, finished_at?}`. Survives restarts indefinitely; auditor controls discards.
- New collection `fa_pending_chunk_pdfs` — sidecar `{upload_id, chunk_index, content_b64}` (gzipped+base64) per chunk so the parent doc stays well under Mongo's 16 MB cap even for 25 MB combined PDFs with many chunks.
- `apply_invoice_uploads`: copies chunk bytes into `fa_invoice_attachments` AND marks `chunks.$.applied = true` + `applied_addition_id` on the parent (so the inbox shows "4 of 9 attached"). Discount-credits / merged children remain rejected. The `409` response on apply when status≠done.
- New endpoints: `GET /runs/{rid}/invoice-inbox` (thin payload — chunk metadata only, no PDF bytes) and `DELETE /runs/{rid}/invoice-inbox/{upload_id}` (drops parent + sidecar PDFs; per-row attachments are NOT touched, so already-applied work survives discard).
- Cascade — run delete now drops both new collections too.
- `gemini_extract`: 3× retry with exponential backoff (3s, 8s) on 502/503/504/timeout/rate-limit, eliminating the user's original `BadGatewayError` failure mode.
- OCR work runs in `asyncio.to_thread(lambda: asyncio.run(...))` so LiteLLM's sync HTTP client doesn't starve the event loop — upload returns in <2 s even for 13-page PDFs.

**Frontend — Multi-file upload + persistent inbox UI**:
- `<input multiple>` accepts many PDFs at once. All upload requests fire in parallel (`Promise.allSettled`), each kicks off a backend OCR job. **No modal opens automatically** (per user choice (c)) — the auditor reviews from the inbox at their own pace.
- New `InvoiceInbox.jsx` component sits below the dropzone, lists every pending upload with: filename · size · auto-detected ledger chip · status badge (processing/done/failed) · `<N>/<M> attached` counter · **Resume** button · **Discard** trash icon. Auto-polls every 4 s while any row is `processing`, then stops.
- The Split-Preview modal now opens via "Resume" on an inbox row. Already-applied chunks render as compact emerald `Already attached → <row description>` strips (read-only); only pending chunks remain editable.
- Inbox stays expanded by default but is collapsible with a chevron. Counter chips at top: "N uploads · X processing · Y chunks unattached".

### End-to-end verification
- ✅ Upload of `sample_velav.pdf` returns in 1.75 s; background OCR completes in 32 s; inbox shows the new entry with auto-detected ledger "Plant & Machinery GST 12%" auto-mapped to `fa_ledger_id`.
- ✅ Frontend Playwright sweep: dropzone present, inbox present, ledger filter present (block dropdown absent), Supplier/Voucher/Inv-No/Inv-Date column headers absent (all `count=0`), Resume button on inbox row opens the preview modal with `detected ledger = Plant & Machinery GST 12%` line visible and modal ledger filter present.
- ✅ Backend lint clean. Frontend lint clean.

## Fixed Assets — Phase 1.5: OCR-powered invoice attachment (2026-04-30 PM-5)

**Single biggest UX win on the whole module.** Auditor uploads a PDF — single tax invoice OR a combined ledger + N invoices PDF — and the system:
1. Calls Gemini 2.5-flash via the Emergent LLM key (no auditor key chase) to **classify every page** AND **extract structured invoice data per chunk** in a single round-trip.
2. **Slices the source PDF** into per-chunk PDFs (`pypdf`), preserving the exact pages of each invoice for audit evidence.
3. **3-pass auto-matches** each chunk to an addition row: (a) exact normalised invoice number, (b) GSTIN+total ± ₹1 / 0.5%, (c) fuzzy invoice number with party-name fuzzy ≥80.
4. Auditor reviews a Split-Preview modal — confirm/change target row per chunk, tick "Overwrite Description with extracted asset line", optionally skip chunks — then commits.

### Backend
- **New module** `/app/backend/modules/fixed_assets/invoice_ocr.py` — `gemini_extract` (single Gemini call with `LlmChat + FileContentWithMimeType`, temperature 0.1, schema-constrained prompt + code-fence-stripping defence) → `slice_pdf` (per-chunk via pypdf, page_range clamped to [1..n]) → `match_invoice_to_addition` (3-pass scoring; skips merged children + discount-credit pseudo-rows) → `split_extract_and_match` orchestrator that returns chunks with their gzipped+base64 PDFs ready to persist.
- **New endpoints** in `controller.py`:
  - `POST /runs/{rid}/upload-invoices` — multipart, .pdf-only + magic-byte (`%PDF`) check + 25 MB cap. Stashes chunks (with their gzipped PDFs) into an in-memory `_PENDING_UPLOADS` dict keyed by upload_id (TTL 1h, GC on every new upload). Returns a thin preview (drops the heavy `pdf_b64` blobs).
  - `POST /runs/{rid}/apply-invoice-uploads` — auditor confirmation step. `replace_one(upsert=True)` semantics on `(run_id, addition_id)` so re-applying replaces (never duplicates) the attachment. `apply_description=true` overwrites the row's description AND flips `reviewed=true`.
  - `GET /runs/{rid}/additions/{aid}/invoice` — streams the gzip-decompressed PDF inline, with `re.sub("[^A-Za-z0-9._-]+","_",...)` filename sanitiser to defend against header injection.
  - `DELETE /runs/{rid}/additions/{aid}/invoice` — detach. **Does NOT** touch the row's description (regression-tested).
  - `GET /runs/{rid}/invoice-attachments` — thin list (no PDF bytes, content_b64 explicitly projected out).
- **New collection** `fa_invoice_attachments` — `{run_id, addition_id, filename, page_range, pdf_size, content_b64 (gzip+base64), ocr_extraction, uploaded_at}`. Cascade-deleted on run delete.
- **Dependencies** — `pypdf==6.10.2` added to `requirements.txt`. `emergentintegrations` already installed.

### Frontend
- **New file** `pages/fixed_assets/additions/InvoiceOcrModal.jsx` — `InvoiceUploadDropZone` (drag-drop + file picker, dashed border that highlights on dragOver, 25 MB client-side guard), `InvoiceUploadPreviewModal` (one card per chunk: extracted metadata grid + asset-description preview + "Attach to addition row" dropdown sorted with the auto-matched row at top with ★, "Overwrite Description" checkbox, "Skip this chunk" toggle), `RowAttachmentIcon` (paperclip + delete X next to the row's Description textarea, opens PDF in new tab on click).
- **AdditionsTab.jsx** — wires the dropzone above the ProgressStrip, parallel-fetches `/invoice-attachments` alongside the additions list, passes `attachments[a.addition_id]` into each AdditionRow, opens the preview modal on successful upload, refreshes everything on apply.
- **AdditionRow.jsx** — paperclip + detach X mounted in the description cell (only renders when an attachment exists; doesn't disturb the existing auto-grow textarea).

### End-to-end on the user's actual sample (Velav Garments — 4-page combined PDF)
- ✅ Page 1 classified `ledger_extract`, pages 2-4 classified as `tax_invoice_first_page`
- ✅ All 3 invoice numbers extracted character-perfect: `TN24-25-SIM-23`, `NA/1596/24-25`, `TN24-25-SIM-314`
- ✅ Asset descriptions audit-grade: e.g. `"PEGASUS - M952-52H-2X4/D222 2 NEEDLE 4 THREAD OVERLOCK MACHINE (6 units)"`
- ✅ 1 chunk auto-matched (party_plus_total fuzzy, score 90); other 2 surface in the modal for manual selection.
- ✅ Per-chunk PDF stored as 1-page slice (~300-600 KB each, gzipped further in DB).
- ✅ `download_invoice_attachment` returns valid PDF (`%PDF` magic preserved).

### Testing (iteration_11.json)
- **Backend pytest** — **12/12 GREEN** in 81 seconds (incl. 2 real Gemini calls). New file `/app/backend/tests/test_invoice_ocr_phase15.py`. Coverage: shape, auth, .pdf-only, magic-byte, 25MB cap, 3-invoice detection, ledger page detection, ≥1 auto-match, repeat-upload-fresh-id, apply-without-desc, apply-with-desc-overwrite, replace-not-duplicate, download (Content-Type + body), delete-preserves-description, second-delete idempotent, unknown-upload_id 404, list-thin-payload, run-delete cascade.
- **Code review (12/12 points GREEN)** — temperature/JSON defence, slice_pdf clamping, matcher skip rules, magic-byte check, in-memory cache GC (with single-worker note), upsert replace semantics, description guard, delete-doesn't-touch-row, header-injection defence, thin payload projection, cascade cleanup, gzip+base64 serialisation safety.
- **Frontend** — main agent screenshot-verified the dropzone, modal, and paperclip icon; testing agent's automated harness deferred to manual confirmation due to a tab-selector quirk (FA tabs already have `data-testid="fa-tab-*"` — false alarm).

## Fixed Assets — Additions tab refactor + Excel round-trip + power features (2026-04-30 PM-4)
**The 640-line `AdditionsTab.jsx` monolith has been split into a slim ~370-line orchestrator + 9 focused sub-components under `pages/fixed_assets/additions/`.** Three user-asked features and five additional power-features land at the same time. Backend 16/16 GREEN, Frontend 8/8 GREEN (`/app/test_reports/iteration_10.json`).

### Component split
```
pages/fixed_assets/additions/
├── utils.js                     # inr / capitalised / ADJ_FIELDS / COLUMN_DEFS / LS keys
├── ProgressStrip.jsx            # extracted as-is from inline def
├── Pager.jsx                    # extracted prev/next pager
├── AdditionsToolbar.jsx         # block + ledger + search filters + page-size + Fill PTU
│                                # + Export / Import buttons + column-vis gear popover
├── AdditionRow.jsx              # editable row + per-row save indicator + auto-grow textarea
├── MergedRow.jsx                # compact "↳ Merged" strip row
├── MergeModal.jsx               # parent-pick + adjustment-column modal (ex-LinkModal)
├── BulkActionBar.jsx            # floating bottom bar — Set Block / Mark Reviewed / PTU=Acc
└── ExcelRoundTripModal.jsx      # ImportPreviewModal + DriftBanner (re-used by ComputeTab)
```

### Per-block Excel round-trip (export ↔ edit ↔ re-import)
- [x] `GET /runs/{rid}/additions/export.xlsx` — multi-sheet workbook (one sheet per active block_label). Each sheet:
      • Title row + frozen totals strip (rows 2-3) + locked headers (row 4)
      • Hidden columns A=addition_id, B=parent_addition_id (so merge linkage survives the round-trip)
      • Editable cells highlighted yellow, locked / read-only cells grey, discount-credit rows tinted rose
      • All 16 visible columns (Ledger · Acc Date · PTU · Description · Invoice Cost · 5× adjustments · Total Capitalised · Supplier · Voucher · Invoice · Inv Date · Source)
- [x] `POST /runs/{rid}/additions/import.xlsx?dry_run=true` — parses, diffs against the live DB, runs a **block-totals drift check** (tolerance ₹1), and returns a JSON preview with `{rows_changed, unknown_ids, changes:[{addition_id, changes:{field:{old,new}}}], drift:{drifted, blocks:[{db_total, excel_total, diff}]}, errors}`. `discount-*` synthetic ids are silently skipped (no spurious unknown_ids). Text fields are trimmed before diff so trailing-newline noise is suppressed.
- [x] `POST /runs/{rid}/additions/import.xlsx?dry_run=false` — applies the diff, recomputes `is_more_than_180`/`half_rate` whenever PTU changes, and persists `fa_runs.excel_drift_warning` only when ≥1 block drifts beyond tolerance.
- [x] `POST /runs/{rid}/clear-excel-drift` — auditor-driven acknowledgement that unsets the persistent warning.
- [x] **Persistent `DriftBanner`** (rose, full-width) renders at the top of BOTH the Additions tab AND the Compute & Export tab whenever `excel_drift_warning` is set on the run. Auditor can't generate the final report without seeing it. Clicking "Mark Reconciled" on either banner clears the flag globally.
- [x] `ExcelImportPreviewModal` — diff table (per-row, per-field old → new), drift banner inside the modal, "Apply Anyway" / "Apply Changes" CTA labelled per drift state.

### User-asked quick wins
- [x] **Configurable rows-per-page** dropdown (10 / 25 / 50) next to the pager, persisted to `localStorage["fa.additions.pageSize"]`.
- [x] **Per-row save indicator** — every editable row now shows a tiny inline status dot near the Acc Date cell: spinning loader while saving, emerald ✓ for ~2.2s on success, rose alert on error. Driven by the row's own promise, not a global flag.
- [x] **Per-block Ledger filter** — when an active block has ≥2 distinct ledgers, a `All ledgers (N)` dropdown appears next to the block filter so the auditor can drill into one ledger at a time. Resets when block changes.

### Additional power features
- [x] **Bulk inline actions** — toolbar "Bulk" toggle reveals checkbox column on every editable row. Selecting one or more rows surfaces a floating action bar at bottom-center with: Set Block to… / Mark Reviewed / PTU = Acc Date / Clear (X). Backed by new `POST /runs/{rid}/additions/bulk-patch` (skips merged children + discount rows; handles the `__copy_ptu_from_acc` magic key server-side and recomputes the half-rate flag).
- [x] **Column visibility toggle** — gear icon in toolbar opens a popover with checkboxes for 10 togglable columns (Acc Date · Description · Invoice Cost · Total · IT Block always visible). State persisted to `localStorage["fa.additions.colVis"]`.
- [x] **Description "Auto-grow textarea"** — replaces the fixed-2-row textarea with a JS-driven height: `min(180px, max(34px, scrollHeight))`. No more cramped multi-line asset descriptions; resize handle removed.
- [x] **Block-aware "Fill PTU"** toolbar button — copies Acc Date → PTU for every row in the active filter that has no PTU yet (only one server round-trip via bulk-patch).
- [x] **Renamed test-id** `fa-add-bulk-ptu` (toolbar) → `fa-add-fill-ptu` to disambiguate from the bulk-bar's `fa-add-bulk-ptu` (testing-agent action item).

### End-to-end verification (testing agent iteration_10)
- **Backend** — `tests/test_fixed_assets_additions_xlsx.py` 16/16 GREEN: export shape, dry-run noop, dry-run-with-edit diff, drift-flag persistence, clear-drift reset, discount-* skipping, bulk-patch mark-reviewed, bulk-patch __copy_ptu_from_acc, bulk-patch discount-id skip, auth gates.
- **Frontend** — page-size persists across full reload, column-vis persists across full reload, Bulk → 21 row checkboxes → floating bar with all 4 actions, Description textarea grows 37px → 103px on six lines, Excel export downloads cleanly, drifted re-import shows `DriftBanner` on BOTH tabs, "Mark Reconciled" on Compute tab clears the banner globally.
- **Run state preserved** — `0e4cc62f-…` run ended with `excel_drift_warning=None`; no data pollution.

## Fixed Assets — Phase 1D + 1H live (2026-04-30 PM-3)
- [x] **Phase 1D — Prior-year 3CD import** — `POST /runs/{rid}/ingest-prior-3cd` parses `FORM3CA.F3CA.Form3cdDeprAllw[]`, aggregates by rate, and for each rate returns the list of active blocks sharing that rate as `candidate_block_labels`. `suggested_block_label` is populated only when the rate uniquely maps to a single block. Companion `POST /runs/{rid}/apply-prior-3cd` (JSON body `{items:[{rate, block_label, opening_wdv}]}`) writes the auditor-confirmed mapping into `fa_block_opening` with `source="prior_3cd"` + a descriptive ref to the uploaded filename.
- [x] **Phase 1H — Multi-FY roll-forward** — `GET /runs/{rid}/roll-forward-source` runs the compute engine on the most recent prior-FY run for the same client (explicitly or by `fy_end` lookup) and returns the resulting positive-closing-WDV rows. `POST /runs/{rid}/roll-forward` writes each into `fa_block_opening` with `source="prior_run"` + `source_ref="run:<src_id>"`, and stamps `rolled_from_run_id` on the current run.
- [x] **Frontend — Compute tab toolbar** (`ComputeTab.jsx`):
      • Amber **"Import from Prior 3CD"** button — hidden file picker → staged-preview modal. Each rate row shows 3CD description, prior closing WDV, an editable opening-WDV input (defaults to prior closing), and a block-label dropdown of candidates (★ marks the auto-suggested one when the mapping is unique). Rose warning when a rate has no active block. Applies only rows where a block was chosen.
      • Emerald **"Roll forward from FY YYYY-YY"** button — enabled only when a prior run exists for the client; button text dynamically shows the source FY. Opens a confirmation modal listing each block + its prior closing WDV + total.
      • **Source chip** on every Opening WDV row — `MANUAL` / `PRIOR 3CD` / `ROLLED FWD` colour-coded, auto-flips based on `fa_block_opening.source`.
- [x] **End-to-end verified** on the live QA env:
      • 3CD import of `sample_3cd.json` (3 rate rows at 40/15/10%) → staged preview returned correctly with candidate lists; apply with 2 confirmed blocks wrote `source=prior_3cd` + sensible description.
      • Seeded a synthetic prior-FY run, computed it (Closing 15% P&M ₹8.5L · 40% Computers ₹1.5L), then roll-forward-source returned those closings, apply wrote both with `source=prior_run` and description `Auto-rolled forward from FY 2023-24`.
      • Frontend smoke — both buttons render, disabled-state text flips to "Roll forward (no prior FY)" when unavailable, opening table now has a 5th Source column.
- [x] **Data hygiene** — the synthetic FY 2023-24 run was deleted and the main run's openings were reset to 0 after verification, keeping the DB clean.

## Fixed Assets — Line-item Merge / Link (2026-04-30 PM-2)
- [x] **Replaced fragile drag-drop with explicit Link UX** (Option A). Each addition row gets a `🔗 Merge` icon next to Invoice Cost; click → modal to pick a parent asset (searchable, same-block-only) and which adjustment column the line item flows into.
- [x] **Backend persistence** — `parent_addition_id` + `linked_as` fields on every addition. Idempotent endpoints `POST /runs/{rid}/additions/{aid}/link` and `/unlink`. Server-side guards: same-block coherence, no self-link, no chained linking (cannot link to a row that's itself merged).
- [x] **Compute engine skips merged rows** to avoid double counting. The full child invoice_cost has already been added to the parent's `<linked_as>` column at link time, atomically.
- [x] **Visual treatment** — merged rows render as a compact grey strip showing `↳ Merged · {child desc} · ₹{amount} · into "{parent desc}" · as {column}` with a one-click `Unlink` button. Filter toggle "Show merged" hides them entirely when off.
- [x] **Sort discipline** — children render directly under their parent in the table for at-a-glance review (no jumping pages to verify a relationship).
- [x] **Smoke-tested** end-to-end on Velav books: parent's `other_expenses` jumps from 0 → ₹142,000 on link; back to 0 on unlink; depreciation total is unchanged because the merged child's invoice_cost flowed into the parent's adjustment column atomically.
- [x] **Invoice Cost column is now read-only** (per earlier ask) — sourced from books, can never be overwritten by accident.

## Fixed Assets — Additions UX overhaul (2026-04-30 PM)
- [x] **Tab order reflowed** Ledgers → Credits → Additions → Compute & Export so the auditor classifies credits before reaching the Additions register.
- [x] **Discount-classified credits surface in Additions** as locked, negative-cost rows (`source: "discount_credit"`, rendered with rose tint, all fields disabled). They flow into the depreciation working as negative pseudo-additions automatically — auditor never has to copy the figure twice.
- [x] **Per-block progress strip** at the top of Additions tab: ✓ Done / ◐ In Progress / ○ Not Started chips per block, with row counts (`reviewed/total`). Clicking a chip switches the active block. Server endpoint `GET /runs/{rid}/additions/progress`.
- [x] **`reviewed` flag** added to addition rows. Server flips it to True on every PATCH so any auditor edit is treated as a review action; that's what drives the progress strip without needing an explicit "Mark Reviewed" button.
- [x] **15-column auditor-friendly layout** in the requested order: Acc Date · PTU Date · Description of Asset (editable multi-line) · Invoice Cost · Other Exp · ITC Reversed · Interest Cap · Forex · Discounts · Total · IT Block · Supplier · Voucher No · Invoice No · Inv Date.
- [x] **Drag-and-drop transfers** — Invoice Cost cell is `draggable`; drop into any of the 5 adjustment columns triggers a `prompt()` with default = full amount. User accepts or types a partial. Server-side: single PATCH adjusts both fields. Drop targets all 5 adjustment columns.
- [x] **Auto-extract Invoice No** from voucher narration on ingest (regex `(?:bill|inv)\s*(?:no)?\s*[:-]?\s*(...)` with sensible tail-stripping). 5 / 60 distinct narrations matched on Velav books — auditor edits the rest inline.
- [x] **Block filter dropdown** + 10-rows-per-page pagination · search box (description, party, voucher, invoice no).
- [x] **Backend response merges discount credits** into `/additions` and `/compute` so all downstream consumers see them as negative additions automatically.

## Fixed Assets — Phase 1F + 1G live (2026-04-30)
- [x] **Tabbed in-run UX** — Ledgers / Additions / Credits / Compute & Export tabs at `/dashboard/clients/:cid/utilities/fixed-assets/runs/:rid`. Tab headers show live counts.
- [x] **Additions Register tab** (`AdditionsTab.jsx`) — group-by-block toggle, free-text search, every row inline-editable: Invoice Date, PTU Date with **`[📅 Copy from Acc Date]`** and **`[📅 Copy from Inv Date]`** quick-fill buttons (per spec); 5 adjustment columns (`Discount/Credits` −, `Other Exp` +, `ITC Reversed` −, `Interest Cap` +, `Forex` +) wired through to a live "Capitalised Cost" formula on the right. Half-rate badge auto-flips when PTU < 180 days from FY end.
- [x] **Credits tab** (`CreditsTab.jsx`) — every credit entry classifiable inline as **Sale** (capture sale_value, sale_date, buyer_name with sensible defaults from the voucher) or **Discount** (transfers magnitude to the addition's adjustment column when computation runs). Reset button to undo.
- [x] **Compute & Export tab** (`ComputeTab.jsx`):
      • **Opening WDV table** — one row per active block (15 standard IT blocks); editable amount + free-form note (e.g. "carried from FY 2023-24 closing WDV (3CD AY24-25)"). Total row.
      • **`Compute` button** → `POST /runs/{rid}/compute` returns rows + totals. UI renders the schedule with STCG u/s 50 highlighted in rose for any extinguished block.
      • **`Download Excel` button** → `GET /runs/{rid}/export.xlsx`. 4-sheet workbook (Block Summary · Additions Register · Deletions Register · Workings) following the user's sample format.
- [x] **Backend additions**:
      • `compute.py` — pure functions: `adjusted_cost(addition)`, `compute_block(block_label, rate, opening_wdv, additions, deletions)` (handles full-rate vs half-rate pool with sale-allocation rules, Sec 50 STCG when block extinguished), `compute_run(...)` aggregator. 5/5 unit tests pass.
      • `export.py` — openpyxl workbook builder with Block Summary mirroring the user's sample (10 columns: Block · Rate · Opening · Adds≥180 · Adds<180 · Sales · Total · Depn · STCG · Closing).
      • New endpoints: `GET/POST /runs/{rid}/block-opening`, `GET /runs/{rid}/additions`, `PATCH /runs/{rid}/additions/{aid}` (auto-recomputes `is_more_than_180` when PTU edits), `GET /runs/{rid}/credits`, `POST /runs/{rid}/credits/{cid}/classify`, `POST /runs/{rid}/compute`, `GET /runs/{rid}/export.xlsx`.
- [x] **End-to-end smoke test on Velav books** with manual Opening WDV (P&M 25L · Comp 1.5L · Furn 75K · Veh 4.5L):
      ```
      4 blocks active · Adds ≥180d ₹1.12Cr · Adds <180d ₹1.63Cr ·
      Depreciation ₹33.7L · Closing WDV ₹2.73Cr · STCG nil
      Excel size 18.6KB · Sheets [Block Summary, Additions Register, Deletions Register, Workings]
      ```

### Pending — same module
- [ ] Phase 1D — `POST /runs/{rid}/ingest-prior-3cd` (parse `Form3cdDeprAllw[]` → opening WDV by rate; cross-validate against the manual Excel; expose `/exceptions` workflow)
- [ ] Phase 1H — Multi-FY continuity ("Roll forward closing WDV" UI button when a prior FY run exists for the same client)
- [ ] Drag-drop UX for moving Invoice Cost into adjustment columns (currently number-input fallback works)
- [ ] Companies Act Schedule II depreciation engine (next phase per user request)

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
