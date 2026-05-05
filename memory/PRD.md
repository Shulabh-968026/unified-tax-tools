# MSS × Assure — Audit Utilities (Merged)

## Release 4.1 · Tabbed UX + Party Master auto-template (2026-05-05)

Two refinements landed on top of Release 4.0's Library foundation:

### 1 · Tabbed layout (`Utilities Catalog` · `Data Library`)

`ClientUtilities.jsx` rewritten to use shadcn `Tabs`:
* Default tab = **Utilities Catalog** (the daily workflow — auditor opens, picks a utility, gets to work).
* Second tab = **Data Library** (the engagement-setup workflow — central place to upload + replace + soft-delete the source files).
* Tab state persisted in URL via `?tab=library` so deep-links work.
* Library status payload is fetched in a hidden mount when on Utilities tab so the per-tile `⊘ Data Missing / ⚠ Outdated / ✓ Up-to-date` chips render correctly on first paint without forcing the auditor into the Library tab.

### 2 · Party Master auto-template generator

New file `modules/library/templates.py` adds a registry-pattern template generator + new endpoint `GET /api/library/clients/{client_id}/template/{file_type}?period=...&division=...`.

Today only `party_master_xlsx` is registered; FA Register and Bank Statements can follow the same pattern in future.

The generator builds a 5-sheet workbook:
* **README** — instructions + legend (pre-filled = pale emerald, auditor-fill = pale amber).
* **Sundry Creditors** — vendors (highest priority for confirmations + 43B(h) MSME).
* **Sundry Debtors** — customers.
* **Loans & Advances** — loan / advance counter-parties.
* **Other Parties** — anything else with a closing balance.

14 columns per row — 6 pre-filled (Party Name, Group, Closing Balance, GSTIN, GST Reg Type, Country) merged from Books JSON + Ledger Mapping XLSX, 8 auditor-fill (Email, Alt Email, Phone, Address, MSME Status, MSME Reg No., PAN, Notes).

UI: catalog now exposes `has_template: true` on the Party Master row; `ClientLibraryPanel` renders an **AUTO-TEMPLATE** chip + a sky-tinted **Template** button right before the Upload button. Auditor downloads, fills offline, re-uploads — done.

Verified live on ABC Textile Mills: 230+ parties pre-populated across the 4 buckets.

### Files touched
**Backend (new):**
- `modules/library/templates.py` — registry-pattern generator + Party Master implementation.

**Backend (modified):**
- `modules/library/catalog.py` — `FILE_TYPES_WITH_TEMPLATES` set.
- `modules/library/controller.py` — `/template/{file_type}` endpoint; `has_template` enriched in catalog response.
- `modules/library/service.py` — `has_template` field in status payload.

**Frontend (modified):**
- `lib/api.js` — `downloadLibraryTemplateUrl` helper.
- `components/ClientLibraryPanel.jsx` — `AUTO-TEMPLATE` badge, sky-tinted Template button, `clientId/period/division` threaded through to chip rows; secondary inputs default-expanded for visibility.
- `pages/ClientUtilities.jsx` — shadcn `Tabs` wrapper; `?tab=` URL persistence; hidden Library mount on Utilities tab to keep chip data fresh on first paint.

### Tests · 78 / 79 (zero new regressions)
- All 11 Library Phase A tests pass.
- All 67 Clause 44 logic tests pass.
- The one failing test (`test_client_count_unchanged`) is a pre-Library stale assertion; flagged in the previous handoff.


## Release 4.0 · Client Library + version-aware module integration (2026-05-05)

Architectural shift agreed with MSS: every source file (Books JSON, Ledger
Map XLSX, prior-year 3CD JSON, ITR JSON, GSTR-1/3B/9, Bank Statements,
Party Master, FA Register, etc.) now lives in a per-engagement Library.
Modules pin to specific file *versions* and are flagged "outdated"
when newer versions exist.

### What shipped in this release
1. **`client_files` collection + storage layer** at `/app/uploads/{firm}/{client}/{period}/{division}/{file_type}/v{N}/`. 13 file types in the catalog, 3-version retention with 30-day soft-delete grace.
2. **Library API** under `/api/library/...` — catalog, status, upload, list, download, soft-delete, restore, prune.
3. **Module dependency graph** declared in `modules/library/catalog.py::MODULE_DEPENDENCIES`. Drives outdated-detection across all 6 utilities.
4. **Action-log schema** — 14 action types pre-modeled in `catalog.py::ACTION_TYPES` for Balance Confirmation (production wiring follows in next release).
5. **Clause 44 fully Library-integrated**: upload also saves to Library, run carries `pinned_files: {file_type → file_id}`, GET returns `library_status` (outdated · missing · fresh + per-dependency detail), new `POST /runs/{id}/rerun` endpoint re-pins to latest and re-parses.
6. **Single morphing button** — the existing Generate button automatically becomes "Rerun on Latest Data" (with amber styling) when outdated; one click re-pins + recomputes; auditor selections (ITC / exempt / exclusion / disclaimer) preserved across rerun.
7. **ClientHome `ClientLibraryPanel` component** — file-type chips with Upload/Replace/Download/Soft-delete actions, period+division selectors, completeness badge.
8. **Outdated/Missing/Fresh badges** on every utility tile (driven by the same status payload) AND on the run-wizard top bar.
9. **Hard-delete protection** — pinned file versions cannot be soft-deleted (409 Conflict).
10. **Tests · 79/79 green** — 11 new live HTTP tests for the full upload → version → outdated → rerun cycle, plus all 67 existing Clause 44 tests.

### What's deferred to Release 4.1 (same architecture, mechanical migration)
- 43BH · Fixed Assets · GST Recon · Fin Statement Designer · Balance Confirmation migrations to the Library pattern (other modules still use their own Import flow today; their tiles correctly show "Data Missing" chips driven by the same dependency graph).
- Action-log production wiring inside Balance Confirmation.
- Multi-run collapse to single working doc + thin generations log.
- Offline confirmation-request PDF generator.

### Files touched
**Backend (new):**
- `lib/file_storage.py` — disk storage primitive (S3-swappable).
- `modules/library/__init__.py` · `catalog.py` · `service.py` · `controller.py`.
- `tests/test_library_phase_a_live.py` — 11 end-to-end tests.

**Backend (modified):**
- `core/db.py` — `client_files` indexes.
- `server.py` — wires the library router.
- `modules/clause44/controller.py` — upload now saves to Library + pins; GET attaches `library_status`; new `POST /runs/{id}/rerun`.
- `tests/test_clause44_release3_1_live.py` — assertion updated for post-3.2.1 candidate-pool size.

**Frontend (new):**
- `components/ClientLibraryPanel.jsx` — file-type chips UI.

**Frontend (modified):**
- `lib/api.js` — `getLibraryCatalog`, `getLibraryStatus`, `uploadLibraryFile`, `deleteLibraryFile`, `rerunRun`, `downloadLibraryFileUrl`.
- `lib/utilities.jsx` — `module_key` field on `UTILITIES`; `UtilityCard` renders Outdated/Missing/Fresh chip when `libraryStatus` prop supplied.
- `pages/ClientUtilities.jsx` — mounts `<ClientLibraryPanel>` above the catalog; subscribes to `onChange` and threads status into each `UtilityCard`.
- `pages/clause44/Clause44Run.jsx` — outdated/missing chips in top bar; Generate button morphs to "Rerun on Latest Data" with amber styling; `proceedExclusion` calls `rerunRun` first when outdated.

### Verified live on ABC Textile Mills
- Library panel renders with completeness badge `0 of 2 PRIMARY UPLOADED`.
- All 6 active utility tiles show `⊘ DATA MISSING` (driven by Library, not hardcoded).
- 79/79 backend tests pass · zero regressions.


## Clause 44 — Release 3.5 · Auto-fit KPI tiles for large clients (2026-05-04)

User reported (with screenshot) that on a large client whose Clause 44
aggregates ran into 9–10 digits (e.g. `₹56,58,19,949.99`,
`₹27,03,59,393.42`), the KPI tile values overflowed their container
widths and visually overlapped the next tile.

### Fix

New reusable component `frontend/src/components/AutoFitText.jsx`:
* Renders children at `maxFontPx` (20 by default).
* After paint, measures `inner.scrollWidth` vs `wrap.clientWidth`.
* If overflowing, scales font-size down by
  `floor(maxFontPx × clientWidth / scrollWidth × 0.96)` clamped to
  `minFontPx` (11) — keeps 4% safety margin for sub-pixel rounding.
