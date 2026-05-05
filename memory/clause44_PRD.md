# Clause 44 — Product Requirements Document (Master)

> **Status:** Live in production (Release 3.5, 2026-05-04)
> **Module owner:** Audit Utilities · MSS × Assure
> **Code:** `/app/backend/modules/clause44/` · `/app/frontend/src/pages/clause44/`
> **Readme route (auditor-facing):** `GET /api/docs/clause-44` (HTML + PDF via WeasyPrint)

---

## 1 · Purpose & scope

Clause 44 of Form 3CD requires the tax auditor to disclose, for every entity carrying on business or profession, the **break-up of total expenditure** between:

* registered vs unregistered vendors under GST,
* further split between exempt supplies, composition dealers, and other registered dealers.

The statute provides only a header row; the **ICAI Guidance Note on Tax Audit (Para 79)** prescribes the working methodology, the recon to books, the disclaimers, and the columnar layout. Real-world Tally exports are noisy, GSTIN coverage is partial, and CA practice has settled on a number of inference heuristics. This module turns one Tally JSON + one books-mapping XLSX into a defensible, ICAI-aligned 3CD-ready Clause 44 schedule.

### Out of scope
* GSTR-3B / GSTR-9 reconciliation (handled by the GST Recon module).
* Verification of GSTIN active/inactive status (no live GSTN lookup; we trust party master).
* Apportionment of single-line composite invoices (auditor handles via splits in Tally).

---

## 2 · Output format (the deliverable the auditor takes to the file)

### 2.1 The 7-column schedule (statutory + engine-internal)

| # | Column | Meaning | Source |
|---|---|---|---|
| 1 | Sr. No. | Auto-assigned (always `1` for the aggregate row) | engine |
| 2 | **Total expenditure during the year** | **Gross** books total (incl. Col 8 items, capital additions per ICAI Para 79.18) | engine |
| 3 | Expenditure on **exempt** supplies | Auditor-tagged (Input A) + ITC-inference (Input B) | engine |
| 4 | Expenditure on **composition** dealers | Party `gstRegistrationType == "composition"` | engine |
| 5 | Expenditure on **other registered** dealers | Party Regular + GSTIN + (ITC ledger present OR inference OFF) | engine |
| 6 | Aggregate registered (3+4+5) | Arithmetic | engine |
| 7 | Expenditure on **unregistered** dealers | URD / Consumer / blank reg / no party / RCM / imports | engine |
| 8 | **Excluded** items (engine internal) | Non-cash · Sch III · Money · Capex add-back · Other auditor-elected | engine |

**Identity:** `Col 2 = Col 6 + Col 7 + Col 8`. The 3CD form prints Cols 1–7 only; Col 8 lives on the Reconciliation sheet so the auditor can defend Col 2.

### 2.2 The auditor-facing UI (Schedule tab)

* **7-tile clickable KPI strip** across the top — one tile per column. Each is a button with three states: idle / active (black ring inset) / dimmed (50% opacity). Click a tile → pivot below filters to rows that contributed to that bucket.
* **Filter banner** — "Filtered to · Col 5 · Other Registered · pivot rows below show only ledgers / parties that contributed to this bucket · Clear filter ×".
* **Unified pivot below** with two tabs:
  * **Expense-wise** — one row per expense ledger; 7 columns; click row to drill to vouchers.
  * **Party-wise** — one row per vendor; same 7 columns + GSTIN/Reg chip + voucher count; click row to drill.
* **Auto-fit text** — KPI tile values shrink the font (20 px → 11 px) when the value is wide enough to overflow (handles 9–10 digit aggregates).
* **Coverage advisory banner** — fires when ITC inference is ON, denominator ≥ 5 registered-vendor purchase vouchers, and `coverage_pct < 70%`. Indicates that some input-tax ledgers are likely un-tagged and Input B is sweeping value into Col 3 incorrectly.
* **Contextual chip strip** — Col 3 split (Input A vs Input B), RCM voucher count, imports total, single-source attribution chip when one source dominates Col 3.

### 2.3 The Reconciliation tab (ICAI Para 79.4)

A 5-line layout that ties the audited P&L total to the schedule:

| Line | Description | Computed |
|---|---|---|
| 1 | Total expenditure as per audited P&L | engine derives from books |
| 2 | (+) Capital additions per ICAI 79.18 | from capex add-back bucket |
| 3 | (-) Non-cash charges (depreciation, ECL, etc.) | from Col 8 sub-bucket `non_cash` |
| 4 | (-) Schedule III items not part of supply | from Col 8 sub-bucket `sch3` |
| 5 | (-) Money / money-securities / other exclusions | from Col 8 sub-buckets `money` + `other` |
| **Σ** | **Equals Col 2 of the schedule** | identity check |

Each excluded ledger row carries an **auto-detected sub-bucket dropdown** so the auditor can override the engine's sub-classification.

### 2.4 The Disclaimer tab (Para 79.21)

Free-text editor seeded with default Para 79.21 boilerplate. Edit per client; the final text is stamped onto the Excel reconciliation sheet on every export.

### 2.5 The Excel export (the working paper)

Endpoint: `GET /api/clause44/runs/{run_id}/export`

Workbook structure:

| Sheet | Contents |
|---|---|
| 1. **Clause 44 Summary** | Aggregate 7-column row + per-ledger pivot with all 7 columns; freeze panes; INR fmt |
| 2. **Reconciliation** | 5-line ICAI recon + auditor's saved disclaimer block |
| 3. **Col 3 · Exempt** | Voucher-level rows that landed in Col 3, with Para 79.20 columns (Reason, Remarks, ITC-eligible) |
| 4. **Col 4 · Composition** | Voucher-level rows that landed in Col 4 |
| 5. **Col 5 · Other Reg ITC** | Voucher-level rows that landed in Col 5 |
| 6. **Col 7 · Unregistered** | Voucher-level rows that landed in Col 7 |
| 7. **Col 8 · Excluded** | Voucher-level rows excluded; sub-bucket banded; sub-totals per band |

Per-row columns on cohort sheets: `Date · Voucher # · Voucher Type · Ledger · Party · GSTIN · Reg Type · Country · Amount · Reason · Remarks · ITC-eligible · Col3 source`. Auto-filter + freeze pane on every cohort sheet so auditors can pivot in Excel without going back to the app. Indian number format (`##,##,##,##0.00`) on every numeric cell.

### 2.6 The consolidated workbook (multi-period)

Endpoint: `GET /api/clause44/clients/{client_id}/consolidated/export` — same workbook structure, but the Summary sheet shows period-over-period totals side by side, and cohort sheets are union'd across periods with a `Period` column.

---

## 3 · Report-generation logic

### 3.1 Inputs

| Input | Format | Source | Required? | Notes |
|---|---|---|---|---|
| Tally JSON | `accounting.json` | Tally export | ✅ | Carries `vouchers[]`, `ledgers[]`, `groups[]`. JSON `partyGSTIN` / `country` / `gstRegistrationType` drive the cascade. |
| Books XLSX | `ledger_mapping.xlsx` | Manually maintained | ✅ | One row per ledger with columns: `Ledger Name`, `Map to BS or P&L`, `Map to Subhead`, `Map to Group Parent`, `Map to Head`, `Closing Balance`. |
| Auditor inputs | UI selections | Step 2 + Step 3 | ⚪ | `itc_selection[]`, `exempt_selection[]`, `exclusion_selection[]`, `use_itc_inference`, `disclaimer_text`. Saved on each PATCH. |

### 3.2 Pre-processing

1. **Cross-client validation** — uploaded JSON's company name (extracted from `companyName` / `pdfTitle` / first voucher) must match the run's `client_name` (case-insensitive, normalised). Reject with `409 Conflict` if it doesn't.
2. **Ledger candidate pool** — ITC tab and Exclusion tab populated by `compute_suggestions(ledgers_xlsx, ledgers_json, vouchers)` (see §3.3 for the multi-signal algorithm).
3. **Expenditure ledger detection** — `determine_expenditure_ledgers(ledgers_xlsx, ledgers_json, group_chains, excluded)` returns every P&L ledger with a debit closing balance + every Tally ledger whose group chain contains "Fixed Assets" (capital additions per ICAI 79.18). Excluded ledgers are removed at this stage.
4. **Group chain build** — `build_group_chain(groups)` flattens Tally's nested group tree into `{ledger_name: "Indirect Expenses › Operating Expenses"}` so the engine can reason on a stable parent-group string.

