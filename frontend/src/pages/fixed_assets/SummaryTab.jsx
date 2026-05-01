import { useEffect, useState, useMemo, useCallback } from "react";
import {
  Loader2, Download, FileText, FileSpreadsheet, ShieldCheck, ShieldAlert,
  AlertTriangle, CheckCircle2, Link2, Receipt, TrendingUp, Users, Layers,
  Clock3, BarChart3, Eye, RefreshCcw, ChevronRight,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

/* ============================================================
   Summary Tab — MIS + Audit-risk command-center for one FA run.
   Single-screen overview that doubles as the Download hub.
   ============================================================ */

const inr = (v) => {
  const n = Number(v || 0);
  if (n === 0) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
  return n < 0 ? `(${s})` : s;
};
const inrCompact = (v) => {
  const n = Math.abs(Number(v || 0));
  if (n >= 1e7) return `₹ ${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹ ${(n / 1e5).toFixed(2)} L`;
  if (n >= 1e3) return `₹ ${(n / 1e3).toFixed(0)} k`;
  return `₹ ${n.toFixed(0)}`;
};

export default function SummaryTab({ rid }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [downloadingXlsx, setDownloadingXlsx] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/summary`);
      setData(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load summary");
    } finally {
      setLoading(false);
    }
  }, [rid]);

  useEffect(() => { refresh(); }, [refresh]);

  const downloadFile = async (path, ext, kind) => {
    const setBusy = ext === "xlsx" ? setDownloadingXlsx : setDownloadingPdf;
    setBusy(true);
    try {
      const res = await http.get(path, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      const cd = res.headers["content-disposition"] || "";
      const m = /filename="?([^";]+)"?/i.exec(cd);
      a.href = url;
      a.download = m?.[1] || `IT_Depreciation.${ext}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || `${kind} download failed`);
    } finally { setBusy(false); }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="animate-spin mr-2" size={16}/>
        Loading summary…
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-5" data-testid="fa-summary-tab">
      {/* ========== Header strip ========== */}
      <SummaryHeader data={data} onRefresh={refresh} loading={loading}/>

      {/* ========== KPI tiles ========== */}
      <KpiStrip k={data.kpis}/>

      {/* ========== Validation + Audit flags ========== */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-4">
          <ValidationCard v={data.validation}/>
          <OcrCoverageCard counts={data.counts} ocr={data.ocr}/>
        </div>
        <div className="lg:col-span-2">
          <AuditFlagsPanel flags={data.audit_flags} openCount={data.open_flag_count}/>
        </div>
      </div>

      {/* ========== MIS counts ========== */}
      <MisCountsPanel counts={data.counts}/>

      {/* ========== Block-wise breakdown ========== */}
      <BlockBreakdownTable blocks={data.blocks}/>

      {/* ========== Two-column insight cuts ========== */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TopAdditionsTable rows={data.top_additions}/>
        <div className="space-y-4">
          <TopSuppliersTable rows={data.top_suppliers}/>
          <AdjustmentUsageStrip rows={data.adjustments}/>
        </div>
      </div>

      {/* ========== Quarterly distribution ========== */}
      <QuarterlyChart rows={data.quarterly}/>

      {/* ========== Download hub ========== */}
      <DownloadHub
        rid={rid}
        onXlsx={() => downloadFile(`/fixed-assets/runs/${rid}/export.xlsx`, "xlsx", "Excel")}
        onPdf={() => downloadFile(`/fixed-assets/runs/${rid}/export.pdf`, "pdf", "PDF")}
        downloadingXlsx={downloadingXlsx}
        downloadingPdf={downloadingPdf}
      />
    </div>
  );
}

/* ==================== Header ==================== */
function SummaryHeader({ data, onRefresh, loading }) {
  return (
    <div className="bg-[#0F172A] text-white px-5 py-4 flex items-center justify-between">
      <div>
        <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-400">Run Summary</div>
        <div className="font-heading text-xl mt-0.5">
          {data.client_name || data.run_id} · FY {data.fy_label}
        </div>
        <div className="text-[11.5px] text-slate-400 mt-1">
          {data.fy_start} – {data.fy_end}
        </div>
      </div>
      <button
        onClick={onRefresh}
        disabled={loading}
        data-testid="fa-summary-refresh"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-slate-200 border border-slate-600 hover:bg-slate-800 disabled:opacity-60"
      >
        {loading ? <Loader2 size={13} className="animate-spin"/> : <RefreshCcw size={13}/>}
        Refresh
      </button>
    </div>
  );
}

