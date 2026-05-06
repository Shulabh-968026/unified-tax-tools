/* Financial Statement Designer — Per-run page.
 *
 * Scoped: /dashboard/clients/:clientId/utilities/fin-statement/runs/:rid
 *
 * Flow:
 *  - Upload FinalStatement JSON
 *  - Preview normalized Schedule III document (BS / P&L / CFS + Notes)
 *  - Download signature-ready PDF in Classic or Boardroom template
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Loader2, Upload, ChartLine, FileText, Sparkles, Download, Building2, History,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import GenerationsDrawer from "@/components/GenerationsDrawer";

const inr = (v, { dashZero = true } = {}) => {
  const n = Number(v || 0);
  if (dashZero && Math.abs(n) < 0.005) return "—";
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
  const [downloading, setDownloading] = useState(null); // "classic" | "boardroom" | null
  const [showHistory, setShowHistory] = useState(false);
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
      toast.error("Please upload a FinalStatement JSON (.json)");
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
      toast.success("Financial statement ingested");
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Ingest failed");
    } finally {
      setUploading(false);
    }
  };

  const downloadPdf = async (template) => {
    setDownloading(template);
    try {
      const resp = await http.get(
        `/fin-statement/runs/${rid}/export.pdf?template=${template}`,
        { responseType: "blob" },
      );
      const blob = new Blob([resp.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = resp.headers?.["content-disposition"] || "";
      const m = /filename="?([^";]+)"?/.exec(cd);
      a.download = m ? m[1] : `financial_statement_${template}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`${template === "classic" ? "Classic" : "Boardroom"} PDF downloaded`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "PDF download failed");
    } finally {
      setDownloading(null);
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
        <div className="flex items-center gap-2 text-[12px] text-[#52524E]">
          <Link to="/dashboard" className="hover:underline">Clients</Link>
          <span>/</span>
          <Link to={`/dashboard/clients/${clientId}/utilities`} className="hover:underline">{run.name}</Link>
          <span>/</span>
          <Link to={`/dashboard/clients/${clientId}/utilities/fin-statement`} className="hover:underline">FS Designer</Link>
          <span>/</span>
          <span className="text-[#0F172A] font-medium">FY {run.fy}</span>
        </div>

        <div className="flex items-start justify-between gap-3 mt-3">
          <div>
            <div className="flex items-center gap-2">
              <ChartLine size={18} className="text-sky-700"/>
              <h1 className="font-heading text-2xl">{run.name}</h1>
            </div>
            <div className="text-[12px] text-[#52524E] mt-1 font-mono">
              FY {run.fy} · {run.fy_start} → {run.fy_end}
              {run.books_loaded && (
                <> · {run.note_count} notes · {run.detail_count} detail lines</>
              )}
            </div>
          </div>
          <input
            type="file" accept=".json,application/json"
            onChange={onUpload} className="hidden" ref={fileRef}
            data-testid="fs-ingest-input"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowHistory(true)}
              data-testid="fs-open-history"
              className="inline-flex items-center gap-1.5 px-3 py-2 border border-slate-300 text-slate-700 text-[12px] hover:bg-slate-50"
            >
              <History size={13}/> History
            </button>
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              data-testid="fs-ingest-btn"
              className="inline-flex items-center gap-2 px-3.5 py-2 bg-sky-800 hover:bg-sky-900 text-white text-[13px] disabled:opacity-60"
            >
              {uploading ? <Loader2 size={14} className="animate-spin"/> : <Upload size={14}/>}
              {run.books_loaded ? "Re-ingest JSON" : "Upload Statement JSON"}
            </button>
          </div>
        </div>

        {!run.books_loaded ? (
          <EmptyHero onPick={() => fileRef.current?.click()}/>
        ) : doc ? (
          <>
            <CompanyCard doc={doc}/>
            <TemplatePicker onDownload={downloadPdf} downloading={downloading}/>
            <StatementPanel title="Balance Sheet" rows={doc.balance_sheet} fy={doc.period}/>
            <StatementPanel title="Statement of Profit & Loss" rows={doc.profit_loss} fy={doc.period}/>
            <CashFlowPanel rows={doc.cash_flow} fy={doc.period}/>
            <NotesPanel notes={doc.notes} fy={doc.period}/>
            <DetailsPanel details={doc.details} fy={doc.period}/>
          </>
        ) : null}
      </div>
      {showHistory && (
        <GenerationsDrawer
          open={showHistory}
          onClose={() => setShowHistory(false)}
          endpoint={`/fin-statement/runs/${rid}`}
          moduleLabel="Financial Statement Designer"
          module="fin_statement"
        />
      )}
    </div>
  );
}

function EmptyHero({ onPick }) {
  return (
    <div className="mt-10 border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <FileText size={32} className="mx-auto text-sky-700 mb-3"/>
      <div className="font-heading text-lg">Upload the FinalStatement JSON</div>
      <p className="text-[12.5px] text-slate-500 mt-2 max-w-lg mx-auto">
        Drop the pre-aggregated Schedule III financial-statement JSON for this FY.
        We'll render a signature-ready PDF with Balance Sheet, P&amp;L, Cash Flow and
        all notes, in your choice of Classic or Boardroom design.
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

function CompanyCard({ doc }) {
  const c = doc.company || {};
  const p = doc.period || {};
  return (
    <div className="mt-6 border border-slate-200 bg-white p-4" data-testid="fs-company-card">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 bg-sky-50 border border-sky-200 text-sky-800 grid place-items-center shrink-0">
          <Building2 size={16}/>
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-heading text-[15px]">{c.name || "Unknown company"}</div>
          {c.address && <div className="text-[11.5px] text-slate-500 mt-0.5">{c.address}</div>}
          <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500 mt-2">
            Current FY {p.fy_current} ({p.current_start} → {p.current_end})
            {p.fy_previous && <> · Prev FY {p.fy_previous}</>}
          </div>
        </div>
      </div>
    </div>
  );
}

function TemplatePicker({ onDownload, downloading }) {
  const templates = [
    { id: "classic",   title: "Classic Compliance",
      copy: "Schedule III purity, crisp monochrome, single-page BS / P&L / CFS — the CA reviewer's default.",
      tone: "bg-slate-50 border-slate-200 text-slate-800" },
    { id: "boardroom", title: "Modern Boardroom",
      copy: "Slate + sky accents with a boardroom feel — ready for management review.",
      tone: "bg-sky-50 border-sky-200 text-sky-900" },
  ];
  return (
    <div className="mt-5 border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5"
         data-testid="fs-template-picker">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={14} className="text-sky-700"/>
        <div className="font-heading text-base">Download Signature-Ready PDF</div>
        <span className="text-[10px] font-mono uppercase tracking-wider text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 ml-2">
          Live
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {templates.map(t => (
          <div key={t.id} className={`border p-4 ${t.tone}`}>
            <div className="font-heading text-[14px]">{t.title}</div>
            <p className="text-[11.5px] text-slate-600 mt-1">{t.copy}</p>
            <button
              onClick={() => onDownload(t.id)}
              disabled={downloading === t.id}
              data-testid={`fs-download-${t.id}`}
              className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 bg-sky-800 hover:bg-sky-900 text-white text-[12px] disabled:opacity-60"
            >
              {downloading === t.id ? <Loader2 size={12} className="animate-spin"/> : <Download size={12}/>}
              Download {t.title}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatementPanel({ title, rows, fy }) {
  const nonZero = rows.filter(r => r.current !== 0 || r.previous !== 0);
  return (
    <div className="mt-5 border border-slate-200 bg-white"
         data-testid={`fs-panel-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
      <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-between">
        <div className="font-heading text-[13px]">{title}</div>
        <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
          {nonZero.length} line items
        </div>
      </div>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <th className="px-3 py-1.5 text-left">Head</th>
            <th className="px-3 py-1.5 text-right w-[60px]">Note</th>
            <th className="px-3 py-1.5 text-right w-[160px]">FY {fy?.fy_current}</th>
            <th className="px-3 py-1.5 text-right w-[160px]">FY {fy?.fy_previous}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.label}-${i}`}
                className={`border-b border-slate-100 ${r.is_header ? "bg-slate-50" : ""}`}>
              <td className="px-3 py-1.5" style={{ paddingLeft: 12 + (r.indent || 0) * 16 }}>
                <span className={r.is_header || r.is_subtotal ? "font-semibold text-slate-900" : "text-slate-800"}>
                  {r.label}
                </span>
              </td>
              <td className="px-3 py-1.5 text-right text-[10.5px] font-mono text-slate-500">
                {r.note || ""}
              </td>
              <td className={`px-3 py-1.5 text-right font-mono ${r.is_header || r.is_subtotal ? "font-semibold" : ""}`}>
                {inr(r.current)}
              </td>
              <td className={`px-3 py-1.5 text-right font-mono text-slate-500 ${r.is_header || r.is_subtotal ? "font-semibold text-slate-800" : ""}`}>
                {inr(r.previous)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CashFlowPanel({ rows, fy }) {
  return (
    <div className="mt-5 border border-slate-200 bg-white" data-testid="fs-panel-cash-flow">
      <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-between">
        <div className="font-heading text-[13px]">Cash Flow Statement</div>
        <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
          {rows.length} rows
        </div>
      </div>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <th className="px-3 py-1.5 text-left">Particulars</th>
            <th className="px-3 py-1.5 text-right w-[160px]">FY {fy?.fy_current}</th>
            <th className="px-3 py-1.5 text-right w-[160px]">FY {fy?.fy_previous}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const isHeader = r.is_header;
            const isBold = r.is_bold;
            const hasTopBorder = r.line_top && r.line_top !== "NONE";
            return (
              <tr key={`${r.label}-${i}`}
                  className={`border-b border-slate-100 ${isHeader ? "bg-slate-50" : ""}`}>
                <td className="px-3 py-1.5"
                    style={{ paddingLeft: 12 + (r.indent || 0) * 14 }}>
                  <span className={isHeader || isBold ? "font-semibold text-slate-900" : "text-slate-800"}>
                    {r.serial && <span className="font-mono text-[10.5px] text-slate-500 mr-2">{r.serial}</span>}
                    {r.label}
                  </span>
                </td>
                <td className={`px-3 py-1.5 text-right font-mono ${isHeader ? "" : ""} ${isBold ? "font-semibold" : ""} ${hasTopBorder ? "border-t border-slate-300" : ""}`}>
                  {isHeader && r.current === 0 ? "" : inr(r.current)}
                </td>
                <td className={`px-3 py-1.5 text-right font-mono text-slate-500 ${isBold ? "font-semibold text-slate-800" : ""} ${hasTopBorder ? "border-t border-slate-300" : ""}`}>
                  {isHeader && r.previous === 0 ? "" : inr(r.previous)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NotesPanel({ notes, fy }) {
  const [expanded, setExpanded] = useState({});
  const toggle = (n) => setExpanded(e => ({ ...e, [n]: !e[n] }));
  if (!notes?.length) return null;
  return (
    <div className="mt-5 border border-slate-200 bg-white" data-testid="fs-panel-notes">
      <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-between">
        <div className="font-heading text-[13px]">Notes ({notes.length})</div>
        <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
          Click to expand sub-items
        </div>
      </div>
      <div>
        {notes.map(n => {
          const rows = n.subitems || [];
          const isOpen = expanded[n.note];
          return (
            <div key={`note-${n.note}`} className="border-b border-slate-100">
              <button
                onClick={() => toggle(n.note)}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-slate-50 text-left"
                data-testid={`fs-note-row-${n.note}`}
              >
                <span className="font-mono text-[10.5px] text-slate-500 w-14">Note {n.note}</span>
                <span className="font-medium text-[13px] text-slate-800 flex-1 truncate">{n.title}</span>
                <span className="font-mono text-[12px] text-slate-800 w-[140px] text-right">{inr(n.current)}</span>
                <span className="font-mono text-[12px] text-slate-500 w-[140px] text-right">{inr(n.previous)}</span>
              </button>
              {isOpen && rows.length > 0 && (
                <table className="w-full text-[12px] bg-[#FAFAF7] border-t border-slate-200">
                  <thead>
                    <tr className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-1.5 text-left">Particulars</th>
                      <th className="px-3 py-1.5 text-right w-[140px]">FY {fy?.fy_current}</th>
                      <th className="px-3 py-1.5 text-right w-[140px]">FY {fy?.fy_previous}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={`nr-${n.note}-${i}`} className="border-t border-slate-100">
                        <td className="px-4 py-1.5">
                          <span className="text-slate-700">
                            {r.prefix && <span className="font-mono text-slate-500 mr-1.5">{r.prefix}</span>}
                            {r.label}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono">{inr(r.current)}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-slate-500">{inr(r.previous)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DetailsPanel({ details, fy }) {
  if (!details?.length) return null;
  // Group by note for compact display
  const byNote = details.reduce((acc, d) => {
    (acc[d.note] = acc[d.note] || []).push(d);
    return acc;
  }, {});
  return (
    <div className="mt-5 border border-slate-200 bg-white" data-testid="fs-panel-details">
      <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-between">
        <div className="font-heading text-[13px]">Details to Financial Statements</div>
        <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500">
          {details.length} sub-line items
        </div>
      </div>
      <div className="divide-y divide-slate-100">
        {Object.entries(byNote).map(([note, rows]) => (
          <div key={`d-${note}`} className="px-4 py-2">
            <div className="text-[11px] font-mono uppercase tracking-wider text-sky-700 mb-1">
              Note {note}
            </div>
            {rows.map((d, i) => (
              <div key={`dr-${note}-${i}`} className="flex items-center gap-3 py-1 text-[12.5px]">
                <span className="font-mono text-slate-500 w-16 text-[11px]">{d.ref}</span>
                <span className="flex-1 text-slate-800 truncate">{d.title}</span>
                <span className="font-mono w-[120px] text-right">{inr(d.current)}</span>
                <span className="font-mono w-[120px] text-right text-slate-500">{inr(d.previous)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
