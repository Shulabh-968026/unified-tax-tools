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

## 11 · Roadmap

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

## 12 · Out of Scope

- Cross-module consolidation (Clause 44 + GST Recon + Balance Confirmation in one workbook) — handled by the firm's manual paper-file process today.
- Real-time Tally connector (current model is JSON export upload).
- Multi-currency books — assumes INR throughout.
- Group / inter-company elimination — out of scope for Clause 44 (handled at the audit-engagement level).

---

## 13 · Appendix · Release History

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