/* ==================== KPI strip ==================== */
function KpiStrip({ k }) {
  const items = [
    { label: "Opening WDV",     value: k.opening_wdv,                  accent: "slate" },
    { label: "Capitalised Adds", value: (k.adds_full || 0) + (k.adds_half || 0), accent: "sky" },
    { label: "Sales",           value: k.deletions,                    accent: "amber" },
    { label: "Depreciation",    value: k.depreciation,                 accent: "violet" },
    { label: "Closing WDV",     value: k.closing_wdv,                  accent: "emerald" },
  ];
  const accentMap = {
    slate:   "bg-slate-50 border-slate-200",
    sky:     "bg-sky-50 border-sky-200",
    amber:   "bg-amber-50 border-amber-200",
    violet:  "bg-violet-50 border-violet-200",
    emerald: "bg-emerald-50 border-emerald-200",
  };
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="fa-summary-kpis">
      {items.map(({ label, value, accent }) => (
        <div key={label} className={`border ${accentMap[accent]} px-3 py-3`}>
          <div className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
          <div className="font-heading text-[15px] mt-1.5 text-slate-900 truncate" title={`₹ ${inr(value)}`}>
            {inrCompact(value)}
          </div>
          <div className="text-[10px] font-mono text-slate-500 mt-0.5">₹ {inr(value)}</div>
        </div>
      ))}
    </div>
  );
}

/* ==================== Validation card ==================== */
function ValidationCard({ v }) {
  if (!v) {
    return (
      <CardShell icon={ShieldCheck} title="3CD Validation" testid="fa-summary-validation">
        <div className="text-[12.5px] text-slate-500 italic">
          No validation run yet. Use the <em>Validate against Prior 3CD</em> button on the Compute tab to tie back sub-block opening WDV.
        </div>
      </CardShell>
    );
  }
  if (v.ok) {
    return (
      <CardShell icon={ShieldCheck} title="3CD Validation" testid="fa-summary-validation"
                 accentCls="border-emerald-300 bg-emerald-50/40">
        <div className="text-[12.5px] text-emerald-900">
          <strong>All rates tie back to 3CD</strong> — drift ₹ {inr(v.totals?.diff || 0)}.
        </div>
        <div className="text-[10.5px] font-mono text-slate-500 mt-1">
          {v.filename} · {(v.validated_at || "").slice(0, 16).replace("T", " ")} UTC
        </div>
      </CardShell>
    );
  }
  return (
    <CardShell icon={ShieldAlert} title="3CD Validation" testid="fa-summary-validation"
               accentCls={v.acknowledged ? "border-amber-300 bg-amber-50/40" : "border-rose-300 bg-rose-50/50"}>
      <div className={`text-[12.5px] ${v.acknowledged ? "text-amber-900" : "text-rose-900"}`}>
        <strong>{v.mismatch_count} mismatch{v.mismatch_count === 1 ? "" : "es"}</strong>
        {v.acknowledged ? " · overridden by auditor" : " · Compute is blocked"}
      </div>
      <div className="text-[10.5px] font-mono text-slate-500 mt-1">
        Drift ₹ {inr(v.totals?.diff || 0)} · {v.filename}
      </div>
    </CardShell>
  );
}

/* ==================== OCR coverage card ==================== */
function OcrCoverageCard({ counts, ocr }) {
  const pct = counts.coverage_pct || 0;
  const cls = pct >= 80 ? "text-emerald-700" : pct >= 50 ? "text-amber-700" : "text-rose-700";
  return (
    <CardShell icon={Receipt} title="OCR Bill Coverage" testid="fa-summary-ocr">
      <div className="flex items-end gap-3">
        <div className={`font-heading text-[26px] leading-none ${cls}`}>{pct.toFixed(1)}%</div>
        <div className="text-[11.5px] text-slate-500 pb-1">
          {counts.bills_attached.count} of {counts.bills_attached.count + counts.bills_unattached.count} additions linked to invoices
        </div>
      </div>
      <div className="mt-2 h-1.5 bg-slate-100 overflow-hidden">
        <div
          className={pct >= 80 ? "h-full bg-emerald-500" : pct >= 50 ? "h-full bg-amber-500" : "h-full bg-rose-500"}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <div className="text-[10.5px] font-mono text-slate-500 mt-2 flex justify-between">
        <span>Attached ₹ {inr(counts.bills_attached.value)}</span>
        <span>Unattached ₹ {inr(counts.bills_unattached.value)}</span>
      </div>
      {ocr.uploads_pending > 0 && (
        <div className="mt-2 text-[11px] text-slate-600 flex items-center gap-1.5 pt-2 border-t border-slate-100">
          <Clock3 size={11} className="text-amber-600"/>
          {ocr.uploads_pending} upload{ocr.uploads_pending === 1 ? "" : "s"} pending — {ocr.chunks_remaining} chunk{ocr.chunks_remaining === 1 ? "" : "s"} unapplied
        </div>
      )}
    </CardShell>
  );
}