### 3.3 ITC ledger detection (multi-signal classifier — Releases 3.1–3.2.1)

Each balance-sheet candidate is classified `input` / `output` / `other` plus a `kind_source` provenance chip via three signals, in priority:

1. **Name** — pattern match on `Input ...`, `Output ...`, `ITC ...`, `Cenvat ...`. Whitespace collapsed (`SGST IN PUT` matches `SGST INPUT`).
2. **Parent group** — Tally users frequently file ledgers under groups like `INPUT CREDIT`, `OUTPUT CREDIT`, `Defrerred Input Credit` (typo preserved) regardless of leaf name.
3. **Voucher usage** — engine walks the daybook and tallies how many *purchase* vs *sales* vouchers each candidate appears on. A 3 : 1 dominance with ≥ 3 appearances flips an otherwise-neutral ledger to `input` (auto-detects bespoke names like `Tax-Cr-Misc-A2`).

**Subhead override:** when name or parent-group strongly signal input/output, the candidate is admitted to the pool **regardless** of whether the auditor mis-mapped its books-XLSX subhead to `Sundry Debtors` / `Trade Receivables` (a real-world recurring mistake).

**Pre-tick rule:** `kind == "input"` AND (legacy subhead match `Balance with Revenue Authorities` / `Statutory Dues Payable` OR voucher-usage tagged input).

**JSON+XLSX union:** the candidate pool draws from BOTH the JSON ledger list and the XLSX mapping — JSON-only ledgers (where the auditor never bothered to map them) still surface for tagging.

### 3.4 Classification cascade (per voucher line — `_classify_single_line`)

For every expenditure line in every voucher, the engine runs this priority cascade:

| Priority | Condition | Bucket | Reason code |
|---|---|---|---|
| 0 | Ledger ∈ `excluded_ledgers` (auditor opt-out) | **Col 8** | `excluded_by_auditor` |
| 1 | `voucherTypeName == "Reverse Charge"` | **Col 7** | `rcm` (`is_rcm = true`) |
| 2 | **Input A** — line's ledger ∈ `exempt_ledgers` | **Col 3** | `input_a_exempt_tag` |
| 3 | Party country set & ≠ India (foreign supplier) | **Col 7** | `import` (`is_import = true`) |
| 4 | `party.gstRegistrationType == "composition"` | **Col 4** | `composition` |
| 5a | `party.gstRegistrationType == "regular"` + GSTIN + `use_itc_inference` ON + voucher has NO ITC ledger | **Col 3** | `input_b_no_itc` |
| 5b | `party.gstRegistrationType == "regular"` + GSTIN + (inference OFF OR ITC ledger present) | **Col 5** | `registered_with_itc` |
| 6 | Everything else (URD, Consumer, blank reg, no party) | **Col 7** | `unregistered_default` |

**Why this order:** ICAI silent on RCM-specific reporting → CA practice puts it in Col 7 separately disclosed. Imports default to Col 7 (no Indian GSTIN). The Input A → Input B fallback mirrors the long-standing CA practice of using ITC availment as a proxy for taxability when explicit exempt tagging isn't done.

### 3.5 Aggregation & per-row attribution

After classification, the engine builds three aggregations:

1. **`summary`** — totals per column (`col2_total`, `col3`–`col8`, `col6 = col3 + col4 + col5`); coverage diagnostic (`itc_coverage_eligible`, `itc_coverage_with_itc`, `itc_coverage_pct`); Col 3 split (`col3_from_input_a`, `col3_from_input_b`); RCM voucher count, imports total.
2. **`by_ledger`** — `{ledger_name: {col3, col4, col5, col7, col8, total}}` — drives the Expense-wise pivot.
3. **`by_party`** — `{party_name: {col3, col4, col5, col7, col8, total, party_gstin, party_reg, vouchers}}` — drives the Party-wise pivot.

Plus a flat `transactions[]` list for voucher-level drill-down.

### 3.6 Reconciliation derivation

When the run is generated, the engine:

1. Sums Col 8 by sub-bucket (auto-detected via ledger name patterns: `Depreciation`, `ECL`, `Tax expense`, `Donation`, `CSR`, `Money`, etc.).
2. Adds capex add-back from `is_capex_ledger` matches.
3. Builds the 5-line table with explicit identity check: `line_1 + line_2 - line_3 - line_4 - line_5 == col2_total ± 1 paisa`.
4. The auditor can override any line's sub-bucket via the dropdown, which re-runs the recon (no re-classification needed).

