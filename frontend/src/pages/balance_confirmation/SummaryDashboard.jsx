/**
 * Balance Confirmation — Analytics Dashboard.
 *
 * Driven entirely by GET /balance-confirmation/runs/{rid}/analytics.
 * Layout (vertical):
 *   1. Hero KPIs · Total parties · Total exposure · Coverage (count + amount)
 *   2. Category Matrix  — 4 cards: Rec / Pay / Bank / Unsecured Loans
 *   3. Confirmation Funnel + Status Donut
 *   4. Top Disputed & Top Unresponsive (2 col)
 *   5. Subhead Coverage Heatmap
 *
 * The Summary XLSX + PDF exports live in the dashboard header.
 */
import React, { useEffect, useMemo, useState } from "react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import {
  AlertTriangle, CheckCircle2, Clock, Download, FileText, Loader2,
  RefreshCw, Send, XOctagon,
} from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

/* ========================= Formatting helpers =========================== */
const inr = (v) => {
  const n = Number(v || 0);
  if (!Number.isFinite(n) || n === 0) return "–";
  return Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  });
};
const inrCompact = (v) => {
  const n = Math.abs(Number(v || 0));
  if (!n) return "₹0";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`;
  return `₹${n.toFixed(0)}`;
};
const pct = (v) => `${Number(v || 0).toFixed(1)}%`;

/* ========================= Status palette =============================== */
const STATUS = {
  confirmed:  { label: "Confirmed",  bg: "#D1FAE5", fg: "#065F46", solid: "#059669", icon: CheckCircle2 },
  reconciled: { label: "Reconciled", bg: "#CFFAFE", fg: "#0E7490", solid: "#0891B2", icon: CheckCircle2 },
  disputed:   { label: "Disputed",   bg: "#FEF3C7", fg: "#92400E", solid: "#D97706", icon: AlertTriangle },
  in_flight:  { label: "In flight",  bg: "#DBEAFE", fg: "#1E40AF", solid: "#2563EB", icon: Send },
  failed:     { label: "Failed",     bg: "#FEE2E2", fg: "#991B1B", solid: "#DC2626", icon: XOctagon },
  not_sent:   { label: "Not sent",   bg: "#F3F4F6", fg: "#4B5563", solid: "#6B7280", icon: Clock },
};
const STATUS_ORDER = ["confirmed", "reconciled", "disputed", "in_flight", "failed", "not_sent"];

const CAT_ACCENT = {
  trade_receivable: { bar: "from-emerald-500 to-emerald-600", ring: "ring-emerald-200", chip: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  trade_payable:    { bar: "from-amber-500 to-amber-600",     ring: "ring-amber-200",   chip: "bg-amber-50 text-amber-800 border-amber-200" },
  bank:             { bar: "from-indigo-500 to-indigo-600",   ring: "ring-indigo-200",  chip: "bg-indigo-50 text-indigo-800 border-indigo-200" },
  unsecured_loans:  { bar: "from-slate-500 to-slate-600",     ring: "ring-slate-200",   chip: "bg-slate-50 text-slate-700 border-slate-200" },
  other:            { bar: "from-gray-400 to-gray-500",       ring: "ring-gray-200",    chip: "bg-gray-50 text-gray-700 border-gray-200" },
};

/* ========================= Top-level component ========================== */
export default function SummaryDashboard({ rid }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    if (!rid) return;
    setLoading(true);
    http.get(`/balance-confirmation/runs/${rid}/analytics`)
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(e?.response?.data?.detail || "Could not load analytics"))
      .finally(() => setLoading(false));
  };
  useEffect(refresh, [rid]);

  const download = async (kind /* xlsx | pdf */) => {
    setBusy(true);
    try {
      const res = await http.get(`/balance-confirmation/runs/${rid}/summary.${kind}`, { responseType: "blob" });
      const cd = res.headers["content-disposition"] || "";
      const m = cd.match(/filename="(.+?)"/);
      const a = document.createElement("a");
      a.href = window.URL.createObjectURL(new Blob([res.data]));
      a.download = m ? m[1] : `BalanceConfirmation_Summary.${kind}`;
      document.body.appendChild(a); a.click(); a.remove();
      toast.success(`${kind.toUpperCase()} downloaded`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Download failed");
    } finally { setBusy(false); }
  };

  if (loading && !data) {
    return (
      <div className="bg-white border border-gray-200 rounded-sm p-16 flex flex-col items-center justify-center text-sm text-gray-500">
        <Loader2 size={18} className="animate-spin mb-3"/> Loading analytics…
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-6" data-testid="bc-dashboard">
      <DashboardHeader data={data} onRefresh={refresh} onDownload={download} busy={busy}/>
      <HeroKPIs overall={data.overall} reconciledCount={data.reconciled_count}/>
      <CategoryMatrix categories={data.categories}/>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <div className="lg:col-span-3 bg-white border border-gray-200 rounded-sm p-5" data-testid="bc-funnel-card">
          <SectionTitle eyebrow="Response journey" title="Confirmation Funnel"
            hint="Drop-off across every stage, weighted by ₹ exposure"/>
          <FunnelPanel funnel={data.funnel}/>
        </div>
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-sm p-5" data-testid="bc-status-donut">
          <SectionTitle eyebrow="Portfolio breakdown" title="Status by ₹ exposure"
            hint="Amount-weighted — audit's materiality lens"/>
          <StatusDonut overall={data.overall}/>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <TopDisputed rows={data.top_disputed}/>
        <TopUnresponsive rows={data.top_unresponsive}/>
      </div>
      <SubheadHeatmap rows={data.subheads}/>
      <Footnote generated={data.generated_at}/>
    </div>
  );
}

/* ========================= Header with downloads ======================== */
function DashboardHeader({ data, onRefresh, onDownload, busy }) {
  return (
    <div className="bg-white border border-gray-200 rounded-sm p-5 flex flex-wrap items-start justify-between gap-4" data-testid="bc-dashboard-header">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Audit working-paper</div>
        <h2 className="font-heading text-xl mt-1">Confirmation Summary · {data.run?.fy}</h2>
        <div className="text-xs text-gray-500 mt-1">
          {data.client?.name || "—"}
          {data.client?.gstin ? ` · GSTIN ${data.client.gstin}` : ""} · as at {data.run?.as_at_date || "—"}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button onClick={onRefresh} disabled={busy}
          className="text-xs px-3 h-9 rounded-sm border border-gray-300 inline-flex items-center gap-1.5 hover:bg-gray-50 disabled:opacity-40"
          data-testid="bc-dashboard-refresh">
          <RefreshCw size={12}/> Refresh
        </button>
        <button onClick={() => onDownload("xlsx")} disabled={busy}
          className="text-xs px-3 h-9 rounded-sm border border-emerald-700 bg-white text-emerald-800 hover:bg-emerald-50 inline-flex items-center gap-1.5 disabled:opacity-40"
          data-testid="bc-summary-xlsx">
          <Download size={12}/> Summary XLSX
        </button>
        <button onClick={() => onDownload("pdf")} disabled={busy}
          className="text-xs px-3 h-9 rounded-sm border border-emerald-700 bg-emerald-700 text-white hover:bg-emerald-800 inline-flex items-center gap-1.5 disabled:opacity-40"
          data-testid="bc-summary-pdf">
          <FileText size={12}/> Summary PDF
        </button>
      </div>
    </div>
  );
}

/* ========================= Row 1 · Hero KPIs ============================ */
function HeroKPIs({ overall, reconciledCount }) {
  const cov = overall?.coverage || {};
  const responded = (overall?.by_status?.confirmed?.count || 0)
                  + (overall?.by_status?.reconciled?.count || 0)
                  + (overall?.by_status?.disputed?.count || 0);
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="bc-hero">
      <HeroCard
        label="Total parties"
        value={String(overall?.count || 0)}
        sub={`${responded} responses received`}
        tone="slate"/>
      <HeroCard
        label="Total exposure"
        value={inrCompact(overall?.amount || 0)}
        sub={`Sum of |closing balance|`}
        tone="emerald"
        primary/>
      <HeroCard
        label="Audit coverage · by count"
        value={pct(cov.audit_count_pct)}
        sub={`${reconciledCount} reconciled + confirmed`}
        tone="blue"
        progress={cov.audit_count_pct || 0}/>
      <HeroCard
        label="Audit coverage · by ₹"
        value={pct(cov.audit_amount_pct)}
        sub={`Response rate ${pct(cov.response_amount_pct)}`}
        tone="teal"
        progress={cov.audit_amount_pct || 0}
        accent/>
    </div>
  );
}

function HeroCard({ label, value, sub, tone = "slate", progress = null, primary = false, accent = false }) {
  const TONE = {
    slate:   "bg-white border-gray-200",
    emerald: "bg-gradient-to-br from-emerald-50 to-emerald-100/40 border-emerald-200",
    blue:    "bg-gradient-to-br from-sky-50 to-sky-100/40 border-sky-200",
    teal:    "bg-gradient-to-br from-teal-50 to-emerald-100/40 border-teal-300",
  };
  return (
    <div className={`border rounded-sm p-5 ${TONE[tone]} ${accent ? "ring-2 ring-emerald-400/40" : ""}`}
         data-testid={`bc-hero-${label.replace(/[^a-z]/gi, "-").toLowerCase()}`}>
      <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-gray-500">{label}</div>
      <div className={`font-heading mt-1.5 ${primary ? "text-3xl" : "text-2xl"}`}>{value}</div>
      {progress !== null && (
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mt-3">
          <div className="h-full bg-gradient-to-r from-emerald-500 to-emerald-600"
               style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}/>
        </div>
      )}
      <div className="text-[11px] font-mono text-gray-500 mt-2">{sub}</div>
    </div>
  );
}

/* ========================= Row 2 · Category Matrix ====================== */
function CategoryMatrix({ categories }) {
  const visible = (categories || []).filter(c => c.key !== "other" || c.count > 0);
  return (
    <div data-testid="bc-category-matrix">
      <SectionTitle eyebrow="Category matrix" title="Coverage by nature of balance"
        hint="Each card = one audit population. Bar shows ₹-weighted status mix."/>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        {visible.map((c) => <CategoryCard key={c.key} cat={c}/>)}
      </div>
    </div>
  );
}

function CategoryCard({ cat }) {
  const accent = CAT_ACCENT[cat.key] || CAT_ACCENT.other;
  const cov = cat.coverage || {};
  return (
    <div className={`bg-white border border-gray-200 rounded-sm p-5 hover:shadow-sm transition`} data-testid={`bc-cat-${cat.key}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className={`inline-block text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 border ${accent.chip} rounded-sm`}>
            {cat.label}
          </div>
          <div className="font-heading text-xl mt-2">{cat.count} <span className="text-sm font-normal text-gray-500">parties</span></div>
          <div className="text-xs font-mono text-gray-600 mt-0.5">{inrCompact(cat.amount)} exposure</div>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Audit coverage</div>
          <div className="font-heading text-2xl text-emerald-700 mt-1">{pct(cov.audit_amount_pct)}</div>
          <div className="text-[10px] font-mono text-gray-500">by ₹ · {pct(cov.audit_count_pct)} by count</div>
        </div>
      </div>
      <StatusStackedBar bucket={cat}/>
      <StatusLegend bucket={cat}/>
    </div>
  );
}