/* ==================== Audit flags panel ==================== */
const FLAG_META = {
  missing_ptu:           { label: "Missing PTU date",        hint: "Half-rate decision needs Put-To-Use date",         tone: "rose" },
  ptu_after_fy_end:      { label: "PTU after FY end",        hint: "Asset can't be capitalised in this FY",            tone: "rose" },
  zero_or_negative_cost: { label: "Zero / negative cost",    hint: "Likely an entry error — review",                   tone: "rose" },
  missing_party:         { label: "Missing party / vendor",  hint: "Vendor field is blank",                            tone: "amber" },
  unreviewed:            { label: "Un-reviewed additions",   hint: "Auditor hasn't ticked the Reviewed box",           tone: "amber" },
  discount_pending:      { label: "Discount classification pending", hint: "Credit row not classified Sale/Discount", tone: "amber" },
};
function AuditFlagsPanel({ flags, openCount }) {
  const sorted = Object.entries(flags).sort(([, a], [, b]) => b.count - a.count);
  return (
    <CardShell
      icon={AlertTriangle}
      title="Audit Risk Flags"
      testid="fa-summary-flags"
      right={
        openCount === 0
          ? <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700 font-mono"><CheckCircle2 size={11}/> CLEAN</span>
          : <span className="inline-flex items-center gap-1 text-[11px] text-rose-700 font-mono"><AlertTriangle size={11}/> {openCount} open</span>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {sorted.map(([k, f]) => {
          const meta = FLAG_META[k] || { label: k, hint: "", tone: "slate" };
          const isOpen = f.count > 0;
          const toneCls = !isOpen
            ? "bg-slate-50 border-slate-200 text-slate-500"
            : meta.tone === "rose"
              ? "bg-rose-50 border-rose-200 text-rose-900"
              : "bg-amber-50 border-amber-200 text-amber-900";
          return (
            <div
              key={k}
              data-testid={`fa-flag-${k}`}
              className={`border ${toneCls} px-3 py-2 flex items-start justify-between gap-3`}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold truncate">{meta.label}</div>
                <div className="text-[10.5px] text-slate-500 mt-0.5">{meta.hint}</div>
              </div>
              <div className="text-right shrink-0">
                <div className={`text-[16px] font-heading leading-none ${isOpen ? "" : "text-slate-400"}`}>
                  {f.count}
                </div>
                <div className="text-[10px] font-mono text-slate-500 mt-1">
                  ₹ {inr(f.value)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </CardShell>
  );
}

/* ==================== MIS counts ==================== */
function MisCountsPanel({ counts }) {
  const items = [
    { icon: Layers,  label: "Active Ledgers",         primary: counts.ledgers,                   sub: `${counts.ledgers_classified} classified`, valueline: null },
    { icon: FileText, label: "Capitalised Additions", primary: counts.additions.count,           sub: `₹ ${inr(counts.additions.value)}`,         testid: "addn" },
    { icon: Link2,   label: "Merged into Parents",    primary: counts.additions_merged.count,    sub: `₹ ${inr(counts.additions_merged.value)}`,  testid: "merged" },
    { icon: TrendingUp, label: "Discount / Credit lines", primary: counts.discounts.count,       sub: `${counts.discounts_merged.count} netted · ₹ ${inr(counts.discounts.value)}`, testid: "disc" },
    { icon: Eye,     label: "Sales (this FY)",        primary: counts.sales.count,               sub: `₹ ${inr(counts.sales.value)}`,             testid: "sales" },
    { icon: Clock3,  label: "Half-rate Pool (<180d)", primary: counts.half_rate_pool.count,      sub: `₹ ${inr(counts.half_rate_pool.value)}`,    testid: "halfrate" },
  ];
  return (
    <CardShell icon={BarChart3} title="MIS Counts" testid="fa-summary-counts">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
        {items.map(({ icon: Icon, label, primary, sub, testid }) => (
          <div key={label} data-testid={testid ? `fa-mis-${testid}` : undefined}
               className="border border-slate-200 bg-white px-3 py-2.5">
            <div className="flex items-center gap-1.5">
              <Icon size={11} className="text-slate-500 shrink-0"/>
              <div className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-slate-500 truncate">
                {label}
              </div>
            </div>
            <div className="text-[20px] font-heading mt-1.5 leading-none">{primary}</div>
            <div className="text-[10.5px] font-mono text-slate-500 mt-1 truncate">{sub}</div>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

/* ==================== Block breakdown ==================== */
function BlockBreakdownTable({ blocks }) {
  return (
    <CardShell icon={Layers} title="Block-wise Breakdown" testid="fa-summary-blocks">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-left text-[10.5px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <th className="px-3 py-1.5">Block</th>
            <th className="px-3 py-1.5 w-[60px] text-center">Rate</th>
            <th className="px-3 py-1.5 w-[80px] text-right">Adds (n)</th>
            <th className="px-3 py-1.5 w-[140px] text-right">Adds Value</th>
            <th className="px-3 py-1.5 w-[140px] text-right">Depreciation</th>
            <th className="px-3 py-1.5 w-[140px] text-right">Closing WDV</th>
          </tr>
        </thead>
        <tbody>
          {blocks.map(b => (
            <tr key={b.block_label} className="border-b border-slate-100 hover:bg-slate-50/50">
              <td className="px-3 py-1.5 font-medium text-slate-800">{b.block_label}</td>
              <td className="px-3 py-1.5 text-center font-mono text-slate-600">{Math.round(b.rate)}%</td>
              <td className="px-3 py-1.5 text-right font-mono text-slate-700">{b.additions_count}</td>
              <td className="px-3 py-1.5 text-right font-mono text-slate-700">{inr(b.additions_value)}</td>
              <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(b.depreciation)}</td>
              <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(b.closing_wdv)}</td>
            </tr>
          ))}
          {blocks.length === 0 && (
            <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-500">No active blocks.</td></tr>
          )}
        </tbody>
      </table>
    </CardShell>
  );
}

/* ==================== Top additions ==================== */
function TopAdditionsTable({ rows }) {
  return (
    <CardShell icon={TrendingUp} title="Top 10 Additions by Capitalised Value" testid="fa-summary-top-additions">
      <div className="space-y-1">
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-slate-500 text-[12px]">No additions.</div>
        ) : rows.map((a, i) => (
          <div key={a.addition_id} className="flex items-start gap-2 px-2 py-1.5 hover:bg-slate-50/70">
            <div className="font-mono text-[10px] text-slate-400 w-5 text-right pt-0.5">{i + 1}</div>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold text-slate-900 line-clamp-1">
                {a.description || "(no description)"}
              </div>
              <div className="text-[10.5px] text-slate-500 truncate">
                {a.party_name || "—"}  ·  {a.block_label}  ·  PTU {a.put_to_use_date || "—"}
                {!a.is_more_than_180 && <span className="ml-2 text-rose-600 font-mono">½ rate</span>}
              </div>
            </div>
            <div className="font-mono text-[12px] font-semibold text-slate-900 shrink-0 pl-2">
              {inrCompact(a.capitalised_cost)}
            </div>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

/* ==================== Top suppliers ==================== */
function TopSuppliersTable({ rows }) {
  const max = Math.max(...rows.map(r => r.value), 1);
  return (
    <CardShell icon={Users} title="Top 5 Suppliers by Value" testid="fa-summary-top-suppliers">
      <div className="space-y-1.5">
        {rows.length === 0 ? (
          <div className="text-center text-slate-500 text-[12px] py-3">No suppliers.</div>
        ) : rows.map((r) => (
          <div key={r.party}>
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <span className="font-medium truncate">{r.party}</span>
              <span className="font-mono text-slate-700 shrink-0">
                {inrCompact(r.value)}
                <span className="text-[10px] text-slate-400 ml-1.5">· {r.count}</span>
              </span>
            </div>
            <div className="h-1 bg-slate-100 mt-1">
              <div
                className="h-full bg-slate-700"
                style={{ width: `${(r.value / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

/* ==================== Adjustment usage ==================== */
function AdjustmentUsageStrip({ rows }) {
  return (
    <CardShell icon={Layers} title="Adjustment Column Usage" testid="fa-summary-adjustments">
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.key}
               data-testid={`fa-adj-${r.key}`}
               className="flex items-center justify-between gap-2 px-2 py-1 hover:bg-slate-50/70 text-[12px]">
            <span className="text-slate-700 flex-1 truncate">
              {r.label}
              {r.reduces_cost && <span className="ml-1.5 text-[9px] font-mono uppercase text-rose-600">−</span>}
            </span>
            <span className="font-mono text-slate-500 w-[40px] text-right">{r.count}</span>
            <span className="font-mono text-slate-700 font-semibold w-[110px] text-right">₹ {inr(r.value)}</span>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

/* ==================== Quarterly distribution ==================== */
function QuarterlyChart({ rows }) {
  const max = useMemo(() => Math.max(...rows.map(r => r.value), 1), [rows]);
  return (
    <CardShell icon={BarChart3} title="Quarterly Distribution of Additions" testid="fa-summary-quarterly">
      <div className="grid grid-cols-5 gap-3 items-end h-[150px]">
        {rows.map((q) => {
          const pct = max ? (q.value / max) * 100 : 0;
          return (
            <div key={q.quarter} className="flex flex-col items-center justify-end h-full">
              <div className="w-full bg-slate-100 relative" style={{ height: "100%" }}>
                <div
                  className="absolute bottom-0 left-0 right-0 bg-slate-700"
                  style={{ height: `${Math.max(2, pct)}%` }}
                />
              </div>
              <div className="text-[11px] font-mono text-slate-700 mt-2">{q.quarter}</div>
              <div className="text-[10px] text-slate-500">{q.count} · {inrCompact(q.value)}</div>
            </div>
          );
        })}
      </div>
    </CardShell>
  );
}

/* ==================== Download hub ==================== */
function DownloadHub({ rid, onXlsx, onPdf, downloadingXlsx, downloadingPdf }) {
  return (
    <div className="border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5"
         data-testid="fa-summary-downloads">
      <div className="flex items-center gap-2 mb-3">
        <Download size={14} className="text-slate-700"/>
        <div className="font-heading text-base">Audit Deliverables</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <DeliverableCard
          icon={FileSpreadsheet}
          title="Excel Workbook"
          subtitle=".xlsx · 4 sheets"
          bullets={[
            "Block Summary — depreciation by block (zero rows skipped)",
            "Additions Register — every line, with adjustment columns",
            "Deletions Register — sales + STCG workings",
            "Workings — Sec 32 method notes",
          ]}
          accent="emerald"
          busy={downloadingXlsx}
          onClick={onXlsx}
          testid="fa-summary-download-xlsx"
        />
        <DeliverableCard
          icon={FileText}
          title="Signature-ready PDF"
          subtitle="A4 portrait · multi-page"
          bullets={[
            "Cover with KPI strip + block summary",
            "Additions register grouped by block",
            "Per-asset 2-row card · PTU / Particulars / Supplier / ₹",
          ]}
          accent="rose"
          busy={downloadingPdf}
          onClick={onPdf}
          testid="fa-summary-download-pdf"
        />
      </div>
    </div>
  );
}

function DeliverableCard({ icon: Icon, title, subtitle, bullets, accent, busy, onClick, testid }) {
  const tones = {
    emerald: { bg: "bg-emerald-50", border: "border-emerald-200", icon: "text-emerald-700", btn: "bg-emerald-700 hover:bg-emerald-800" },
    rose:    { bg: "bg-rose-50",    border: "border-rose-200",    icon: "text-rose-700",    btn: "bg-rose-700 hover:bg-rose-800" },
  }[accent] || {};
  return (
    <div className={`border ${tones.border} ${tones.bg} p-4 flex flex-col gap-3`}>
      <div className="flex items-start gap-3">
        <Icon size={22} className={tones.icon}/>
        <div className="flex-1 min-w-0">
          <div className="font-heading text-base">{title}</div>
          <div className="font-mono text-[10.5px] uppercase tracking-wider text-slate-500 mt-0.5">{subtitle}</div>
        </div>
      </div>
      <ul className="text-[11.5px] text-slate-600 space-y-0.5 pl-1">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-1.5">
            <ChevronRight size={11} className="mt-0.5 shrink-0 text-slate-400"/>
            <span>{b}</span>
          </li>
        ))}
      </ul>
      <button
        onClick={onClick}
        disabled={busy}
        data-testid={testid}
        className={`mt-1 inline-flex items-center justify-center gap-2 px-4 py-2 ${tones.btn} text-white text-[13px] disabled:opacity-60`}
      >
        {busy ? <Loader2 size={13} className="animate-spin"/> : <Download size={13}/>}
        Download {accent === "emerald" ? "Excel" : "PDF"}
      </button>
    </div>
  );
}

/* ==================== Generic card shell ==================== */
function CardShell({ icon: Icon, title, testid, children, right, accentCls = "border-slate-200 bg-white" }) {
  return (
    <div className={`border ${accentCls}`} data-testid={testid}>
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <Icon size={13} className="text-slate-600"/>
          <div className="font-heading text-[13px]">{title}</div>
        </div>
        {right}
      </div>
      <div className="px-4 py-3">{children}</div>
    </div>
  );
}
