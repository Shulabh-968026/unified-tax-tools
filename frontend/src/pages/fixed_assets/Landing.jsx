/**
 * Fixed Assets Landing — IT Depreciation
 * ----------------------------------------------------------
 * Inline classification flow (no modal):
 *   • Books JSON ingest → server auto-classifies each ledger by name+subhead
 *   • Workbench shows Ledger | Subhead | Closing | Adds | Credits | IT Block (dropdown)
 *   • Auditor changes the dropdown directly to override the auto-suggestion
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FolderUp, Loader2, Plus, Trash2, Wrench, Search, BookOpen, FileText, ArrowDown, Calculator, LayoutGrid, History } from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import AdditionsTab from "@/pages/fixed_assets/AdditionsTab";
import CreditsTab from "@/pages/fixed_assets/CreditsTab";
import ComputeTab from "@/pages/fixed_assets/ComputeTab";
import SummaryTab from "@/pages/fixed_assets/SummaryTab";
import GenerationsDrawer from "@/components/GenerationsDrawer";
import { DEFAULT_FY } from "@/lib/fy";
import { readScopeFromUrl, scopeRequestPayload } from "@/lib/scope";
import ScopeChip from "@/components/ScopeChip";
import ConsolidationStrip from "@/components/ConsolidationStrip";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

export default function FixedAssetsLanding() {
  const { clientId, rid } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const urlScope = readScopeFromUrl(location.search);

  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [ledgers, setLedgers] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [busy, setBusy] = useState(false);
  const [savingFor, setSavingFor] = useState(null); // ledger_id when saving
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all | unclassified | classified
  const [tab, setTab] = useState("ledgers"); // ledgers | additions | credits | compute | summary
  const [auditFilter, setAuditFilter] = useState(null); // optional audit-flag filter passed to AdditionsTab
  const [showHistory, setShowHistory] = useState(false);
  const dropRef = useRef(null);
  // Phase C.2 — divisions list for ConsolidationStrip.
  const [divisions, setDivisions] = useState([]);
  useEffect(() => {
    if (!clientId) return;
    http.get(`/clients/${clientId}`)
      .then(({ data }) => setDivisions(data?.divisions || []))
      .catch(() => setDivisions([]));
  }, [clientId]);

  // Cross-tab navigation helper invoked by Summary's audit-flag cards.
  const goToFilteredAdditions = (flagKey) => {
    if (flagKey === "discount_pending") {
      // Discount pending lives on the Credits tab (different shape)
      setAuditFilter(null);
      setTab("credits");
      return;
    }
    setAuditFilter(flagKey);
    setTab("additions");
  };

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

  // Backfill auto-classification for legacy runs that were ingested before
  // the auto-classifier existed. Triggers exactly once per run when we see
  // ledgers loaded but ALL have empty block_label.
  const backfilledRef = useRef(new Set());
  useEffect(() => {
    if (!rid || !ledgers.length) return;
    if (backfilledRef.current.has(rid)) return;
    const allEmpty = ledgers.every(L => !L.block_label);
    if (!allEmpty) return;
    backfilledRef.current.add(rid);
    http.post(`/fixed-assets/runs/${rid}/auto-classify-pending`)
      .then(({ data }) => {
        if (data?.classified > 0) {
          toast.success(`Auto-classified ${data.classified} of ${ledgers.length} ledgers — review and override as needed.`);
          refreshRun();
          refreshLedgers();
        }
      })
      .catch(() => {});
  }, [rid, ledgers]);

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
    const fy = window.prompt("Enter Financial Year (e.g., 2025-26):", urlScope.fy || DEFAULT_FY);
    if (!fy) return;
    setBusy(true);
    try {
      const { data } = await http.post(`/fixed-assets/runs`, {
        client_id: clientId, fy,
        ...scopeRequestPayload(urlScope),
      });
      setRuns(rs => [data, ...rs]);
      toast.success(`Run created · FY ${data.fy}${data.scope_label ? " · " + data.scope_label : ""}`);
      navigate(`/dashboard/clients/${clientId}/utilities/fixed-assets/runs/${data.id}${location.search || ""}`);
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
      const auto = (data.summary?.confirmed || 0);
      toast.success(
        `${data.ledgers} FA ledgers · ${data.additions} additions · ${data.credits} credits · ` +
        `${auto} auto-classified, ${data.summary?.pending || 0} need review`
      );
      refreshRun(); refreshLedgers();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Books ingest failed");
    } finally { setBusy(false); }
  };

  /* --- Inline block change --- */
  const setBlock = async (ledger_id, block_label) => {
    setSavingFor(ledger_id);
    // Optimistic UI
    setLedgers(rows => rows.map(r => r.fa_ledger_id === ledger_id
      ? { ...r, block_label, classification_status: block_label ? "confirmed" : "pending" }
      : r));
    try {
      await http.patch(`/fixed-assets/runs/${rid}/ledgers/${ledger_id}/block`, { block_label });
      // Quietly refresh run summary so the stats strip stays accurate
      refreshRun();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save block");
      refreshLedgers();
    } finally {
      setSavingFor(null);
    }
  };

  /* --- Filtered rows --- */
  const visibleLedgers = useMemo(() => {
    let rows = ledgers;
    if (filter === "unclassified") rows = rows.filter(r => !r.block_label);
    else if (filter === "classified") rows = rows.filter(r => !!r.block_label);
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter(r => `${r.name} ${r.parent_group}`.toLowerCase().includes(q));
    return rows;
  }, [ledgers, search, filter]);

  const summary = run?.summary || {};
  const unclassifiedCount = summary.pending || 0;
  const classifiedCount = summary.confirmed || 0;

  /* ============================================================ */
  /* No-run state                                                 */
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
                Each run is a single financial year of depreciation working. Books JSON,
                classifications, additions and computations are scoped to the run.
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
            <>
              {/* Phase C.2 — Consolidation View scaffold */}
              <ConsolidationStrip
                clientId={clientId}
                fy={urlScope.fy || DEFAULT_FY}
                divisions={divisions}
                scope={urlScope}
                listPath="/fixed-assets/runs"
                runHrefBase={`/dashboard/clients/${clientId}/utilities/fixed-assets/runs`}
                runIdField="id"
              />
              <div className="bg-white border border-[#E5E5E0] divide-y divide-[#EDEDE7]">
              {runs.map(r => (
                <div key={r.id} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-[#F9F9F8]">
                  <Link
                    to={`/dashboard/clients/${clientId}/utilities/fixed-assets/runs/${r.id}`}
                    data-testid={`fa-run-${r.id}`}
                    className="flex-1 min-w-0"
                  >
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-700">FY {r.fy}</span>
                      {r.rolled_from_run_id && (
                        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5">
                          Rolled forward
                        </span>
                      )}
                      <ScopeChip run={r} isMulti={(r.scope_label && r.scope_label !== "Consolidation")} />
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
            </>
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
            <button
              data-testid="fa-open-history"
              onClick={() => setShowHistory(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 border border-slate-300 text-slate-700 text-[12px] hover:bg-slate-50"
            >
              <History size={13}/> History
            </button>
            <BooksDrop dropRef={dropRef} onFile={onIngest} busy={busy}/>
          </div>
        </div>

        {/* Stats strip */}
        <div className="grid grid-cols-5 gap-2 mb-6">
          <Stat label="FA Ledgers" value={summary.total_ledgers || 0}/>
          <Stat label="Unclassified" value={unclassifiedCount} accent="amber"/>
          <Stat label="Classified" value={classifiedCount} accent="emerald"/>
          <Stat label="Additions" value={summary.additions || 0}/>
          <Stat label="Credits to Review" value={summary.credits || 0} accent="rose"/>
        </div>

        {/* Tab bar */}
        <div className="flex items-center gap-1 mb-4 border-b border-[#E5E5E0]">
          {[
            ["ledgers",   "Ledgers",     BookOpen,    summary.total_ledgers || 0],
            ["credits",   "Credits",     ArrowDown,   summary.credits || 0],
            ["additions", "Additions",   FileText,    summary.additions || 0],
            ["compute",   "Compute",     Calculator,  null],
            ["summary",   "Summary",     LayoutGrid,  null],
          ].map(([id, label, Icon, count]) => (
            <button
              key={id}
              data-testid={`fa-tab-${id}`}
              onClick={() => { setAuditFilter(null); setTab(id); }}
              className={`inline-flex items-center gap-1.5 px-3 py-2 text-[12.5px] -mb-px border-b-2 ${
                tab === id ? "border-slate-900 text-slate-900 font-semibold" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <Icon size={13}/>
              {label}
              {count !== null && (
                <span className={`text-[10.5px] font-mono px-1.5 py-0.5 ${tab === id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>

        {tab === "ledgers" && (
        /* Workbench */
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
                  placeholder="Search ledger or subhead…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                data-testid="fa-filter"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="px-2 py-1.5 text-[12px] border border-[#D4D4D0] focus:outline-none"
              >
                <option value="all">All ({ledgers.length})</option>
                <option value="unclassified">Unclassified ({unclassifiedCount})</option>
                <option value="classified">Classified ({classifiedCount})</option>
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
                    <th className="px-3 py-2">Subhead</th>
                    <th className="px-3 py-2 text-right">Closing</th>
                    <th className="px-3 py-2 text-center">Adds</th>
                    <th className="px-3 py-2 text-center">Credits</th>
                    <th className="px-3 py-2 w-[260px]">IT Block</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EDEDE7]">
                  {visibleLedgers.map(L => (
                    <tr key={L.fa_ledger_id} className="hover:bg-[#FBFBF8]">
                      <td className="px-4 py-2 font-medium" data-testid={`fa-led-${L.fa_ledger_id}`}>{L.name}</td>
                      <td className="px-3 py-2 text-slate-600">{L.parent_group}</td>
                      <td className="px-3 py-2 text-right font-mono text-[12px]">{inr(L.closing_balance)}</td>
                      <td className="px-3 py-2 text-center">{L.addition_count || 0}</td>
                      <td className="px-3 py-2 text-center">{L.deletion_count || 0}</td>
                      <td className="px-3 py-2">
                        <BlockSelect
                          value={L.block_label}
                          status={L.classification_status}
                          options={blocks}
                          saving={savingFor === L.fa_ledger_id}
                          onChange={(v) => setBlock(L.fa_ledger_id, v)}
                          testid={`fa-block-${L.fa_ledger_id}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        )}

        {tab === "additions" && (
          <AdditionsTab
            rid={rid}
            blocks={blocks}
            auditFilter={auditFilter}
            onClearAuditFilter={() => setAuditFilter(null)}
          />
        )}
        {tab === "credits"   && <CreditsTab rid={rid}/>}
        {tab === "compute"   && <ComputeTab rid={rid}/>}
        {tab === "summary"   && (
          <SummaryTab rid={rid} onJumpToFlag={goToFilteredAdditions}/>
        )}
      </div>
      {showHistory && (
        <GenerationsDrawer
          open={showHistory}
          onClose={() => setShowHistory(false)}
          endpoint={`/fixed-assets/runs/${rid}`}
          moduleLabel="Fixed Assets · IT Depreciation"
          module="fixed_assets"
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

function BlockSelect({ value, status, options, saving, onChange, testid }) {
  // Subtle visual hint: italic + amber border when the block was auto-suggested
  // (server flagged it but the auditor hasn't ratified it yet via the dropdown).
  const isAuto = status === "auto_suggested" && !!value;
  const isEmpty = !value;
  const cls = isEmpty
    ? "border-amber-300 bg-amber-50 text-amber-900"
    : isAuto
      ? "border-sky-200 bg-sky-50 text-slate-900 italic"
      : "border-emerald-200 bg-emerald-50 text-emerald-900";
  return (
    <div className="relative">
      <select
        data-testid={testid}
        value={value || ""}
        disabled={saving}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full pr-7 pl-2 py-1.5 text-[12.5px] border focus:outline-none focus:border-slate-700 ${cls}`}
      >
        <option value="">— Select block —</option>
        {options.map(b => (
          <option key={b.block_label} value={b.block_label}>
            {b.block_label} ({b.rate}%)
          </option>
        ))}
      </select>
      {saving && (
        <Loader2 size={11} className="absolute right-2 top-1/2 -translate-y-1/2 animate-spin text-slate-500"/>
      )}
    </div>
  );
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