### 3.7 Coverage diagnostic (Release 3.2)

For every voucher matching:
* `party.gstRegistrationType == "regular"` AND
* `party.partyGSTIN` non-empty AND
* `voucherTypeName != "Reverse Charge"` AND
* `party.country == "India"` (or blank)

Engine increments `cov_eligible`. If the voucher carries any ledger ∈ `itc_selection`, increments `cov_with_itc`. Final `coverage_pct = 100 × cov_with_itc / cov_eligible`. UI banner triggers at `< 70%`.

### 3.8 Auditor-friendly automations

* **First-load auto-tick** — Step 2 pre-ticks every "suggested" ITC ledger; Step 3 pre-ticks every name-hinted exclusion (`Depreciation`, `Bank Charges`, `Tax Expense`, etc.). Both can be reset with one click.
* **Newly-detected fold-in** — when an existing run loads under a new heuristic (e.g. usage-based detection added in 3.2), newly-suggested ledgers silently fold into the saved selection with a toast notification.
* **Output-ledger cleanup** — Output-side ledgers wrongly auto-ticked under the older heuristic are silently removed on first load with a one-time toast: "Removed N Output-side ledger(s) that were auto-ticked under the older heuristic. Re-generate the report to refresh totals."
* **Group-bulk select** — every parent-group row in Step 2 has a one-click "Tick all" / "Untick all" so the auditor can pull in the entire `INPUT CREDIT` branch at once.
* **"Used in vouchers only" toggle** — hides dormant ledgers (often >50% of the BS pool on large datasets).
* **Provenance chips** — every candidate row shows `via name match` / `via group match` / `via voucher usage`, plus telemetry chips (`N purchase · N sales`).

---

## 4 · API surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/clause44/runs` | Upload JSON + XLSX, create run, return suggestions |
| `GET` | `/api/clause44/runs` | List runs (filtered by client / period / archived) |
| `GET` | `/api/clause44/runs/{run_id}` | Return full run incl. summary, by_ledger, by_party, candidates |
| `POST` | `/api/clause44/runs/{run_id}/generate` | Re-classify with current selections; persist `summary`, `by_ledger`, `by_party`, `transactions`, `recon` |
| `PATCH` | `/api/clause44/runs/{run_id}/selections` | Save partial selections (itc, exempt, exclusion, disclaimer, use_itc_inference) |
| `GET` | `/api/clause44/runs/{run_id}/transactions` | Voucher-level drill (filter by ledger / party / bucket) |
| `POST` | `/api/clause44/runs/{run_id}/archive` | Soft-archive (toggle `archived` flag) |
| `GET` | `/api/clause44/runs/{run_id}/export` | Excel workbook (7 sheets) |
| `GET` | `/api/clause44/clients/{client_id}/consolidated` | Multi-period roll-up JSON |
| `GET` | `/api/clause44/clients/{client_id}/consolidated/export` | Multi-period Excel |
| `GET` | `/api/docs/clause-44` | Readme HTML/PDF |

---

## 5 · Data model

### 5.1 `runs` collection

```jsonc
{
  "run_id": "run_0ef0127bba5c",
  "client_id": "cli_ad137f29aebb",
  "client_name": "ABC Textile Mills",
  "period": "2023-24",
  "division": null,
  "created_at": "2026-04-30T10:14:22Z",
  "created_by_email": "ca@firm.in",
  "archived": false,

  "ledgers_xlsx": { /* {name → {bsOrPl, subhead, groupParent, head, closingBalance}} */ },
  "accounting": { /* full Tally JSON: vouchers[], ledgers[], groups[] */ },

  "itc_candidates": [ /* {name, kind, kind_source, suggested, n_purchase, ...} */ ],
  "pl_ledgers":     [ /* {name, suggested} */ ],

  "itc_selection":      [ "Input CGST @ 9%", ... ],
  "exempt_selection":   [ "Petroleum Diesel A/c", ... ],
  "exclusion_selection":[ "Depreciation", "Bank Charges", ... ],
  "use_itc_inference":  true,
  "disclaimer_text":    "We have relied on...",

  "generated":          true,
  "generated_at":       "2026-05-01T08:42:11Z",
  "summary":            { /* col2_total, col3..col8, col6, coverage, ... */ },
  "by_ledger":          { /* {ledger_name → {col3,col4,col5,col7,col8,total}} */ },
  "by_party":           { /* {party_name → {col3..col8, total, party_gstin, party_reg, vouchers}} */ },
  "transactions":       [ /* full voucher-line list */ ],
  "recon":              { /* 5-line ICAI table */ },
  "exclusion_categories": { /* {ledger_name → "non_cash" | "sch3" | ... } */ }
}
```

