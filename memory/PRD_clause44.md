# Clause 44 — Product Requirements Document
**Module**: Clause 44 of Form 3CD (Tax Audit Report) · Total Expenditure Bifurcation
**Status**: Production · Release 4.4.12 (2026-02-09)
**Owner**: MSS × Assure (audit firm full-stack)
**ICAI Reference**: Guidance Note on Tax Audit, Para 79.3 – 79.20

---

## 1 · Module Purpose

Generate the Clause 44 working paper from a client's Tally / ERP books for a given financial year. The auditor uploads the books (JSON + Schedule III ledger mapping XLSX), the engine classifies every expenditure voucher into one of five reportable cohorts (Col 3 / 4 / 5 / 6 / 7), reconciles the per-books P&L back to the reportable Col 2 figure per ICAI Para 79.4, and emits a multi-sheet working-paper Excel.

### Output of record
A single Excel workbook with the following sheets:
- **Clause 44 Summary** — bucket totals + per-ledger seven-column pivot.
- **Reconciliation** — ICAI Para 79.4 five-line format (P&L + Capex − four deduction buckets = Col 2).
- **Col 3 · Exempt** — voucher-level cohort.
- **Col 4 · Composition** — voucher-level cohort.
- **Col 5 · Other Reg ITC** — voucher-level cohort + "Value eligible for ITC" column (Para 79.20).
- **Col 7 · Unregistered** — voucher-level cohort.
- **Col 8 · Excluded** — auditor-elected exclusions (Sch III, non-cash, money, other) grouped by sub-bucket.

A separate **Mapping Snapshot** Excel (3 sheets — Exempt / ITC / Exclusions) captures the engine's auto-suggestions and the auditor's current ticks, downloadable from any mid-flow step (no Generate required).

---

## 2 · User Personas

| Persona | Workflow |
|---|---|
| **Senior auditor / Manager** | Uploads books, reviews auto-suggested ledger picks, overrides as needed, generates the report, signs off the Excel. Primary user. |
| **Article / Junior** | Receives "next-step" tasks (e.g. "tick missing ITC ledgers"), works through Mapping Snapshot, doesn't make policy calls. |
| **Partner** | Reads the Excel for sign-off; never touches the UI. The Excel must be self-explanatory and audit-trail-friendly. |

---

## 3 · Core User Journey (5-step flow)

```
   Import → ITC → Exempt → Exclusions → Report
   ──────   ────  ──────   ──────────   ──────
   01       02    03       04           05
```

### Step 01 · Import
- Upload Books JSON (Tally export) + Ledger Mapping XLSX (Schedule III taxonomy).
- Mapping XLSX columns: `Ledger Name`, `Subhead`, `Group Parent`, `Head`, `BS/PL`, `Closing Balance`.
- Books are auto-pinned to the firm's central Library; future runs reuse pinned files via `POST /runs/from-library`.

### Step 02 · ITC Ledgers
- Pool 2 of the three-pool model — BS-side ledgers carrying Input GST credit.
- Default view: ledgers under `Subhead ∈ {Balance with Revenue Authorities, Statutory Dues Payable}`.
- "Show all BS-side" toggle expands to every B-side ledger (for clients with bespoke Schedule III mapping).
- Auto-suggestion based on (a) name token (`input`, `cgst`, `sgst`, `igst`, `cenvat`, `itc`), (b) parent-group token, (c) voucher-usage inference (≥ 3 purchase vouchers, dominates 3:1 over sales).
- **Negative list (Release 4.4.6 + 4.4.7)** — usage-based upgrade is blocked when:
  - Name matches: `tds`, `tcs`, `advance tax`, `income tax`, `professional tax`, `late fee`, `penalty`, `penal interest`, `interest on`.
  - Bank-charge-GST shape: name contains `bank` AND (`gst` / `charge` / `charges`).
  - Group parent in: `Bank Accounts`, `Advance Taxes`, `Provisions`.
  - Head whitelist: ITC ledgers can ONLY sit under `Other Current Assets` or `Other Current Liabilities`. Any ledger with a head outside this set has the usage upgrade unconditionally blocked.