* Re-measures on container resize via a `ResizeObserver` whose
  callback is deferred to `requestAnimationFrame` to avoid the
  "ResizeObserver loop completed with undelivered notifications" dev
  overlay (since the observer's callback mutates layout-affecting state).
* Wrapper has `overflow-hidden` so a one-frame race during shrink
  doesn't bleed into adjacent tiles.

`StepReport.jsx::KPI` now wraps the formatted INR amount in
`<AutoFitText maxFontPx={20} minFontPx={11}>` while keeping the label
unchanged.  All 7 tiles benefit; smaller values still render at the
full 20 px size.

### Verified
- ABC Textile Mills (current data): all 7 tiles render at full 20 px,
  no clipping at 1280 / 900 px viewports.
- Math sanity: `56,58,19,949.99` measured at 20 px = 174 px wide; in a
  138 px wrap → autofit scales to 15 px (~131 px wide) → fits cleanly.
- Runtime error overlay no longer fires.


## Tests · Auto-cleanup of seeded clients on session end (2026-05-04)

Recurring DB drift: live test fixtures (e.g. `test_iteration4_modules_archive_period.py`) seed clients with file numbers like `ITER4_DUP_*`, `ITER4_PER_*`, `ITER4_ARCH_*`, `ITER4_DIV_*` and don't tear them down, so they accumulate across iterations and pollute the All Clients list.

### Fix

`backend/tests/conftest.py` adds a session-scoped `autouse` fixture that runs once after the entire pytest session and deletes any clients whose `file_number` matches `^(ITER\d|TEST_|R3[0-9]_|FORK_|QA_|FIXTURE_)`, plus their downstream artefacts in `runs`, `balance_confirmation_runs`, `fixed_assets_runs`, `fin_statement_runs`, `msme_runs`, `msme43bh_runs`, `gst_recon_runs`, `invoice_ocr_runs`. Test users / sessions seeded via `_bootstrap_session` are also wiped.

The regex deliberately excludes real production file numbers (`A-504`, `V-904`, etc.) so live data is never touched. Cleanup is best-effort (try/except) so a failure during teardown never breaks the test summary.

### Verified
- Run any pytest → `[conftest cleanup] dropped N test client(s) + M run(s)` line appears in the session summary.
- End-to-end proof: seeded fake `FIXTURE_PROOF_42` client + run, ran one test, both gone afterward.
- Live API after session: 3 originals only (ABC Textile Mills · Allman Knitwear · Velav Garments India P Limited).


## Clause 44 — Release 3.4 · Readme inside the run wizard + content refresh (2026-05-04)

User asked: "I don't find the Readme button anywhere. If you redo, redo
the same in line with ICAI guidance note and the logic we have
implemented so far."

### Fix 1 — Surface Readme inside the run

`Clause44Run.jsx` sticky top bar now carries a small **Readme** pill
right after the breadcrumb (`← ABC TEXTILE MILLS · CLAUSE 44 FY 2023-24
· 📖 README · …`).  It links to `/api/docs/clause-44`, opens in a new
tab, and is visible from every step (Special Ledgers / Exclusions /
Report).  The existing client-home Readme button stays intact.

### Fix 2 — Readme content refreshed for everything we've shipped

`backend/modules/docs/templates/clause-44.html` updated:

* **Regulatory primer (§1)** — Col 8 added to the column list with the
  identity **`Col 2 = Col 6 + Col 7 + Col 8`** (was previously stated
  as Col 2 = Col 6 + Col 7).  Note clarifies Col 8 is engine-internal /
  recon-only; the 3CD form prints Cols 1–7 only.
* **Cascade (§2)** re-ordered to match the actual engine: Col 8
  excluded → RCM → Input A → import → composition → registered (Input
  B) → URD.
* **New callout — "How the engine surfaces ITC ledgers (multi-signal)"**
  documents the JSON+XLSX union, the 3-signal classifier (name → group
  → voucher usage with whitespace collapsing), and the subhead
  override that admits ledgers mis-mapped to Sundry Debtors / Trade
  Receivables.
* **New callout — "Coverage diagnostic on the Schedule tab"** explains
  the `itc_coverage_pct` advisory banner that fires when registered-
  vendor purchase vouchers don't carry ITC ledgers.
* **Walkthrough Step 5** rewritten to describe the **7-tile clickable
  KPI strip** (Col 2 · Col 3 · Col 4 · Col 5 · Col 6 · Col 7 · Col 8),
  click-to-filter behaviour, active-column highlighting, dim/clear
  states, and the per-line override on the Reconciliation tab for Col
  8 sub-buckets.
* Cohort waterfall caption updated to the 3-term identity.

### Files touched
- `frontend/src/pages/clause44/Clause44Run.jsx` — Readme pill in sticky bar.
- `backend/modules/docs/templates/clause-44.html` — primer + cascade + callouts + Step 5 + figcaption.

### Verified
- Live curl on `/api/docs/clause-44` renders 200; new tokens present:
  `Col 8`, `multi-signal`, `coverage`, `union`, `voucher usage`.
- Screenshot: Readme button shows on every step; pivot KPI strip with
  7 tiles unchanged.


## Clause 44 — Release 3.3 · Clickable 7-tile KPI strip + bucket-filter pivot (2026-05-04)

User asked: "make all 7 KPI tiles populated and clickable; on click, the
table below should filter to that bucket's figures for both Expense-wise
and Party-wise summaries."

### Implementation

`StepReport.jsx` — Schedule tab now renders **all 7 KPI tiles** (Col 2 ·
Col 3 · Col 4 · Col 5 · Col 6 · Col 7 · Col 8) on a `lg:grid-cols-7`
strip.  Each tile is a button with three visual states:

* **Idle** — default colour-coded tile.
* **Active** — black ring inset + un-dimmed; the column it represents
  is highlighted in the pivot below (dark header background, bold cells).
* **Dimmed** — 50% opacity; appears when *another* tile is active.

A filter banner appears between the strip and the pivot:
> "Filtered to · `<col label>` · pivot rows below show only ledgers /
>  parties that contributed to this bucket · Clear filter ×"

The pivot below applies the bucket filter to:
* Hide rows where `row[bucket] === 0` (no contribution).
* **Sort** rows by that bucket descending so the biggest contributors
  surface at the top.
* Highlight the active column header (black bg) and dim the others.
* Footer "Aggregate (filtered)" recomputes the active column sum for
  the *visible rows*, so the auditor can verify the KPI tile total
  against the table footer at a glance.

Column headers themselves are also clickable — same handler as KPI
tiles — for power users who prefer to drive from the table.

Toggle behaviour: clicking the active tile (or column header) clears
the filter; clicking another tile switches the filter to that bucket.

### Files touched
- `frontend/src/pages/clause44/StepReport.jsx` —
  * `Schedule` lifts `bucketFilter` state, renders 7-tile clickable strip + filter banner.
  * `UnifiedPivot` accepts `bucketFilter` + `onColumnClick`; filters / sorts rows; highlights active col; re-computes filtered footer.
  * `KPI` becomes a `<button>` with `active` / `dimmed` / `onClick` props.

### Tests
- 60/60 unit tests pass (no backend changes).
- Live UI verified on `run_0ef0127bba5c`:
  * baseline: all 7 tiles visible, 40 rows in pivot.
  * click Col 5 → tile gains ring, banner appears, pivot drops to 20
    rows sorted by Col 5 desc (Yarn Purchase A/c ₹37.83 L on top).
  * Re-click Col 5 → filter clears, full 40 rows return.


## Clause 44 — Release 3.2.1 · ITC pool union & subhead-override (2026-05-04)

User retest revealed that Release 3.2 still missed 8 of 9 expected ITC
ledgers on the ABC Textile Mills run.  Two compounding root causes:

1. **XLSX gating** — `compute_suggestions` only iterated the books-XLSX
   mapping, so ledgers present in the JSON but absent from the XLSX
   never reached the candidate pool.
2. **Mis-mapped subhead** — the auditor's XLSX mapped the GST input
   ledgers to subhead `Sundry Debtors` / `Trade Receivables` (which are
   in the exclude pool).  Even when the XLSX had the row, the
   exclude-pool filter dropped it before the heuristic ever ran.

### Fix
* `compute_suggestions` now iterates the **union** of XLSX and JSON
  ledgers (JSON-first, then XLSX-only stragglers).  JSON's `bsOrPnl`
  is the BS/PL marker when XLSX doesn't supply one.
* New helper `_admit(name, subhead, group_parent, head)`: when the
  multi-signal classifier returns `kind ∈ {input, output}` via the
  *name* or *parent group* signal, the ledger is admitted to the pool
  **regardless** of subhead-mis-mapping.  The exclude-pool filter only
  applies when the name/group give no kind signal.
* Dropped the over-broad `"rcm"` name synonym — was matching "Rcm
  Apparels And Company" (a vendor) as input.  Updated unit tests.

### Real-data verification
On `run_0ef0127bba5c` (ABC Textile Mills) the candidate pool now
returns **11 input + 3 output** ledgers (vs 1+3 before), with the 6
actively-used Input CGST/SGST @ rate ledgers auto-pre-ticked via
voucher usage.  The 3 dormant ITC ledgers (2 Deferred Input Credit + 1
SGST IN PUT) surface and can be ticked in one click via the
Release 3.2 group-bulk action.

### Files touched (additionally)
- `backend/modules/clause44/service.py` — JSON+XLSX union loop in
  `compute_suggestions`; new `_admit` helper; `rcm` synonym removed.
- `backend/tests/test_clause44_release3_1.py` — updated `RCM 18%` test.
- `backend/tests/test_clause44_release3_2.py` — 2 new tests:
  `test_mis_mapped_subhead_does_not_hide_input_ledgers`,
  `test_json_only_ledger_surfaces_when_xlsx_lacks_row`.

### Tests · 60/60 unit + 16/16 live = 76 green · zero regressions


## Clause 44 — Release 3.2 · Naming-agnostic ITC detection (2026-05-04)

User reported a recurring failure mode on real-world Tally JSON: the
3.1 heuristic missed ITC ledgers like `SGST IN PUT` (embedded space)
and would generally miss any client using bespoke ledger names.  Picked
combo (c) = A + B + C + D from the recommendation framework.

### Fix A — Multi-signal `_classify_itc_kind`

`modules/clause44/service.py` now collapses each input string to
lowercase alphanumerics (`_alnum_lower`) before matching, and checks
**three signals** with priority `output` > `input` > `other`:

1. ledger NAME (existing — `Input ...`, `RCM ...`, `ITC ...`, `Cenvat`)
2. parentGroup NAME (NEW — catches `INPUT CREDIT`, `OUTPUT CREDIT`,
   `Defrerred Input Credit` typo from the user's books)
3. books-XLSX subhead (NEW — same patterns)

`_classify_itc_kind` now returns `(kind, source)` where `source` ∈
{`name`, `group`, `subhead`, `""`} so the UI can render a provenance
chip ("via name match", "via group match", etc.).

### Fix B — Voucher-usage classifier

New function `compute_voucher_usage_kinds(candidates, vouchers)` walks
every voucher and tallies per-candidate-ledger:
* `n_purchase` — appearances on Purchase / Debit Note vouchers
* `n_sales`    — appearances on Sales / Credit Note vouchers
* `n_voucher`  — total vouchers touched

Scores `usage_kind`:
* `input`  if `n_purchase ≥ 3` and dominant over sales by 3:1
* `output` if `n_sales ≥ 3` and dominant over purchases by 3:1
* `neutral` otherwise (mixed / dormant / below threshold)

`compute_suggestions` then **merges** name-kind with usage-kind: name
signal wins when ≠ "other", usage promotes only the "other" bucket.
This blocks an Output-named ledger from being flipped to Input by stray
purchase entries while still auto-detecting cryptically-named ledgers
like `Tax-Cr-Misc-A2`.  Pre-tick rule extended: `kind == "input"` AND
(legacy subhead match OR `usage_kind == "input"`).

### Fix C — Coverage diagnostic

`classify_vouchers` now adds three fields to its summary:
* `itc_coverage_eligible` — count of registered-vendor purchase vouchers
* `itc_coverage_with_itc`  — of those, how many had an ITC ledger
* `itc_coverage_pct`        — ratio (or `None` when denominator is 0)

`StepReport.jsx` renders a yellow **advisory banner** when ITC inference
is ON, denominator ≥ 5, and `coverage_pct < 70`.  Banner copy:
"ITC coverage is low: X% — N vouchers will route to Col 3 via Input B.
Some input-tax ledgers may not be tagged.  Review ITC selection →".

### Fix D — Manual override UI

`LedgerList.jsx` (ITC tab only) gains:
* **Provenance chip** — `via name match` / `group match` / `subhead match` /
  `voucher usage` — auditor sees *why* the engine flagged a row.
* **Usage telemetry chip** — "N purchase · N sales" (or "unused").
* **Conflict advisory chip** — "⚠ name vs usage" when name says input
  but ledger fired only on sales vouchers.
* **"Used in vouchers only" toggle** — hides dormant ledgers (often
  >50% of the BS pool on large datasets).
* **Group-bulk select** — every parent-group row carries a one-click
  "Tick all" / "Untick all" button (e.g. tick all 7 ledgers under
  `INPUT CREDIT` in one click).

`Clause44Run.jsx` first-load logic extended to silently fold in any
**newly-detected usage-based** ITC ledgers on existing runs uploaded
under the older heuristic, with a separate toast notification.

### Real-data verification (ABC Textile Mills JSON · 280 ledgers · 1,119 vouchers)

| Group | Ledger | Before 3.2 | After 3.2 |
|---|---|---|---|
| INPUT CREDIT | Input CGST/SGST @ 2.5/6/9% (×6) | input | input |
| INPUT CREDIT | **SGST IN PUT** (space) | other ❌ | **input ✅** |
| Defrerred Input Credit | CGST/SGST Deferred Input Credit (×2) | input | input |
| OUTPUT CREDIT | Output CGST/SGST/IGST (×3) | output | output |

12/12 GST ledgers correctly classified.

### Files touched
- `backend/modules/clause44/service.py` — `_alnum_lower`, expanded
  `_classify_itc_kind` (returns tuple), new `compute_voucher_usage_kinds`,
  upgraded `compute_suggestions` (vouchers param), coverage diagnostic
  in `classify_vouchers`.
- `backend/modules/clause44/controller.py` — pass vouchers to
  `compute_suggestions` on upload + GET.
- `backend/modules/docs/templates/clause-44.html` — Step 2 / Tab B
  copy rewritten to document provenance chips + usage chips + group
  bulk + "Used in vouchers only" filter.
- `frontend/src/pages/clause44/LedgerList.jsx` — provenance chip,
  usage chip, used-only filter, group-bulk action.
- `frontend/src/pages/clause44/StepSpecialLedgers.jsx` — wires
  `showUsageControls`, `showGroupBulk`, `setSelected` on ITC tab.
- `frontend/src/pages/clause44/StepReport.jsx` — coverage advisory
  banner.
- `frontend/src/pages/clause44/Clause44Run.jsx` — fold-in newly-
  detected usage-based ITC ledgers + toast.
- `backend/tests/test_clause44_release3_1.py` — assertions updated
  for tuple return type.
- `backend/tests/test_clause44_release3_2.py` — 19 NEW unit tests.
- `backend/tests/test_clause44_release3_2_live.py` (testing-agent) —
  9 NEW live-HTTP tests using the real ABC Textile Mills JSON.

### Tests · 45/45 green (29 unit + 16 live · zero regressions)


## Clause 44 — Release 3.1 · ITC seeding fix (2026-05-04)

User-reported defect: bulk of expenditure on `run_0ef0127bba5c` was
landing in Col 3 (Exempt) — ₹64.2 L of ₹78.4 L (82%).  Diagnosis:
Output-side tax ledgers were being auto-ticked because the prior
seeding heuristic only checked the BS-subhead.  Output ledgers fire on
sales vouchers; they don't appear on purchase vouchers; with ITC
inference ON, every registered-vendor purchase consequently missed the
"has ITC ledger" check and routed to Col 3 via Input B.

### Fix 1 — Smarter ITC seeding (per user direction)

`modules/clause44/service.py` now exposes `_classify_itc_kind(name,
subhead, group)` which inspects the ledger NAME pattern:

- `Input ` / `Input-` / RCM-input / ITC-input → `kind = "input"`
- `Output ` / `Output-` → `kind = "output"`
- Otherwise → `kind = "other"`

`compute_suggestions` returns each candidate with that `kind` field,
and pre-ticks (`suggested=True`) only when **both** signals fire:
subhead matches *and* `kind == "input"`.  Output ledgers stay in the
candidate pool for manual selection but never ride the default tick.

### Fix 3 — Silent first-load cleanup of historical runs (per choice 7A)

`Clause44Run.jsx`'s first-load effect now strips Output-kind ledgers
from any persisted `itc_selection` and re-saves the cleaned set via
`PATCH /selections`.  A toast tells the auditor: "Removed N Output-side
ledger(s) that were auto-ticked under the older heuristic.  Re-generate
the report to refresh totals."  No admin migration needed; the next
open of any affected run self-heals.

### Better selection framework (per user request)

`StepSpecialLedgers.jsx` ITC tab gains:

- **Quick-filter strip** — *All / Input only / Output only / Other*
  one-click chips above the picker.
- **Inline `INPUT` / `OUTPUT · sales-side` chips** on every row of
  `LedgerList` so the auditor sees the kind at a glance.
- **Red `⚠ may misclassify Col 5` warning chip** when an Output-kind
  ledger is selected.
- **Persistent rose-banner** above the picker if any Output ledger is
  ticked, listing exactly which ones, with copy: "Output ledgers fire
  on sales vouchers, not purchases — they will not mark a purchase as
  having ITC, so Input B will continue routing those purchases to
  Col 3.  Untick these unless you have a specific reason."

### Real-data verification (run_0ef0127bba5c)

Before fix:  itc_selection = `[Output SGST @ 2.5%, Input SGST @ 9%, Output CGST @ 2.5%, Output IGST @ 5%]` → Col 3 = 82% of Col 2.

After fix (cleaned to `[Input SGST @ 9%]` on first open):
- Col 2 = 80.7L · Col 3 = 63.9L (still high — *underlying books only
  expose one Input ledger; toggle OFF or add more Input ledgers in
  Tally to fix data quality*).
- With toggle OFF: Col 5 jumps to 65L (the strict ICAI Col-5 figure).

The framework now signals this clearly to the auditor.

### Files touched
- `backend/modules/clause44/service.py` — new `_classify_itc_kind`;
  updated `compute_suggestions`.
- `frontend/src/pages/clause44/StepSpecialLedgers.jsx` — kind filter,
  Output warning banner, kind chips wired through.
- `frontend/src/pages/clause44/Clause44Run.jsx` — first-load Output-kind
  strip + auto-save + toast.
- `frontend/src/pages/clause44/LedgerList.jsx` — kind chips (INPUT /
  OUTPUT · sales-side / ⚠ may misclassify Col 5).
- `backend/tests/test_clause44_release3_1.py` — 9 new unit tests.
- Testing agent: 8 new live-HTTP tests in
  `tests/test_clause44_release3_1_live.py`.

### Tests · 50 unit + 48 live = 98 green · zero regressions


## Clause 44 — Release 3 · Reading B + Col 8 + new disclaimer (2026-05-04)

User-driven structural shift on the engine plus a complete rewrite of
the Schedule UI to "Reading B" (one unified pivot, no cohort accordion).

### Conceptual change — what Col 2 means now

Per-user-affirmed reading of ICAI Para 79.4: **Col 2 of Clause 44 is the
*gross* total expenditure** (P&L plus capex additions), including
non-cash charges, Sch III items, money / securities and any other
auditor-elected exclusion.  The reportable split (Cols 3-7) covers only
those items that *should* appear in the 3CD table.  The residual is now
its own bucket: **Col 8 · Excluded**.

Identity: `Col 2 = Col 3 + Col 4 + Col 5 + Col 7 + Col 8`
Reportable: `Col 6 + Col 7` (= Cols 3+4+5+7).

### Cascade — Step 0 added

`_classify_single_line` now opens with:
```
0. Ledger ∈ excluded_ledgers  → Col 8  (wins over everything else)
1. RCM voucher                → Col 7
2. Input A (exempt-tagged)    → Col 3
3. Foreign supplier           → Col 7
4. Composition                → Col 4
5. Regular + GSTIN ± inference → Col 5 / Col 3
6. Else                        → Col 7
```

### Frontend — Schedule tab rewrite (Reading B)

Cohort accordion removed.  New layout:
- **KPI strip** — Col 2 · Col 6 · Col 7 · **Col 8** (4 tiles).
- **Tabbed unified pivot** — `Expense-wise | Party-wise`.  Each tab is
  a single 7-column table (Col 2 / Col 3 / Col 4 / Col 5 / Col 6 /
  Col 7 / Col 8) with one row per ledger or per party.
- **Click any row** → inline drawer with voucher-level detail
  (lazy-loaded via `getTransactions`).

### Excel — 7 sheets

1. `Clause 44 Summary` — aggregate row + per-ledger 7-col pivot.
2. `Reconciliation` — ICAI 5-line + disclaimer block.
3-6. `Col 3 · Exempt`, `Col 4 · Composition`, `Col 5 · Other Reg ITC`,
     `Col 7 · Unregistered` — Para 79.20 column set unchanged.
7. **`Col 8 · Excluded`** (new) — vouchers grouped by ICAI sub-bucket
   (Non-cash charges / Schedule III items / Money / Securities /
   Capex add-back / Other) with a per-sub-bucket subtotal and a final
   "Col 8 Total · Excluded expenditure" grand-total row.

### Disclaimer text — replaced verbatim

`DEFAULT_DISCLAIMER` in `controller.py` now reads exactly as the user
dictated (management-affirmation framing, RCM/foreign-supplier note,
Para 79.20 / 79.21 reference).  Existing runs keep their custom text;
new runs receive the new default.

### Database
DB cleaned in Release 2; remains: ABC Textile Mills, Allman Knitwear,
Velav Garments.

### Files touched
- `backend/modules/clause44/service.py` — Step 0 cascade + col8 in
  every aggregator + `compute_recon_and_filter` no longer filters.
- `backend/modules/clause44/controller.py` — DEFAULT_DISCLAIMER swap;
  `excluded_ledgers` passed through `_run_classification`; transactions
  endpoint accepts `bucket=col8`.
- `backend/modules/clause44/exports.py` — 7-col summary; new Col 8
  sub-bucketed sheet; `BUCKET_META` extended.
- `frontend/src/pages/clause44/StepReport.jsx` — `Schedule` rewritten
  to KPI strip + `UnifiedPivot` (Expense-wise / Party-wise tabs with
  inline drill).
- `backend/tests/test_clause44_release3.py` — 7 new unit tests.
- `backend/tests/test_clause44_release1.py` /
  `backend/tests/test_clause44_iteration_patch.py` — fixtures rebased
  for Col 8.

### Tests · 41 unit + 40 live-API = 81 green
Live HTTP suite verified Col 2 gross identity, 7-sheet workbook, Col 8
sub-bucket band headers, transactions endpoint with `bucket=col8`,
DEFAULT_DISCLAIMER verbatim round-trip via PATCH → export.



## Clause 44 — Release 2 · RCM polish · Para 79.20 columns · disclaimer UI · Readme rewrite (2026-05-04)

Slices 2, 4, 5, 6 from the Release 2 plan.  All 4 shipped in one cut.
69/69 tests green (27 unit + 14 live-API + 28 prior green in parent suites).

### What landed

**Slice 2 · RCM polish.**  Cohort Excel sheets now carry an explicit
`RCM` column (Yes / blank) populated from the transaction's `is_rcm`
flag.  Complements the existing cascade behaviour (RCM → Col 7) with
working-paper visibility.

**Slice 4 · Foreign supplier branch.**  `_classify_single_line` reason
string now includes the country name, e.g. *"Foreign supplier 'AWS Inc'
(Usa) — import, no Indian GSTIN"*.  Country is title-cased so the
working paper is legible.

**Slice 5 · ICAI Para 79.20 columns + editable disclaimer.**

- Every cohort Excel sheet now carries the full 79.20 schema:
  Date · Voucher Type · Voucher No · [Division] · Ledger · Party ·
  Party GSTIN · Party Reg · **Country** · **RCM** · Amount ·
  **Value Eligible for ITC** · Reason for NIL GST / Classification
  Notes · **Auditor Remarks**.  Auto-filter enabled on the header row;
  pivot-ready out of the box.
- "Value Eligible for ITC" computed as `amount` iff the voucher has a
  tagged ITC-input ledger AND is not RCM AND the line isn't Input A
  (exempt-tagged).  Everything else shows zero.
- A third tab "Disclaimer" added to the Report screen with a
  textarea seeded from the default Para 79.21 boilerplate.  Edits
  persist via `PATCH /api/runs/{id}/selections`.
- Excel Reconciliation sheet stamps the run's disclaimer at the
  bottom — dynamically inherited from the run document.

**Slice 6 · Readme rewrite.**  `clause-44.html` Sections 1/2/4/5/6 +
TOC + glossary + FAQ fully replaced.  Removed every false claim from
the prior version:

- ❌ "Non-GST cohort" — does not exist in our engine.
- ❌ "200+ rule keyword set" — the cascade is 6 deterministic steps.
- ❌ "92-97% accuracy on first pass" — engine is deterministic.
- ❌ "Exceptions drawer" / "Suggest correction button" — no such UI.
- ❌ "5-sheet workbook" — we ship 6 sheets.
- ❌ "Prior-year mapping recall" — future release, not today.

Added explicit enumeration of the JSON-data limitations in Section 1
("What the books JSON does not carry"), documented cascade in Section 2,
and tied edge-case narratives in Section 6 to real engine behaviour
(RCM → Col 7, imports → Col 7, Sch III items → excluded + recon
bucket, capex flows in per Para 79.18).

### Database cleanup
Removed 9 stale test clients (`Dup1`, `PeriodTest-*`, `ArchiveMe`,
`MultiDedup`) from earlier iteration test runs.  DB now holds exactly
the 3 originals: ABC Textile Mills, Allman Knitwear, Velav Garments.

### Files touched
- `backend/modules/clause44/exports.py` — cohort column schema +
  auto-filter + recon sheet disclaimer block.
- `backend/modules/clause44/service.py` — foreign supplier reason
  enrichment.
- `frontend/src/pages/clause44/StepReport.jsx` — new `DisclaimerEditor`
  tab on the Report screen.
- `backend/modules/docs/templates/clause-44.html` — full rewrite of
  Sections 1/2/4/5/6 + TOC + glossary + FAQ.
- `backend/tests/test_clause44_release2.py` — 7 new unit tests.
- `backend/tests/test_clause44_iteration_patch.py` — updated footer-
  column assertion for new column layout.

### Tests · 34 unit + 14 live-API + 27 prior = 69 green
No regressions.  The only failing tests in the broader sweep are
pre-existing `test_clause44_backend.py` entries hard-coded to an old
preview URL — unrelated to Release 2.



## Clause 44 — Release 1 · ICAI-aligned cascade + 5-line recon (2026-05-04)

Biggest conceptual correctness fix so far.  Aligns the engine to the
stipulations of the ICAI Guidance Note on Tax Audit (Revised 2025),
Paragraphs 79.1 – 79.21 for Clause 44 of Form 3CD — scoped to what is
derivable from the Tally books JSON we actually receive.

### What changed

**New cascade (`modules/clause44/service.py :: _classify_single_line`).**
Per expense line, the order is now:

1. `voucherTypeName == "Reverse Charge"` → **Col 7** (with `is_rcm=true`).
2. **Input A** — line's ledger sits in the auditor-tagged
   `exempt_ledgers` set → **Col 3** (`col3_source="input_a"`).
3. Foreign supplier (`party.country` non-blank ≠ India) → **Col 7**
   (with `is_import=true`).
4. `party.gstRegistrationType == "composition"` → **Col 4**.
5. `party.gstRegistrationType == "regular"` + GSTIN:
   - if `use_itc_inference` is ON and voucher has no ITC-ledger entry →
     **Col 3** (Input B, `col3_source="input_b"`).
   - otherwise → **Col 5**.
6. Else (URD / consumer / blank) → **Col 7**.

**Input A always wins per line** — a ledger tagged as exempt can never
double-count via Input B because classification is done line-by-line
before the voucher-level inference kicks in.

**5-line reconciliation (`compute_recon_and_filter`).**  Recon now splits
`total_books` into `pl_total` + `capex_total` and auto-buckets each
excluded ledger into one of `non_cash` / `sch3` / `money` / `other` using
name+group-chain heuristics (`categorise_exclusion`).  The arrival line
`pl_total + capex_total − Σ(excluded buckets) = reportable_total` ties
exactly to `summary.col2_total`.  Auditor overrides the auto-category
per line via the recon table's dropdown; the override is persisted on
the run document and consumed on the next Generate.

**New run document fields.** `exempt_selection`, `use_itc_inference`
(default True), `exclusion_categories`, `disclaimer_text`.  Silent
re-classification on `GET /api/runs/{id}` for generated runs so opening
an old run reflects the current engine without a re-generate click.

**Frontend.**

- `StepSpecialLedgers.jsx` replaces `StepItc.jsx`.  Two tabs:
  "Exempt Purchases · Input A" (P&L ledger picker) and
  "ITC Ledgers · Input B" (original picker) + prominent
  **"Use ITC inference for Col 3"** Switch (default ON).
- `Clause44Run.jsx` step key renamed `itc → special`; legacy URL shim
  keeps `?step=itc` working.
- `ReconTable.jsx` rewritten as a 5-line ICAI layout with a per-line
  bucket dropdown.
- `StepReport.jsx` gains a Release-1 info strip showing the Col 3 split
  (Input A vs B), RCM voucher count, and import totals.

**Excel export.** Reconciliation sheet now emits the 5-line ICAI format
with indented lines under each bucket + a Disclaimer block at the
bottom.  The other 5 sheets (Summary, Col 3/4/5/7) unchanged.

### Files touched
- `backend/modules/clause44/service.py` (cascade + recon rewrite)
- `backend/modules/clause44/controller.py` (new fields + silent re-class)
- `backend/modules/clause44/exports.py` (recon sheet)
- `frontend/src/pages/clause44/StepSpecialLedgers.jsx` — new
- `frontend/src/pages/clause44/Clause44Run.jsx` — step routing
- `frontend/src/pages/clause44/StepReport.jsx` — info strip + recon
  category persister
- `frontend/src/pages/ReconTable.jsx` — ICAI 5-line
- `frontend/src/pages/clause44/StepItc.jsx` — deleted
- `backend/tests/test_clause44_release1.py` — 15 unit tests
- Testing agent shipped 9 live-API integration tests too

### Tests: 37 green
- 15 unit (new cascade, de-dupe, toggle, auto-categoriser, recon math).
- 12 iteration-patch (company-guard + Excel shape) — still green.
- 9 live-API integration from testing agent against real Mongo + preview
  URL.

### Known limitations (documented for Release 2 Readme rewrite)
The JSON doesn't carry per-voucher nature-of-supply, tax rate, Section
17(5) eligibility, bill-of-supply markers, or status-at-time-of-supply.
The standard disclaimer on exports now calls this out explicitly.
Release 2 will rewrite `clause-44.html` to enumerate these limitations.



## Clause 44 — iteration patch (2026-05-04)

Three-point iteration on the freshly-shipped stepper:

1. **Cross-client books leak fixed.** `POST /api/runs` now compares the
   uploaded books' company name (new `companyName` key is honoured alongside
   the legacy `name`) with the client file it's being uploaded into using
   RapidFuzz token-set/token-sort scoring (≥ 80 threshold, after stripping
   common corporate suffixes like "P Ltd" / "Private Limited" / "& Co."). A
   clear mismatch hard-aborts with a 400 pointing the user to the right
   file. Empty `companyName` still passes (can't verify what isn't there).
   One orphan run (ABC Textile Mills books sitting inside Velav Garments
   file) was cleaned up from Mongo.

2. **Report page — classic 6-col pivot restored + drill-downs kept.** The
   Schedule tab now stacks:
   - KPI strip (Col 2 · Col 6 · Col 7).
   - **Per-Ledger Breakdown** — the legacy six-column pivot, read-only,
     searchable, with a footer aggregate row. Mirrors what the printed 3CD
     schedule looks like so partners can eyeball the tie-out.
   - **Cohort Drill-down** — the 4 expandable rows (Col 3/4/5/7) with
     Expense-wise / Party-wise tabs from the new stepper UI, untouched.

3. **Excel rebuilt into 6 sheets.** `modules/clause44/exports.py` rewritten:
   - Sheet 1 `Clause 44 Summary` — aggregate row + per-ledger six-column
     pivot (the "consolidated pivotable list"). Frozen header row.
   - Sheet 2 `Reconciliation` — Books → Clause 44 tie-out.
   - Sheets 3-6 — one per cohort (`Col 3 · Exempt`, `Col 4 · Composition`,
     `Col 5 · Other Reg ITC`, `Col 7 · Unregistered`) with the raw vouchers,
     header-frozen, totaled footer, Indian number formatting.

### Tests
`/app/backend/tests/test_clause44_iteration_patch.py` — 12 assertions:
company-name matcher (exact, Pvt/P-Ltd variant, clear mismatch blocks, both
empty-name edge cases pass), normaliser drops suffixes, JSON extractor
handles both legacy/new keys, Excel has exactly 6 sheets in the right
order, pivot sheet carries all 6 column headers, each cohort sheet contains
only its own bucket's vouchers with a correct footer total. All GREEN.

### Files touched
- `backend/modules/clause44/controller.py` — helpers + upload-time guard.
- `backend/modules/clause44/exports.py` — full rewrite.
- `frontend/src/pages/clause44/StepReport.jsx` — added `PivotTable`, kept
  cohort drill-downs.
- `backend/tests/test_clause44_iteration_patch.py` — new.



## Clause 44 — stepper refactor (2026-05-04)

### Team feedback addressed
1. **Stepper format** with top-right Proceed button, 4 steps: Import · ITC · Exclusions · Report. Replaces the old two-pane StepMapping + standalone Report screens.
2. **ITC auto-select** restricted to **Balance with Revenue Authorities** and **Statutory Dues Payable** subheads (substring match on `Map to Subhead`). Old keyword heuristic (`gst|input|cgst…`) retired.
3. **BS candidate pool** widened to every BS-side ledger *except* Trade Payables / Receivables / Sundry Debtors / Creditors / Fixed Assets / Cash / Bank / Bank OD — walks subhead + groupParent + head so granular Tally subheads (Buildings, Furniture, Plant &amp; Machinery) still get caught.
4. **Report** has a top Tabs: [Schedule, Reconciliation]. Schedule = 3 hero KPIs + 4 expandable cohort rows. Each cohort body carries its own [Expense-wise | Party-wise] tabs; clicking a row inline-drills to the transactions for that (bucket × ledger) OR (bucket × party) — no more pop-up Sheet.

### Backend changes
- `service.py` — replaced `compute_suggestions()`, added `_subhead_matches()` + `_fields_match()`, `ITC_SUGGEST_SUBHEADS`, `ITC_POOL_EXCLUDE_SUBHEADS`. `classify_vouchers()` now emits `by_party` alongside `by_ledger`. `compute_recon_and_filter()` rebuilds `by_party` from filtered transactions so excluded ledgers don't leak. `merge_runs_for_consolidation()` also merges `by_party`.
- `controller.py` — new `PATCH /runs/{run_id}/selections` for incremental persistence across stepper navigation. `GET /runs/{run_id}/transactions` accepts optional `?party=` filter. `GET /runs/{run_id}` recomputes ITC/P&L suggestions on every fetch so runs uploaded before this change immediately benefit. Storage of `by_party` on the run document.

### Frontend changes
- New stepper under `pages/clause44/`:
  - `Clause44Run.jsx` — shell with sticky top bar (stepper pills + Proceed/Back/Export), URL-driven step via `?step=itc|exclusion|report`. Legacy `/runs/:id/report` defaults to the report step.
  - `StepItc.jsx` — single-column ITC picker with selected-chip tray + suggested badges.
  - `StepExclusion.jsx` — single-column P&L picker.
  - `StepReport.jsx` — schedule with hero KPIs, expand-in-place cohort rows, inline expense/party tabs + voucher drill.
  - `LedgerList.jsx` — shared ledger-picker primitive.
- Retired `pages/StepMapping.jsx`, `pages/StepReport.jsx`, `pages/Dashboard.jsx` (the wrappers that hosted them).
- `lib/api.js` — added `saveSelections()` + extended `getTransactions()` with party filter.

### Tests
- Backend unit harness (inline in this run): 12 assertions across subhead matcher, ITC pool filter (pre-select only the 2 target subheads, excludes trade pay/rec/FA/cash/bank), `by_party` shape + cross-tie to `by_ledger`, `compute_recon_and_filter` rebuilds `by_party`. All GREEN.
- `/api/runs/{id}/analytics`, `PATCH /selections`, `GET /transactions?bucket=col3&party=...` verified live against existing Velav Garments run (68 parties, 40 ledgers, drill = 3 txns for `Nmu Apparels Pvt Ltd`).
- Frontend: five visual checkpoints captured — Step 02 ITC, Schedule top, expense-wise drill, party-wise drill, party-drill to voucher rows. All render as designed.



## Docs feedback widget — heatmap-ready (2026-05-03)

### Why
Each readme now ends with a "Did this guide help?" widget AND every numbered
section has a tiny "Was this section clear?" thumbs strip. Over time, the
admin can see which sections silent-fail for new joinees — the reason
free-text gives prose-level signal.

### Backend  ·  `modules/docs/feedback.py`
- `POST /api/docs/feedback` — any logged-in user. Body:
  `{module_key, section_id, helpful: bool, reason?: str}`. Idempotent
  upsert keyed on `(user_id, module_key, section_id)` — users can flip
  their thumbs without polluting the dataset.
- `GET  /api/docs/feedback/aggregate?module_key=…` — admin only.
  Group-by `(module_key, section_id)` returning `{up, down, total, score,
  recent_reasons[]}`. Score = up / (up + down). Reasons sorted recent-first
  and capped at 5.
- `GET  /api/docs/feedback/raw?module_key=…&limit=200` — admin only,
  full row dump for triage.
- DB collection `docs_feedback` with `feedback_id`, `user_email`,
  `user_name`, `ts`, `updated_at`.

### Frontend (vanilla JS embedded in `_base.html`)
- Per-section widget: `<div class="fb fb--section" data-fb-module="…"
  data-fb-section="…">`. Two thumbs. Picking "No" reveals an inline
  `<textarea>` with a "Send feedback" button — submits with the reason.
- Overall card at the very bottom: same shape, slightly bigger, serif title.
- Confirmation message replaces title after submit ("Thanks — captured.").
- `@media print { .fb { display: none !important; } }` AND the whole script
  is wrapped in `{% if not for_pdf %}` — verified zero markup leaks into
  the PDF.

### Tests  ·  `tests/test_docs.py` — 12/12 GREEN
- 6 endpoint/branding tests (unchanged)
- 6 new feedback tests: thumbs-up, thumbs-down with reason, idempotent
  re-submit, aggregate shape, admin gating on aggregate, payload validation.

### Observability path forward
Aggregate JSON is consumable as-is. When you want a UI, plug the
`/feedback/aggregate` endpoint into a tiny admin page with a colour-graded
table (red for low score sections). Section IDs we already track:
`regulatory · cohorts · prereq · walkthrough · output · edge · faq ·
glossary · _overall`.



## User Guides + AssureAI rebrand (2026-05-03)

### New module — `modules/docs/` (HTML + PDF user guides)
- `GET /api/docs/{key}` → branded HTML readme (login-gated)
- `GET /api/docs/{key}.pdf` → WeasyPrint PDF rendered from the SAME Jinja2
  template (single source of truth, zero drift)
- `GET /api/docs/{key}/_asset/{name}` → static SVG/CSS/screenshots
- Module catalogue defined in `MODULES` list — each entry needs one
  `templates/{key}.html`. Catalogue currently: `clause-44`. Adding a new
  module = add one HTML file + one catalogue entry.

### Clause 44 readme — gold-standard reference
- 11-page user guide; cover + executive summary on page 1 (paywall page for
  busy reviewers), then 8 numbered sections: regulatory primer · 4 cohorts
  demystified (with cohort waterfall SVG) · prerequisites (Tally export
  paths) · click-by-click walkthrough (6 steps with callouts) · output
  workbook structure · 7 edge cases · 8-item FAQ · glossary
- Premium typography: Fraunces serif headings + Inter body + JetBrains Mono
  monospace; emerald accent; printable A4 with page numbers and running
  header
- Six callout flavours: note · tip · warn · pitfall — auditor-tone copy

### Frontend
- `Readme` button (lucide `BookOpen` icon) added to Clause 44 page header
  (`ClientHome.jsx`) — opens `/api/docs/clause-44` in a new tab
- `data-testid="readme-clause-44"` for regression

### Brand rebrand — MSS × Assure → AssureAI Utilities
Touched 14 files across frontend & backend:
- Frontend sidebar mark "M" → "A", brand text, login page hero copy,
  consolidated footer, balance-confirmation public landing footer,
  client-utilities subtitle
- Backend PDF footers (balance-confirmation summary, ledger letter, fixed
  assets working paper, GST recon), QA Test Pack title + filename, invitation
  email template, FastAPI app title, Resend `EMAIL_FROM` default
- Auditor firm fallback (was "MSS & Co.") → "AssureAI Audit Utilities"
- Verified: zero `MSS` references remain in production code
  (`grep -r "MSS" --include="*.{py,jsx,tsx}"` returns empty)

### Tests
- New `backend/tests/test_docs.py` — 6/6 GREEN
  - HTML index renders + lists modules
  - Clause 44 HTML carries Executive Summary, Walkthrough, Edge cases, FAQ, Glossary
  - PDF returns `application/pdf` with `%PDF-` magic, > 30 KB, correct branded filename
  - Unknown module → 404 (both HTML and PDF routes)
  - Anonymous → 401/403

### Dependency added
- `weasyprint==68.1` (HTML → PDF). Pango/Cairo system libs already present
  in the container; no Dockerfile changes required.



## Balance Confirmation — CC/BCC legal safeguard (2026-05-02)

### Vulnerability closed
The recipient-confirmation email previously embedded a single tokenised CTA
(`/confirm/{token}`) inside one HTML body that Resend delivered to **TO + CC +
BCC** simultaneously. Anyone in the cc/bcc list could click "Confirm balance"
and submit a confirmation in the primary recipient's name — including the
client themselves when CC'd, which is a legal lacuna for a statutory audit.

### Fix
Bulk-send is now a **two-message pipeline** per ledger:

1. **Primary message** — `to=[ledger.email]`, `cc=None`, `bcc=None`. Carries the
   live `<a href="...track/click/{token}">Confirm or dispute balance</a>` CTA
   plus the open-tracking pixel. Telemetry (opened / clicked / responded) flows
   only from this address.
2. **Notice message** — fired only when `cc_emails ∪ bcc_emails` is non-empty.
   `to=[first cc | auditor]`, `cc=[remaining cc]`, `bcc=[bcc list]`. Body is
   piped through new `sender.build_notice_body()` which:
   - Strips the open-tracking pixel.
   - Replaces every `<a>` anchor pointing to the click URL or the response
     link with an inert grey badge: `Confirm or dispute balance` (line-through)
     plus an italic *Action required by `<primary email>` only*.
   - Prepends an amber `Informational copy. No action is required …` banner.
   - Subject prefixed with `[Informational copy]`; `tags=[kind:"notice"]`;
     SENDLOG entry written with `kind="notice"` for audit trail.

### Tests
`backend/tests/test_balance_confirmation_cc_safeguard.py` — 5/5 GREEN.
Asserts: primary keeps CTA + pixel; notice strips pixel; notice contains zero
clickable CTA hrefs (both click_url AND response_link variants); banner +
primary-email caption render; safeguard works for customer/vendor/bank
default templates.



## Balance Confirmation — Summary Analytics Dashboard (2026-05-02)

The Balance Confirmation run view now ships a top-level `Dashboard | Workbench`
tab switcher. Dashboard is the default landing view once books are ingested.

### What's new
- **New API**: `GET /api/balance-confirmation/runs/{rid}/analytics` — the single
  source of truth consumed by both the on-screen dashboard and the Summary PDF.
- **New shared module**: `backend/modules/balance_confirmation/analytics.py`
  computes the full payload (overall, categories, funnel, top-disputed,
  top-unresponsive, subhead heatmap).
- **New frontend component**: `frontend/src/pages/balance_confirmation/SummaryDashboard.jsx`
  renders (1) Hero KPIs — Total parties, Total exposure ₹, Audit coverage by
  count & by ₹, (2) Category matrix — one card per Rec/Pay/Bank/Unsec Loans with
  ₹-weighted stacked status bar + coverage %, (3) Confirmation Funnel (6 stages),
  (4) Recharts donut of status by ₹ exposure, (5) Top Disputed by variance &
  Top Unresponsive by ₹, (6) Subhead coverage heatmap for audit sampling.
- **Six-bucket status model**: confirmed · reconciled (= disputed + auditor
  recon comment exists) · disputed · in_flight · failed · not_sent. Reconciled
  rolls into audit coverage; disputed-without-comments does not.
- **Summary PDF rewritten** — now mirrors the on-screen dashboard exactly:
  page 1 Hero + Category Matrix · page 2 Funnel + Top Disputed · page 3
  Top Unresponsive + Subhead Heatmap · page 4 Variances detail · page 5
  Confirmed · page 6 Sign-off.
- **Download relocation** — Summary XLSX + Summary PDF buttons removed from
  the run-header strip and moved into the new dashboard header.

### Testing (iteration_17)
7/7 backend pytest green. Frontend regression green: switcher default =
Dashboard, all data-testids present (`bc-view-dashboard`, `bc-view-workbench`,
`bc-dashboard`, `bc-hero-total-parties/exposure/coverage-count/coverage-amount`,
`bc-category-matrix`, `bc-cat-*`, `bc-funnel-*`, `bc-status-donut`,
`bc-top-disputed`, `bc-top-unresponsive`, `bc-subhead-heatmap`,
`bc-summary-pdf`, `bc-summary-xlsx`). Live demo run analytics: 838 parties ·
₹291.98 Cr exposure · 5 categories populated.



## FS Designer — Drop 2c: structural alignment with the in-house FS reference (2026-05-01 PM-10)

After comparing my Drop-2b output against the user's V-904 reference PDF, several **structural** mismatches surfaced. RCA + fixes:

### RCA — what was wrong
1. **Notes section was using `details_report`** (ledger-level drill-down) as the body of each note — should have been using `notes_report.children` (the Schedule III a./b./c. sub-items). The ledger-level data belongs in a **separate** "Details to Financial Statements" section.
2. **Note 1 title** showed "Shareholders' Funds" — that's the BS-grouping label, not the note title. The JSON's `notes_report` carries this incorrectly because Note 1 is a wrapper.
3. **Note 8** was rendering as "Depreciation and Amortisation Expense" (P&L leaf) — should be "Property, Plant and Equipment" (BS leaf). Note 8 is shared between BS+PL because the matrix block accommodates both views.
4. **No PPE matrix**, **no ageing schedules**, **no Details section** — all in the reference but missing in my output.
5. **3-col vs 4-col headers** — Notes pages have a 3-col header (no Note No. column); Details pages have a 4-col header with "Notes" column on the left.

### Fixes shipped

#### Normalizer (`normalizer.py`)
- New `_walk_note_titles()` — builds a `{note_number: {leaf, parent}}` map from the BS+PL trees. **BS leaf labels are the canonical title source** (PL trees walked first so BS overrides any ambiguity for shared notes like 8).
- `_notes_with_details()` rewritten:
  - Title from BS title-map (falls back to `notes_report.account`).
  - Sub-items lettered a./b./c. from `notes_report.children`.
  - **Wrapper unwrap** — when a note has 1 child whose label matches the canonical title (e.g. "Share Capital" inside "Shareholders' Funds"), drill in: the unwrapped child's total becomes the note total, its grandchildren become sub-items.
  - **Empty-children fallback** — when a note has no `children` and the JSON's account differs from the canonical title (e.g. "Other Current Liabilities" wrapping a single "Statutory Dues Payable" leaf), surface the account as the lone "a." sub-item.
  - **Note 8 special-case** — clears sub-items and forces values from `fixed_asset_report` so the renderer attaches the PPE matrix block. Synthesizes a Note 8 entry if absent in `notes_report`.
- New `_details_sections()` — flattens `details_report` rows into ledger-level blocks with `N (letter)` references (e.g. "1 (a)", "23 (b)").
- New `_normalize_ageing()` — maps `ageing_report` per FY × category into renderable rows for trade payables / receivables.

#### PDF renderer (`pdf_renderer.py`)
- New `_details_col_header()` — 4-col header (Notes / PARTICULARS / Rs. Ps. / Rs. Ps.) for the Details section.
- `_note_block()` rewritten — 3-col (no Note No. col), letter-prefixed sub-items, total row showing only the underlined number (no "Total" word).
- New `_ageing_table()` — appends the Trade Payables Ageing schedule under Note 5 and the Trade Receivables schedule under Note 12 (one mini-table per FY with bucket columns Not Due / <1Y / 1–2Y / 2–3Y / >3Y / Total).
- New `_ppe_matrix()` — Note 8 PPE matrix in the reference's exact shape: rows are Gross Block / Depreciation / Net Block sub-sections (CY + PY), columns are asset categories + Total. Uppercase section bands.
- New `_details_block()` — renders each lettered sub-item as a block with leaf rows + total, wrapped in `KeepTogether` so a sub-item never breaks across pages.
- Removed the obsolete generic `_fa_block` — Note 8 PPE is now the primary surface for FA data.
- Old `pdf_common.py` deleted (consolidated into the renderer).

#### Frontend (`RunPage.jsx`)
- `NotesPanel` updated to read the new `subitems` schema with letter prefixes.
- New `DetailsPanel` — groups ledger-level entries by parent note with `N (letter) <head>` references, rendered as a compact list with `data-testid="fs-panel-details"`.

### Tests — `tests/test_fin_statement_pdf.py` (**13/13 GREEN**, lint clean)
- Title resolution: Note 1 = "Share Capital" (₹16,92,04,730.54), Note 8 = "Property, Plant and Equipment" (₹4,62,41,795.83).
- Letter prefixes: Note 3 has a./b. for Term Loans / Unsecured Loans; Note 11 has 4 sub-items.
- Note 8 has no sub-items (matrix block handles it).
- Details section: ≥50 lettered entries including "1 (a)" and "23 (a)".
- Ageing normalized for trade payables AND trade receivables.
- BS balances: TOTAL (I) ≡ TOTAL (II) within ₹1.
- PDF integrity: ≥5 pages, all 3 statement pages carry the full signatory footer (MSS AND CO, FRN 001893S, both DINs, Membership 207277, Place Tiruppur, Date 10-07-2025); notes pages spot-check "NOTE NO : 1 SHARE CAPITAL", "NOTE NO : 8 PROPERTY, PLANT AND EQUIPMENT", "NOTE NO : 11 INVENTORIES"; Details section contains "1 (A) SHARE CAPITAL" + "23 (A)".

### Live end-to-end
Re-ingested Velav run via live API — Notes 24 · Details 80 · Note 1 title "Share Capital" · Classic 61,274 B · Boardroom 62,474 B · 20 pages each (1 BS + 1 P&L + 1 CFS + 4 notes + 13 details).

Course-correction after user shared a reference PDF (`V-904_VELAV_…_Final.pdf`). Clarification: each of BS / P&L / CFS must fit on **its own** portrait page (not all three on one page), and **every** statement page must carry the full signatory footer (auditor + client directors with DIN).

### Normalizer rewritten (`normalizer.py`)
- `_render_tree()` walks each BS/P&L tree and emits flat rows with:
  - **numbering prefix** per indent: indent-0 → Roman (I, II), indent-1 → Arabic (1, 2), indent-2 → lowercase `a. b. c.`, indent-3 → uppercase `A. B.` (for Trade-Payables MSE-vs-Other split).
  - `kind ∈ {header, subhead, leaf, subtotal, total}` — subtotals (`Total(N)`) are synthesized after each indent-1 group closes; `TOTAL (I)` / `TOTAL (II)` are synthesized after each root closes.
- New period helpers: `current_end_short` (`31/03/2025`), `current_end_long` (`31st March 2025` with ordinal suffix) so the page titles match the reference verbatim.
- New `_signatory()` helper — converts `authorized_signatory_role` into a `directors: [{name, role, din}]` list, formats `reportDate` as DD-MM-YYYY, accepts an optional `client_record` arg so the controller passes CIN in from the `clients` collection.
- Cleaner short-address helper returns just the city line ("NALLUR , TIRUPUR") for the page header.

### PDF renderer rewritten (`pdf_renderer.py`)
- A4 **portrait** throughout. One page per statement:
  - **Page 1** — Balance Sheet with company header (name / CIN / city) → statement title ("Balance Sheet as at 31st March 2025") → 4-col table (Particulars / Note No. / Rs. Ps. CY / Rs. Ps. PY) → full signatory footer → page number.
  - **Page 2** — Statement of Profit and Loss (same structure, YE column labels).
  - **Page 3** — Cash Flow Statement (3-col layout without Note col, serial A/1/2…).
  - **Page 4+** — Notes, each wrapped in `KeepTogether`.
- The signatory footer renders in a 2-column layout: **Left** — "For MSS and Co" / "Chartered Accountants" / FRN / partner's name / Partner / Membership No. / Place / Date (+ UDIN when set). **Right** — "For VELAV…" / directors side-by-side with their role and DIN. Preamble lines "The Accompanying Notes form an integral part…" + "Subject to our report of even date" span both columns.
- Indent-0 section headers are uppercased (`EQUITY AND LIABILITIES`, not `Equity and Liabilities`) to match the reference. Header / subhead rows carry **no** values — values appear only on leaf + synthesized `Total(N)` / `TOTAL (I)` rows. `kind=total` rows get a heavier line-above + line-below + light band background.
- Column-header rows inside the table (PARTICULARS / Note No. / Rs. Ps.) are `repeatRows` so they re-appear if a statement ever wraps onto a second page.
- Two palettes (Classic / Boardroom) continue to share identical structure; only accent colours differ.

### Velav seed
- Seeded `clients.cli_8656f99622ae.cin = U17299TZ2022PTC037953` so the demo run's header matches the reference 1:1.

### Tests — `tests/test_fin_statement_pdf.py` (**9/9 GREEN**, lint clean)
- Normalizer shape · company+period+CIN · numbering prefixes (I / 1 / a. / Total(1) / TOTAL (I)) · signatory enrichment (2 directors with DINs, date formatted DD-MM-YYYY) · `inr_rupee_paise` formatter (0 → "0.00", negatives → `(…)`, grouping at lakh/crore).
- PDF structure: ≥4 pages · p1 portrait A4 · p1 contains "BALANCE SHEET AS AT 31ST MARCH 2025" + "EQUITY AND LIABILITIES" + "TOTAL (I)" · p2 P&L · p3 Cash Flow · **all three statement pages carry** MSS AND CO · FRN 001893S · both DINs · Membership No. 207277 · Place Tiruppur · Date 10-07-2025 · portrait dimensions verified.
- Notes pagination: company header persists, notes titled "Note No : 1" / "Note No : 11" / "Note No : 16" all present.
- BS balances: TOTAL (I) == TOTAL (II) within ₹1 for both FYs.

### Live end-to-end
- Re-ingested Velav run `04dd1b84-033f-433d-a4c7-b37b94bd4f73` via live `/api/fin-statement/runs/{rid}/ingest`; both templates downloaded ~49 KB (Classic 49,023 · Boardroom 49,709). 15 pages each (1 BS + 1 P&L + 1 CFS + 12 notes pages).

### Drop 1 (2026-04-30 PM-9) — superseded
Initial 3-col landscape "all-on-one-page" design based on user's first instruction, replaced by the above redesign once the user clarified the real ask.

## Fixed Assets — Excel block-summary auto-fit (no number wrapping) (2026-05-01 PM-7)

Mirror of the PDF auto-fit fix — Excel column widths were hard-coded (15 chars for Opening WDV, 14 chars for Depreciation etc.) which would wrap ₹999 Cr-class numbers in cells. Applied the same content-aware sizing across all 3 data sheets.

### Implementation (`export.py`)
- New `_format_inr_indian()` helper mirrors the Excel `#,##,##0.00` cell format string in pure Python — used for *measurement only* (Excel renders the actual number itself).
- New `_fit_column_widths(ws, *, header_row, last_row, num_cols, num_col_indexes, text_cap=50, num_cap=22)` walks every populated cell in the given row range, computes the widest content per column (numbers via the formatted Indian-style string, others via raw `str()`), and overrides the explicit column widths. Caps prevent runaway 200-char Particulars from blowing the column out.
- `write_block_summary` / `write_additions` / `write_deletions` now call `_fit_column_widths()` after writing all rows; the explicit `(header, width)` tuples were stripped down to plain header strings.
- Workings sheet keeps a fixed 110-char width (it's an explanatory single-column note, not data).

### Tests
- `tests/test_fixed_assets_xlsx_autofit.py` — 5/5 GREEN: ₹999.99 Cr renders to 17 chars · normal-run widths fit actual numbers · huge-run (₹11,55,55,55,555.55) widths accommodate 16-char closing WDV · Additions register caps the 250-char particulars at 50 · total-row figures drive widths when larger than any block's value.
- Demo run actual widths: Block 30.4, numeric cols 13–18 sized to widest formatted value, runaway text capped at 50.
- Cumulative regression: **60/60 GREEN** across all FA test modules.

## Fixed Assets — PDF block-summary auto-fit (no number wrapping) (2026-05-01 PM-6)

User's screenshot showed `62,42,845.45` (Depn for 15% P&M) and `73,73,996.11` (Total Depn) wrapping onto two lines in the IT Depreciation Schedule PDF. Real-world client books may go up to ₹999 Cr (16 chars including grouping commas) — the table needs to auto-fit so numbers never wrap.

### Implementation (`pdf_export.py`)
- New `_autofit_summary_geometry(rows, totals, available_width)` helper:
  1. Pre-measures every cell (header + data + total row) using `reportlab.pdfbase.pdfmetrics.stringWidth`.
  2. Adds 8 pt horizontal padding (4+4) per column.
  3. If sum > 180 mm A4 portrait usable width, **shrinks the body font** in 0.5 pt steps from 7.5 pt down to a 6 pt floor.
  4. As a last resort (still over budget after font shrink), trims the Block-text column (text can wrap onto a 2nd line; numbers cannot) and proportionally rebalances the rest.
  5. Slack (when total ≤ available) flows to the Block column for visual balance.
- Column metadata externalised as `_SUMM_COLS` so headers/keys/alignment are declared once.
- Built paragraph styles dynamically tuned to the chosen body font size (with leading scaled to font + 1.5) so small fonts don't leave awkward vertical gaps.

### Tests
- `tests/test_fixed_assets_pdf_autofit.py` — 5/5 GREEN: widths sum to AVAILABLE for normal runs · auto-fit shrinks font for ₹999 Cr-class numbers · pdfplumber-extracted text shows the depreciation value on ONE line (no `\n` mid-number) · normal runs keep the comfortable 7.5 pt body · table renders without exception.
- Production demo run: both circled wrapping values from the user's screenshot (`62,42,845.45` + `73,73,996.11`) now appear on a single line in `/api/fixed-assets/runs/{rid}/export.pdf`.
- Cumulative regression: **39/39 GREEN** across all FA test modules.

## Fixed Assets — Cockpit-style audit-flag jumps + blank-on-ingest PTU (2026-05-01 PM-5)

### #1 — Clickable audit-flag cards turn the Summary tab into a *cockpit*
- `Landing.jsx` owns an `auditFilter` state + `goToFilteredAdditions(flagKey)` helper.
  - Routes `discount_pending` to the **Credits tab**; the rest to the **Additions tab** with the filter applied.
  - Manual tab clicks auto-clear any pending audit filter so the user is never surprised by a stale scope.
- `SummaryTab.AuditFlagsPanel` accepts an `onJumpToFlag` callback; cards with `count > 0` render as `<button>` (with an italic "Open in Additions →" affordance below the hint), cards with `count == 0` stay as non-interactive `<div>`s.
- `AdditionsTab` accepts `auditFilter` + `onClearAuditFilter` props and renders an `AuditFilterBanner` above the toolbar (`fa-additions-audit-filter-banner`) showing the active filter name + hint + match count + "Clear filter" link. Predicates: `missing_ptu` (empty PTU), `ptu_after_fy_end` (PTU > fy_end), `missing_party` (empty), `unreviewed` (`!reviewed && !parent_addition_id`), `zero_or_negative_cost`. Synthetic discount-credit pseudo-rows are excluded.
- When an audit filter is active the block/ledger scope filters are intentionally **bypassed** so the auditor sees ALL flagged rows across blocks at once (also eliminates a transient row-count race during the activeBlock-clear effect).

### #2 — PTU date no longer auto-populated on ingest
- `service.stage_addition_rows()` now leaves `put_to_use_date` blank — auditor types it manually or uses the existing bulk "Copy PTU = Acc Date" helper.
- Default `is_more_than_180=True` (full rate) so an un-filled PTU doesn't penalise the auditor's first-pass review.
- Existing demo run is unaffected (its PTUs were filled long ago); blank-by-default applies to fresh ingests only.
- Bulk "Copy PTU = Acc Date" + per-row inline edit + Excel round-trip all remain available — just no implicit population.

### Tests
- `tests/test_fixed_assets_ptu_blank.py` — 1/1 GREEN: ingestion leaves PTU empty + sets default `is_more_than_180=True`.
- Cumulative regression: 34/34 GREEN across all FA test modules.
- Frontend Playwright (iteration_16) — **100% in-scope GREEN**: clickable Un-reviewed → Additions cockpit jump verified end-to-end; banner + Clear-filter + auto-clear-on-tab-switch all working; zero-count cards stay non-interactive.

## Fixed Assets — Summary tab: MIS dashboard + audit command-center + download hub (2026-05-01 PM-4)

A 'feather on the cap' Summary tab that consolidates every MIS + audit-risk insight for one FA run on a single screen, and doubles as the only place from which deliverables (Excel + PDF) are downloaded.

### Scope
- ✅ Renamed Compute tab button to just **"Compute"**; removed Excel + PDF buttons from there.
- ✅ New **Summary tab** with KPIs, audit flags, MIS counts, block breakdown, insight cuts, quarterly distribution, and download hub.
- ✅ Single GET `/runs/{rid}/summary` endpoint — one call, full payload (no waterfall).

### Backend (`summary.py` + 1 endpoint)
- `build_summary()` — pure aggregator (no DB writes) consuming raw additions, credits, ledgers, compute rows, attached_addition_ids, pending_uploads. Computes:
  - **KPIs**: opening · adds_full · adds_half · sales · depreciation · closing
  - **MIS counts** (count + ₹): ledgers (+ classified), additions, additions_merged, discounts (+ merged), sales, bills_attached / bills_unattached, coverage_pct, half_rate_pool
  - **Audit-risk flags** (count + ₹): missing_ptu, ptu_after_fy_end, missing_party, unreviewed, discount_pending, zero_or_negative_cost; `open_flag_count` is the count of flags with count > 0
  - **Block-wise breakdown**: per active block — count + capitalised value + depreciation + closing WDV (sorted by descending rate)
  - **Top 10 additions** by capitalised value with addition_id + description + party + block + PTU + ½-rate flag
  - **Top 5 suppliers** by capitalised value
  - **Adjustment-column usage** — touched count + ₹ for each of Other Exp / ITC Rev / Int Cap / Forex / Disc-Cr (latter flagged `reduces_cost=True`)
  - **Quarterly distribution**: Q1/Q2/Q3/Q4/Outside-FY buckets with count + ₹ (sums must equal active additions count)
  - **OCR coverage**: uploads_pending, uploads_total, chunks_total, chunks_applied, chunks_remaining
- New endpoint `GET /runs/{rid}/summary` — pulls raw rows (excluding compute's synthetic discount pseudo-rows so audit stats aren't polluted), assembles the payload, returns the run-level `prior_3cd_validation` flag for the validation card.

### Frontend (`SummaryTab.jsx` + `Landing.jsx`)
- New tab "Summary" (LayoutGrid icon, testid `fa-tab-summary`) right after Compute.
- Single-page composition: dark slate-900 header strip · 5-card KPI strip (compact + exact ₹) · two-column row [3CD validation + OCR coverage cards | audit-flags grid] · MIS counts (6-card row) · block breakdown table · two-column [top additions list | top suppliers + adjustments] · quarterly distribution bars · download hub (two large cards: emerald Excel + rose PDF, each with a 3-bullet "what's inside" legend).
- Compute tab now points users to Summary in the helper copy; Compute button stays.

### Tests
- `tests/test_fixed_assets_summary.py` — 10/10 GREEN: payload shape, KPIs match `/compute` totals exactly, counts cross-foot to the additions count, audit flag shape + open-flag arithmetic, blocks sorted desc by rate, top additions ≤ 10 sorted desc, top suppliers ≤ 5 sorted desc, adjustments has all 5 keys (`discount_credits.reduces_cost=True`), quarterly counts sum to active additions count, OCR consistency (`chunks_applied ≤ chunks_total`).
- Frontend Playwright (iteration_15) — **100% GREEN**: tab wiring, Compute tab cleanup (no export buttons), all 24+ Summary testids present, KPI strip values match (Opening ₹3.01 Cr · Adds ₹2.63 Cr · Sales ₹50 k · Depn ₹72.92 L · Closing ₹4.90 Cr), audit-flag panel shows '1 open' (50 unreviewed), MIS counts populate, block breakdown 5 rows sorted desc, top additions 10 rows, top suppliers 5 rows with proportional bars, adjustment usage 5 rows, quarterly 5 bars, Excel download 18,765 bytes + PDF download 25,549 bytes.

## Fixed Assets — PDF additions register grouped by block (2026-05-01 PM-3)

The A4 PDF working-paper now groups the additions register by **IT block** with sticky-style sub-headers — the user's exact ask: "32 assets · ₹2.34 Cr" pattern.

### Implementation (`pdf_export.py`)
- New `_block_header_strip(block_label, rate, count, total, widths)` — slate-900 strip spanning the full table width: left = bold white block label + yellow rate pill; right = muted "<N> assets · ₹<total>" summary.
- New `_column_header_strip(widths)` — slate-50 sub-header (PTU DATE · PARTICULARS / SUPPLIER · CAPITALISED COST) repeated under each block strip so the columns stay self-documenting.
- `_asset_card(a, widths)` extracted as a helper; the block_label was removed from Row B's metadata strip since the block name is already shouted at the top of the group.
- `_additions_section(additions, block_meta)` groups by `block_label`, orders groups by descending rate, sorts cards within a group by PTU date, and uses `KeepTogether` on `[block_strip + column_header + first_card]` so a sub-header is never orphaned at the bottom of a page.
- `build_pdf` accepts an optional `block_meta` arg; the controller passes `inputs["blocks_meta"]` so the rate pill is correct even for blocks that have no current-year activity.

### Layout polish
- Block summary table column widths recalibrated to **180 mm** total (was overflowing): 48+10+22+22+22+17+17+22 = 180. Dedicated `summ_th/summ_l/summ_r/summ_b` paragraph styles at 7.5 pt to keep all 8-digit ₹ values single-line in a 22-mm column.

### Tests
- `tests/test_fixed_assets_3cd_gate_pdf.py::test_export_pdf_groups_additions_by_block` — extracts text via pdfplumber and asserts the three active block sub-headers + asset-count strings + new "grouped by IT Block" copy. GREEN.
- Cumulative regression: **23/23 GREEN** across all FA test modules. Demo run state preserved (5 active blocks, 98 capitalised assets).

### What the auditor sees
On page 2+ of the PDF the additions are now organised as:

1. `Additions Register · 98 asset(s) capitalised in this run, grouped by IT Block.`
2. **40% Block – Computers**  40%  →  9 assets · ₹4,31,500 (slate strip)
   - cards in PTU-date order …
3. **40% Block – Plant & Machinery**  40%  →  N assets · ₹X
4. **15% Block – Plant & Machinery**  15%  →  49 assets · ₹2,26,81,637.92
5. … and so on, descending rate.

## Fixed Assets — Compute gate, zero-row skip, A4 PDF (2026-05-01 PM-2)

Three asks landed together:

### #1 — Drift-banner-style 3CD gate (Compute disabled until match or override)
- Backend `validate-3cd` now persists a compact `prior_3cd_validation` summary on the run: `{ok, mismatch_count, totals, validated_at, filename, acknowledged}` — `acknowledged=ok` so a green validation auto-resolves while a mismatch fires the gate.
- New endpoint `POST /runs/{rid}/clear-3cd-validation-warning` — auditor-driven "I've reviewed — proceed anyway" override; flips `acknowledged=True`.
- Every opening-WDV mutator (`POST /block-opening`, `/import.xlsx`, `/apply-prior-3cd`, `/roll-forward`) auto-`$unset`s the prior validation so a stale green can never linger after the auditor edits openings.
- Frontend `Validation3CDBanner` renders three states: rose blocking banner with override CTA when `ok=false && !acknowledged`; emerald acknowledged strip when `acknowledged=true` (with different copy for "passed" vs "overridden"); nothing when no validation exists.
- `Compute` button disabled (`cursor-not-allowed` + tooltip) while `computeBlocked` memo is true.

### #2 — Skip zero-only block rows
- `compute_run` filters every row where opening + adds + dels + depn + closing + STCG are all zero, before sorting + emitting. Excel Block Summary + on-screen result table both consume that filtered list, so the auditor sees only active blocks (5 vs 15 in the demo run).

### #3 — A4 portrait PDF working-paper (`pdf_export.py`)
- New `GET /runs/{rid}/export.pdf` — reportlab-built, A4 595×842 pt:
  - Page 1: H1 title + client/FY/run header + 4-card KPI strip (Opening · Adds · Depreciation · Closing) + full Block Summary table with TOTAL row.
  - Pages 2+: Additions Register, **one card per asset** as the user requested:
    - Row A (primary scan path): PTU Date · **Particulars** + muted Supplier · Capitalised Cost (right-aligned, bold ₹).
    - Row B (muted detail strip): Voucher · Inv # · Inv Dt · Block · Ledger, plus a smaller bottom-line breakdown showing Inv Cost ± Other Exp ± ITC Rev ± Int Cap ± Forex ± Disc/Cr.
- Indian-format (lakh/crore) ₹ helper, slate-100 row alts, sky-100 KPI accent, slate-900 header band, hairline borders. Frame footer carries page number + "MSS × Assure · Audit Working-Paper" + run name.
- Sort discipline: additions ordered by PTU date → block → supplier so the auditor reads chronologically.
- New rose `Download PDF` button (testid `fa-export-pdf-btn`, FileText icon) sits right of the existing Excel button.

### Tests
- `tests/test_fixed_assets_3cd_gate_pdf.py` — 6/6 GREEN: validate persists with acknowledged=False on mismatch / True on match; clear-warning acks; opening-WDV writes auto-invalidate stale gate; compute filters all-zero blocks; export.pdf returns ≥5 KB %PDF.
- Cumulative regression: 22/22 GREEN across all FA test modules.
- Frontend Playwright (iteration_14) — 5/5 GREEN: case-A green-gate, case-B mismatch + override, screen zero-row skip (5 blocks shown vs 15 active), Excel zero-row skip, PDF download (27,548 bytes, A4 portrait MediaBox 595.28×841.89, multi-page).

## Fixed Assets — Opening WDV Excel round-trip + optional 3CD validation (2026-05-01 PM-1)

3CD JSON only carries opening WDV at the **rate level** but the depreciation working needs sub-block resolution (e.g. "15% Block – P&M" ₹25.78L vs "15% Block – Vehicles" ₹0.45L, both at 15%). Auditors now have a clean Excel round-trip for Opening WDV; 3CD becomes an OPTIONAL sanity-check.

### Backend (`block_opening_xlsx.py` + 3 controller endpoints)
- `GET /runs/{rid}/block-opening/export.xlsx` — one-sheet workbook with one row per active `block_label` (incl. zero-value rows), pre-populated with the current `fa_block_opening` values. Hidden col-A canonical key + locked Block/Rate cells; only Opening WDV + Note are editable. Live SUM total in row 3.
- `POST /runs/{rid}/block-opening/import.xlsx` — multipart, parses, upserts each block with `source="manual_xlsx"` + `source_ref=<filename>`. Footer informational rows are silently skipped; rows with bogus block_label surface in `unknown_blocks` for the auditor.
- `POST /runs/{rid}/block-opening/validate-3cd` — multipart, parses optional 3CD JSON, sums current openings by rate, returns a per-rate diff `{rate, opening_excel, opening_3cd, diff, status: match|mismatch|missing_in_*, blocks: [...]}` + global ok flag (within ±₹1 tolerance). **Read-only** — nothing is written.

### Frontend (`ComputeTab.jsx`)
- Toolbar reorganised into two rows: primary path = Export/Import Excel + Roll-forward; optional path = Validate/Import 3CD with a dashed top-border separator, an `OPTIONAL` mono pill, and explanatory copy ("only carries rate-level totals — use it to validate sub-block sums").
- New `Validate3CDModal` shows a per-rate diff table with status pills (match=emerald, mismatch=rose, missing=amber), totals strip, and a clear "Read-only check — adjust the Excel and re-import to fix mismatches" CTA.
- New `manual_xlsx` source chip (sky-blue "Excel") on the Opening WDV table.
- Existing `Import from Prior 3CD` flow preserved end-to-end (single-block-per-rate convenience path) — moved into the optional row.

### Tests
- `tests/test_fixed_assets_block_opening_xlsx.py` — 7/7 GREEN: export shape + hidden-key, round-trip persists with `source="manual_xlsx"`, import rejects non-xlsx, unknown blocks surfaced, validate 3CD match (P&M+Vehicles 15% sum to 3CD ₹26,233,559), validate mismatch surfaces drift, validate rejects non-3CD JSON.
- Frontend Playwright (iteration_13) — 5/5 GREEN: toolbar 2-row layout, export downloads valid xlsx, hidden inputs in DOM, sky "Excel" source chip on manual_xlsx rows, existing Prior3CDModal flow preserved.

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
