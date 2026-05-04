/**
 * Step 4 — Clause 44 Schedule + Reconciliation.
 *
 * No more drill-down pop-up — each cohort tile (Col 3-7) expands inline,
 * revealing an [ Expense-wise | Party-wise ] tab strip.  Clicking a row in
 * either tab lazy-loads the individual vouchers for that (bucket × ledger)
 * or (bucket × party).
 */
import { useMemo, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatINR, formatDate } from "@/lib/format";
import { getTransactions } from "@/lib/api";
import { ACCENTS, COL_ACCENTS } from "@/lib/colors";
import { CaretDown, CaretRight, MagnifyingGlass, ArrowUp, ArrowDown } from "@phosphor-icons/react";
import { toast } from "sonner";
import ReconTable from "@/pages/ReconTable";

const COHORTS = [
  { key: "col3", label: "Col 3 · Exempt supply",          desc: "Registered party (with GSTIN), exempt supply" },
  { key: "col4", label: "Col 4 · Composition",            desc: "Vendor is a Composition dealer" },
  { key: "col5", label: "Col 5 · Other Registered (ITC)", desc: "Voucher carries an ITC ledger entry" },
  { key: "col7", label: "Col 7 · Unregistered",           desc: "No GSTIN / consumer / no party" },
];

export default function StepReport({ run }) {
  return (
    <section className="mx-auto max-w-[1200px]" data-testid="step-report">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 04 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Clause 44 Schedule</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        Drill into any cohort — amount is split across the expense head
        (what was bought) and the party (who it was bought from). Clicking
        a line unveils the underlying voucher transactions. Use the
        <strong> Reconciliation</strong> tab to tie books to schedule before
        you export.
      </p>

      <div className="mt-8">
        <Tabs defaultValue="schedule" className="w-full">
          <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
            <TabsTrigger value="schedule" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-schedule">
              Schedule
            </TabsTrigger>
            <TabsTrigger value="recon" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-recon">
              Reconciliation
            </TabsTrigger>
          </TabsList>
          <TabsContent value="schedule" className="mt-6">
            <Schedule run={run}/>
          </TabsContent>
          <TabsContent value="recon" className="mt-6">
            <ReconTable recon={run.recon}/>
          </TabsContent>
        </Tabs>
      </div>
    </section>
  );
}

