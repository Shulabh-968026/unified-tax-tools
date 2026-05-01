/* Financial Statement Designer — Per-run page.
 *
 * Scoped: /dashboard/clients/:clientId/utilities/fin-statement/runs/:rid
 *
 * Phase 1:
 *  - Upload Tally books JSON
 *  - Render the auto-derived Schedule III preview (Balance Sheet + P&L)
 *  - PDF-template picker is rendered but disabled ("coming in Drop 2")
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Loader2, Upload, ChartLine, FileText, Sparkles, CheckCircle2,
  ArrowRight,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (n === 0) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
  return n < 0 ? `(${s})` : s;
};

export default function FsRunPage() {
  const { clientId, rid } = useParams();
  const [run, setRun] = useState(null);
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await http.get(`/fin-statement/runs/${rid}`);
      setRun(r.data);
      if (r.data.books_loaded) {
        const d = await http.get(`/fin-statement/runs/${rid}/document`);
        setDoc(d.data);
      } else {
        setDoc(null);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load run");
    } finally {
      setLoading(false);
    }
  }, [rid]);

  useEffect(() => { refresh(); }, [refresh]);

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".json")) {
      toast.error("Please upload the Tally books JSON (.json)");
      return;
    }
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      await http.post(`/fin-statement/runs/${rid}/ingest`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000,
      });
      toast.success("Books ingested");
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Ingest failed");
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-slate-500">
        <Loader2 className="animate-spin mr-2" size={16}/> Loading…
      </div>
    );
  }
  if (!run) return null;

  return (
    <div className="min-h-screen bg-[#FAFAF7]">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* breadcrumb */}
        <div className="flex items-center gap-2 text-[12px] text-[#52524E]">
          <Link to="/dashboard" className="hover:underline">Clients</Link>
          <span>/</span>
          <Link to={`/dashboard/clients/${clientId}/utilities`} className="hover:underline">{run.name}</Link>
          <span>/</span>
          <Link to={`/dashboard/clients/${clientId}/utilities/fin-statement`} className="hover:underline">FS Designer</Link>
          <span>/</span>
          <span className="text-[#0F172A] font-medium">FY {run.fy}</span>
        </div>

        {/* header */}
        <div className="flex items-start justify-between gap-3 mt-3">
          <div>
            <div className="flex items-center gap-2">
              <ChartLine size={18} className="text-sky-700"/>
              <h1 className="font-heading text-2xl">{run.name}</h1>
            </div>
            <div className="text-[12px] text-[#52524E] mt-1 font-mono">
              FY {run.fy} · {run.fy_start} → {run.fy_end}
              {run.books_loaded && <> · {run.ledger_count} ledgers · {run.voucher_count} vouchers</>}
            </div>
          </div>
          <input
            type="file" accept=".json,application/json"
            onChange={onUpload} className="hidden" ref={fileRef}
            data-testid="fs-ingest-input"
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            data-testid="fs-ingest-btn"
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-sky-800 hover:bg-sky-900 text-white text-[13px] disabled:opacity-60"
          >
            {uploading ? <Loader2 size={14} className="animate-spin"/> : <Upload size={14}/>}
            {run.books_loaded ? "Re-ingest Books JSON" : "Upload Books JSON"}
          </button>
        </div>

        {!run.books_loaded ? (
          <EmptyHero onPick={() => fileRef.current?.click()}/>
        ) : doc ? (
          <>
            <KpiStrip totals={doc.totals}/>
            <StatementPanel title="Balance Sheet" rows={doc.balance_sheet}/>
            <StatementPanel title="Statement of Profit & Loss" rows={doc.profit_loss}/>
            <TemplatePicker />
          </>
        ) : null}
      </div>
    </div>
  );
}

