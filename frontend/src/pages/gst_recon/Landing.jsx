import { useState, useRef, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { FileText, CheckCircle2, XCircle, FolderUp, Loader2, ArrowLeft, Calculator } from "lucide-react";
import { toast } from "sonner";
import { http } from "@/lib/api";

const BUCKETS = [
  { id: "gstr1",   label: "GSTR-1",    expected: 12 },
  { id: "gstr2b",  label: "GSTR-2B",   expected: 12 },
  { id: "gstr3b",  label: "GSTR-3B",   expected: 12 },
  { id: "books",   label: "Books",     expected: 1 },
  { id: "mapping", label: "Ledger Mapping", expected: 1 },
];

const fmtINR = (n) => {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const v = Number(n);
  const s = Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  return v < 0 ? `(${s})` : s;
};

export default function GstReconLanding() {
  const { clientId: cid } = useParams();
  const [runId, setRunId] = useState(null);
  const [fy, setFy] = useState("2024-25");
  const [files, setFiles] = useState([]);
  const [buckets, setBuckets] = useState({});
  const [months, setMonths] = useState([]);
  const [hasBooks, setHasBooks] = useState(false);
  const [hasMapping, setHasMapping] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState(null);
  const [summary, setSummary] = useState(null);
  const inputRef = useRef();

  const ensureRun = async () => {
    if (runId) return runId;
    const { data } = await http.post("/gst-recon/runs", { client_id: cid, fy });
    setRunId(data.id);
    setMonths(data.months);
    return data.id;
  };

  const onFiles = useCallback(async (list) => {
    if (!list || !list.length) return;
    setBusy(true);
    try {
      const rid = await ensureRun();
      const form = new FormData();
      Array.from(list).forEach(f => form.append("files", f));
      const { data } = await http.post(`/gst-recon/runs/${rid}/files`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setBuckets(data.buckets);
      setMonths(data.months);
      setHasBooks(data.has_books);
      setHasMapping(data.has_mapping);
      setFiles(prev => [...prev, ...Array.from(list).map(f => f.name)]);
      setValidation(null); // stale after a new upload
      setSummary(null);    // stale after a new upload
      toast.success(`${data.accepted} file(s) categorized`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, cid, fy]);

  const handleDrop = (e) => { e.preventDefault(); onFiles(e.dataTransfer.files); };

  const runValidation = async () => {
    if (!runId) return;
    setBusy(true);
    try {
      const { data } = await http.post(`/gst-recon/runs/${runId}/validate`);
      setValidation(data);
      if (data.ok) toast.success("Pre-flight validation passed");
      else toast.error(`${data.errors.length} issue(s) — see below`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Validation failed");
    } finally {
      setBusy(false);
    }
  };

  const coverageComplete =
    hasBooks && hasMapping &&
    months.length === 12 && months.every(m => m.gstr1 && m.gstr2b && m.gstr3b);
  const canRun = coverageComplete && validation?.ok === true;

  return (
    <div className="min-h-screen bg-[#f9f9f8]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <Link to={`/dashboard/clients/${cid}`} className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-black mb-6" data-testid="gst-recon-back">
          <ArrowLeft size={14}/> Back to Utilities
        </Link>

        <div className="flex items-end justify-between gap-6 mb-8">
          <div>
            <div className="text-[11px] font-mono tracking-widest uppercase text-gray-500 mb-2">Utility</div>
            <h1 className="text-3xl font-semibold tracking-tight text-gray-900">GST Turnover & ITC Reconciliation</h1>
            <p className="text-sm text-gray-600 mt-1">Upload 38 files (12× GSTR-1, 12× GSTR-2B, 12× GSTR-3B, Books, Mapping) for the financial year.</p>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-[11px] font-mono uppercase text-gray-500">FY</label>
            <select
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              disabled={!!runId}
              className="border border-gray-300 rounded-sm h-9 px-3 text-sm font-mono bg-white"
              data-testid="gst-recon-fy-select"
            >
              {["2022-23","2023-24","2024-25","2025-26"].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        {/* Dropzone */}
        <div
          className="dropzone rounded-sm p-10 text-center cursor-pointer mb-8"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          data-testid="gst-recon-dropzone"
        >
          <input ref={inputRef} type="file" multiple className="hidden" onChange={(e) => onFiles(e.target.files)} data-testid="gst-recon-file-input"/>
          {busy ? <Loader2 className="mx-auto animate-spin text-gray-600" /> : <FolderUp className="mx-auto text-gray-700" size={28}/>}
          <div className="mt-3 font-medium text-gray-900">Drop files here or click to browse</div>
          <div className="text-xs text-gray-500 mt-1">Multi-select supported — accepts JSON, PDF, XLSX, CSV</div>
          {files.length > 0 && <div className="text-[11px] text-gray-500 mt-3 font-mono">{files.length} uploaded this session</div>}
        </div>

        {/* Bucket summary */}
        <div className="grid grid-cols-5 gap-3 mb-8">
          {BUCKETS.map(b => {
            const count = buckets[b.id] || 0;
            const ok = count >= b.expected;
            return (
              <div key={b.id} className={`border rounded-sm p-4 ${ok ? "border-emerald-300 bg-emerald-50/40" : "border-gray-200 bg-white"}`} data-testid={`bucket-${b.id}`}>
                <div className="text-[10px] font-mono uppercase tracking-wider text-gray-500">{b.label}</div>
                <div className="mt-2 flex items-end justify-between">
                  <div className="font-mono text-2xl font-semibold">{count}<span className="text-gray-400 text-base">/{b.expected}</span></div>
                  {ok ? <CheckCircle2 size={18} className="text-emerald-600"/> : <FileText size={18} className="text-gray-400"/>}
                </div>
              </div>
            );
          })}
        </div>

        {/* 12-month grid */}
        {months.length > 0 && (
          <div className="border border-gray-200 rounded-sm overflow-hidden bg-white mb-8">
            <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 text-[11px] font-mono uppercase tracking-wider text-gray-600">
              12-Month Coverage (Apr → Mar)
            </div>
            <div className="grid grid-cols-6 md:grid-cols-12 text-xs">
              {months.map(m => {
                const full = m.gstr1 && m.gstr2b && m.gstr3b;
                return (
                  <div key={m.period} className={`border-r border-b border-gray-100 p-3 ${full ? "bg-emerald-50/50" : "bg-white"}`} data-testid={`month-${m.period}`}>
                    <div className="font-mono text-[11px] font-semibold text-gray-900">{m.month_label}</div>
                    <div className="mt-2 space-y-1 text-[10px] font-mono">
                      <Row ok={m.gstr1} label="R1"/>
                      <Row ok={m.gstr2b} label="R2B"/>
                      <Row ok={m.gstr3b} label="R3B"/>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-500 font-mono">
            Phase C · 12-month Turnover & ITC reconciliation
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={!coverageComplete || busy}
              onClick={runValidation}
              className={`h-9 px-4 rounded-sm border border-gray-300 text-sm font-medium bg-white hover:bg-gray-50 ${coverageComplete ? "" : "opacity-40 cursor-not-allowed"}`}
              data-testid="validate-btn"
            >
              {busy ? "Validating…" : "Run Pre-flight Check"}
            </button>
            <button
              disabled={!canRun}
              onClick={runReconciliation}
              className={`btn-primary-swiss ${canRun ? "" : "opacity-40 cursor-not-allowed"}`}
              data-testid="run-reconciliation-btn"
            >
              <Calculator size={14} className="mr-2 inline"/> Run Reconciliation
            </button>
          </div>
        </div>

        {validation && (
          <div className={`mt-6 border rounded-sm p-4 text-sm ${validation.ok ? "border-emerald-300 bg-emerald-50/50" : "border-red-300 bg-red-50/50"}`} data-testid="validation-result">
            <div className="font-medium mb-2 flex items-center gap-2">
              {validation.ok ? <CheckCircle2 size={16} className="text-emerald-600"/> : <XCircle size={16} className="text-red-600"/>}
              {validation.ok ? "All gates passed — ready to reconcile" : `${validation.errors.length} blocker(s)`}
            </div>
            {validation.errors.length > 0 && (
              <ul className="list-disc ml-6 space-y-1 text-red-800 text-[13px]" data-testid="validation-errors">
                {validation.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
            {validation.warnings?.length > 0 && (
              <ul className="list-disc ml-6 space-y-1 text-amber-800 text-[13px] mt-2">
                {validation.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
            <div className="mt-2 text-[11px] font-mono text-gray-500">
              GSTIN: {validation.summary.client_gstin || "—"} ·
              GST files: {validation.summary.gst_files} ·
              Mismatches: {validation.summary.mismatched_gstins} ·
              Integrity failures: {validation.summary.integrity_failures}
            </div>
          </div>
        )}

        {summary && <SummaryPanel summary={summary} />}
      </div>
    </div>
  );
}

function SummaryPanel({ summary }) {
  const { rows, totals, fy } = summary;
  return (
    <div className="mt-8 border border-gray-200 rounded-sm bg-white overflow-hidden" data-testid="summary-panel">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div className="text-[11px] font-mono uppercase tracking-wider text-gray-600">
          12-Month Reconciliation · FY {fy}
        </div>
        <div className="text-[10px] font-mono text-gray-500">All values in INR</div>
      </div>

      {/* Outward Turnover */}
      <ReconTable
        title="Outward Turnover (Books vs GSTR-1 vs GSTR-3B)"
        rows={rows}
        totals={totals}
        cols={[
          { key: "books_outward_taxable", label: "Books" },
          { key: "r1_outward_taxable",    label: "GSTR-1" },
          { key: "r3b_outward_taxable",   label: "GSTR-3B" },
          { key: "var_books_vs_r1_outward", label: "Books − R1", variance: true },
          { key: "var_r1_vs_r3b_outward",   label: "R1 − R3B",   variance: true },
        ]}
        testid="summary-outward"
      />

      {/* ITC */}
      <ReconTable
        title="Input Tax Credit (Books vs GSTR-2B vs GSTR-3B)"
        rows={rows}
        totals={totals}
        cols={[
          { key: "books_itc_total",   label: "Books" },
          { key: "r2b_itc_total",     label: "GSTR-2B" },
          { key: "r3b_itc_total",     label: "GSTR-3B (Net)" },
          { key: "var_books_vs_r2b_itc", label: "Books − R2B", variance: true },
          { key: "var_r2b_vs_r3b_itc",   label: "R2B − R3B",   variance: true },
        ]}
        testid="summary-itc"
      />
    </div>
  );
}

function ReconTable({ title, rows, totals, cols, testid }) {
  return (
    <div className="border-t border-gray-200" data-testid={testid}>
      <div className="px-4 py-2 bg-white border-b border-gray-100 text-[12px] font-medium text-gray-800">
        {title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px] font-mono">
          <thead>
            <tr className="bg-gray-50 text-gray-600 text-[10px] uppercase tracking-wider">
              <th className="text-left px-3 py-2 w-28 border-b border-gray-200">Month</th>
              {cols.map(c => (
                <th key={c.key} className={`text-right px-3 py-2 border-b border-gray-200 ${c.variance ? "bg-amber-50/40" : ""}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.period} className={i % 2 ? "bg-gray-50/40" : "bg-white"} data-testid={`${testid}-row-${r.period}`}>
                <td className="px-3 py-2 text-gray-800 border-b border-gray-100">{r.month_label}</td>
                {cols.map(c => {
                  const v = r[c.key] || 0;
                  const cls = c.variance
                    ? Math.abs(v) < 1 ? "text-emerald-700" : "text-amber-700 font-semibold"
                    : "text-gray-900";
                  return (
                    <td key={c.key} className={`text-right px-3 py-2 border-b border-gray-100 ${cls} ${c.variance ? "bg-amber-50/30" : ""}`}>
                      {fmtINR(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="bg-gray-100 font-semibold border-t-2 border-gray-300">
              <td className="px-3 py-2 text-gray-900">Annual</td>
              {cols.map(c => {
                const v = totals[c.key] || 0;
                const cls = c.variance
                  ? Math.abs(v) < 1 ? "text-emerald-800" : "text-amber-800"
                  : "text-gray-900";
                return (
                  <td key={c.key} className={`text-right px-3 py-2 ${cls} ${c.variance ? "bg-amber-100/60" : ""}`} data-testid={`${testid}-total-${c.key}`}>
                    {fmtINR(v)}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({ ok, label }) {
  return (
    <div className={`flex items-center justify-between ${ok ? "text-emerald-700" : "text-gray-400"}`}>
      <span>{label}</span>
      {ok ? <CheckCircle2 size={11}/> : <XCircle size={11}/>}
    </div>
  );
}
