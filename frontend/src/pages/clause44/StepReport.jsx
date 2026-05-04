/**
 * Step 4 — Clause 44 Schedule + Reconciliation.
 *
 * Layout:
 *   1. KPI strip (Col 2 · Col 6 · Col 7 aggregate)
 *   2. Classic six-column per-ledger table — read-only pivot that
 *      mirrors the 3CD schedule (restored from legacy UI on user request).
 *   3. Four cohort drill-downs (Col 3, 4, 5, 7) with Expense-wise /
 *      Party-wise tabs & voucher-level popovers.
 *   4. Reconciliation tab ties books → schedule.
 */
import { useMemo, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatINR, formatDate } from "@/lib/format";
import { getTransactions, saveSelections } from "@/lib/api";
import { ACCENTS } from "@/lib/colors";
import { CaretDown, CaretRight, MagnifyingGlass, ChartPieSlice } from "@phosphor-icons/react";
import { toast } from "sonner";
import ReconTable from "@/pages/ReconTable";

// Seven-column pivot cells (Col 2 · Col 3 · Col 4 · Col 5 · Col 6 · Col 7 · Col 8).
// This schema is used identically on the Expense-wise and Party-wise tabs
// so auditors see the full Clause 44 shape wherever they look.
const PIVOT_COLS = [
  { key: "col2_total", label: "Col 2 · Total",         bucket: "col2", accent: "slate" },
  { key: "col3",       label: "Col 3 · Exempt",        bucket: "col3", accent: "emerald" },
  { key: "col4",       label: "Col 4 · Composition",   bucket: "col4", accent: "amber" },
  { key: "col5",       label: "Col 5 · Other Reg.",    bucket: "col5", accent: "emerald" },
  { key: "col6",       label: "Col 6 · Total (3+4+5)", bucket: "col6", accent: "emerald" },
  { key: "col7",       label: "Col 7 · Unregistered",  bucket: "col7", accent: "rose" },
  { key: "col8",       label: "Col 8 · Excluded",      bucket: "col8", accent: "slate" },
];