- **ITC Inference toggle** — when ON, vouchers from a Regular-registered vendor without an ITC-ledger entry are presumed Input B (exempt-by-non-ITC) and routed to Col 3.

### Step 03 · Exempt Purchases
- Pool 1 of the three-pool model — P-side ledgers whose underlying supplies are exempt by GST law (petroleum, alcohol, life insurance, agricultural, etc.).
- Auto-suggestion based on keyword match: `petrol`, `diesel`, `alcoh`, `liquor`, `spirit`, `tobacco`, `life insurance`, `insurance premium`, financing-interest patterns. Penal-interest / GST-late-fee patterns are explicitly blocked from pre-tick.
- **Exempt × ITC voucher cross-check (Release 4.4.8)** — on entry to this step, the engine walks every voucher and demotes any pre-ticked exempt ledger that appears on a voucher carrying an ITC-ledger entry (taxable supply ≠ exempt supply per GST law). Auditor sees an amber banner with chips like `Insurance Premium · 12/80 vouchers carry ITC`. Zero-tolerance threshold; auditor can manually re-tick mixed-use ledgers.

### Step 04 · Exclusions
- Pool 3 of the three-pool model — auditor-elected exclusions that do not contribute to Col 2 (Schedule III items, non-cash charges, money / securities transactions, "other").
- Auto-suggestion based on keyword match: `salary`, `wages`, `pf`, `esi`, `gratuity`, `bonus`, `dividend`, `depreciation`, `provision`, `interest on income tax`, `interest on TDS`, `share`, `investment`, etc.
- Each ticked exclusion auto-categorises into one of four ICAI buckets (`non_cash`, `sch3`, `money`, `other`). Auditor can override the bucket via dropdown.
- **Capex auto-flow (Release 4.4.9)** — BS-side capex ledgers (heads ∈ `Property, Plant and Equipment` / `Intangible Assets` / `Capital Work-in-progress`) are NO LONGER surfaced here; they auto-flow to Col 2 via voucher classification and into the Para 79.18 recon row.

### Step 05 · Report
- Schedule tab: Col-2 / Col-3 / Col-4 / Col-5 / Col-6 / Col-7 totals + per-ledger pivot.
- Reconciliation tab: ICAI Para 79.4 five-line format.
- Drill-down: click any cell → slide-over shows underlying transactions.
- Generate Excel: produces the Output of Record described above.
- Re-Generate: idempotent; runs whose engine logic has been refined silently re-classify on every read so the on-screen view always reflects current logic.

### Mapping Snapshot (cross-cutting)
- Available from Steps 02-04 via a `Download Mapping Snapshot` button.
- 3-sheet Excel: Exempt / ITC / Exclusions, each row enriched with `Auto-Suggested?`, `Currently Selected?`, voucher counters, ITC overlap, and Schedule III metadata.
- Lets auditors review pre-tick decisions before clicking Generate.

---

## 4 · Engine Architecture

### 4.1 Three-pool model (Release 4.4)
- **Pool 1 — Exempt (`exempt_ledgers`)**: P-side ledgers feeding Col 3 / Input A.
- **Pool 2 — ITC (`itc_ledgers` + `itc_ledgers_all_bs`)**: BS-side ledgers driving Col 5 / Input B inference.
- **Pool 3 — Exclusions (`exclusion_ledgers`)**: P-side-only ledgers (Schedule III / non-cash / money / other) — capex no longer surfaced here.

### 4.2 Voucher classification cascade (`classify_vouchers`)
For each expenditure line on each voucher:
0. Ledger in auditor-elected exclusions → **Col 8**.
1. `voucherTypeName == "Reverse Charge"` → **Col 7**.
2. **Input A** — line's ledger in `exempt_ledgers` → **Col 3**.
3. Foreign supplier (non-India country) → **Col 7** (import).
4. Party `reg_type == "composition"` → **Col 4**.
5. Party `reg_type == "regular"` + GSTIN:
   - **Input B** — `use_itc_inference` ON & voucher carries no ITC ledger → **Col 3**.
   - Otherwise → **Col 5**.
