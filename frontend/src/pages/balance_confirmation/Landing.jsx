import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileText, FolderUp, Loader2, Plus, Trash2, Download, Upload, Mail, FileEdit, ShieldCheck, X, Search, Send, Bell, Activity } from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

/* ---------- Helpers ---------- */
const inr = (v) => {
  const n = Number(v || 0);
  if (n === 0) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};
const CATS = [
  { key: "trade_receivable", label: "Receivables", chip: "emerald" },
  { key: "trade_payable",    label: "Payables",    chip: "amber" },
  { key: "bank",             label: "Banks",       chip: "indigo" },
  { key: "other",            label: "Other",       chip: "slate" },
];
const CHIP_CLS = {
  emerald: "bg-emerald-50 text-emerald-800 border-emerald-200",
  amber:   "bg-amber-50 text-amber-800 border-amber-200",
  indigo:  "bg-indigo-50 text-indigo-800 border-indigo-200",
  slate:   "bg-slate-50 text-slate-700 border-slate-200",
  rose:    "bg-rose-50 text-rose-800 border-rose-200",
};
const STATUS_CHIP = {
  not_sent:  { label: "Not Sent",  cls: "bg-gray-100 text-gray-600 border-gray-200" },
  queued:    { label: "Queued",    cls: "bg-blue-50 text-blue-700 border-blue-200" },
  sent:      { label: "Sent",      cls: "bg-blue-100 text-blue-800 border-blue-300" },
  delivered: { label: "Delivered", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  opened:    { label: "Opened",    cls: "bg-emerald-100 text-emerald-800 border-emerald-300" },
  clicked:   { label: "Clicked",   cls: "bg-emerald-200 text-emerald-900 border-emerald-400" },
  confirmed: { label: "Confirmed", cls: "bg-emerald-700 text-white border-emerald-800" },
  disputed:  { label: "Disputed",  cls: "bg-amber-200 text-amber-900 border-amber-300" },
  bounced:   { label: "Bounced",   cls: "bg-rose-100 text-rose-800 border-rose-300" },
  failed:    { label: "Failed",    cls: "bg-rose-200 text-rose-900 border-rose-400" },
};

/* ============================================================
 * Landing page — covers no-run AND in-run states (same URL pattern as GST Recon).
 * ============================================================ */
export default function BalanceConfirmationLanding() {
  const { clientId, rid } = useParams();
  const navigate = useNavigate();

  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [ledgers, setLedgers] = useState([]);
  const [activeTab, setActiveTab] = useState("trade_receivable");
  const [missingEmailOnly, setMissingEmailOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [showSendLog, setShowSendLog] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [universalCc, setUniversalCc] = useState("");
  const dropRef = useRef(null);

  /* Load past runs + (optionally) hydrate run if URL has :rid */
  useEffect(() => {
    if (!clientId) return;
    http.get(`/balance-confirmation/runs?client_id=${clientId}`)
      .then(({ data }) => setRuns(data || []))
      .catch(() => {});
  }, [clientId]);

  useEffect(() => {
    if (!rid) { setRun(null); setLedgers([]); return; }
    refreshRun();
    refreshLedgers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  const refreshRun = async () => {
    const { data } = await http.get(`/balance-confirmation/runs/${rid}`);
    setRun(data);
  };
  const refreshLedgers = async () => {
    const { data } = await http.get(`/balance-confirmation/runs/${rid}/ledgers`);
    setLedgers(data?.rows || []);
  };

  /* ---------- Run create / resume / delete ---------- */
  const createRun = async () => {
    const fy = window.prompt("Enter financial year (e.g. 2024-25):", "2024-25");
    if (!fy) return;
    setBusy(true);
    try {
      const { data } = await http.post(`/balance-confirmation/runs`, { client_id: clientId, fy });
      toast.success(`Run created · FY ${data.fy}`);
      navigate(`/dashboard/clients/${clientId}/utilities/balance-confirmation/runs/${data.id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create run");
    } finally { setBusy(false); }
  };
  const deleteRun = async (id) => {
    if (!window.confirm("Delete this run? Ledgers will be removed.")) return;
    await http.delete(`/balance-confirmation/runs/${id}`);
    toast.success("Run deleted");
    setRuns(r => r.filter(x => x.id !== id));
    if (id === rid) navigate(`/dashboard/clients/${clientId}/utilities/balance-confirmation`);
  };

  /* ---------- Books upload ---------- */
  const onFileDrop = async (file) => {
    if (!file) return;
    if (!rid) { toast.error("Create a run first"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await http.post(`/balance-confirmation/runs/${rid}/upload-books`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Ingested ${data.ledger_count} ledgers`);
      refreshRun(); refreshLedgers();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally { setBusy(false); }
  };

  /* ---------- Ledger CSV import / export ---------- */
  const exportCsv = async () => {
    if (!rid) return;
    const res = await http.get(`/balance-confirmation/runs/${rid}/ledgers/export.csv`, { responseType: "blob" });
    const cd = res.headers["content-disposition"] || "";
    const m = cd.match(/filename="(.+?)"/);
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(new Blob([res.data]));
    a.download = m ? m[1] : "EmailMaster.csv";
    document.body.appendChild(a); a.click(); a.remove();
    toast.success("CSV downloaded");
  };
  const importCsv = async (file) => {
    if (!file || !rid) return;
    const fd = new FormData(); fd.append("file", file);
    setBusy(true);
    try {
      const { data } = await http.post(`/balance-confirmation/runs/${rid}/ledgers/import.csv`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`${data.matched} of ${data.rows_in_csv} ledgers updated${data.not_found?.length ? ` · ${data.not_found.length} unmatched` : ""}`);
      refreshLedgers(); refreshRun();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import failed");
    } finally { setBusy(false); }
  };

  /* ---------- Patch ledger field inline ---------- */
  const patchLedger = async (ledger_id, patch) => {
    try {
      const { data } = await http.patch(`/balance-confirmation/runs/${rid}/ledgers/${ledger_id}`, patch);
      setLedgers(rows => rows.map(r => r.ledger_id === ledger_id ? { ...r, ...data } : r));
      // Refresh summary in run header (best-effort)
      refreshRun();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Update failed");
    }
  };

  /* ---------- Phase 3 — Bulk Send + Reminders ---------- */
  const sendIds = async (ledger_ids, isReminder = false) => {
    if (!ledger_ids?.length) return;
    setBusy(true);
    try {
      const cc = universalCc.split(",").map(s => s.trim()).filter(s => s.includes("@"));
      const { data } = await http.post(`/balance-confirmation/runs/${rid}/send`, {
        ledger_ids, cc, is_reminder: isReminder,
      });
      const tone = data.failed > 0 ? "warning" : "success";
      const msg = `Sent ${data.sent} · Failed ${data.failed}${data.skipped ? ` · Skipped ${data.skipped}` : ""}`;
      tone === "success" ? toast.success(msg) : toast.warning(msg);
      if (data.failed && data.results) {
        const firstErr = data.results.find(r => !r.ok);
        if (firstErr) toast.error(`${firstErr.name || firstErr.ledger_id}: ${firstErr.error}`);
      }
      setSelected(new Set());
      refreshLedgers(); refreshRun();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk send failed");
    } finally { setBusy(false); }
  };
  const sendSelected = () => sendIds(Array.from(selected), false);
  const remindSelected = () => sendIds(Array.from(selected), true);
  const sendAllVisible = () => {
    const ids = visibleLedgers.filter(l => l.email && (l.confirmation_status === "not_sent" || l.confirmation_status === "failed")).map(l => l.ledger_id);
    if (!ids.length) { toast.info("No eligible ledgers in current view (need email + status not_sent or failed)"); return; }
    if (!window.confirm(`Send confirmations to ${ids.length} parties?`)) return;
    sendIds(ids, false);
  };
  const toggleRow = (id) => setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = (rows) => setSelected(prev => {
    const allIds = rows.map(r => r.ledger_id);
    const allSelected = allIds.every(id => prev.has(id));
    return allSelected ? new Set() : new Set(allIds);
  });

  /* ---------- Filtered rows ---------- */
  const visibleLedgers = useMemo(() => {
    let rows = ledgers;
    if (activeTab !== "all") rows = rows.filter(r => r.category === activeTab);
    if (missingEmailOnly) rows = rows.filter(r => !r.email);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(r =>
        (r.name || "").toLowerCase().includes(q) ||
        (r.parent_group || "").toLowerCase().includes(q) ||
        (r.email || "").toLowerCase().includes(q));
    }
    return rows;
  }, [ledgers, activeTab, missingEmailOnly, search]);

  const summary = run?.summary;

  return (
    <div className="min-h-screen bg-[#f9f9f8]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <Link to={`/dashboard/clients/${clientId}`} className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-black mb-6" data-testid="bc-back">
          <ArrowLeft size={14}/> Back to Utilities
        </Link>

        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] font-mono text-gray-500">Utility</div>
            <h1 className="font-heading text-3xl tracking-tight mt-1">Balance Confirmation</h1>
            <p className="text-sm text-gray-600 mt-1.5 max-w-2xl">
              Ingest the year's books, classify ledgers, link emails, and (next phases) bulk-send confirmations to vendors, customers and banks with secure response links.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowTemplates(true)} className="h-9 px-3 rounded-sm border border-gray-300 text-xs font-medium inline-flex items-center gap-1.5 hover:bg-white" data-testid="bc-open-templates">
              <FileEdit size={13}/> Email Templates
            </button>
            <button onClick={() => setShowAuth(true)} className="h-9 px-3 rounded-sm border border-gray-300 text-xs font-medium inline-flex items-center gap-1.5 hover:bg-white" data-testid="bc-open-auth">
              <ShieldCheck size={13}/> Authorisation Letter
            </button>
            <button onClick={createRun} disabled={busy} className="h-9 px-3 rounded-sm border border-emerald-700 bg-emerald-700 text-white text-xs font-medium inline-flex items-center gap-1.5 hover:bg-emerald-800 disabled:opacity-50" data-testid="bc-new-run">
              <Plus size={13}/> New Run
            </button>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* ---------- Past Runs sidebar ---------- */}
          <div className="col-span-3 space-y-3" data-testid="bc-past-runs">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Past Runs · {runs.length}</div>
            {runs.length === 0 && <div className="text-xs text-gray-500 border border-dashed border-gray-300 p-4">No runs yet. Click "New Run" to start.</div>}
            {runs.map(r => {
              const active = r.id === rid;
              const t = r.summary?.total ?? 0;
              return (
                <div key={r.id} className={`relative border ${active ? "border-emerald-700 bg-white" : "border-gray-200 bg-white hover:border-gray-300"} p-3 cursor-pointer rounded-sm transition`}
                  onClick={() => navigate(`/dashboard/clients/${clientId}/utilities/balance-confirmation/runs/${r.id}`)}
                  data-testid={`bc-run-${r.id}`}>
                  <div className="text-sm font-semibold truncate">{r.name}</div>
                  <div className="text-[11px] text-gray-500 font-mono mt-0.5">FY {r.fy} · As at {r.as_at_date || "—"}</div>
                  <div className="text-[11px] text-gray-500 mt-1.5">Status: <span className={`font-medium ${r.status === "ingested" ? "text-emerald-700" : "text-gray-700"}`}>{r.status}</span></div>
                  {t > 0 && <div className="text-[10px] text-gray-500 font-mono mt-0.5">{t} ledgers · {r.summary?.with_email || 0} mapped</div>}
                  <button onClick={(e) => { e.stopPropagation(); deleteRun(r.id); }} className="absolute top-2 right-2 text-gray-300 hover:text-red-600" data-testid={`bc-run-${r.id}-delete`}><Trash2 size={12}/></button>
                </div>
              );
            })}
          </div>

          {/* ---------- Workbench ---------- */}
          <div className="col-span-9 space-y-6">
            {!rid && (
              <div className="border border-dashed border-gray-300 bg-white p-12 text-center rounded-sm" data-testid="bc-empty">
                <div className="text-sm text-gray-600">Select a run on the left or click <span className="font-semibold">New Run</span> to begin.</div>
              </div>
            )}

            {rid && run && (
              <>
                {/* Run header strip */}
                <div className="bg-white border border-gray-200 p-5 rounded-sm">
                  <div className="flex items-start justify-between">
                    <div>
                      <h2 className="font-heading text-xl">{run.name}</h2>
                      <div className="text-[11px] font-mono text-gray-500 mt-1">FY {run.fy} · As at {run.as_at_date || "—"} · Source: {run.source_filename || "(not uploaded)"}</div>
                    </div>
                  </div>

                  {/* Summary cards */}
                  {summary && (
                    <div className="grid grid-cols-4 gap-3 mt-5">
                      {CATS.map(c => {
                        const s = summary.categories?.[c.key] || { count: 0, balance: 0, with_email: 0 };
                        return (
                          <div key={c.key} className={`border p-3 rounded-sm ${CHIP_CLS[c.chip]}`} data-testid={`bc-summary-${c.key}`}>
                            <div className="text-[10px] uppercase tracking-widest font-mono opacity-80">{c.label}</div>
                            <div className="font-mono text-lg font-bold mt-1">{s.count}</div>
                            <div className="text-[11px] mt-0.5 font-mono">{inr(s.balance)} · {s.with_email}/{s.count} email</div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Books upload zone */}
                  {!run.source_filename && (
                    <div ref={dropRef}
                      className="mt-5 border border-dashed border-gray-300 p-6 rounded-sm text-center hover:bg-gray-50 cursor-pointer"
                      onDragOver={e => { e.preventDefault(); }}
                      onDrop={e => { e.preventDefault(); onFileDrop(e.dataTransfer.files?.[0]); }}
                      onClick={() => document.getElementById("bc-books-input").click()}
                      data-testid="bc-books-dropzone">
                      <FolderUp size={28} className="mx-auto text-gray-400"/>
                      <div className="text-sm text-gray-700 font-medium mt-2">Drop the year's Books JSON, or click to browse</div>
                      <div className="text-[11px] text-gray-500 mt-1">Tally export with `ledgers[]`, `groups[]`, `vouchers[]`</div>
                      <input id="bc-books-input" type="file" accept=".json,application/json" className="hidden"
                        onChange={e => onFileDrop(e.target.files?.[0])}/>
                    </div>
                  )}
                </div>

                {/* Ledger workbench */}
                {ledgers.length > 0 && (
                  <div className="bg-white border border-gray-200 rounded-sm">
                    <div className="px-5 pt-4 pb-3 border-b border-gray-100 flex flex-wrap items-center gap-3">
                      <div className="flex gap-1">
                        {[{ key: "trade_receivable", label: "Receivables" },
                          { key: "trade_payable",    label: "Payables" },
                          { key: "bank",             label: "Banks" },
                          { key: "other",            label: "Other" },
                          { key: "all",              label: "All" }].map(t => (
                          <button key={t.key} onClick={() => { setActiveTab(t.key); setSelected(new Set()); }}
                            className={`px-2.5 py-1 text-xs font-medium rounded-sm border ${activeTab === t.key ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"}`}
                            data-testid={`bc-tab-${t.key}`}>{t.label}</button>
                        ))}
                      </div>
                      <label className="inline-flex items-center gap-1.5 text-xs cursor-pointer">
                        <input type="checkbox" checked={missingEmailOnly} onChange={e => setMissingEmailOnly(e.target.checked)} className="accent-rose-700" data-testid="bc-filter-missing-email"/>
                        Missing email only
                      </label>
                      <div className="relative">
                        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400"/>
                        <input type="text" placeholder="Search ledger / group / email"
                          value={search} onChange={e => setSearch(e.target.value)}
                          className="text-xs h-8 pl-7 pr-3 border border-gray-300 rounded-sm w-56 focus:outline-none focus:border-emerald-600"
                          data-testid="bc-search"/>
                      </div>
                      <div className="ml-auto flex items-center gap-2">
                        <input type="text" placeholder="Universal cc (comma-separated)" value={universalCc}
                          onChange={e => setUniversalCc(e.target.value)}
                          className="text-xs h-8 px-2 border border-gray-300 rounded-sm w-56 focus:outline-none focus:border-emerald-600"
                          data-testid="bc-universal-cc"/>
                        <button onClick={() => setShowSendLog(true)} className="text-xs px-3 h-8 rounded-sm border border-gray-300 inline-flex items-center gap-1.5 hover:bg-gray-50" data-testid="bc-open-send-log">
                          <Activity size={12}/> Send Log
                        </button>
                        <button onClick={exportCsv} className="text-xs px-3 h-8 rounded-sm border border-gray-300 inline-flex items-center gap-1.5 hover:bg-gray-50" data-testid="bc-csv-export">
                          <Download size={12}/> Export CSV
                        </button>
                        <label className="text-xs px-3 h-8 rounded-sm border border-gray-300 inline-flex items-center gap-1.5 hover:bg-gray-50 cursor-pointer" data-testid="bc-csv-import">
                          <Upload size={12}/> Import CSV
                          <input type="file" accept=".csv,text/csv" className="hidden" onChange={e => importCsv(e.target.files?.[0])}/>
                        </label>
                      </div>
                    </div>

                    {/* Bulk action bar */}
                    <div className="px-5 py-2.5 border-b border-gray-100 bg-gray-50 flex items-center gap-3 text-xs">
                      <span className="font-mono text-gray-600">{selected.size} selected</span>
                      <button disabled={!selected.size || busy} onClick={sendSelected}
                        className="px-3 py-1.5 rounded-sm bg-emerald-700 text-white font-medium inline-flex items-center gap-1.5 hover:bg-emerald-800 disabled:opacity-40 disabled:cursor-not-allowed"
                        data-testid="bc-bulk-send">
                        <Send size={12}/> Send Selected
                      </button>
                      <button disabled={!selected.size || busy} onClick={remindSelected}
                        className="px-3 py-1.5 rounded-sm border border-amber-700 text-amber-800 bg-white font-medium inline-flex items-center gap-1.5 hover:bg-amber-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        data-testid="bc-bulk-remind">
                        <Bell size={12}/> Send Reminder
                      </button>
                      <button disabled={busy} onClick={sendAllVisible}
                        className="px-3 py-1.5 rounded-sm border border-gray-300 text-gray-700 bg-white font-medium inline-flex items-center gap-1.5 hover:bg-gray-100 disabled:opacity-40"
                        data-testid="bc-send-all-visible">
                        <Send size={12}/> Send All in View
                      </button>
                      <span className="text-[11px] text-gray-500 ml-auto">Sender: <code>onboarding@resend.dev</code> · Reply-to: your email · Default cadence: 3/7/14 days</span>
                    </div>

                    <LedgerTable rows={visibleLedgers} onPatch={patchLedger}
                      selected={selected} onToggle={toggleRow} onToggleAll={() => toggleAll(visibleLedgers)}/>
                    {visibleLedgers.length === 0 && (
                      <div className="p-8 text-center text-xs text-gray-500 font-mono">No ledgers match the current filter.</div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {showTemplates && <TemplatesDrawer onClose={() => setShowTemplates(false)}/>}
      {showAuth && <AuthorisationDrawer clientId={clientId} onClose={() => setShowAuth(false)}/>}
      {showSendLog && <SendLogDrawer rid={rid} onClose={() => setShowSendLog(false)}/>}
    </div>
  );
}

/* ============================================================ */
function LedgerTable({ rows, onPatch, selected, onToggle, onToggleAll }) {
  const allChecked = rows.length > 0 && rows.every(r => selected.has(r.ledger_id));
  return (
    <div className="overflow-x-auto" data-testid="bc-ledger-table">
      <table className="w-full text-[12px]">
        <thead className="bg-gray-50 text-gray-600 text-[10px] uppercase tracking-wider">
          <tr>
            <th className="px-3 py-2 border-b border-gray-200 w-8">
              <input type="checkbox" checked={allChecked} onChange={onToggleAll} className="accent-emerald-700" data-testid="bc-select-all"/>
            </th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Ledger</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Group</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Category</th>
            <th className="text-right px-3 py-2 border-b border-gray-200">Closing</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Status</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Email</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Cc</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">Contact</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <Row key={r.ledger_id} row={r} onPatch={onPatch}
              checked={selected.has(r.ledger_id)} onToggle={() => onToggle(r.ledger_id)}/>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ row, onPatch, checked, onToggle }) {
  const cat = CATS.find(c => c.key === row.category) || CATS[3];
  const statusInfo = STATUS_CHIP[row.confirmation_status] || STATUS_CHIP.not_sent;
  return (
    <tr className="hover:bg-gray-50" data-testid={`bc-row-${row.ledger_id}`}>
      <td className="px-3 py-2 border-b border-gray-100 text-center">
        <input type="checkbox" checked={checked} onChange={onToggle} disabled={!row.email} className="accent-emerald-700 disabled:opacity-30" data-testid={`bc-row-${row.ledger_id}-select`}/>
      </td>
      <td className="px-3 py-2 border-b border-gray-100 max-w-[240px] truncate" title={row.name}>{row.name}</td>
      <td className="px-3 py-2 border-b border-gray-100 text-gray-500 font-mono text-[11px] max-w-[140px] truncate" title={row.parent_group}>{row.parent_group || "—"}</td>
      <td className="px-3 py-2 border-b border-gray-100">
        <select
          value={row.category} onChange={e => onPatch(row.ledger_id, { category: e.target.value })}
          className={`text-[11px] px-1.5 py-0.5 border rounded-sm font-medium ${CHIP_CLS[cat.chip]}`}
          data-testid={`bc-row-${row.ledger_id}-category`}>
          <option value="trade_receivable">Receivable</option>
          <option value="trade_payable">Payable</option>
          <option value="bank">Bank</option>
          <option value="other">Other</option>
        </select>
      </td>
      <td className="px-3 py-2 border-b border-gray-100 text-right font-mono whitespace-nowrap">
        {inr(Math.abs(row.closing_balance))} <span className={`text-[10px] ${row.dr_cr === "dr" ? "text-rose-700" : "text-emerald-700"}`}>{(row.dr_cr || "").toUpperCase()}</span>
      </td>
      <td className="px-3 py-2 border-b border-gray-100">
        <span className={`text-[10px] font-mono px-1.5 py-0.5 border rounded-sm ${statusInfo.cls}`} data-testid={`bc-row-${row.ledger_id}-status`}>{statusInfo.label}</span>
      </td>
      <Editable value={row.email} placeholder="email@example.com" type="email"
        onSave={v => onPatch(row.ledger_id, { email: v })}
        testid={`bc-row-${row.ledger_id}-email`}/>
      <Editable value={(row.cc_emails || []).join(", ")} placeholder="cc1@x.com, cc2@x.com"
        onSave={v => onPatch(row.ledger_id, { cc_emails: v ? v.split(",").map(s => s.trim()).filter(s => s.includes("@")) : [] })}
        testid={`bc-row-${row.ledger_id}-cc`}/>
      <Editable value={row.contact_name} placeholder="Mr. ABC"
        onSave={v => onPatch(row.ledger_id, { contact_name: v })}
        testid={`bc-row-${row.ledger_id}-contact`}/>
    </tr>
  );
}

function Editable({ value, placeholder, onSave, type = "text", testid }) {
  const [v, setV] = useState(value || "");
  const [dirty, setDirty] = useState(false);
  useEffect(() => { setV(value || ""); setDirty(false); }, [value]);
  return (
    <td className="px-3 py-2 border-b border-gray-100">
      <input type={type} value={v} placeholder={placeholder}
        onChange={e => { setV(e.target.value); setDirty(true); }}
        onBlur={() => { if (dirty) onSave(v); }}
        onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
        className={`text-[12px] px-2 py-1 border rounded-sm w-full ${dirty ? "border-amber-400 bg-amber-50/50" : "border-transparent hover:border-gray-200 focus:border-emerald-500 bg-transparent"} focus:outline-none`}
        data-testid={testid}/>
    </td>
  );
}

/* ============================================================ */
function TemplatesDrawer({ onClose }) {
  const [tabs, setTabs] = useState([]);
  const [active, setActive] = useState("customer");
  const [editing, setEditing] = useState(null);
  useEffect(() => {
    http.get(`/balance-confirmation/templates`).then(({ data }) => setTabs(data?.rows || []));
  }, []);
  const current = useMemo(() => tabs.find(t => t.kind === active && t.is_default) || tabs.find(t => t.kind === active), [tabs, active]);
  const save = async () => {
    if (!editing || !current) return;
    const { data } = await http.patch(`/balance-confirmation/templates/${current.template_id}`, {
      kind: current.kind, name: editing.name, subject: editing.subject, html_body: editing.html_body,
    });
    setTabs(rows => rows.map(r => r.template_id === data.template_id ? data : r));
    setEditing(null);
    toast.success("Template saved");
  };
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} data-testid="bc-templates-backdrop"/>
      <div className="fixed top-0 right-0 h-screen w-[min(95vw,900px)] bg-white shadow-2xl z-50 flex flex-col" data-testid="bc-templates-drawer">
        <div className="p-5 border-b border-gray-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Configuration</div>
            <h2 className="text-lg font-semibold mt-1">Email Templates</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-2" data-testid="bc-templates-close">×</button>
        </div>
        <div className="px-5 pt-3 border-b border-gray-200 bg-gray-50">
          <div className="flex gap-1">
            {[{ k: "customer", label: "Customers" }, { k: "vendor", label: "Vendors" }, { k: "bank", label: "Banks" }].map(t => (
              <button key={t.k} onClick={() => { setActive(t.k); setEditing(null); }}
                className={`px-3 py-2 text-xs font-medium rounded-t-sm border-x border-t ${active === t.k ? "bg-white border-gray-300 text-gray-900" : "border-transparent text-gray-600 hover:text-gray-900"}`}
                data-testid={`bc-template-tab-${t.k}`}>{t.label}</button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-auto p-5">
          {!current && <div className="text-sm text-gray-500">Loading…</div>}
          {current && (
            <div className="space-y-3">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500 mb-1">Name</div>
                <input value={editing?.name ?? current.name}
                  onChange={e => setEditing({ ...(editing || current), name: e.target.value })}
                  className="w-full text-sm border border-gray-300 rounded-sm px-3 py-2 focus:outline-none focus:border-emerald-600"/>
              </div>
              <div>
                <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500 mb-1">Subject</div>
                <input value={editing?.subject ?? current.subject}
                  onChange={e => setEditing({ ...(editing || current), subject: e.target.value })}
                  className="w-full text-sm border border-gray-300 rounded-sm px-3 py-2 focus:outline-none focus:border-emerald-600"/>
              </div>
              <div>
                <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500 mb-1">HTML Body</div>
                <textarea value={editing?.html_body ?? current.html_body}
                  onChange={e => setEditing({ ...(editing || current), html_body: e.target.value })}
                  className="w-full font-mono text-[11px] border border-gray-300 rounded-sm px-3 py-2 focus:outline-none focus:border-emerald-600 min-h-[260px]"/>
              </div>
              <div className="text-[11px] text-gray-500">Available placeholders:
                <span className="font-mono text-[10.5px] ml-1">
                  {`{{client_name}} {{client_gstin}} {{as_at_date}} {{party_name}} {{contact_name_or_party}} {{closing_balance_inr}} {{dr_cr}} {{response_link}} {{auditor_name}} {{auditor_firm}} {{address}}`}
                </span>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                {editing && <button onClick={() => setEditing(null)} className="text-xs px-3 py-2 border border-gray-300 rounded-sm hover:bg-gray-50">Cancel</button>}
                <button disabled={!editing} onClick={save} className="text-xs px-3 py-2 bg-emerald-700 text-white rounded-sm hover:bg-emerald-800 disabled:opacity-40" data-testid="bc-template-save">Save</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/* ============================================================ */
function AuthorisationDrawer({ clientId, onClose }) {
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    http.get(`/balance-confirmation/clients/${clientId}/authorization`)
      .then(({ data }) => setMeta(data))
      .finally(() => setLoading(false));
  }, [clientId]);
  const upload = async (file) => {
    const fd = new FormData(); fd.append("file", file);
    const { data } = await http.post(`/balance-confirmation/clients/${clientId}/authorization`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    setMeta(data);
    toast.success("Authorisation letter uploaded");
  };
  const downloadTemplate = async () => {
    const res = await http.get(`/balance-confirmation/clients/${clientId}/authorization/template.docx`, { responseType: "blob" });
    const cd = res.headers["content-disposition"] || "";
    const m = cd.match(/filename="(.+?)"/);
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(new Blob([res.data]));
    a.download = m ? m[1] : "Authorization_Template.docx";
    document.body.appendChild(a); a.click(); a.remove();
    toast.success("Template downloaded");
  };
  const downloadSigned = async () => {
    const res = await http.get(`/balance-confirmation/clients/${clientId}/authorization/file`, { responseType: "blob" });
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(new Blob([res.data]));
    a.download = meta?.filename || "authorization.pdf";
    document.body.appendChild(a); a.click(); a.remove();
  };
  const remove = async () => {
    if (!window.confirm("Remove the signed authorisation letter?")) return;
    await http.delete(`/balance-confirmation/clients/${clientId}/authorization`);
    setMeta(null);
    toast.success("Removed");
  };
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} data-testid="bc-auth-backdrop"/>
      <div className="fixed top-0 right-0 h-screen w-[min(92vw,720px)] bg-white shadow-2xl z-50 flex flex-col" data-testid="bc-auth-drawer">
        <div className="p-5 border-b border-gray-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Configuration</div>
            <h2 className="text-lg font-semibold mt-1">Authorisation Letter</h2>
            <div className="text-xs text-gray-500 mt-0.5">Signed letter that gives banks / parties permission to share information directly with you.</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-2" data-testid="bc-auth-close">×</button>
        </div>
        <div className="flex-1 overflow-auto p-5 space-y-5">
          <div className="border border-gray-200 rounded-sm p-4 bg-gray-50">
            <div className="font-medium text-sm mb-1">Step 1 — Download editable template</div>
            <div className="text-xs text-gray-600 mb-3">Customise on the client's letterhead, get it signed, then save as PDF.</div>
            <button onClick={downloadTemplate} className="text-xs px-3 py-2 border border-gray-300 rounded-sm bg-white inline-flex items-center gap-1.5 hover:bg-gray-100" data-testid="bc-auth-download-template">
              <Download size={12}/> Download Word template
            </button>
          </div>
          <div className="border border-gray-200 rounded-sm p-4">
            <div className="font-medium text-sm mb-1">Step 2 — Upload the signed PDF</div>
            <div className="text-xs text-gray-600 mb-3">This PDF will be auto-attached to every confirmation email sent for this client.</div>
            {loading ? <div className="text-xs text-gray-500">Loading…</div> : meta ? (
              <div className="flex items-center justify-between gap-3 border border-emerald-200 bg-emerald-50/50 p-3 rounded-sm">
                <div>
                  <div className="text-sm font-medium text-emerald-900 inline-flex items-center gap-2"><FileText size={14}/> {meta.filename}</div>
                  <div className="text-[11px] font-mono text-gray-600 mt-0.5">{(meta.size / 1024).toFixed(1)} KB · uploaded {meta.uploaded_at?.slice(0, 10)}{meta.uploaded_by_name ? ` by ${meta.uploaded_by_name}` : ""}</div>
                </div>
                <div className="flex gap-2">
                  <button onClick={downloadSigned} className="text-xs px-2.5 py-1.5 border border-gray-300 rounded-sm bg-white hover:bg-gray-50" data-testid="bc-auth-download">Download</button>
                  <button onClick={remove} className="text-xs px-2.5 py-1.5 border border-red-300 text-red-700 rounded-sm bg-white hover:bg-red-50" data-testid="bc-auth-remove">Remove</button>
                </div>
              </div>
            ) : null}
            <label className="mt-3 inline-flex items-center text-xs px-3 py-2 border border-gray-300 rounded-sm hover:bg-gray-50 cursor-pointer gap-1.5" data-testid="bc-auth-upload">
              <Upload size={12}/> {meta ? "Replace PDF" : "Upload signed PDF"}
              <input type="file" accept="application/pdf,.pdf" className="hidden" onChange={e => e.target.files?.[0] && upload(e.target.files[0])}/>
            </label>
          </div>
        </div>
      </div>
    </>
  );
}

/* ============================================================ */
function SendLogDrawer({ rid, onClose }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const refresh = () => {
    setLoading(true);
    http.get(`/balance-confirmation/runs/${rid}/send-log`)
      .then(({ data }) => setRows(data?.rows || []))
      .finally(() => setLoading(false));
  };
  useEffect(refresh, [rid]);
  const STATUS_TONE = {
    sent: "text-blue-700", delivered: "text-emerald-700", opened: "text-emerald-800", clicked: "text-emerald-900",
    bounced: "text-rose-700", failed: "text-rose-800", queued: "text-blue-600",
  };
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} data-testid="bc-sendlog-backdrop"/>
      <div className="fixed top-0 right-0 h-screen w-[min(95vw,900px)] bg-white shadow-2xl z-50 flex flex-col" data-testid="bc-sendlog-drawer">
        <div className="p-5 border-b border-gray-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">Telemetry</div>
            <h2 className="text-lg font-semibold mt-1">Send Log</h2>
            <div className="text-xs text-gray-500 mt-0.5">Every send, webhook event, open and click recorded against this run.</div>
          </div>
          <div className="flex gap-2 items-center">
            <button onClick={refresh} className="text-xs px-2.5 py-1.5 border border-gray-300 rounded-sm hover:bg-gray-50" data-testid="bc-sendlog-refresh">Refresh</button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-2" data-testid="bc-sendlog-close">×</button>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {loading ? <div className="p-5 text-sm text-gray-500">Loading…</div> : rows.length === 0 ? (
            <div className="p-8 text-center text-xs text-gray-500 font-mono">No events yet.</div>
          ) : (
            <table className="w-full text-[12px]">
              <thead className="bg-gray-50 text-[10px] uppercase tracking-wider text-gray-600 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2 border-b">When</th>
                  <th className="text-left px-3 py-2 border-b">Kind</th>
                  <th className="text-left px-3 py-2 border-b">Status</th>
                  <th className="text-left px-3 py-2 border-b">To</th>
                  <th className="text-left px-3 py-2 border-b">Subject / Note</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.log_id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 border-b font-mono text-[10.5px]">{r.ts?.slice(0, 19).replace("T", " ")}</td>
                    <td className="px-3 py-2 border-b font-medium">{r.kind}</td>
                    <td className={`px-3 py-2 border-b font-mono ${STATUS_TONE[r.status] || ""}`}>{r.status}</td>
                    <td className="px-3 py-2 border-b text-gray-700">{r.to_email || "—"}</td>
                    <td className="px-3 py-2 border-b text-gray-600 max-w-[360px] truncate" title={r.subject || r.error}>{r.subject || r.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