export default function StepReport({ run }) {
  const col3FromA = run?.summary?.col3_from_input_a || 0;
  const col3FromB = run?.summary?.col3_from_input_b || 0;
  const rcmCount = run?.summary?.rcm_vouchers || 0;
  const importTotal = run?.summary?.import_total || 0;
  const useItcInf = run?.use_itc_inference !== false;
  const col3HasSplit = col3FromA > 0 || col3FromB > 0;

  // Coverage diagnostic — Release 3.2 / option C.  When fewer than 70%
  // of registered-vendor purchase vouchers carried an ITC ledger, we
  // surface a yellow advisory because Input B is almost certainly
  // sweeping value into Col 3 due to mis-tagged ITC ledgers, not real
  // exempt supplies.  Only show when ITC inference is ON (the toggle
  // that drives the issue) and there's a meaningful denominator.
  const covEligible = run?.summary?.itc_coverage_eligible || 0;
  const covWith = run?.summary?.itc_coverage_with_itc || 0;
  const covPct = run?.summary?.itc_coverage_pct;
  const showCoverageBanner = useItcInf && covEligible >= 5 && covPct !== null && covPct < 70;

  return (
    <section className="mx-auto max-w-[1200px]" data-testid="step-report">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 04 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Clause 44 Schedule</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        Review the classic six-column schedule, then drill into any cohort
        to see which expense heads and parties contributed to that bucket.
        Use the <strong>Reconciliation</strong> tab to tie books to schedule
        before you export.
      </p>

      {/* Coverage diagnostic banner — naming-agnostic safety net for
          Release 3.2 / option C.  Yellow advisory shown when registered-
          vendor purchase vouchers don't carry ITC ledger entries — a
          strong indicator the auditor missed tagging some input ledgers. */}
      {showCoverageBanner && (
        <div
          className="mt-4 p-3 bg-amber-50 border border-amber-300 rounded-sm text-[11.5px] text-amber-950 flex items-start gap-2.5"
          data-testid="itc-coverage-banner"
        >
          <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-amber-800 mt-0.5">⚠ Heads up</span>
          <p className="leading-snug flex-1 min-w-0">
            <strong>ITC coverage is low: {covPct}%</strong> ({covWith} of {covEligible} registered-vendor purchase vouchers carry an ITC ledger).
            With ITC inference ON, the remaining {covEligible - covWith} vouchers will route to <span className="font-mono">Col 3</span> (Input B).
            If your client charges GST normally, this usually means some <strong>input-tax ledgers haven't been tagged</strong> on the previous step.
            <button
              onClick={() => window.history.back()}
              className="ml-2 underline font-medium hover:text-amber-700"
              data-testid="coverage-banner-review-link"
            >
              Review ITC selection →
            </button>
          </p>
        </div>
      )}

      {(col3HasSplit || rcmCount > 0 || importTotal > 0) && (
        <div className="mt-4 p-3 bg-[#FAFAF7] border border-[#E5E5E0] rounded-sm text-[11.5px] text-[#52524E] flex flex-wrap gap-x-6 gap-y-1" data-testid="report-info-strip">
          {col3HasSplit && (
            <span data-testid="col3-split">
              <strong>Col 3 split:</strong> Input A ≈ {formatINR(col3FromA)} · Input B ≈ {formatINR(col3FromB)}
              {" "}
              (<em>ITC inference {useItcInf ? "ON" : "OFF"}</em>)
            </span>
          )}
          {rcmCount > 0 && (
            <span data-testid="rcm-chip">
              <strong>RCM:</strong> {rcmCount} vouchers tagged → Col 7
            </span>
          )}
          {importTotal > 0 && (
            <span data-testid="imports-chip">
              <strong>Imports:</strong> {formatINR(importTotal)} → Col 7
            </span>
          )}
        </div>
      )}

      <div className="mt-8">
        <Tabs defaultValue="schedule" className="w-full">
          <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
            <TabsTrigger value="schedule" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-schedule">
              Schedule
            </TabsTrigger>
            <TabsTrigger value="recon" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-recon">
              Reconciliation
            </TabsTrigger>
            <TabsTrigger value="disclaimer" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-disclaimer">
              Disclaimer
            </TabsTrigger>
          </TabsList>
          <TabsContent value="schedule" className="mt-6">
            <Schedule run={run}/>
          </TabsContent>
          <TabsContent value="recon" className="mt-6">
            <ReconTable
              recon={run.recon}
              onUpdateCategory={async (ledgerName, newBucket) => {
                try {
                  const next = { ...(run.exclusion_categories || {}), [ledgerName]: newBucket };
                  await saveSelections(run.run_id, { exclusion_categories: next });
                  toast.success(`Re-categorised '${ledgerName}' — re-generate to refresh totals`);
                } catch {
                  toast.error("Failed to save category");
                }
              }}
            />
          </TabsContent>
          <TabsContent value="disclaimer" className="mt-6">
            <DisclaimerEditor run={run}/>
          </TabsContent>
        </Tabs>
      </div>
    </section>
  );
}