/* ─────────────────── Schedule tab — 4 expandable cohort rows ────────── */
function Schedule({ run }) {
  const summary = run?.summary || {};
  const [open, setOpen] = useState(null); // "col3" | ... | null

  // Header KPIs
  const col2 = summary.col2_total || 0;
  const col6 = summary.col6 || 0;

  return (
    <div data-testid="schedule-view">
      {/* Aggregate strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden mb-6">
        <KPI label="Col 2 · Total expenditure" amt={col2} accent="slate"/>
        <KPI label="Col 6 · Aggregate registered (3+4+5)" amt={col6} accent="emerald"/>
        <KPI label="Col 7 · Unregistered" amt={summary.col7 || 0} accent="rose"/>
      </div>

      {/* 4 cohort rows */}
      <div className="border border-[#E5E5E0] rounded-sm bg-white divide-y divide-[#E5E5E0]">
        {COHORTS.map((c) => {
          const amt = summary[c.key] || 0;
          const a = ACCENTS[COL_ACCENTS[c.key]] || ACCENTS.slate;
          const isOpen = open === c.key;
          const pct = col2 > 0 ? (amt / col2) * 100 : 0;
          return (
            <div key={c.key} data-testid={`cohort-row-${c.key}`}>
              <button
                className="w-full flex items-center gap-4 px-5 py-4 hover:bg-[#FAFAF7] text-left"
                onClick={() => setOpen(isOpen ? null : c.key)}
                data-testid={`cohort-toggle-${c.key}`}
              >
                {isOpen ? <CaretDown size={14} weight="bold" className={a.text}/> : <CaretRight size={14} weight="bold" className="text-[#8A8A83]"/>}
                <div className="flex-1">
                  <div className={`font-mono text-[11px] uppercase tracking-[0.12em] ${a.text}`}>{c.label}</div>
                  <div className="text-[11px] text-[#52524E] mt-0.5">{c.desc}</div>
                </div>
                <div className="text-right">
                  <div className="num text-[18px] tracking-tight font-medium">{formatINR(amt)}</div>
                  <div className="font-mono text-[10px] text-[#8A8A83]">{pct.toFixed(1)}% of Col 2</div>
                </div>
              </button>
              {isOpen && <CohortBody run={run} cohort={c.key}/>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KPI({ label, amt, accent }) {
  const a = ACCENTS[accent] || ACCENTS.slate;
  return (
    <div className={`${a.bg} px-4 py-3`} style={{ borderTop: `2px solid ${a.fg}` }}>
      <div className={`font-mono text-[10px] uppercase tracking-[0.12em] ${a.text}`}>{label}</div>
      <div className="mt-1.5 num text-[20px] tracking-tight font-medium">{formatINR(amt)}</div>
    </div>
  );
}

/* ─────────────────── Cohort body — Expense-wise / Party-wise ────────── */
function CohortBody({ run, cohort }) {
  return (
    <div className="bg-[#FAFAF7] px-5 py-4 border-t border-[#E5E5E0]" data-testid={`cohort-body-${cohort}`}>
      <Tabs defaultValue="expense" className="w-full">
        <TabsList className="bg-white border border-[#E5E5E0] rounded-sm p-1 h-auto">
          <TabsTrigger value="expense" className="font-mono text-[10.5px] uppercase tracking-[0.12em] data-[state=active]:bg-[#0F172A] data-[state=active]:text-white" data-testid={`cohort-${cohort}-tab-expense`}>
            Expense-wise
          </TabsTrigger>
          <TabsTrigger value="party" className="font-mono text-[10.5px] uppercase tracking-[0.12em] data-[state=active]:bg-[#0F172A] data-[state=active]:text-white" data-testid={`cohort-${cohort}-tab-party`}>
            Party-wise
          </TabsTrigger>
        </TabsList>
        <TabsContent value="expense" className="mt-3">
          <ExpenseBreakup run={run} cohort={cohort}/>
        </TabsContent>
        <TabsContent value="party" className="mt-3">
          <PartyBreakup run={run} cohort={cohort}/>
        </TabsContent>
      </Tabs>
    </div>
  );
}

/* ─────────── Expense-wise (derived from run.by_ledger × cohort) ─────── */
function ExpenseBreakup({ run, cohort }) {
  const rows = useMemo(() => {
    const items = Object.entries(run?.by_ledger || {})
      .map(([name, v]) => ({ name, amt: Number(v?.[cohort] || 0) }))
      .filter((r) => r.amt > 0)
      .sort((a, b) => b.amt - a.amt);
    return items;
  }, [run, cohort]);
  return (
    <BreakupTable
      rows={rows}
      kind="expense"
      headerLabel="Expense head"
      cohort={cohort}
      runId={run.run_id}
      fetchKey="ledger"
    />
  );
}

/* ─────────── Party-wise (derived from run.by_party × cohort) ────────── */
function PartyBreakup({ run, cohort }) {
  const rows = useMemo(() => {
    return Object.entries(run?.by_party || {})
      .map(([name, v]) => ({
        name,
        amt: Number(v?.[cohort] || 0),
        gstin: v?.party_gstin || "",
        reg: v?.party_reg || "",
        vouchers: Number(v?.vouchers || 0),
      }))
      .filter((r) => r.amt > 0)
      .sort((a, b) => b.amt - a.amt);
  }, [run, cohort]);
  if (!run?.by_party) {
    return (
      <div className="p-6 text-sm text-[#8A8A83] bg-white border border-dashed border-[#D4D4D0] rounded-sm">
        Party-wise breakup isn't available on this run. Re-run the classification to populate it.
      </div>
    );
  }
  return (
    <BreakupTable
      rows={rows}
      kind="party"
      headerLabel="Party"
      cohort={cohort}
      runId={run.run_id}
      fetchKey="party"
    />
  );
}

/* ─────────── Generic breakup table with drill to vouchers ───────────── */
function BreakupTable({ rows, kind, headerLabel, cohort, runId, fetchKey }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("amt-desc");
  const [drill, setDrill] = useState({}); // { rowName: { loading, txns } }

  const filtered = useMemo(() => {
    const q2 = q.trim().toLowerCase();
    let list = q2 ? rows.filter((r) => r.name.toLowerCase().includes(q2)) : rows;
    if (sort === "amt-desc") list = [...list].sort((a, b) => b.amt - a.amt);
    else if (sort === "amt-asc") list = [...list].sort((a, b) => a.amt - b.amt);
    else if (sort === "name") list = [...list].sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }, [rows, q, sort]);

  const total = rows.reduce((a, b) => a + b.amt, 0);

  const toggle = async (name) => {
    setDrill((d) => {
      if (d[name]) { const n = { ...d }; delete n[name]; return n; }
      return { ...d, [name]: { loading: true, txns: null } };
    });
    // Already drilled? toggle was a close — no fetch needed.
    if (drill[name]) return;
    try {
      const params = fetchKey === "party"
        ? { party: name }
        : { ledger: name };
      const data = await getTransactions(runId, cohort, params.ledger, params.party);
      setDrill((d) => ({ ...d, [name]: { loading: false, txns: data?.transactions || [] } }));
    } catch {
      toast.error("Failed to load transactions");
      setDrill((d) => { const n = { ...d }; delete n[name]; return n; });
    }
  };

  return (
    <div className="bg-white border border-[#E5E5E0] rounded-sm" data-testid={`${kind}-breakup-${cohort}`}>
      <div className="px-3 py-2 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-1 min-w-[180px] border border-[#E5E5E0] rounded-sm px-2 h-8">
          <MagnifyingGlass size={12} className="text-[#8A8A83]"/>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Filter ${kind}…`} className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-xs"/>
        </div>
        <button
          onClick={() => setSort(sort === "amt-desc" ? "amt-asc" : sort === "amt-asc" ? "name" : "amt-desc")}
          className="font-mono text-[10px] uppercase tracking-[0.1em] text-[#52524E] hover:text-[#0F172A] inline-flex items-center gap-1"
          data-testid={`${kind}-sort-${cohort}`}
        >
          {sort === "amt-desc" && <><ArrowDown size={10}/> Amount</>}
          {sort === "amt-asc" && <><ArrowUp size={10}/> Amount</>}
          {sort === "name" && <>A–Z</>}
        </button>
        <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
          {filtered.length} / Σ {formatINR(total)}
        </Badge>
      </div>
      <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
        <table className="fiscal-table w-full">
          <thead className="sticky top-0 z-10 bg-[#F3F4F1]">
            <tr>
              <th className="w-6"></th>
              <th className="min-w-[220px]">{headerLabel}</th>
              {kind === "party" && <th className="whitespace-nowrap">Reg / GSTIN</th>}
              {kind === "party" && <th className="text-right">Vouchers</th>}
              <th className="text-right">Amount</th>
              <th className="text-right">%</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={kind === "party" ? 6 : 4} className="text-center py-8 text-[#8A8A83] text-sm">No entries for this cohort.</td></tr>
            )}
            {filtered.map((r) => {
              const pct = total > 0 ? (r.amt / total) * 100 : 0;
              const isOpen = !!drill[r.name];
              const info = drill[r.name];
              return (
                <>
                  <tr key={r.name} data-testid={`${kind}-row-${cohort}-${encodeURIComponent(r.name)}`} className="cursor-pointer hover:bg-[#F9F9F8]" onClick={() => toggle(r.name)}>
                    <td>{isOpen ? <CaretDown size={11}/> : <CaretRight size={11}/>}</td>
                    <td className="font-medium text-[13px]">{r.name}</td>
                    {kind === "party" && (
                      <td>
                        {r.gstin ? <span className="font-mono text-[10.5px]">{r.gstin}</span> : <em className="text-[#8A8A83] text-[11px]">no GSTIN</em>}
                        {r.reg && <div className="text-[10px] text-[#8A8A83] uppercase">{r.reg}</div>}
                      </td>
                    )}
                    {kind === "party" && <td className="cell-num text-[12px]">{r.vouchers}</td>}
                    <td className="cell-num text-[13px]">{formatINR(r.amt)}</td>
                    <td className="cell-num text-[11px] text-[#52524E]">{pct.toFixed(1)}%</td>
                  </tr>
                  {isOpen && (
                    <tr key={`${r.name}-drill`} data-testid={`${kind}-drill-${cohort}-${encodeURIComponent(r.name)}`}>
                      <td colSpan={kind === "party" ? 6 : 4} className="bg-[#F9F9F8] p-0">
                        {info?.loading ? (
                          <div className="px-4 py-4 font-mono text-[11px] text-[#8A8A83]">Loading transactions…</div>
                        ) : info?.txns?.length === 0 ? (
                          <div className="px-4 py-4 font-mono text-[11px] text-[#8A8A83]">No vouchers to show.</div>
                        ) : (
                          <div className="max-h-[280px] overflow-y-auto">
                            <table className="fiscal-table w-full text-[11.5px]">
                              <thead className="bg-[#EDEDE8]">
                                <tr>
                                  <th>Date</th>
                                  <th>Voucher</th>
                                  <th>{kind === "party" ? "Ledger" : "Party"}</th>
                                  <th className="text-right">Amount</th>
                                  <th>Reason</th>
                                </tr>
                              </thead>
                              <tbody>
                                {info?.txns?.map((t, i) => (
                                  <tr key={`${t.voucher_id}_${i}`}>
                                    <td className="num">{formatDate(t.date)}</td>
                                    <td className="num">{t.voucher_type}<div className="text-[10px] text-[#8A8A83]">{t.voucher_number}</div></td>
                                    <td className="max-w-[180px] truncate">{kind === "party" ? t.ledger_name : (t.party_name || <em className="text-[#8A8A83]">—</em>)}</td>
                                    <td className="cell-num">{formatINR(t.amount)}</td>
                                    <td className="text-[10.5px] text-[#52524E] max-w-[260px]">{t.reason}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
