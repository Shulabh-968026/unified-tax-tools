import { useState, useRef, useCallback, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { FileText, CheckCircle2, XCircle, FolderUp, Loader2, ArrowLeft, Calculator, Plus, Trash2, History, Download, Activity } from "lucide-react";
import { toast } from "sonner";
import { http } from "@/lib/api";
import GenerationsDrawer from "@/components/GenerationsDrawer";
import { FY_OPTIONS, DEFAULT_FY } from "@/lib/fy";

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

const formatRunDate = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: true,
    }).toUpperCase();
  } catch { return iso; }
};

export default function GstReconLanding() {
  const { clientId: cid } = useParams();
  const [runId, setRunId] = useState(null);
  const [fy, setFy] = useState(DEFAULT_FY);
  const [files, setFiles] = useState([]);
  const [buckets, setBuckets] = useState({});
  const [months, setMonths] = useState([]);
  const [hasBooks, setHasBooks] = useState(false);
  const [hasMapping, setHasMapping] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState(null);
  const [summary, setSummary] = useState(null);
  const [pastRuns, setPastRuns] = useState([]);
  const [unmapped, setUnmapped] = useState([]);
  const [showPast, setShowPast] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [relaxed, setRelaxed] = useState(true); // ON by default — auto-matches same-party + same-period + same-amount
  const inputRef = useRef();

  // Load past runs on mount + after any new run is created
  const refreshPastRuns = useCallback(async () => {
    try {
      const { data } = await http.get(`/gst-recon/runs?client_id=${cid}`);
      setPastRuns(data || []);
    } catch {
      // silent — page still usable without past runs
    }
  }, [cid]);

  useEffect(() => { refreshPastRuns(); }, [refreshPastRuns]);

  const resumeRun = async (r) => {
    setRunId(r.id);
    setFy(r.fy);
    setMonths(r.months || []);
    setHasBooks(r.has_books);
    setHasMapping(r.has_mapping);
    setValidation(r.validation || null);
    setSummary(r.summary || null);
    setUnmapped(r.mapping_unmapped_ledgers || []);
    const bcounts = {};
    for (const f of (r.files || [])) bcounts[f.bucket] = (bcounts[f.bucket] || 0) + 1;
    setBuckets(bcounts);
    setFiles((r.files || []).map(f => f.filename));
    setShowPast(false);
    toast.success(`Resumed run · FY ${r.fy}`);
  };

  const newRun = () => {
    setRunId(null); setFy(DEFAULT_FY); setFiles([]); setBuckets({}); setMonths([]);
    setHasBooks(false); setHasMapping(false); setValidation(null); setSummary(null); setUnmapped([]);
    setShowPast(false);
  };

  const deleteRun = async (r) => {
    if (!window.confirm(`Delete run "${r.name}" from ${formatRunDate(r.created_at)}? This cannot be undone.`)) return;
    try {
      await http.delete(`/gst-recon/runs/${r.id}`);
      toast.success("Run deleted");
      if (runId === r.id) newRun();
      refreshPastRuns();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const ensureRun = async () => {
    if (runId) return runId;
    const { data } = await http.post("/gst-recon/runs", { client_id: cid, fy });
    setRunId(data.id);
    setMonths(data.months);
    refreshPastRuns();
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
      setUnmapped(data.mapping_unmapped_ledgers || []);
      setFiles(prev => [...prev, ...Array.from(list).map(f => f.name)]);
      setValidation(null); // stale after a new upload
      setSummary(null);    // stale after a new upload
      const reprocess = data.books_reprocessed ? " · books re-aggregated with mapping" : "";
      toast.success(`${data.accepted} file(s) categorized${reprocess}`);
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

  const runReconciliation = async () => {
    if (!runId) return;
    setBusy(true);
    try {
      const { data } = await http.post(`/gst-recon/runs/${runId}/summary`);
      setSummary(data);
      toast.success("Reconciliation complete");
      setTimeout(() => {
        document.querySelector('[data-testid="summary-panel"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reconciliation failed");
    } finally {
      setBusy(false);
    }
  };

  const downloadWorkbook = async () => {
    if (!runId) return;
    setBusy(true);
    try {
      const res = await http.get(`/gst-recon/runs/${runId}/export.xlsx?relaxed=${relaxed}`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const cd = res.headers["content-disposition"] || "";
      const m = cd.match(/filename="(.+?)"/);
      const filename = m ? m[1] : `GST_Recon_FY${fy}.xlsx`;
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`Workbook downloaded${relaxed ? " (relaxed fuzzy)" : ""}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Download failed");
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!runId) return;
    setBusy(true);
    try {
      const res = await http.get(`/gst-recon/runs/${runId}/working-paper.pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const cd = res.headers["content-disposition"] || "";
      const m = cd.match(/filename="(.+?)"/);
      const filename = m ? m[1] : `GST_Recon_WorkingPaper_FY${fy}.pdf`;
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("PDF working-paper downloaded");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "PDF download failed");
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
            {runId && (
              <button
                onClick={() => setShowHistory(true)}
                className="h-9 px-3 rounded-sm border border-gray-300 text-xs font-medium bg-white hover:bg-gray-50 inline-flex items-center gap-1.5"
                data-testid="gst-open-history"
              >
                <Activity size={13}/> History
              </button>
            )}
            {runId && (
              <button
                onClick={() => setShowPast(true)}
                className="h-9 px-3 rounded-sm border border-gray-300 text-xs font-medium bg-white hover:bg-gray-50 inline-flex items-center gap-1.5"
                data-testid="view-past-runs-btn"
              >
                <History size={13}/> Past Runs
              </button>
            )}
            <label className="text-[11px] font-mono uppercase text-gray-500">FY</label>
            <select
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              disabled={!!runId}
              className="border border-gray-300 rounded-sm h-9 px-3 text-sm font-mono bg-white"
              data-testid="gst-recon-fy-select"
            >
              {FY_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        {/* Past Runs panel — shown when no active run OR user clicks History */}
        {(showPast || !runId) && pastRuns.length > 0 && (
          <PastRunsPanel runs={pastRuns} activeId={runId} onResume={resumeRun} onDelete={deleteRun} onNew={newRun}/>
        )}

        {/* Pending Classification — ledgers the Mapping parser couldn't categorise */}
        {unmapped.length > 0 && (
          <div className="mb-6 border border-amber-300 bg-amber-50/60 rounded-sm p-4" data-testid="unmapped-ledgers">
            <div className="flex items-center gap-2 mb-2 text-amber-900 font-medium text-sm">
              <XCircle size={14}/> Pending Classification · {unmapped.length} ledger{unmapped.length !== 1 ? "s" : ""}
            </div>
            <p className="text-xs text-amber-800 mb-2">
              The Ledger Mapping file doesn't classify these tax-related ledgers. Books figures for transactions
              using these ledgers will NOT appear in the reconciliation until the Mapping is updated.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {unmapped.map((l, i) => (
                <span key={i} className="inline-block px-2 py-0.5 text-[11px] font-mono bg-white border border-amber-200 rounded-sm text-amber-900" data-testid={`unmapped-${i}`}>
                  {l}
                </span>
              ))}
            </div>
          </div>
        )}

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
            Phase D · Voucher-level reconciliation with rapidfuzz matching
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
            <button
              disabled={!summary || busy}
              onClick={downloadWorkbook}
              className={`h-9 px-3 rounded-sm border text-xs font-medium inline-flex items-center gap-1.5 ${
                summary && !busy
                  ? "border-emerald-700 bg-white text-emerald-800 hover:bg-emerald-50"
                  : "border-gray-200 text-gray-400 cursor-not-allowed bg-white"
              }`}
              data-testid="download-workbook-btn"
              title={summary ? "Download audit working-paper (XLSX)" : "Run reconciliation first"}
            >
              <Download size={13}/> Audit Working-Paper
            </button>
            <button
              disabled={!summary || busy}
              onClick={downloadPdf}
              className={`h-9 px-3 rounded-sm border text-xs font-medium inline-flex items-center gap-1.5 ${
                summary && !busy
                  ? "border-rose-700 bg-white text-rose-800 hover:bg-rose-50"
                  : "border-gray-200 text-gray-400 cursor-not-allowed bg-white"
              }`}
              data-testid="download-pdf-btn"
              title={summary ? "Download signature-ready PDF for the audit file" : "Run reconciliation first"}
            >
              <Download size={13}/> Working-Paper PDF
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

        {summary && <SummaryPanel summary={summary} runId={runId} relaxed={relaxed} onRelaxedChange={setRelaxed} />}
      </div>
      {showHistory && runId && (
        <GenerationsDrawer
          open={showHistory}
          onClose={() => setShowHistory(false)}
          endpoint={`/gst-recon/runs/${runId}`}
          moduleLabel="GST Turnover & ITC Reconciliation"
          module="gst_recon"
        />
      )}
    </div>
  );
}

function SummaryPanel({ summary, runId, relaxed, onRelaxedChange }) {
  const { rows, totals, fy } = summary;
  const [drawer, setDrawer] = useState(null); // { mode:'period'|'party', period?, month_label?, direction, party_gstin?, party_name? }
  const [tab, setTab] = useState("partywise"); // 'partywise' | 'monthly'
  const [direction, setDirection] = useState("inward"); // partywise direction

  return (
    <div className="mt-8 space-y-4" data-testid="summary-panel">
      <DashboardCards totals={totals} rows={rows}/>

      {/* Tab switcher */}
      <div className="border border-gray-200 rounded-sm bg-white overflow-hidden">
        <div className="bg-gray-50 px-2 py-2 border-b border-gray-200 flex items-center justify-between">
          <div className="flex gap-1">
            <TabBtn active={tab === "partywise"} onClick={() => setTab("partywise")} testid="tab-partywise">
              Annual Party-wise
            </TabBtn>
            <TabBtn active={tab === "monthly"} onClick={() => setTab("monthly")} testid="tab-monthly">
              12-Month Reconciliation
            </TabBtn>
          </div>
          <div className="text-[10px] font-mono text-gray-500 pr-2">
            FY {fy} · all values in INR
          </div>
        </div>

        {tab === "partywise" && (
          <PartywisePanel runId={runId} direction={direction} onDirectionChange={setDirection}
                          onPartyDrill={(party_gstin, party_name) => setDrawer({ mode: "party", direction, party_gstin, party_name })}/>
        )}

        {tab === "monthly" && (
          <>
            <ReconTable
              title="Outward Turnover (Books vs GSTR-1 vs GSTR-3B)"
              rows={rows}
              totals={totals}
              cols={[
                { key: "books_outward_taxable", label: "Books" },
                { key: "r1_outward_taxable",    label: "GSTR-1", drillDirection: "outward" },
                { key: "r3b_outward_taxable",   label: "GSTR-3B" },
                { key: "var_books_vs_r1_outward", label: "Books − R1", variance: true },
                { key: "var_r1_vs_r3b_outward",   label: "R1 − R3B",   variance: true },
              ]}
              onDrill={(period, monthLabel, dir) => setDrawer({ mode: "period", period, month_label: monthLabel, direction: dir })}
              testid="summary-outward"
            />
            <ReconTable
              title="Input Tax Credit (Books vs GSTR-2B vs GSTR-3B)"
              rows={rows}
              totals={totals}
              cols={[
                { key: "books_itc_total",   label: "Books" },
                { key: "r2b_itc_total",     label: "GSTR-2B", drillDirection: "inward" },
                { key: "r3b_itc_total",     label: "GSTR-3B (Net)" },
                { key: "var_books_vs_r2b_itc", label: "Books − R2B", variance: true },
                { key: "var_r2b_vs_r3b_itc",   label: "R2B − R3B",   variance: true },
              ]}
              onDrill={(period, monthLabel, dir) => setDrawer({ mode: "period", period, month_label: monthLabel, direction: dir })}
              testid="summary-itc"
            />
          </>
        )}
      </div>

      {drawer && <MatchDrawer runId={runId} drawer={drawer} relaxed={relaxed} onRelaxedChange={onRelaxedChange} onClose={() => setDrawer(null)} />}
    </div>
  );
}

function TabBtn({ active, onClick, children, testid }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium rounded-sm transition ${
        active ? "bg-white border border-gray-300 text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900"
      }`}
      data-testid={testid}
    >
      {children}
    </button>
  );
}

function PartywisePanel({ runId, direction, onDirectionChange, onPartyDrill }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    http.get(`/gst-recon/runs/${runId}/partywise?direction=${direction}`)
      .then(({ data: d }) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { toast.error(e?.response?.data?.detail || "Party-wise failed"); setLoading(false); } });
    return () => { cancelled = true; };
  }, [runId, direction]);

  const portalLabel = direction === "inward" ? "GSTR-2B" : "GSTR-1";

  return (
    <div data-testid="partywise-panel">
      <div className="px-4 py-3 border-b border-gray-100 bg-white flex items-center justify-between">
        <div className="text-[12px] font-medium text-gray-800">
          Annual Party-wise Comparison
          <span className="ml-2 text-[10px] font-mono text-gray-500">
            {direction === "inward" ? "(ITC values · click row to drill)" : "(Taxable values · click row to drill)"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono uppercase tracking-wider text-gray-500">View</span>
          <select
            value={direction}
            onChange={(e) => onDirectionChange(e.target.value)}
            className="border border-gray-300 rounded-sm h-7 px-2 text-xs font-mono bg-white"
            data-testid="partywise-direction-select"
          >
            <option value="inward">Input Tax (Books vs GSTR-2B)</option>
            <option value="outward">Outward (Books vs GSTR-1)</option>
          </select>
        </div>
      </div>

      {loading && <div className="p-8 text-center text-sm text-gray-500"><Loader2 className="inline animate-spin mr-2" size={14}/>Aggregating party-wise…</div>}
      {!loading && data && <PartywiseTable data={data} portalLabel={portalLabel} direction={direction} onPartyDrill={onPartyDrill}/>}
    </div>
  );
}

function PartywiseTable({ data, portalLabel, direction, onPartyDrill }) {
  const rows = data.rows || [];
  const totals = data.totals || {};
  if (!rows.length) {
    return <div className="p-8 text-center text-sm text-gray-400 font-mono">No party-wise records — upload Books with party GSTINs and {portalLabel} files.</div>;
  }

  // Column choice depends on direction:
  //   inward  → ITC = igst+cgst+sgst+cess (tax only)
  //   outward → taxable value (excludes tax — that's the "turnover" comparison)
  const booksKey  = direction === "inward" ? "books_tax"  : "books_taxable";
  const portalKey = direction === "inward" ? "portal_tax" : "portal_taxable";
  const diffKey   = direction === "inward" ? "diff_tax"   : "diff_taxable";
  const valueLabel = direction === "inward" ? "ITC" : "Taxable Value";

  return (
    <div className="overflow-x-auto" data-testid="partywise-table">
      <table className="w-full text-[12px] font-mono">
        <thead>
          <tr className="bg-gray-50 text-gray-600 text-[10px] uppercase tracking-wider sticky top-0">
            <th className="text-left px-3 py-2 border-b border-gray-200 w-44">GSTIN</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Party Name</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">Books ({valueLabel})</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">{portalLabel} ({valueLabel})</th>
            <th className="text-right px-3 py-2 border-b border-gray-200 bg-amber-50/40">Books − {portalLabel}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const diff = r[diffKey] || 0;
            const cls = Math.abs(diff) < 1 ? "text-emerald-700" : "text-amber-700 font-semibold";
            return (
              <tr key={r.party_gstin} className={`${i % 2 ? "bg-gray-50/40" : "bg-white"} cursor-pointer hover:bg-blue-50`}
                  onClick={() => onPartyDrill && onPartyDrill(r.party_gstin, r.party_name)}
                  title={`Drill into ${r.party_name || r.party_gstin} (all months)`}
                  data-testid={`partywise-row-${r.party_gstin}`}>
                <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{r.party_gstin}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-gray-900 hover:underline">{r.party_name || "—"}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r[booksKey])}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r[portalKey])}</td>
                <td className={`px-3 py-2 border-b border-gray-100 text-right bg-amber-50/30 ${cls}`}>{fmtINR(diff)}</td>
              </tr>
            );
          })}
          <tr className="bg-gray-100 font-semibold border-t-2 border-gray-300">
            <td className="px-3 py-2 text-gray-900">ANNUAL</td>
            <td className="px-3 py-2 text-gray-700">{rows.length} parties</td>
            <td className="px-3 py-2 text-right">{fmtINR(totals[booksKey])}</td>
            <td className="px-3 py-2 text-right">{fmtINR(totals[portalKey])}</td>
            <td className="px-3 py-2 text-right bg-amber-100/60">{fmtINR(totals[diffKey])}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ReconTable({ title, rows, totals, cols, testid, onDrill }) {
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
                  const drillable = c.drillDirection && onDrill;
                  return (
                    <td
                      key={c.key}
                      className={`text-right px-3 py-2 border-b border-gray-100 ${cls} ${c.variance ? "bg-amber-50/30" : ""} ${drillable ? "cursor-pointer hover:bg-blue-50 hover:underline" : ""}`}
                      onClick={drillable ? () => onDrill(r.period, r.month_label, c.drillDirection) : undefined}
                      data-testid={drillable ? `drill-${c.drillDirection}-${r.period}` : undefined}
                      title={drillable ? `Click to drill into ${r.month_label} ${c.label} vouchers` : undefined}
                    >
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

const TABS = [
  { id: "matched",          label: "Matched",          dot: "bg-emerald-500" },
  { id: "value_mismatch",   label: "Value Mismatch",   dot: "bg-amber-500" },
  { id: "date_mismatch",    label: "Date Mismatch",    dot: "bg-blue-500" },
  { id: "missing_in_books", label: "Missing in Books", dot: "bg-red-500" },
  { id: "missing_in_portal",label: "Missing in Portal",dot: "bg-red-500" },
];

function MatchDrawer({ runId, drawer, relaxed, onRelaxedChange, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("matched");
  const isPartyMode = drawer.mode === "party";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const url = isPartyMode
      ? `/gst-recon/runs/${runId}/match-party?party_gstin=${encodeURIComponent(drawer.party_gstin)}&direction=${drawer.direction}&relaxed=${relaxed}`
      : `/gst-recon/runs/${runId}/match?period=${drawer.period}&direction=${drawer.direction}&relaxed=${relaxed}`;
    http.post(url)
      .then(({ data: d }) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { toast.error(e?.response?.data?.detail || "Match failed"); setLoading(false); } });
    return () => { cancelled = true; };
  }, [runId, drawer.period, drawer.party_gstin, drawer.direction, relaxed, isPartyMode]);

  const counts = data?.counts || {};
  const portalLabel = drawer.direction === "outward" ? "GSTR-1" : "GSTR-2B";
  const headerTitle = isPartyMode
    ? `${drawer.party_name || drawer.party_gstin} · all months`
    : `${drawer.month_label} · ${drawer.direction}`;
  const headerSubtitle = isPartyMode
    ? `${drawer.party_gstin} · Books ↔ ${portalLabel}`
    : `Books ↔ ${portalLabel}`;

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} data-testid="match-drawer-backdrop"/>
      <div className="fixed top-0 right-0 h-screen w-[min(92vw,1100px)] bg-white shadow-2xl z-50 flex flex-col" data-testid="match-drawer">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Voucher-level match</div>
            <h2 className="text-lg font-semibold text-gray-900 mt-1">
              {headerTitle}
            </h2>
            <div className="text-[11px] font-mono text-gray-500 mt-0.5">{headerSubtitle}</div>
          </div>
          <div className="flex items-center gap-3">
            <label className="inline-flex items-center gap-2 text-xs font-medium cursor-pointer select-none" data-testid="relaxed-fuzzy-toggle">
              <input
                type="checkbox"
                checked={relaxed}
                onChange={(e) => onRelaxedChange(e.target.checked)}
                className="h-4 w-4 accent-blue-600"
                data-testid="relaxed-fuzzy-checkbox"
              />
              <span className={relaxed ? "text-blue-700" : "text-gray-700"}>
                Relaxed Fuzzy
              </span>
              <span className="text-[10px] font-normal text-gray-500" title="When enabled, residual unmatched vouchers with same Party + Month + Amount are auto-matched even if bill numbers and dates differ.">
                (party + month + amount)
              </span>
            </label>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-2" data-testid="match-drawer-close">×</button>
          </div>
        </div>

        {/* Tabs */}
        <div className="px-6 pt-3 border-b border-gray-200 bg-gray-50">
          <div className="flex gap-1">
            {TABS.map(t => {
              const n = counts[t.id] ?? 0;
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-3 py-2 text-xs font-medium rounded-t-sm border-x border-t flex items-center gap-2 ${active ? "bg-white border-gray-300 text-gray-900" : "border-transparent text-gray-600 hover:text-gray-900"}`}
                  data-testid={`match-tab-${t.id}`}
                >
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${t.dot}`}/>
                  {t.label}
                  <span className="font-mono text-[10px] text-gray-500">({n})</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto">
          {loading && <div className="p-8 text-center text-sm text-gray-500"><Loader2 className="inline animate-spin mr-2" size={14}/>Matching invoices…</div>}
          {!loading && data && (
            <MatchTable rows={data[tab] || []} tab={tab} portalLabel={portalLabel} />
          )}
        </div>
      </div>
    </>
  );
}

function MatchTable({ rows, tab, portalLabel }) {
  if (!rows.length) {
    return <div className="p-8 text-center text-sm text-gray-400 font-mono">No records in this category.</div>;
  }
  // The shape of each row depends on tab:
  // matched/value_mismatch/date_mismatch: { books, portal, value_diff, books_date, portal_date, fuzzy_score? }
  // missing_in_*: flat invoice record
  const isPair = tab === "matched" || tab === "value_mismatch" || tab === "date_mismatch";

  if (isPair) {
    return (
      <table className="w-full text-[12px] font-mono">
        <thead className="bg-gray-50 text-gray-600 text-[10px] uppercase tracking-wider sticky top-0">
          <tr>
            <th className="text-left px-3 py-2 border-b border-gray-200">Party GSTIN</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Party Name</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Books #</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">{portalLabel} #</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">Books Total</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">{portalLabel} Total</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">Δ</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Books Date</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">{portalLabel} Date</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">Match</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => {
            const pname = p.books?.party_name || p.portal?.party_name || "—";
            const matchType = p.relaxed_match ? "Relaxed" : (p.fuzzy_score ? `Fuzzy ${p.fuzzy_score}` : "Exact");
            const matchCls = p.relaxed_match ? "text-blue-700 font-semibold" : "text-gray-500";
            return (
              <tr key={i} className={i % 2 ? "bg-gray-50/40" : "bg-white"} data-testid={`match-row-${tab}-${i}`}>
                <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{p.books?.party_gstin || p.portal?.party_gstin}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-gray-900">{pname}</td>
                <td className="px-3 py-2 border-b border-gray-100">{p.books?.voucher_no || p.books?.invoice_no || "—"}</td>
                <td className="px-3 py-2 border-b border-gray-100">{p.portal?.invoice_no || "—"}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(p.books?.total)}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(p.portal?.total)}</td>
                <td className={`px-3 py-2 border-b border-gray-100 text-right ${Math.abs(p.value_diff || 0) < 1 ? "text-gray-500" : "text-amber-700 font-semibold"}`}>{fmtINR(p.value_diff)}</td>
                <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{p.books_date || "—"}</td>
                <td className={`px-3 py-2 border-b border-gray-100 ${tab === "date_mismatch" ? "text-blue-700 font-semibold" : "text-gray-700"}`}>{p.portal_date || "—"}</td>
                <td className={`px-3 py-2 border-b border-gray-100 text-right ${matchCls}`}>{matchType}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }

  // missing_in_* — flat invoice list
  const invKey = tab === "missing_in_books" ? "invoice_no" : "voucher_no";
  return (
    <table className="w-full text-[12px] font-mono">
      <thead className="bg-gray-50 text-gray-600 text-[10px] uppercase tracking-wider sticky top-0">
        <tr>
          <th className="text-left px-3 py-2 border-b border-gray-200">Party GSTIN</th>
          <th className="text-left px-3 py-2 border-b border-gray-200">Party Name</th>
          <th className="text-left px-3 py-2 border-b border-gray-200">{tab === "missing_in_books" ? "Portal #" : "Books #"}</th>
          <th className="text-left px-3 py-2 border-b border-gray-200">Date</th>
          <th className="text-right px-3 py-2 border-b border-gray-200">Taxable</th>
          <th className="text-right px-3 py-2 border-b border-gray-200">IGST</th>
          <th className="text-right px-3 py-2 border-b border-gray-200">CGST</th>
          <th className="text-right px-3 py-2 border-b border-gray-200">SGST</th>
          <th className="text-right px-3 py-2 border-b border-gray-200">Total</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={i % 2 ? "bg-gray-50/40" : "bg-white"} data-testid={`match-row-${tab}-${i}`}>
            <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{r.party_gstin || "—"}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{r.party_name || "—"}</td>
            <td className="px-3 py-2 border-b border-gray-100">{r[invKey] || r.invoice_no || r.voucher_no || "—"}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-gray-700">{r.date || "—"}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r.taxable)}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r.igst)}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r.cgst)}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r.sgst)}</td>
            <td className="px-3 py-2 border-b border-gray-100 text-right">{fmtINR(r.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
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

function PastRunsPanel({ runs, activeId, onResume, onDelete, onNew }) {
  return (
    <div className="mb-8 border border-gray-200 rounded-sm bg-white overflow-hidden" data-testid="past-runs-panel">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-wider text-gray-600">
          <History size={13}/> Past Runs · {runs.length}
        </div>
        <button
          onClick={onNew}
          className="h-7 px-3 rounded-sm border border-gray-900 bg-gray-900 text-white text-xs font-medium inline-flex items-center gap-1.5 hover:bg-gray-800"
          data-testid="new-run-btn"
        >
          <Plus size={12}/> New Run
        </button>
      </div>
      <div className="divide-y divide-gray-100">
        {runs.map(r => {
          const fileCount = (r.files || []).length;
          const coverage = (r.months || []).filter(m => m.gstr1 && m.gstr2b && m.gstr3b).length;
          const isActive = r.id === activeId;
          return (
            <div
              key={r.id}
              className={`px-4 py-3 flex items-center justify-between hover:bg-gray-50 ${isActive ? "bg-blue-50/40" : ""}`}
              data-testid={`past-run-${r.id}`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <div className="font-medium text-sm text-gray-900">{r.name || `Run ${r.id.slice(0, 8)}`}</div>
                  <span className="text-[10px] font-mono uppercase tracking-wider bg-gray-100 text-gray-700 px-2 py-0.5 rounded-sm">FY {r.fy}</span>
                  {isActive && <span className="text-[10px] font-mono uppercase tracking-wider bg-blue-100 text-blue-800 px-2 py-0.5 rounded-sm">Active</span>}
                  <StatusPill status={r.status}/>
                </div>
                <div className="mt-1 text-[11px] font-mono text-gray-500 flex items-center gap-3">
                  <span>{formatRunDate(r.created_at)}</span>
                  <span>·</span>
                  <span>{fileCount} files</span>
                  <span>·</span>
                  <span>{coverage}/12 months</span>
                  {r.validation?.ok && <><span>·</span><span className="text-emerald-700">validated</span></>}
                  {r.summary && <><span>·</span><span className="text-blue-700">summarised</span></>}
                </div>
              </div>
              <div className="flex items-center gap-2 ml-3">
                <button
                  onClick={() => onResume(r)}
                  disabled={isActive}
                  className={`h-8 px-3 rounded-sm border text-xs font-medium ${isActive ? "border-gray-200 text-gray-400 cursor-not-allowed" : "border-gray-300 bg-white hover:bg-gray-100"}`}
                  data-testid={`resume-run-${r.id}`}
                >
                  {isActive ? "Current" : "Resume"}
                </button>
                <button
                  onClick={() => onDelete(r)}
                  className="h-8 w-8 rounded-sm border border-gray-200 bg-white text-gray-500 hover:border-red-300 hover:text-red-600 inline-flex items-center justify-center"
                  title="Delete run"
                  data-testid={`delete-run-${r.id}`}
                >
                  <Trash2 size={12}/>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    draft:       { cls: "bg-gray-100 text-gray-700",   label: "Draft" },
    summarized:  { cls: "bg-blue-100 text-blue-800",   label: "Summarised" },
    complete:    { cls: "bg-emerald-100 text-emerald-800", label: "Complete" },
  };
  const s = map[status] || map.draft;
  return <span className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-sm ${s.cls}`}>{s.label}</span>;
}

// =========================================================================
// Summary Dashboard — discrepancy cards
// =========================================================================
function DashboardCards({ totals, rows }) {
  // Count months with material variance (|Δ| >= ₹1)
  const monthsWithR1vs3b   = rows.filter(r => Math.abs(r.var_r1_vs_r3b_outward || 0) >= 1).length;
  const monthsWithR2bvs3b  = rows.filter(r => Math.abs(r.var_r2b_vs_r3b_itc || 0) >= 1).length;
  const monthsWithBooksR1  = rows.filter(r => Math.abs(r.var_books_vs_r1_outward || 0) >= 1).length;
  const monthsWithBooksR2b = rows.filter(r => Math.abs(r.var_books_vs_r2b_itc || 0) >= 1).length;

  const absTurnover = Math.abs(totals.var_r1_vs_r3b_outward || 0);
  const absITC      = Math.abs(totals.var_r2b_vs_r3b_itc   || 0);
  const absBooksR1  = Math.abs(totals.var_books_vs_r1_outward || 0);
  const absBooksR2b = Math.abs(totals.var_books_vs_r2b_itc || 0);

  const cards = [
    {
      testid: "card-books-vs-r1",
      title: "Books vs GSTR-1",
      subtitle: "Outward Turnover",
      value: totals.books_outward_taxable - totals.r1_outward_taxable,
      base: totals.r1_outward_taxable,
      monthsFlagged: monthsWithBooksR1,
      variant: monthsWithBooksR1 === 0 ? "ok" : "warn",
    },
    {
      testid: "card-r1-vs-r3b",
      title: "GSTR-1 vs GSTR-3B",
      subtitle: "Outward Turnover",
      value: totals.var_r1_vs_r3b_outward,
      base: totals.r3b_outward_taxable,
      monthsFlagged: monthsWithR1vs3b,
      variant: monthsWithR1vs3b === 0 ? "ok" : "warn",
    },
    {
      testid: "card-books-vs-r2b",
      title: "Books vs GSTR-2B",
      subtitle: "Input Tax Credit",
      value: totals.var_books_vs_r2b_itc,
      base: totals.r2b_itc_total,
      monthsFlagged: monthsWithBooksR2b,
      variant: monthsWithBooksR2b === 0 ? "ok" : (absBooksR2b > 100000 ? "danger" : "warn"),
    },
    {
      testid: "card-r2b-vs-r3b",
      title: "GSTR-2B vs GSTR-3B",
      subtitle: "Input Tax Credit",
      value: totals.var_r2b_vs_r3b_itc,
      base: totals.r3b_itc_total,
      monthsFlagged: monthsWithR2bvs3b,
      variant: monthsWithR2bvs3b === 0 ? "ok" : (absITC > 100000 ? "danger" : "warn"),
    },
  ];

  const totalFlagged = cards.reduce((acc, c) => acc + c.monthsFlagged, 0);
  const worstVariant = cards.some(c => c.variant === "danger") ? "danger"
                      : cards.some(c => c.variant === "warn") ? "warn" : "ok";

  return (
    <div className="border border-gray-200 rounded-sm bg-white overflow-hidden" data-testid="dashboard-cards">
      <div className={`px-4 py-3 border-b border-gray-200 flex items-center justify-between ${
        worstVariant === "danger" ? "bg-red-50" : worstVariant === "warn" ? "bg-amber-50" : "bg-emerald-50"
      }`}>
        <div className="text-[11px] font-mono uppercase tracking-wider text-gray-700">
          Reconciliation Health · FY {summary_fy_from_rows(rows)}
        </div>
        <div className={`text-[11px] font-mono ${
          worstVariant === "danger" ? "text-red-700" : worstVariant === "warn" ? "text-amber-700" : "text-emerald-700"
        }`} data-testid="dashboard-overall-status">
          {totalFlagged === 0 ? "ALL RECONCILED" : `${totalFlagged} MONTH-ISSUE${totalFlagged > 1 ? "S" : ""} FLAGGED`}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-gray-100">
        {cards.map(c => <DashCard key={c.testid} {...c}/>)}
      </div>
    </div>
  );
}

function summary_fy_from_rows(rows) {
  if (!rows?.length) return "";
  const first = rows[0]?.month_label || "";
  const last = rows[rows.length - 1]?.month_label || "";
  if (!first || !last) return "";
  return `${first.split(" ")[1]}-${last.split(" ")[1].slice(-2)}`;
}

function DashCard({ title, subtitle, value, base, monthsFlagged, variant, testid }) {
  const pct = base ? (Math.abs(value) / Math.abs(base)) * 100 : 0;
  const sign = (value || 0) > 0 ? "+" : "";
  const tone = variant === "danger" ? {
    dot: "bg-red-500", border: "border-l-4 border-red-500", num: "text-red-700", chip: "bg-red-100 text-red-800",
  } : variant === "warn" ? {
    dot: "bg-amber-500", border: "border-l-4 border-amber-500", num: "text-amber-700", chip: "bg-amber-100 text-amber-800",
  } : {
    dot: "bg-emerald-500", border: "border-l-4 border-emerald-500", num: "text-emerald-700", chip: "bg-emerald-100 text-emerald-800",
  };
  return (
    <div className={`p-4 hover:bg-gray-50 ${tone.border}`} data-testid={testid}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${tone.dot}`}/>
        <div className="text-[11px] font-mono uppercase tracking-wider text-gray-500">{subtitle}</div>
      </div>
      <div className="text-sm font-medium text-gray-900">{title}</div>
      <div className={`mt-3 text-2xl font-semibold font-mono ${tone.num}`} data-testid={`${testid}-value`}>
        {sign}{fmtINR(value)}
      </div>
      <div className="mt-1 text-[11px] font-mono text-gray-500">
        {pct.toFixed(2)}% of {fmtINR(base)}
      </div>
      <div className="mt-3 inline-flex items-center gap-1.5">
        <span className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-sm ${tone.chip}`} data-testid={`${testid}-months`}>
          {monthsFlagged === 0 ? "0 / 12 flagged" : `${monthsFlagged} / 12 flagged`}
        </span>
      </div>
    </div>
  );
}