/* ────────────── Schedule tab — KPI + Unified 7-col Expense / Party views ────────── */
function Schedule({ run }) {
  const summary = run?.summary || {};
  const col2 = summary.col2_total || 0;
  const col6 = summary.col6 || 0;
  const col7 = summary.col7 || 0;
  const col8 = summary.col8 || 0;

  // Ledger rows — one per expense head, with all 7 column values.
  const ledgerRows = useMemo(() => {
    if (!run?.by_ledger) return [];
    return Object.entries(run.by_ledger).map(([name, v]) => {
      const col3 = v.col3 || 0;
      const col4 = v.col4 || 0;
      const col5 = v.col5 || 0;
      const col7 = v.col7 || 0;
      const col8 = v.col8 || 0;
      const total = v.total != null ? v.total : col3 + col4 + col5 + col7 + col8;
      return {
        name,
        col3, col4, col5, col7, col8,
        col6: col3 + col4 + col5,
        col2_total: total,
      };
    }).sort((a, b) => b.col2_total - a.col2_total);
  }, [run]);

  // Party rows — one per vendor, with all 7 column values.
  const partyRows = useMemo(() => {
    if (!run?.by_party) return [];
    return Object.entries(run.by_party).map(([name, v]) => {
      const col3 = v.col3 || 0;
      const col4 = v.col4 || 0;
      const col5 = v.col5 || 0;
      const col7 = v.col7 || 0;
      const col8 = v.col8 || 0;
      const total = v.total != null ? v.total : col3 + col4 + col5 + col7 + col8;
      return {
        name,
        col3, col4, col5, col7, col8,
        col6: col3 + col4 + col5,
        col2_total: total,
        gstin: v.party_gstin || "",
        reg: v.party_reg || "",
        vouchers: Number(v.vouchers || 0),
      };
    }).sort((a, b) => b.col2_total - a.col2_total);
  }, [run]);

  return (
    <div data-testid="schedule-view">
      {/* Aggregate KPI strip — 4 tiles: Col 2 · Col 6 · Col 7 · Col 8 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden mb-6">
        <KPI label="Col 2 · Total expenditure (books)" amt={col2} accent="slate" testid="kpi-col2"/>
        <KPI label="Col 6 · Aggregate registered (3+4+5)" amt={col6} accent="emerald" testid="kpi-col6"/>
        <KPI label="Col 7 · Unregistered" amt={col7} accent="rose" testid="kpi-col7"/>
        <KPI label="Col 8 · Excluded" amt={col8} accent="slate" testid="kpi-col8"/>
      </div>

      {/* ── Unified 7-column pivot with Expense-wise / Party-wise tabs ── */}
      <div className="border border-[#E5E5E0] rounded-sm bg-white" data-testid="unified-pivot-block">
        <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
          <ChartPieSlice size={14} className="text-[#52524E]"/>
          <h3 className="font-heading text-base">Clause 44 Breakup</h3>
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]">Seven-column pivot · click any row to drill to vouchers</span>
        </div>
        <Tabs defaultValue="expense" className="w-full">
          <div className="px-4 pt-3">
            <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
              <TabsTrigger value="expense" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-expense">
                Expense-wise
              </TabsTrigger>
              <TabsTrigger value="party" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-party">
                Party-wise
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="expense" className="mt-0">
            <UnifiedPivot
              rows={ledgerRows} summary={summary}
              headerLabel="Ledger" kind="ledger" runId={run.run_id}
            />
          </TabsContent>
          <TabsContent value="party" className="mt-0">
            <UnifiedPivot
              rows={partyRows} summary={summary}
              headerLabel="Party" kind="party" runId={run.run_id}
              extraCols={[
                { key: "gstin", label: "GSTIN / Reg", align: "left", renderer: (r) => (
                  <span>
                    {r.gstin ? <span className="font-mono text-[10.5px]">{r.gstin}</span> : <em className="text-[#8A8A83] text-[11px]">no GSTIN</em>}
                    {r.reg && <span className="font-mono text-[10px] text-[#8A8A83] uppercase ml-2">{r.reg}</span>}
                  </span>
                ) },
                { key: "vouchers", label: "Vouchers", align: "right", renderer: (r) => r.vouchers || 0 },
              ]}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

/* Unified 7-column pivot — one row per ledger or per party.  Click a
   row to expand a sub-drawer with voucher-level detail (across all 7
   columns). */
function UnifiedPivot({ rows, summary, headerLabel, kind, runId, extraCols = [] }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState({}); // { rowName: { loading, txns } }
  const s = summary || {};
  const filtered = useMemo(() => {
    const q2 = q.trim().toLowerCase();
    return q2 ? rows.filter((r) => r.name.toLowerCase().includes(q2)) : rows;
  }, [rows, q]);

  const expand = async (rowName) => {
    setOpen((o) => {
      if (o[rowName]) { const n = { ...o }; delete n[rowName]; return n; }
      return { ...o, [rowName]: { loading: true, txns: null } };
    });
    if (open[rowName]) return;  // was a close
    try {
      const data = kind === "party"
        ? await getTransactions(runId, null, null, rowName)
        : await getTransactions(runId, null, rowName, null);
      setOpen((o) => ({ ...o, [rowName]: { loading: false, txns: data?.transactions || [] } }));
    } catch {
      toast.error("Failed to load transactions");
      setOpen((o) => { const n = { ...o }; delete n[rowName]; return n; });
    }
  };

  return (
    <div className="w-full" data-testid={`unified-pivot-${kind}`}>
      <div className="px-4 py-2.5 border-t border-b border-[#E5E5E0] flex items-center gap-2 flex-wrap bg-[#FAFAF7]">
        <div className="flex items-center gap-2 border border-[#E5E5E0] rounded-sm px-2 h-8 w-full sm:w-72 bg-white">
          <MagnifyingGlass size={12} className="text-[#8A8A83]"/>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Filter ${kind === "party" ? "party" : "ledger"}…`}
            className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-xs"
            data-testid={`pivot-search-${kind}`}
          />
        </div>
        <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none ml-auto">
          {filtered.length} rows
        </Badge>
      </div>
      <div className="overflow-x-auto max-h-[520px] overflow-y-auto">
        <table className="fiscal-table w-full" data-testid={`pivot-table-${kind}`}>
          <thead className="sticky top-0 z-10 bg-[#F3F4F1]">
            <tr>
              <th className="w-6"></th>
              <th className="min-w-[240px]">{headerLabel}</th>
              {extraCols.map((c) => (
                <th key={c.key} className={c.align === "right" ? "text-right whitespace-nowrap" : "whitespace-nowrap"}>{c.label}</th>
              ))}
              {PIVOT_COLS.map((c) => (
                <th key={c.key} className="text-right whitespace-nowrap">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={PIVOT_COLS.length + 2 + extraCols.length} className="text-center py-10 text-[#8A8A83] text-sm">No rows in this view.</td></tr>
            )}
            {filtered.map((row) => {
              const isOpen = !!open[row.name];
              const info = open[row.name];
              return (
                <FragmentRow
                  key={row.name} row={row} isOpen={isOpen} info={info}
                  onExpand={() => expand(row.name)}
                  kind={kind} extraCols={extraCols}
                />
              );
            })}
          </tbody>
          {filtered.length > 0 && (
            <tfoot>
              <tr className="bg-[#F3F4F1]">
                <td></td>
                <td className="font-medium">Aggregate</td>
                {extraCols.map((c) => <td key={c.key}/>) }
                {PIVOT_COLS.map((c) => (
                  <td key={c.key} className="cell-num font-medium">{formatINR(s[c.key])}</td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

function FragmentRow({ row, isOpen, info, onExpand, kind, extraCols }) {
  return (
    <>
      <tr
        data-testid={`pivot-row-${kind}-${encodeURIComponent(row.name)}`}
        className="cursor-pointer hover:bg-[#F9F9F8]"
        onClick={onExpand}
      >
        <td className="text-[#8A8A83]">
          {isOpen ? <CaretDown size={11}/> : <CaretRight size={11}/>}
        </td>
        <td className="font-medium text-[13px]">{row.name}</td>
        {extraCols.map((c) => (
          <td key={c.key} className={c.align === "right" ? "cell-num text-[12px]" : ""}>
            {c.renderer ? c.renderer(row) : row[c.key]}
          </td>
        ))}
        {PIVOT_COLS.map((c) => {
          const v = row[c.key] || 0;
          return (
            <td key={c.key} className={`cell-num ${v === 0 ? "text-[#8A8A83]" : ""}`} data-testid={`pivot-cell-${kind}-${c.bucket}-${encodeURIComponent(row.name)}`}>
              {formatINR(v)}
            </td>
          );
        })}
      </tr>
      {isOpen && (
        <tr className="bg-[#FAFAF7]" data-testid={`pivot-drill-${kind}-${encodeURIComponent(row.name)}`}>
          <td colSpan={PIVOT_COLS.length + 2 + extraCols.length} className="p-0">
            <DrillDrawer info={info}/>
          </td>
        </tr>
      )}
    </>
  );
}

function DrillDrawer({ info }) {
  if (!info) return null;
  if (info.loading) {
    return <div className="px-6 py-4 font-mono text-[11px] text-[#8A8A83]">Loading vouchers…</div>;
  }
  const txns = info.txns || [];
  if (txns.length === 0) {
    return <div className="px-6 py-4 font-mono text-[11px] text-[#8A8A83]">No vouchers matched.</div>;
  }
  return (
    <div className="px-4 py-3 border-t border-[#E5E5E0]">
      <div className="overflow-x-auto">
        <table className="fiscal-table w-full text-[12px]">
          <thead>
            <tr>
              <th>Date</th><th>Type</th><th>Voucher No</th><th>Ledger</th><th>Party</th>
              <th className="text-right">Amount</th><th>Bucket</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {txns.map((t, i) => (
              <tr key={`${t.voucher_id || ""}-${i}`}>
                <td>{formatDate(t.date)}</td>
                <td>{t.voucher_type || ""}</td>
                <td className="font-mono text-[11px]">{t.voucher_number || ""}</td>
                <td>{t.ledger_name || ""}</td>
                <td>{t.party_name || "—"}</td>
                <td className="cell-num">{formatINR(t.amount || 0)}</td>
                <td>
                  <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-[#52524E] px-1.5 py-0.5 bg-[#F3F4F1] rounded-sm">{(t.bucket || "").replace("col","Col ")}</span>
                </td>
                <td className="text-[11px] text-[#52524E] max-w-[340px]">{t.reason || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ────────────── KPI tile for the Schedule header strip ─────────────── */
function KPI({ label, amt, accent, testid }) {
  const a = ACCENTS[accent] || ACCENTS.slate;
  return (
    <div className={`${a.bg} px-4 py-3`} style={{ borderTop: `2px solid ${a.fg}` }} data-testid={testid}>
      <div className={`font-mono text-[10px] uppercase tracking-[0.12em] ${a.text}`}>{label}</div>
      <div className="mt-1.5 num text-[20px] tracking-tight font-medium">{formatINR(amt)}</div>
    </div>
  );
}


/* ─────────────────── Disclaimer editor (tab 3) ───────────────────────── */
function DisclaimerEditor({ run }) {
  const [text, setText] = useState(run?.disclaimer_text || "");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await saveSelections(run.run_id, { disclaimer_text: text });
      setDirty(false);
      toast.success("Disclaimer saved — will be stamped on the next Excel export");
    } catch {
      toast.error("Failed to save disclaimer");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setText(run?.disclaimer_text || "");
    setDirty(false);
  };

  return (
    <div className="border border-[#E5E5E0] bg-white rounded-sm p-6 max-w-3xl" data-testid="disclaimer-editor-block">
      <h3 className="font-heading text-lg tracking-tight">Working-paper Disclaimer</h3>
      <p className="mt-2 text-[12.5px] text-[#52524E] leading-snug max-w-2xl">
        Per <strong>ICAI Guidance Note Para 79.21</strong>, where the underlying books
        don't carry complete nature-of-supply / ITC-eligibility data, the tax auditor
        should attach a qualified disclosure.  The text below is stamped into the
        Reconciliation sheet of every Excel export.  Edit per client, then save.
      </p>
      <textarea
        value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); }}
        rows={10}
        className="mt-4 w-full font-mono text-[12.5px] border border-[#D4D4D0] rounded-sm p-3 focus-visible:ring-1 focus-visible:ring-[#0F172A] focus-visible:outline-none leading-relaxed"
        data-testid="disclaimer-textarea"
      />
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={save}
          disabled={!dirty || saving}
          data-testid="disclaimer-save"
          className="h-9 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none font-mono text-[10.5px] uppercase tracking-[0.12em] disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save disclaimer"}
        </button>
        {dirty && (
          <button
            onClick={reset}
            data-testid="disclaimer-reset"
            className="h-9 px-3 font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] hover:text-[#991B1B]"
          >
            Discard changes
          </button>
        )}
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]" data-testid="disclaimer-state">
          {dirty ? "Unsaved edits" : "In sync"}
        </span>
      </div>
    </div>
  );
}