function StatusStackedBar({ bucket }) {
  const total = bucket?.amount || 0;
  if (total <= 0) {
    return (
      <div className="mt-4 h-6 rounded-sm border border-dashed border-gray-300 flex items-center justify-center text-[10px] font-mono text-gray-400">
        No exposure to show
      </div>
    );
  }
  return (
    <div className="mt-4 flex h-7 rounded-sm overflow-hidden border border-gray-200">
      {STATUS_ORDER.map((st) => {
        const seg = bucket.by_status?.[st];
        if (!seg || seg.amount <= 0) return null;
        const p = (seg.amount / total) * 100;
        const S = STATUS[st];
        return (
          <div key={st}
            className="flex items-center justify-center text-[10px] font-semibold transition hover:brightness-95"
            style={{ width: `${p}%`, background: S.bg, color: S.fg, minWidth: p > 4 ? 24 : 2 }}
            title={`${S.label}: ${inrCompact(seg.amount)} (${p.toFixed(1)}%) · ${seg.count} parties`}
            data-testid={`bc-cat-${bucket.key}-bar-${st}`}>
            {p >= 11 ? `${p.toFixed(0)}%` : ""}
          </div>
        );
      })}
    </div>
  );
}

function StatusLegend({ bucket }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
      {STATUS_ORDER.map((st) => {
        const seg = bucket.by_status?.[st] || { count: 0, amount: 0 };
        const S = STATUS[st];
        return (
          <div key={st} className="inline-flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-sm" style={{ background: S.solid }}/>
            <span className="text-gray-700">{S.label}</span>
            <span className="font-mono text-gray-500">{seg.count}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ========================= Row 3a · Funnel chart ======================== */
function FunnelPanel({ funnel }) {
  const rows = (funnel || []).map((s) => ({
    name: s.label,
    value: s.count,
    amount: s.amount,
    amount_pct: s.amount_pct,
    count_pct: s.count_pct,
  }));
  return (
    <div className="mt-3">
      <div className="space-y-1.5">
        {rows.map((r, i) => {
          const w = Math.max(6, Math.min(100, r.amount_pct || 0));
          const toneMap = [
            "from-slate-400 to-slate-500",
            "from-indigo-400 to-indigo-500",
            "from-sky-500 to-sky-600",
            "from-teal-500 to-teal-600",
            "from-emerald-500 to-emerald-600",
            "from-emerald-600 to-emerald-700",
          ];
          return (
            <div key={r.name} className="flex items-center gap-3" data-testid={`bc-funnel-${r.name.toLowerCase().replace(/\s/g, "-")}`}>
              <div className="w-24 text-[11px] font-mono text-gray-700 flex-shrink-0">{r.name}</div>
              <div className="flex-1 h-7 bg-gray-50 rounded-sm relative overflow-hidden">
                <div className={`absolute top-0 left-0 h-full bg-gradient-to-r ${toneMap[i % toneMap.length]} transition-[width] duration-700`}
                     style={{ width: `${w}%` }}/>
                <div className="absolute inset-0 flex items-center px-2 text-[11px] font-semibold text-white mix-blend-plus-lighter">
                  <span className="drop-shadow-sm">{r.value}</span>
                  <span className="ml-1 opacity-80 font-normal">· {inrCompact(r.amount)}</span>
                </div>
              </div>
              <div className="w-16 text-right text-[11px] font-mono">
                <div className="text-gray-900 font-semibold">{pct(r.amount_pct)}</div>
                <div className="text-gray-400 text-[10px]">by ₹</div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="text-[10px] font-mono text-gray-400 mt-4 border-t border-gray-100 pt-2">
        Each bar is scaled against total exposure. Count shown inside; ₹% on the right.
      </div>
    </div>
  );
}

/* ========================= Row 3b · Status donut (Recharts) ============= */
function StatusDonut({ overall }) {
  const total = overall?.amount || 0;
  const segments = STATUS_ORDER
    .map((st) => ({
      name: STATUS[st].label,
      key: st,
      value: overall?.by_status?.[st]?.amount || 0,
      count: overall?.by_status?.[st]?.count || 0,
    }))
    .filter((s) => s.value > 0);

  if (!segments.length) {
    return (
      <div className="h-48 flex items-center justify-center text-xs text-gray-500">
        No exposure to visualise yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center mt-2">
      <div className="w-full h-52 relative">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={segments} dataKey="value" nameKey="name"
                 cx="50%" cy="50%" innerRadius={55} outerRadius={85} paddingAngle={2} stroke="none">
              {segments.map((s) => <Cell key={s.key} fill={STATUS[s.key].solid}/>)}
            </Pie>
            <Tooltip
              contentStyle={{ borderRadius: 2, border: "1px solid #E5E7EB", fontSize: 11 }}
              formatter={(v, n, p) => [`${inrCompact(v)} · ${p.payload.count} parties`, n]}/>
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Total ₹</div>
          <div className="font-heading text-base">{inrCompact(total)}</div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 w-full">
        {segments.map((s) => (
          <div key={s.key} className="inline-flex items-center gap-2 text-[11px]">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: STATUS[s.key].solid }}/>
            <span className="text-gray-700 flex-1 truncate">{s.name}</span>
            <span className="font-mono text-gray-900">{((s.value / total) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ========================= Row 4 · Attention panels ===================== */
function TopDisputed({ rows }) {
  return (
    <div className="bg-white border border-gray-200 rounded-sm p-5" data-testid="bc-top-disputed">
      <SectionTitle eyebrow="Needs reconciliation" title="Top Disputed — by variance"
        hint="Largest ₹ gaps first; click through via workbench to drill in."/>
      {(!rows || !rows.length) ? (
        <EmptyRow msg="No disputed confirmations yet."/>
      ) : (
        <div className="mt-3 divide-y divide-gray-100">
          {rows.slice(0, 10).map((r, i) => (
            <div key={r.ledger_id + i} className="py-2.5 flex items-start gap-3">
              <div className="text-[10px] font-mono text-gray-400 w-5 pt-0.5">{i + 1}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{r.party || "—"}</div>
                <div className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">{r.reason || "(no reason)"}</div>
              </div>
              <div className="text-right whitespace-nowrap">
                <div className="text-xs text-gray-500 font-mono">Us {inrCompact(r.our_amount)} {r.our_dr_cr}</div>
                <div className="text-xs text-gray-500 font-mono">Them {r.their_amount === null ? "—" : `${inrCompact(r.their_amount)} ${r.their_dr_cr || ""}`}</div>
                <div className="text-xs text-amber-700 font-mono font-semibold mt-0.5">
                  Δ {r.diff === null ? "—" : inrCompact(Math.abs(r.diff))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TopUnresponsive({ rows }) {
  return (
    <div className="bg-white border border-gray-200 rounded-sm p-5" data-testid="bc-top-unresponsive">
      <SectionTitle eyebrow="Follow-up needed" title="Top Unresponsive — by ₹"
        hint="Sent 7+ days ago, no reply. Prioritise reminders top-down."/>
      {(!rows || !rows.length) ? (
        <EmptyRow msg="No stale confirmations. All dispatched parties replied in time."/>
      ) : (
        <div className="mt-3 divide-y divide-gray-100">
          {rows.slice(0, 10).map((r, i) => (
            <div key={r.ledger_id + i} className="py-2.5 flex items-start gap-3">
              <div className="text-[10px] font-mono text-gray-400 w-5 pt-0.5">{i + 1}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{r.party || "—"}</div>
                <div className="text-[11px] text-gray-500 mt-0.5 truncate">{r.email || "(no email)"}</div>
              </div>
              <div className="text-right whitespace-nowrap">
                <div className="text-xs font-mono text-gray-900">{inrCompact(r.amount)} {r.dr_cr}</div>
                <div className="text-[11px] font-mono text-blue-700 mt-0.5">{r.days_pending}d pending</div>
                <div className="text-[10px] font-mono text-gray-400">{r.status}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ========================= Row 5 · Subhead heatmap ====================== */
function SubheadHeatmap({ rows }) {
  const sorted = useMemo(() => (rows || []).slice().sort((a, b) => b.amount - a.amount), [rows]);
  return (
    <div className="bg-white border border-gray-200 rounded-sm p-5" data-testid="bc-subhead-heatmap">
      <SectionTitle eyebrow="Sampling rationale" title="Subhead Coverage Heatmap"
        hint="Group-wise exposure + coverage. Intensity encodes ₹ coverage achieved."/>
      {!sorted.length ? <EmptyRow msg="No subhead data yet."/> : (
        <div className="overflow-x-auto mt-3 -mx-2">
          <table className="w-full text-[12.5px]" data-testid="bc-subhead-table">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-wider text-gray-500 bg-gray-50">
                <th className="text-left px-3 py-2 border-b border-gray-200">Subhead (parent group)</th>
                <th className="text-right px-3 py-2 border-b border-gray-200 w-[12%]">Parties</th>
                <th className="text-right px-3 py-2 border-b border-gray-200 w-[18%]">Exposure ₹</th>
                <th className="text-right px-3 py-2 border-b border-gray-200 w-[18%]">Coverage ₹ %</th>
                <th className="text-right px-3 py-2 border-b border-gray-200 w-[18%]">Response ₹ %</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const v = r.audit_amount_pct;
                const bg = v >= 80 ? "bg-emerald-100 text-emerald-900"
                  : v >= 50 ? "bg-emerald-50 text-emerald-800"
                  : v >= 25 ? "bg-amber-50 text-amber-800"
                  : v > 0   ? "bg-rose-50 text-rose-800"
                  :            "bg-gray-50 text-gray-500";
                return (
                  <tr key={r.parent_group} className="hover:bg-gray-50">
                    <td className="px-3 py-2 border-b border-gray-100 truncate" title={r.parent_group}>{r.parent_group || "—"}</td>
                    <td className="px-3 py-2 border-b border-gray-100 text-right font-mono">{r.count}</td>
                    <td className="px-3 py-2 border-b border-gray-100 text-right font-mono">{inrCompact(r.amount)}</td>
                    <td className="px-3 py-2 border-b border-gray-100 text-right">
                      <span className={`inline-block px-2 py-0.5 rounded-sm font-mono font-semibold ${bg}`}>
                        {pct(v)}
                      </span>
                    </td>
                    <td className="px-3 py-2 border-b border-gray-100 text-right font-mono text-gray-700">{pct(r.response_amount_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ========================= Small UI primitives ========================== */
function SectionTitle({ eyebrow, title, hint }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">{eyebrow}</div>
      <h3 className="font-heading text-base mt-0.5">{title}</h3>
      {hint && <div className="text-[11px] text-gray-500 mt-0.5">{hint}</div>}
    </div>
  );
}

function EmptyRow({ msg }) {
  return (
    <div className="mt-4 border border-dashed border-gray-200 rounded-sm p-5 text-center text-[12px] text-gray-500">
      {msg}
    </div>
  );
}

function Footnote({ generated }) {
  return (
    <div className="text-[10px] font-mono text-gray-400 text-right">
      Regenerated on {generated?.slice(0, 19).replace("T", " ")} UTC ·
      Coverage = (Confirmed + Reconciled) ÷ Total
    </div>
  );
}