### 5.2 Indices
* `(client_id, period, archived)` — list view.
* `run_id` (unique).

---

## 6 · Quality bars

* **Identity check** on every generate: `col6 == col3 + col4 + col5` AND `col2_total == col6 + col7 + col8 ± ₹0.01`. Asserts in `_run_classification` raise `500` if violated.
* **Coverage diagnostic** must be present in every summary even when 0 (`cov_eligible == 0` returns `coverage_pct = null`).
* **Cross-client safety:** company-name normalisation rejects mis-uploaded JSONs.
* **Test corpus:** 60 unit tests across `test_clause44_release1.py` → `release3_2.py` (Cascade, Recon, ICAI buckets, multi-signal classifier, voucher usage, coverage diagnostic, mis-mapped subhead override, JSON-only ledger surface). Plus 16 live-HTTP tests on the actual `ABC_Textile_Mills` JSON. **Zero regressions** since Release 1.

---

## 7 · Release ledger (audit trail)

| Release | Date | Headline |
|---|---|---|
| 1 | Apr-26 | ICAI cascade + 5-line recon |
| 2 | Apr-26 | RCM, Imports, Readme rewrite, dummy-client cleanup |
| 3 | May-26 | Custom disclaimer, Col 2 redefined as gross, Col 8 added, all UI 7-columns |
| 3.1 | May-26 | ITC seeding fix — drop Output-side ledgers from auto-tick |
| 3.2 | May-26 | Naming-agnostic ITC detection — multi-signal heuristic + voucher usage + coverage diagnostic + manual-override UI |
| 3.2.1 | May-26 | JSON+XLSX union + subhead override (catches mis-mapped Sundry Debtors) |
| 3.3 | May-26 | Clickable 7-tile KPI strip + bucket-filter pivot |
| 3.4 | May-26 | Readme pill in run wizard + content refresh |
| 3.5 | May-26 | Auto-fit KPI tile font for 9–10 digit aggregates |

---

## 8 · Known limitations & design decisions

1. **No automated GSTIN active/inactive check** — we trust the party master's `gstRegistrationType`. CA verifies on-file separately.
2. **RCM disclosure is engine-classified, not ICAI-mandated** — ICAI is silent; CA practice puts it in Col 7 with an `is_rcm` flag for separate disclosure in working papers.
3. **Composite-supply invoices** — a single voucher line spanning multiple GST treatments has to be split in Tally first; the engine does not apportion.
4. **Capex add-back** — only Tally ledgers under a "Fixed Assets" group chain are detected. Manual capex (e.g. routed through an asset-WIP P&L ledger) needs auditor-explicit exclusion via Step 3.
5. **Single-currency** — INR only. Multi-currency totals would need an FX layer that doesn't exist yet.
6. **RCM tax payable as-purchase** — under §9(3)/9(4), the tax paid under RCM is sometimes booked back as a purchase with a separate ledger; the engine treats those as Col 7 by voucher type. CA practice diverges here; we follow ICAI's silence by disclosing separately.

---

## 9 · Future / backlog

* P1 · Replicate the Readme HTML/PDF + feedback pattern to 43B(h), Fixed Assets, Balance Confirmation, Fin Statement Designer.
* P2 · Save-as-ledger-profile for Step 2 selections (next-year run for the same client pre-ticks the auditor's exact selection automatically).
* P2 · "Filtered view" Excel sheet that exports only the rows currently filtered in the Schedule tab.
* P2 · XLSX mapping audit on upload — flag GST-named ledgers mapped to Sundry Debtors / Trade Payables before the auditor runs Clause 44.
* P3 · Refactor — migrate the page from shadcn/ui to MUI to align with the rest of the app.

---

*Document maintained at `/app/memory/clause44_PRD.md`. Last regenerated: 2026-05-04.*