6. Else (URD / consumer / blank) → **Col 7**.

### 4.3 Reconciliation math (`compute_recon_and_filter`)
```
   pl_total        (P-side voucher amounts, head ∉ _FA_HEADS)
+  capex_total     (P-side voucher amounts, head ∈ _FA_HEADS)
−  non_cash_total  (auditor-ticked + bucketed `non_cash`)
−  sch3_total      (auditor-ticked + bucketed `sch3`)
−  money_total     (auditor-ticked + bucketed `money`)
−  other_total     (auditor-ticked + bucketed `other`)
=  reportable_total  (must tie to Col 2 on the Schedule tab)
```

`_FA_HEADS = {property, plant and equipment, intangible assets, intangible fixed assets, capital work-in-progress, …}` — head-based capex split (Release 4.4.9). Falls back to parent-group chain only when head is empty.

### 4.4 Fresh re-classification contract (Releases 4.4.6 → 4.4.11)
Every read of a generated run silently re-classifies the run with current engine logic before serving:
- `GET /api/runs/{id}` — for the on-screen Reconciliation / Schedule tabs.
- `GET /api/runs/{id}/export` — for the main Excel.
- `GET /api/runs/{id}/mapping-export` — for the Mapping Snapshot Excel.
- `GET /api/clients/{id}/consolidated` + `/consolidated/export` — for the merged view (re-classifies each contributing division run).

This means engine refinements (e.g. capex head-split, ITC negative list) automatically apply to existing generated runs without requiring re-Generate. Falls back to stored snapshot if re-classification raises.

### 4.5 Excel sanitisation (Release 4.4.10)
A `_clean()` boundary helper strips ASCII control characters (`\x00-\x08`, `\x0b-\x0c`, `\x0e-\x1f`) from every voucher / ledger / narration string before openpyxl writes it. Caps strings at openpyxl's 32 760-char limit. Without this, stray clipboard-paste artefacts in Tally narrations crashed the export with `IllegalCharacterError`.

---

## 5 · Multi-Division Handling (Release 4.4.12)

### Mode A only — "Division uploads, computed Consolidated"
- Each division is a separate run scoped via `scope_kind="division"` + `division_id`.
- The Consolidated Report is the **computed merge** of generated division runs — there is no upload at Consolidation scope.
- `POST /runs` and `POST /runs/from-library` reject `scope_kind="consolidation"` with HTTP 400.
- `GET /clients/{id}/consolidated` queries `scope_kind != "consolidation"` AND `division_id != null`, applies Fix 6 fresh re-classification per division run, then merges via `merge_runs_for_consolidation`.
- Frontend gates the Consolidated Report button by `urlScope.scopeKind === "consolidation"` (hidden inside any Division view).
- Quick-start panel in Consolidation scope shows `Σ N division runs · Auto-computed` chip + a `View Consolidated Report` CTA (no upload button).

### Single-working-document semantics
A run is uniquely identified by `(client_id, period, scope_key)`. Re-uploading books for the same scope upserts onto the same `run_id`, unpins the previous Library file versions, and pins the new ones. Deep-links remain stable.

---

## 6 · Key API Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` | Upload books + mapping → create division run (consolidation scope rejected). |
| `POST /api/runs/from-library` | Reuse pinned Library files → create division run. |
| `GET /api/runs/{id}` | Fetch run with fresh re-classification. |
| `GET /api/runs/{id}/export` | Main Excel — fresh re-classified. |
| `GET /api/runs/{id}/mapping-export` | 3-sheet Mapping Snapshot Excel. |
| `POST /api/runs/{id}/exempt-pool` | Refresh Pool 1 with Exempt × ITC voucher cross-check. |
| `POST /api/runs/{id}/selections` | Persist auditor's ITC / Exempt / Exclusion ticks. |
| `POST /api/runs/{id}/generate` | Final classification + Mongo persist. |
| `GET /api/clients/{id}/consolidated?period=...` | Computed merge of division runs (Mode A). |
| `GET /api/clients/{id}/consolidated/export?period=...` | Same merge as Excel. |

