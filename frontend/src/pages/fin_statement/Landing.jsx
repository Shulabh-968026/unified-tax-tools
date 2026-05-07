/* Financial Statement Designer — Landing page.
 *
 * Scoped: /dashboard/clients/:clientId/utilities/fin-statement
 *
 * Phase 1: runs list + New Run modal + Open-run navigation.
 * Each run is a (client, FY) pair that ingests a Tally books JSON and
 * produces a Schedule III financial-statement document which can then be
 * exported as a designer PDF.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Loader2, Plus, Trash2, ChartLine, Upload, FileText, Calendar,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import { FY_OPTIONS, DEFAULT_FY } from "@/lib/fy";
import { readScopeFromUrl, scopeRequestPayload } from "@/lib/scope";
import ScopeChip from "@/components/ScopeChip";

function fyDates(fy) {
  // "2024-25" → { start: "2024-04-01", end: "2025-03-31" }
  const [y] = fy.split("-");
  const start = Number(y);
  return {
    fy_start: `${start}-04-01`,
    fy_end:   `${start + 1}-03-31`,
  };
}

export default function FsDesignerLanding() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const urlScope = readScopeFromUrl(location.search);
  const [client, setClient] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [c, r] = await Promise.all([
        http.get(`/clients/${clientId}`),
        http.get(`/fin-statement/runs?client_id=${clientId}`),
      ]);
      setClient(c.data);
      setRuns(r.data?.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load runs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [clientId]);

  const deleteRun = async (rid) => {
    if (!window.confirm("Delete this run and its uploaded books? This cannot be undone.")) return;
    try {
      await http.delete(`/fin-statement/runs/${rid}`);
      toast.success("Run deleted");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="min-h-screen bg-[#FAFAF7]">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* breadcrumb */}
        <div className="flex items-center gap-2 text-[12px] text-[#52524E] mb-2">
          <Link to="/dashboard" className="hover:underline">Clients</Link>
          <span>/</span>
          <Link to={`/dashboard/clients/${clientId}/utilities`} className="hover:underline">
            {client?.name || clientId}
          </Link>
          <span>/</span>
          <span className="text-[#0F172A] font-medium">Financial Statement Designer</span>
        </div>

        {/* header */}
        <div className="flex items-start justify-between gap-4 mt-3">
          <div>
            <div className="flex items-center gap-2">
              <ChartLine size={18} className="text-sky-700"/>
              <h1 className="font-heading text-2xl">Financial Statement Designer</h1>
            </div>
            <p className="text-[13px] text-[#52524E] mt-1 max-w-2xl">
              Drop a Tally books JSON, review the auto-derived Schedule III Balance Sheet,
              P&amp;L, Cash Flow and Notes, then download a signature-ready PDF in a
              classic or boardroom template.
            </p>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            data-testid="fs-new-run-btn"
            className="inline-flex items-center gap-2 px-4 py-2 bg-sky-800 hover:bg-sky-900 text-white text-[13px]"
          >
            <Plus size={14}/>
            New Run
          </button>
        </div>

        {/* runs grid */}
        <div className="mt-8 border border-[#E5E5E0] bg-white">
          <div className="px-4 py-2 border-b border-[#EDEDE7] text-[10.5px] font-mono uppercase tracking-[0.18em] text-slate-500">
            Runs
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-12 text-slate-500">
              <Loader2 className="animate-spin mr-2" size={16}/> Loading…
            </div>
          ) : runs.length === 0 ? (
            <div className="py-14 text-center text-[13px] text-slate-500">
              No runs yet. Click <strong>New Run</strong> above to start.
            </div>
          ) : (
            <div className="divide-y divide-[#EDEDE7]">
              {runs.map((r) => (
                <div
                  key={r.id}
                  data-testid={`fs-run-${r.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50/70"
                >
                  <ChartLine size={14} className="text-sky-700 shrink-0"/>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-[13.5px] truncate">{r.name}</span>
                      <ScopeChip run={r} isMulti={(r.scope_label && r.scope_label !== "Consolidation")} />
                    </div>
                    <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                      FY {r.fy} · {r.fy_start} → {r.fy_end}
                      {r.books_loaded && <> · {r.ledger_count} ledgers · {r.voucher_count} vouchers</>}
                    </div>
                  </div>
                  <StatusPill status={r.status}/>
                  <button
                    onClick={() => navigate(
                      `/dashboard/clients/${clientId}/utilities/fin-statement/runs/${r.id}`,
                    )}
                    data-testid={`fs-run-open-${r.id}`}
                    className="px-3 py-1.5 text-[12px] border border-slate-300 hover:bg-slate-100"
                  >
                    Open
                  </button>
                  <button
                    onClick={() => deleteRun(r.id)}
                    title="Delete run"
                    className="p-1.5 text-slate-400 hover:text-rose-700"
                  >
                    <Trash2 size={14}/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {modalOpen && (
        <NewRunModal
          clientName={client?.name}
          onClose={() => setModalOpen(false)}
          onCreate={async (payload) => {
            try {
              const { data } = await http.post("/fin-statement/runs", {
                client_id: clientId, ...payload,
                ...scopeRequestPayload(urlScope),
              });
              toast.success(`Run created${data.scope_label ? " · " + data.scope_label : ""}`);
              setModalOpen(false);
              navigate(
                `/dashboard/clients/${clientId}/utilities/fin-statement/runs/${data.id}${location.search || ""}`,
              );
            } catch (e) {
              toast.error(e?.response?.data?.detail || "Create failed");
            }
          }}
        />
      )}
    </div>
  );
}

function StatusPill({ status }) {
  const tone = {
    draft:    "bg-slate-100 text-slate-600 border-slate-200",
    ingested: "bg-sky-50 text-sky-800 border-sky-200",
    rendered: "bg-emerald-50 text-emerald-800 border-emerald-200",
  }[status] || "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 border ${tone}`}>
      {status}
    </span>
  );
}

function NewRunModal({ clientName, onClose, onCreate }) {
  const [fy, setFy] = useState(DEFAULT_FY);
  const [name, setName] = useState(clientName || "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    const { fy_start, fy_end } = fyDates(fy);
    await onCreate({ fy, fy_start, fy_end, name });
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-40 flex items-center justify-center"
         onClick={onClose}>
      <div className="bg-white border border-[#E5E5E0] w-[420px] max-w-[90vw]"
           onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-[#EDEDE7]">
          <div className="font-heading text-base">New Financial Statement Run</div>
          <div className="text-[11px] text-slate-500 mt-0.5">{clientName}</div>
        </div>
        <div className="px-4 py-4 space-y-3">
          <label className="block">
            <span className="text-[11px] font-mono uppercase tracking-wider text-slate-500">FY</span>
            <select value={fy} onChange={(e) => setFy(e.target.value)}
                    className="mt-1 block w-full border border-slate-300 px-2 py-1.5 text-[13px]">
              {FY_OPTIONS.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-[11px] font-mono uppercase tracking-wider text-slate-500">Run Name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                   className="mt-1 block w-full border border-slate-300 px-2 py-1.5 text-[13px]"
                   data-testid="fs-new-run-name"/>
          </label>
        </div>
        <div className="px-4 py-3 border-t border-[#EDEDE7] flex items-center justify-end gap-2 bg-[#FAFAF7]">
          <button onClick={onClose} className="px-3 py-1.5 border border-slate-300 text-[12px] hover:bg-slate-100">Cancel</button>
          <button
            onClick={submit}
            disabled={busy || !name.trim()}
            data-testid="fs-new-run-create"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-sky-800 text-white text-[12px] hover:bg-sky-900 disabled:opacity-60"
          >
            {busy ? <Loader2 size={12} className="animate-spin"/> : <Plus size={12}/>}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
