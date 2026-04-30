/**
 * Fixed Assets Landing — Phase 1A/B/C/E
 * ----------------------------------------------------------
 * Run picker → Books JSON ingest → Ledger Classification Workbench
 *
 * Subsequent phases (additions UI, 3CD opening import, computation,
 * Excel export) will mount additional tabs/drawers on this same page.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, FolderUp, Loader2, Plus, Trash2, Wrench, CheckCircle2,
  AlertTriangle, Search, BookOpen, RotateCcw,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

const STATUS_CHIP = {
  pending:        { label: "Pending",         cls: "bg-amber-50 text-amber-800 border-amber-200" },
  auto_suggested: { label: "Auto-Suggested",  cls: "bg-sky-50 text-sky-800 border-sky-200" },
  confirmed:      { label: "Confirmed",       cls: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  skipped:        { label: "Skipped",         cls: "bg-slate-50 text-slate-700 border-slate-200" },
};

export default function FixedAssetsLanding() {
  const { clientId, rid } = useParams();
  const navigate = useNavigate();

  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [ledgers, setLedgers] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [legalRows, setLegalRows] = useState({}); // block_label → rows[]
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all"); // all | pending | confirmed
  const [classifyFor, setClassifyFor] = useState(null); // ledger row when modal open
  const dropRef = useRef(null);

  /* --- Initial loads --- */
  useEffect(() => {
    if (!clientId) return;
    http.get(`/fixed-assets/runs?client_id=${clientId}`)
      .then(({ data }) => setRuns(data?.rows || []))
      .catch(() => {});
    http.get(`/fixed-assets/blocks`)
      .then(({ data }) => setBlocks(data?.rows || []))
      .catch(() => {});
  }, [clientId]);

  useEffect(() => {
    if (!rid) { setRun(null); setLedgers([]); return; }
    refreshRun();
    refreshLedgers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  const refreshRun = async () => {
    const { data } = await http.get(`/fixed-assets/runs/${rid}`);
    setRun(data);
  };
  const refreshLedgers = async () => {
    const { data } = await http.get(`/fixed-assets/runs/${rid}/ledgers`);
    setLedgers(data?.rows || []);
  };

  /* --- Run create / delete --- */
  const createRun = async () => {
    const fy = window.prompt("Enter Financial Year (e.g., 2024-25):", "2024-25");
    if (!fy) return;
    setBusy(true);
    try {
      const { data } = await http.post(`/fixed-assets/runs`, { client_id: clientId, fy });
      setRuns(rs => [data, ...rs]);
      toast.success(`Run created · FY ${data.fy}`);
      navigate(`/dashboard/clients/${clientId}/utilities/fixed-assets/runs/${data.id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create run");
    } finally { setBusy(false); }
  };
  const deleteRun = async (id) => {
    if (!window.confirm("Delete this run? Ledgers, additions and credits will be removed.")) return;
    await http.delete(`/fixed-assets/runs/${id}`);
    setRuns(rs => rs.filter(x => x.id !== id));
    toast.success("Run deleted");
    if (id === rid) navigate(`/dashboard/clients/${clientId}/utilities/fixed-assets`);
  };

  /* --- Books JSON upload --- */
  const onIngest = async (file) => {
    if (!file || !rid) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await http.post(`/fixed-assets/runs/${rid}/ingest-books`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Detected ${data.ledgers} FA ledgers · ${data.additions} additions · ${data.credits} credits`);
      refreshRun(); refreshLedgers();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Books ingest failed");
    } finally { setBusy(false); }
  };

  /* --- Classification --- */
  const openClassify = async (led) => {
    setClassifyFor(led);
  };
  const fetchLegalRowsForBlock = async (blockLabel) => {
    if (legalRows[blockLabel]) return legalRows[blockLabel];
    const { data } = await http.get(`/fixed-assets/legal-master`, {
      params: { block_label: blockLabel, active: true },
    });
    const rows = data?.rows || [];
    setLegalRows(prev => ({ ...prev, [blockLabel]: rows }));
    return rows;
  };
  const submitClassification = async ({ ledger_id, block_label, legal_master_row_id, note }) => {
    setBusy(true);
    try {
      await http.post(
        `/fixed-assets/runs/${rid}/ledgers/${ledger_id}/classify`,
        { block_label, legal_master_row_id, note: note || "", confirm: true },
      );
      toast.success("Ledger classified");
      setClassifyFor(null);
      refreshLedgers(); refreshRun();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Classification failed");
    } finally { setBusy(false); }
  };

  /* --- Filtered rows --- */
  const visibleLedgers = useMemo(() => {
    let rows = ledgers;
    if (statusFilter !== "all") {
      if (statusFilter === "confirmed") rows = rows.filter(r => r.classification_status === "confirmed");
      else rows = rows.filter(r => r.classification_status === "pending" || r.classification_status === "auto_suggested");
    }
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter(r => `${r.name} ${r.parent_group}`.toLowerCase().includes(q));
    return rows;
  }, [ledgers, search, statusFilter]);

  const summary = run?.summary || {};
  const pendingCount = summary.pending || 0;
  const confirmedCount = summary.confirmed || 0;

  /* ============================================================ */
  /* No-run state — runs list                                     */
  /* ============================================================ */
  if (!rid) {
    return (
      <div className="min-h-screen bg-[#FAFAF7] text-[#1A1A19]">
        <Header clientId={clientId}/>
        <div className="max-w-6xl mx-auto px-6 pt-8 pb-24">
          <div className="flex items-end justify-between mb-6">
            <div>
              <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-600">Income-tax Depreciation</div>
              <h1 className="font-heading text-3xl mt-1">Fixed Assets — Runs</h1>
              <p className="text-sm text-[#52524E] mt-1.5 max-w-2xl">
                Each run is a single financial year of depreciation working. Books JSON, classifications,
                additions and computations are scoped to the run.
              </p>
            </div>
            <button
              data-testid="fa-create-run"
              onClick={createRun}
              disabled={busy}
              className="inline-flex items-center gap-2 px-3.5 py-2 bg-slate-900 text-white text-[13px] hover:bg-slate-800 disabled:opacity-60"
            >
              {busy ? <Loader2 size={14} className="animate-spin"/> : <Plus size={14}/>}
              New Run
            </button>
          </div>

          {runs.length === 0 ? (
            <div className="bg-white border border-[#E5E5E0] p-10 text-center">
              <Wrench size={28} className="mx-auto text-slate-400"/>
              <div className="mt-3 font-heading text-lg">No runs yet</div>
              <p className="text-sm text-[#52524E] mt-1">Click <strong>New Run</strong> to start the FY's depreciation working.</p>
            </div>
          ) : (
            <div className="bg-white border border-[#E5E5E0] divide-y divide-[#EDEDE7]">
              {runs.map(r => (
                <div key={r.id} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-[#F9F9F8]">
                  <Link
                    to={`/dashboard/clients/${clientId}/utilities/fixed-assets/runs/${r.id}`}
                    data-testid={`fa-run-${r.id}`}
                    className="flex-1 min-w-0"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-700">
                        FY {r.fy}
                      </span>
                      {r.rolled_from_run_id && (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5">
                          Rolled forward
                        </span>
                      )}
                      <span className="font-heading text-base truncate">{r.name || "Untitled"}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {r.summary?.total_ledgers || 0} FA ledgers · {r.summary?.additions || 0} additions ·
                      {" "}{r.summary?.credits || 0} credits to classify ·
                      {" "}created {(r.created_at || "").slice(0, 10)}
                    </div>
                  </Link>
                  <button
                    data-testid={`fa-run-delete-${r.id}`}
                    onClick={() => deleteRun(r.id)}
                    className="text-rose-600 hover:bg-rose-50 p-1.5"
                    title="Delete run"
                  >
                    <Trash2 size={14}/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ============================================================ */
  /* In-run state                                                 */
  /* ============================================================ */
  return (
    <div className="min-h-screen bg-[#FAFAF7] text-[#1A1A19]">
      <Header clientId={clientId}/>
      <div className="max-w-7xl mx-auto px-6 pt-6 pb-24">
        {/* Run summary header */}
        <div className="flex items-end justify-between gap-4 mb-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.18em] text-slate-600">
              <Link to={`/dashboard/clients/${clientId}/utilities/fixed-assets`} className="hover:text-slate-900">Runs</Link>
              <span>›</span>
              <span>FY {run?.fy || "…"}</span>
            </div>
            <h1 className="font-heading text-2xl mt-1">{run?.name || "Fixed Assets Run"}</h1>
            <div className="text-[12px] text-slate-500 mt-1">
              FY {run?.fy_start} → {run?.fy_end} ·
              {" "}<span className="font-mono">{run?.source_filename || "no books ingested yet"}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <BooksDrop dropRef={dropRef} onFile={onIngest} busy={busy}/>
          </div>
        </div>

        {/* Stats strip */}
        <div className="grid grid-cols-5 gap-2 mb-6">
          <Stat label="FA Ledgers" value={summary.total_ledgers || 0}/>
          <Stat label="Pending Classification" value={pendingCount} accent="amber"/>
          <Stat label="Confirmed" value={confirmedCount} accent="emerald"/>
          <Stat label="Additions" value={summary.additions || 0}/>
          <Stat label="Credits to Review" value={summary.credits || 0} accent="rose"/>
        </div>

        {/* Workbench */}
        <div className="bg-white border border-[#E5E5E0]">
          <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#EDEDE7]">
            <div className="flex items-center gap-2">
              <BookOpen size={15} className="text-slate-600"/>
              <h2 className="font-heading text-base">Ledger Classification Workbench</h2>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"/>
                <input
                  data-testid="fa-ledger-search"
                  className="pl-7 pr-2 py-1.5 text-[12px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 w-56"
                  placeholder="Search ledger or group…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                data-testid="fa-status-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-2 py-1.5 text-[12px] border border-[#D4D4D0] focus:outline-none"
              >
                <option value="all">All ({ledgers.length})</option>
                <option value="pending">Pending ({pendingCount})</option>
                <option value="confirmed">Confirmed ({confirmedCount})</option>
              </select>
            </div>
          </div>

          {ledgers.length === 0 ? (
            <div className="p-10 text-center">
              <FolderUp size={26} className="mx-auto text-slate-400"/>
              <div className="mt-3 font-heading text-base">No ledgers ingested yet</div>
              <p className="text-[13px] text-[#52524E] mt-1">Drop your <span className="font-mono">Books.json</span> in the upload zone above.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-left bg-[#F9F9F8] text-[11px] font-mono uppercase tracking-wider text-slate-600">
                    <th className="px-4 py-2">Ledger</th>
                    <th className="px-3 py-2">Group</th>
                    <th className="px-3 py-2 text-right">Opening</th>
                    <th className="px-3 py-2 text-right">Closing</th>
                    <th className="px-3 py-2 text-center">Adds</th>
                    <th className="px-3 py-2 text-center">Credits</th>
                    <th className="px-3 py-2">Block</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EDEDE7]">
                  {visibleLedgers.map(L => (
                    <tr key={L.fa_ledger_id} className="hover:bg-[#FBFBF8]">
                      <td className="px-4 py-2 font-medium" data-testid={`fa-led-${L.fa_ledger_id}`}>{L.name}</td>
                      <td className="px-3 py-2 text-slate-600">{L.parent_group}</td>
                      <td className="px-3 py-2 text-right font-mono text-[12px]">{inr(L.opening_balance)}</td>
                      <td className="px-3 py-2 text-right font-mono text-[12px]">{inr(L.closing_balance)}</td>
                      <td className="px-3 py-2 text-center">{L.addition_count || 0}</td>
                      <td className="px-3 py-2 text-center">{L.deletion_count || 0}</td>
                      <td className="px-3 py-2">
                        {L.block_label ? (
                          <span className="font-mono text-[11px] bg-slate-50 border border-slate-200 px-1.5 py-0.5">
                            {L.block_label}
                          </span>
                        ) : <span className="text-slate-400 italic">—</span>}
                      </td>
                      <td className="px-3 py-2">
                        <Chip status={L.classification_status}/>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          data-testid={`fa-classify-btn-${L.fa_ledger_id}`}
                          onClick={() => openClassify(L)}
                          className="text-[11.5px] px-2 py-1 border border-slate-300 hover:bg-slate-100"
                        >
                          {L.classification_status === "confirmed" ? "Re-classify" : "Classify"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {classifyFor && (
        <ClassifyModal
          ledger={classifyFor}
          blocks={blocks}
          fetchLegalRowsForBlock={fetchLegalRowsForBlock}
          onClose={() => setClassifyFor(null)}
          onSubmit={submitClassification}
          busy={busy}
        />
      )}
    </div>
  );
}

/* ---------- Sub-components ---------- */
function Header({ clientId }) {
  return (
    <div className="border-b border-[#E5E5E0] bg-white">
      <div className="max-w-7xl mx-auto px-6 h-12 flex items-center gap-3">
        <Link to={`/dashboard/clients/${clientId}`} className="text-slate-600 hover:text-slate-900">
          <ArrowLeft size={16}/>
        </Link>
        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-600">Fixed Assets — IT Depreciation</div>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }) {
  const cls = accent === "amber"   ? "text-amber-700" :
              accent === "rose"    ? "text-rose-700" :
              accent === "emerald" ? "text-emerald-700" : "text-slate-900";
  return (
    <div className="bg-white border border-[#E5E5E0] px-3 py-2.5">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-xl font-heading mt-0.5 ${cls}`}>{value}</div>
    </div>
  );
}

function Chip({ status }) {
  const c = STATUS_CHIP[status] || STATUS_CHIP.pending;
  return <span className={`inline-block text-[10.5px] font-mono uppercase tracking-wider px-1.5 py-0.5 border ${c.cls}`}>{c.label}</span>;
}

function BooksDrop({ dropRef, onFile, busy }) {
  const inputRef = useRef(null);
  const [over, setOver] = useState(false);
  return (
    <div
      ref={dropRef}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        const f = e.dataTransfer.files?.[0]; if (f) onFile(f);
      }}
      className={`border border-dashed px-3 py-2 cursor-pointer text-[12px] flex items-center gap-2 ${over ? "border-slate-700 bg-slate-50" : "border-slate-300 bg-white"}`}
      onClick={() => inputRef.current?.click()}
      data-testid="fa-books-drop"
    >
      {busy ? <Loader2 size={13} className="animate-spin"/> : <FolderUp size={13}/>}
      <span>Drop Books.json or click</span>
      <input
        ref={inputRef} type="file" accept=".json,.gz,.gzip"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }}
      />
    </div>
  );
}

function ClassifyModal({ ledger, blocks, fetchLegalRowsForBlock, onClose, onSubmit, busy }) {
  const [block, setBlock] = useState(ledger.block_label || "");
  const [rows, setRows] = useState([]);
  const [rowId, setRowId] = useState(ledger.legal_master_row_id || null);
  const [note, setNote] = useState(ledger.classification_note || "");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!block) { setRows([]); setRowId(null); return; }
    setLoading(true);
    fetchLegalRowsForBlock(block).then(r => { setRows(r); setLoading(false); });
  }, [block]); // eslint-disable-line

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6" data-testid="fa-classify-modal">
      <div className="bg-white border border-[#E5E5E0] w-full max-w-3xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#EDEDE7]">
          <div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-600">Classify ledger</div>
            <div className="font-heading text-base mt-0.5 truncate">{ledger.name}</div>
            <div className="text-[11px] text-slate-500">Group: {ledger.parent_group}</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 px-2 py-1">×</button>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600">IT Block</label>
            <select
              data-testid="fa-classify-block"
              value={block}
              onChange={(e) => setBlock(e.target.value)}
              className="mt-1 w-full border border-[#D4D4D0] px-2 py-2 text-[13px] focus:outline-none focus:border-slate-700"
            >
              <option value="">— Select block —</option>
              {blocks.map(b => (
                <option key={b.block_label} value={b.block_label}>
                  {b.block_label} ({b.rate}%)
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600">
              Legal entry (Appendix I) {loading && <Loader2 size={11} className="inline animate-spin ml-1"/>}
            </label>
            <select
              data-testid="fa-classify-legal-row"
              value={rowId || ""}
              onChange={(e) => setRowId(parseInt(e.target.value, 10))}
              disabled={!rows.length}
              className="mt-1 w-full border border-[#D4D4D0] px-2 py-2 text-[13px] focus:outline-none focus:border-slate-700 max-h-64"
            >
              <option value="">— Select specific entry —</option>
              {rows.map(r => (
                <option key={r.row_id} value={r.row_id}>
                  {r.depreciation_rate}% — {r.legal_entry_text || r.ui_display_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600">Note (optional)</label>
            <textarea
              data-testid="fa-classify-note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="mt-1 w-full border border-[#D4D4D0] px-2 py-1.5 text-[13px] focus:outline-none focus:border-slate-700"
              placeholder="e.g. Ledger covers AC + UPS, mapped to Office Equipments — 15% block."
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">Cancel</button>
          <button
            data-testid="fa-classify-submit"
            disabled={!block || !rowId || busy}
            onClick={() => onSubmit({
              ledger_id: ledger.fa_ledger_id,
              block_label: block,
              legal_master_row_id: rowId,
              note,
            })}
            className="px-3 py-1.5 text-[12.5px] bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {busy ? <Loader2 size={12} className="animate-spin"/> : <CheckCircle2 size={12}/>}
            Confirm classification
          </button>
        </div>
      </div>
    </div>
  );
}