---

## 7 · Data Model (per-run document)

```python
{
  "run_id": str,
  "module": "clause44",
  "client_id": str,        "client_name": str,
  "period": "2024-25",     "scope_kind": "division",
  "scope_key": str,        "division_id": str,    "division_name": str,
  "company_name": str,
  "accounting": {...},     # Books JSON (lazy-loaded from Library on demand)
  "ledgers_xlsx": {...},   # Schedule III mapping (lazy-loaded)
  "pinned_files": {"books_json": <id>, "ledger_mapping_xlsx": <id>},

  # Auditor selections (persisted)
  "itc_selection": [...],            "exempt_selection": [...],
  "exclusion_selection": [...],      "exclusion_categories": {...},
  "use_itc_inference": True,

  # Engine output (refreshed on every read; persisted on Generate)
  "summary": {...},                  # bucket totals
  "by_ledger": {...},                # 7-column pivot
  "by_party": {...},                 # party-level pivot
  "transactions": [...],             # voucher-level cohort lines
  "recon": {...},                    # 5-line ICAI Para 79.4

  "generated": bool,    "generated_at": iso,
  "archived": bool,     "created_at": iso, "created_by_name": str,
}
```

---

## 8 · Edge Cases & Business Rules

### What gets pre-ticked
- **ITC** — Default-view subhead match AND name-side OR usage-based input signal AND head ∈ ITC-eligible whitelist. Output-named ledgers can NEVER be auto-ticked, even if they appear on purchase vouchers.
- **Exempt** — Keyword match OR financing-interest pattern, AND no voucher carries an ITC-ledger entry (Release 4.4.8 cross-check). Penal-interest patterns explicitly blocked.
- **Exclusions** — Keyword match across Sch III / non-cash / money / other categorisers.

### What never gets pre-ticked
- TDS / TCS Payable / Receivable ledgers (statutory deductions, not ITC).
- Bank-charge GST ledgers (Bank GST / Bank Charges GST).
- Advance-tax / Income-tax / Professional-tax ledgers.
- Penal-interest ledgers (`Interest on Income Tax`, `Interest on TDS`, `Late Fee GSTR-3B`).
- Capex ledgers under PPE / Intangibles / CWIP heads (auto-flow to Col 2 via voucher classification, never need a tick).
- Trade Receivables / Trade Payables / Cash / Investments / Equity / Inventories.

### What auto-flows without auditor action
- Capex purchases → Col 2 + Para 79.18 recon row (head-based detection per Release 4.4.9).
- Reverse-charge vouchers → Col 7 (RCM).
- Foreign-vendor vouchers → Col 7 (import of services).

### Stale-tick cleanup
On every page-load, the frontend silently drops:
- ITC ticks where `kind == "output"` (Release 3.1).
- ITC ticks where `in_default_view == false` AND `name_kind != "input"` AND `kind != "input"` (Release 4.4.6 — handles vendor-advance / loans-and-advances picks carried over from older engine versions).

---

## 9 · Quality Bars

### Performance
- Run with 50 K vouchers + 5 K ledgers must classify in < 5 s on the standard preview pod.
- Excel export must complete in < 10 s for the same scale.
- Mapping Snapshot: < 2 s.