function EmptyHero({ onPick }) {
  return (
    <div className="mt-10 border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <FileText size={32} className="mx-auto text-sky-700 mb-3"/>
      <div className="font-heading text-lg">Upload your Tally Books JSON</div>
      <p className="text-[12.5px] text-slate-500 mt-2 max-w-lg mx-auto">
        Drop a Tally export for this FY. We'll aggregate the ledger + voucher
        data into Schedule III Balance Sheet, P&amp;L, Cash Flow and Notes —
        and prepare it for a designer-style PDF.
      </p>
      <button
        onClick={onPick}
        data-testid="fs-hero-upload-btn"
        className="mt-5 inline-flex items-center gap-2 px-4 py-2 bg-sky-800 text-white text-[13px] hover:bg-sky-900"
      >
        <Upload size={14}/> Upload JSON
      </button>
    </div>
  );
}

function KpiStrip({ totals }) {
  const items = [
    { label: "Equity + Liabilities", value: totals?.equity_and_liabilities_current, accent: "sky" },
    { label: "Assets",               value: totals?.assets_current,                 accent: "sky" },
    { label: "Revenue",              value: totals?.revenue_current,                accent: "emerald" },
    { label: "Expenses",             value: totals?.expenses_current,               accent: "amber" },
    { label: "Profit After Tax",     value: totals?.pat_current,                    accent: "violet" },
  ];
  const accentMap = {
    sky:     "bg-sky-50 border-sky-200",
    emerald: "bg-emerald-50 border-emerald-200",
    amber:   "bg-amber-50 border-amber-200",
    violet:  "bg-violet-50 border-violet-200",
  };
  return (
    <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="fs-kpi-strip">
      {items.map(({ label, value, accent }) => (
        <div key={label} className={`border ${accentMap[accent]} px-3 py-3`}>
          <div className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
          <div className="font-heading text-[15px] mt-1.5 text-slate-900 truncate" title={`₹ ${inr(value)}`}>
            ₹ {inr(value)}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatementPanel({ title, rows }) {
  const nonZero = rows.filter(r => r.current !== 0 || r.previous !== 0);
  return (
    <div className="mt-5 border border-slate-200 bg-white" data-testid={`fs-panel-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
      <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-between">
        <div className="font-heading text-[13px]">{title}</div>
        <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
          {nonZero.length} line item{nonZero.length === 1 ? "" : "s"}
        </div>
      </div>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <th className="px-3 py-1.5 text-left w-[140px]">Section</th>
            <th className="px-3 py-1.5 text-left">Head</th>
            <th className="px-3 py-1.5 text-right w-[160px]">Current FY</th>
            <th className="px-3 py-1.5 text-right w-[160px]">Previous FY</th>
          </tr>
        </thead>
        <tbody>
          {nonZero.length === 0 ? (
            <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-500">
              No balances mapped to this statement.
            </td></tr>
          ) : nonZero.map((r, i) => (
            <tr key={`${r.section}-${r.head}-${i}`} className="border-b border-slate-100">
              <td className="px-3 py-1.5 text-slate-500 text-[11.5px] font-mono">{r.section}</td>
              <td className="px-3 py-1.5 text-slate-800">{r.head}</td>
              <td className="px-3 py-1.5 text-right font-mono">{inr(r.current)}</td>
              <td className="px-3 py-1.5 text-right font-mono text-slate-500">{inr(r.previous)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TemplatePicker() {
  return (
    <div className="mt-8 border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5"
         data-testid="fs-template-picker">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={14} className="text-sky-700"/>
        <div className="font-heading text-base">PDF Templates</div>
        <span className="text-[10px] font-mono uppercase tracking-wider text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 ml-2">
          Drop 2
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {[
          { id: "classic",   title: "Classic Compliance", copy: "Schedule III purity, crisp B/W, single-page B/S / P&L / CFS — the CA reviewer's default." },
          { id: "boardroom", title: "Modern Boardroom",   copy: "Slate + sky accents, inline mini-charts, large KPIs on the cover — management-review vibe." },
        ].map(t => (
          <div key={t.id} className="border border-slate-200 bg-white p-4 opacity-70">
            <div className="font-heading text-[14px]">{t.title}</div>
            <p className="text-[11.5px] text-slate-500 mt-1">{t.copy}</p>
            <button disabled
                    className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-300 text-slate-500 text-[12px] cursor-not-allowed">
              <ArrowRight size={12}/> Coming in Drop 2
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