### Correctness invariants (asserted by tests)
- `pl_total + capex_total − Σ deduction buckets == reportable_total` exactly (no float drift > 0.5).
- Col 3 + Col 4 + Col 5 + Col 7 + Col 8 == Col 2 (gross expenditure).
- Per-ledger pivot row totals tie to summary bucket totals to the rupee.
- Consolidated merge is idempotent at N=1 (single-division total ≡ that division's total).
- Generated Excel ≡ on-screen view to the rupee (Release 4.4.11).

### Robustness
- Excel export must not crash on Tally narrations carrying control chars (Release 4.4.10).
- Stray `scope_kind="consolidation"` runs in Mongo must not bleed into the merged Consolidated view (Release 4.4.12).
- Engine refinements must apply to existing generated runs without requiring re-Generate (Release 4.4.11 fresh-classification contract).

---

## 10 · Test Coverage

**111 offline unit/integration tests** across 14 test files in `/app/backend/tests/`. Major suites:

| Suite | Tests | Coverage |
|---|---|---|
| `test_clause44_release4_4_pools.py` | ~12 | Three-pool model semantics |
| `test_clause44_itc_negative_list.py` | 23 | TDS/TCS/Bank-GST/PPE/CWIP/Loans head whitelist |
| `test_clause44_exempt_itc_cross_check.py` | 9 | Exempt × ITC voucher cross-check |
| `test_clause44_capex_auto_flow.py` | 11 | Head-based capex split + Pool 3 cleanup |
| `test_clause44_export_control_char_safe.py` | 6 | Excel sanitisation |
| `test_clause44_export_fresh_classification.py` | 4 | Excel ≡ on-screen contract |
| `test_clause44_consolidated_merge.py` | 8 | Consolidated merge semantics |
| `test_clause44_consolidated_guards.py` | 3 | Consolidation-scope upload rejection + query filter |
| `test_clause44_mapping_export.py` | 5 | Mapping Snapshot Excel |
| `test_phase_c1_scope_runs.py` | ~10 | Scope (division / GSTIN-group) backfill |

3 pre-existing live-test failures (require backend env) — tracked but not blocking; documented in PRD.md.

---

## 11 · Engineer Onboarding

A new engineer should be productive on Clause 44 in half a day with this section.

### 11.1 Code map

```
/app/backend/modules/clause44/
├── controller.py          ← FastAPI routes (~1320 lines).  Entry points
│                            for all `/api/runs/...` and
│                            `/api/clients/{id}/consolidated*` endpoints.
│                            Mongo upserts, scope resolution, fresh
│                            re-classification path.
├── service.py             ← Pure-function engine (~1420 lines).  No
│                            FastAPI / Mongo imports — easy to unit-test
│                            offline.  Houses:
│                              · `compute_pools`        — Pool 1/2/3
│                              · `classify_vouchers`    — cohort cascade
│                              · `compute_recon_and_filter` — Para 79.4
│                              · `merge_runs_for_consolidation` — Mode A
│                              · `filter_exempt_by_itc_overlap` — 4.4.8
│                              · `_classify_itc_kind`   — Input/Output
│                              · `_is_blocked_from_usage_upgrade` — 4.4.6/7
│                              · `_is_exclusion_hint`, `_is_exempt_hint`
│                            Constants:  `_FA_HEADS`,
│                            `_ITC_ELIGIBLE_HEADS`, `_REVENUE_HEADS_EXCLUDE`,
│                            `_USAGE_BLOCK_NAME_PATTERNS`, etc.
└── exports.py             ← Excel writers (openpyxl).  `build_export_response`
                             (main 7-sheet workbook) and
                             `build_mapping_export_response` (3-sheet
                             snapshot).  All voucher / narration data is
                             routed through `_clean_row()` to strip
                             control chars (Release 4.4.10).

/app/frontend/src/pages/clause44/
├── Clause44Run.jsx        ← Run-level shell.  Owns the 5-step state
│                            (import / itc / exempt / exclusion / report),
│                            the action cluster (Proceed / Generate /
│                            Mapping Snapshot / Export Excel), the legacy
│                            URL shim (`?step=special` → `?step=itc`),
│                            and the on-load stale-tick cleanup.
├── StepITC.jsx            ← Step 02 — Pool 2 (BS-side ITC ledger picks).
├── StepExempt.jsx         ← Step 03 — Pool 1.  Calls
│                            `POST /runs/{id}/exempt-pool` on mount with
│                            the locked ITC selection to fetch the
│                            cross-checked pool; renders amber banner
│                            with `12/80` overlap chips.
├── StepExclusion.jsx      ← Step 04 — Pool 3 with bucket dropdowns.
├── StepReport.jsx         ← Step 05 — Schedule + Reconciliation tabs +
│                            drill-down + Generate / Export.
├── LedgerTable.jsx        ← Shared table row renderer used by all 3
│                            pool steps.  Handles the kind / kind-source
│                            chip enrichment, voucher counters, etc.
└── StepSpecialLedgers.jsx ← Legacy combined ITC+Exempt step.  No longer
                             imported (Release 4.4.8 split).  Pending
                             cleanup.

/app/frontend/src/pages/
├── ClientHome.jsx         ← Per-client dashboard.  Hosts the runs list,
│                            quick-start panel (with the Mode-A
│                            consolidation-aware CTA), upload dialog.
└── Consolidated.jsx       ← Computed merge viewer.  Reads
                             `GET /api/clients/{id}/consolidated`.
                             Mode-A only.

/app/backend/tests/         ← Offline unit + integration tests.
                             111 passing tests across 14 files at
                             Release 4.4.12.  Run with:
                               cd /app/backend && pytest tests/
                                 -k "clause44 and not live"
                                 --ignore=tests/test_bc_release_4_6_live.py
                                 --ignore=tests/test_clause44_backend.py
```

### 11.2 Mongo collections used

| Collection | Purpose | Key fields |
|---|---|---|
| `runs` | One document per `(client_id, period, scope_key)` working document. Lazy fields `accounting` and `ledgers_xlsx` hydrated from Library on demand. | `run_id` (PK), `client_id`, `period`, `scope_kind`, `scope_key`, `division_id`, `generated`, `archived` |
| `clients` | Client master with `divisions[]` array. | `client_id`, `name`, `type` ("single" / "multi"), `divisions` |
| `library_files` | Pinned file blobs, dedup'd by SHA. Drives the Library Reuse pattern. | `file_id`, `client_id`, `period`, `scope_key`, `key`, `sha256`, `pinned` |
| `divisions` | Division master (multi-division clients). | `division_id`, `client_id`, `name`, `gstin_group_id` |

**Recommended composite indexes** (already present):
- `runs`: `(client_id, period, scope_key)` — unique constraint
- `runs`: `(client_id, period, generated, scope_kind, division_id)` — drives Consolidated query
- `library_files`: `(client_id, period, scope_key, key, pinned)`

### 11.3 Where to start reading

1. Open `service.py` and read top-to-bottom — the engine is plain Python with no framework noise.
2. Open `controller.py` and grep for `@router` — every route has a doc-string explaining what release it's from.
3. Run the offline test suite (`pytest tests/test_clause44_*.py`) and skim a couple of test files. The tests are written narratively and double as reference docs.
4. Open `Clause44Run.jsx` and trace `step` through the cascade. The 5 step components are tiny (~150 lines each).

### 11.4 Common engineering tasks — patterns

**Adding a new ICAI rule (e.g. blocking a new ledger pattern from auto-tick)**
1. Add the pattern to the appropriate constant in `service.py` (`_USAGE_BLOCK_NAME_PATTERNS`, `_FA_HEADS`, `_ITC_ELIGIBLE_HEADS`, etc.).
2. If a new helper is needed, add it as a private function next to its constant.
3. Wire it into `compute_pools._enrich_itc` or `compute_recon_and_filter` (pure-function — no controller change).
4. Add unit tests in the matching `test_clause44_*` file. The tests use synthetic ledger / voucher dicts; no Mongo / FastAPI required.
5. The fresh-re-classification contract (Release 4.4.11) means the change applies to *existing* generated runs without re-Generate. No migration.

**Adding a new step to the wizard**
1. Create `StepFoo.jsx` mirroring `StepExempt.jsx` (smallest existing step).
2. Update `STEPS` array in `Clause44Run.jsx`.
3. Add proceed/back handlers and wire the action-cluster JSX.
4. Add a row to the test for stepper navigation in `tests/frontend/test_clause44_step_navigation.spec.tsx` (or the closest equivalent).

**Adding a new column to the working-paper Excel**
1. Open `exports.py`, find the relevant `_write_*_sheet` function.
2. Append the header label to the `headers` list.
3. Append the value to the row tuple — wrap any string-typed value in `_clean()` if it could carry user / Tally data.
4. Update column widths array.
5. Update the matching test in `test_clause44_export_*.py` to assert the new column's index + value.

**Adding a new endpoint**
1. Add the route to `controller.py` with the standard `Cookie + Header` auth dependency.
2. Always include the `_ensure_run_data` + `_run_classification` fresh-classify spread for any endpoint that returns engine-derived data.
3. Always exclude `_id` in the Mongo projection (`{"_id": 0}`).
4. Always wrap Mongo writes that mutate the input dict with `{...d}` to avoid the `_id`-leak gotcha.

### 11.5 Common failure modes & where to look

| Symptom | Look at |
|---|---|
| `IllegalCharacterError` in Excel export | `exports.py` — verify the offending `ws.append` is wrapped in `_clean_row()` |
| Recon "Capital expenditure additions" row shows ₹0 | `service.py::compute_recon_and_filter` — check `head` field in `ledgers_xlsx`; head must be in `_FA_HEADS` (case-insensitive) |
| ITC pool wrongly pre-tics a TDS / advance-tax ledger | `service.py::_is_blocked_from_usage_upgrade` — check name / group / head match the negative list |
| Exempt pool wrongly pre-ticks a ledger that has ITC vouchers | `service.py::filter_exempt_by_itc_overlap` — verify ITC selection is being passed to the endpoint |
| Consolidated view shows division data twice | `controller.py::get_consolidated` — confirm the query has `scope_kind: {$ne: "consolidation"}` AND `division_id: {$ne: None}` |
| Excel and on-screen recon disagree | `controller.py::export_run` — confirm the fresh re-classify spread is in place (Release 4.4.11) |
| `KeyError: 'client_id'` on `getRun` | Run document was created via legacy upload before scope backfill — check `scope_kind` + `division_id` are populated |

### 11.6 Glossary (ICAI-speak ↔ engine terms)

| ICAI term | Engine term |
|---|---|
| Para 79.4 | Reconciliation 5-line format (`pl_total + capex_total − Σ deductions = reportable`) |
| Para 79.18 | "Capital expenditure additions" recon row (`recon.capex_total`) |
| Para 79.20 | "Value eligible for ITC" column on the Col 5 cohort sheet |
| Col 2 | Total expenditure (gross) — `summary.col2_total` |
| Col 3 | Exempt purchases — `summary.col3` |
| Col 4 | Composition vendor purchases — `summary.col4` |
| Col 5 | Other registered, ITC eligible — `summary.col5` |
| Col 6 | Total registered — Col 4 + Col 5 (memo line) |
| Col 7 | Unregistered / RCM / Foreign — `summary.col7` |
| Col 8 | Excluded items — `summary.col8` |
| Input A | Exempt-by-nature ledgers (Pool 1) |
| Input B | Exempt-by-non-ITC vouchers (inferred at voucher level) |
| Three-pool model | Pool 1 (Exempt) / Pool 2 (ITC) / Pool 3 (Exclusions) — Release 4.4 |

### 11.7 Useful one-liners

```bash
# Lint
cd /app/backend && ruff check modules/clause44/

# Run only Clause 44 offline tests
cd /app/backend && python -m pytest tests/ -k "clause44 and not live" \
  --ignore=tests/test_bc_release_4_6_live.py \
  --ignore=tests/test_clause44_backend.py -q

# Tail backend errors during a live debug
tail -f /var/log/supervisor/backend.err.log

# Hit the consolidated endpoint locally
API_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d'=' -f2)
curl -s "$API_URL/api/clients/<client-id>/consolidated?period=2024-25"

# Re-classify a single run from a Python REPL
cd /app/backend && python -c "
import asyncio
from modules.clause44.controller import _fetch_run, _ensure_run_data, _run_classification
async def go():
    r = await _ensure_run_data(await _fetch_run('<run-id>'))
    fresh = _run_classification(r)
    print('capex_total:', fresh['recon']['capex_total'])
    print('reportable:',  fresh['recon']['reportable_total'])
asyncio.run(go())
"
```

### 11.8 What NOT to do

- **Don't add Mongo writes inside `service.py`.** It's a pure-function module; controller-only writes keep tests fast and the engine portable.
- **Don't bypass `_clean_row()` when writing voucher data to Excel.** The `IllegalCharacterError` regression is real and recurring.
- **Don't reintroduce `scope_kind="consolidation"` upload paths.** Mode-A only (Release 4.4.12). The two backend guards in `controller.py` will 400 you anyway.
- **Don't auto-tick anything that isn't auditor-policy-driven.** Auditors are accountable; the engine's job is to suggest, not decide. Every auto-tick rule must be (a) keyword-explicit or (b) backed by a verifiable signal (e.g. voucher overlap with another auditor-confirmed list).
- **Don't merge the Consolidated view from raw division `summary` numbers.** Always re-classify each contributing division run first (Release 4.4.11 contract), so the merged view inherits engine refinements.

---

## 12 · Roadmap

### P0 (next up)
- 🔴 **Refine Exempt keyword/subhead positive list** — widen suggestion base (`freight`, `gta`, `goods transport`, `commission`, `brokerage`, `rent on residential`, `agricultural`); add subhead-based detection in addition to name-keyword. Awaiting auditor's refined rules.

### P1 (backlog)
- Configurable Exempt × ITC overlap threshold (currently zero-tolerance) — let firms set 5% / 10% if they prefer.
- Reconciliation health-check chip on Report header (auto-validate Col 2 ≡ pl_total + capex_total to the rupee).
- Division contribution sparkline on Consolidated Report.
- Persist-on-export — when `_run_classification` produces a fresh recon different from stored, write back to Mongo for audit trail.
- Mapping-Snapshot diff between two snapshots (before / after auditor's rule refinement).

### P2 (future)
- Companion module: 26AS / GSTR-2A reconciliation feeding into Col 5.
- Auto-detect bespoke client taxonomies (e.g. firms whose Schedule III mapping uses non-standard heads).
- Multi-period trend report (3-year Col 2 / Col 3 / Col 5 evolution).

---

## 13 · Out of Scope

- Cross-module consolidation (Clause 44 + GST Recon + Balance Confirmation in one workbook) — handled by the firm's manual paper-file process today.
- Real-time Tally connector (current model is JSON export upload).
- Multi-currency books — assumes INR throughout.
- Group / inter-company elimination — out of scope for Clause 44 (handled at the audit-engagement level).

---

## 14 · Appendix · Release History

| Release | Date | What shipped |
|---|---|---|
| 4.4.0 | 2026-01-xx | Three-pool model (Exempt / ITC / Exclusions) + new ITC default view |
| 4.4.5 | 2026-01-xx | ICAI Para 79.4 5-line recon format |
| 4.4.6 | 2026-02-09 | ITC negative list — TDS/TCS/Bank-GST/Advance-Tax patterns |
| 4.4.7 | 2026-02-09 | ITC head whitelist — only `Other Current Assets` / `Other Current Liabilities` heads eligible |
| 4.4.8 | 2026-02-09 | Stepper split (combined Special Ledgers → ITC + Exempt) + Exempt × ITC voucher cross-check |
| 4.4.9 | 2026-02-09 | Capex auto-flow — head-based split, BS-side capex removed from Pool 3, CWIP included |
| 4.4.10 | 2026-02-09 | Excel sanitisation (control-char strip) |
| 4.4.11 | 2026-02-09 | Excel ≡ on-screen — fresh re-classification on every export read |
| 4.4.12 | 2026-02-09 | Consolidated = computed merge (Mode A only); consolidation-scope upload rejected |
| 4.4.13 | 2026-02-09 | Consolidated tile chip — division-coverage-driven (Data Missing → Partial → Report Ready) |

