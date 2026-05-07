import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, BarChart3, Archive, Loader2, FileSpreadsheet, FileJson,
} from "lucide-react";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { api, http } from "@/lib/msme-api";
import AppShell from "@/components/AppShell";
import { readScopeFromUrl, scopeRequestPayload } from "@/lib/scope";
import ScopeChip from "@/components/ScopeChip";

// Generate FY options: current FY back to FY 2018-19
function buildFYOptions() {
  const now = new Date();
  const month = now.getMonth() + 1; // 1-12
  // FY in India is Apr-Mar; current FY is yyyy-yy where yyyy = year if month>=4 else year-1
  const baseYear = month >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  const opts = [];
  for (let y = baseYear; y >= 2018; y--) {
    const next = String((y + 1) % 100).padStart(2, "0");
    opts.push(`FY ${y}-${next}`);
  }
  return opts;
}

// Default to most recent completed FY (i.e., current FY - 1) since 43B(h) runs lag a year
const DEFAULT_FY = (() => {
  const opts = buildFYOptions();
  return opts[1] || opts[0] || "";
})();

function formatTs(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: true,
    }).toUpperCase();
  } catch { return iso; }
}

export default function Msme43bhLanding() {
  const { clientId: cid } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const urlScope = readScopeFromUrl(location.search);
  const fyOptions = useMemo(buildFYOptions, []);

  const [client, setClient] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [fy, setFy] = useState(DEFAULT_FY);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!cid) return;
    try {
      const [clientRes, sessRes] = await Promise.all([
        http.get(`/clients/${cid}`),
        api.get(`/sessions`, { params: { client_id: cid } }),
      ]);
      setClient(clientRes.data);
      setSessions(sessRes.data || []);
    } catch (e) {
      toast.error("Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, [cid]);

  useEffect(() => { refresh(); }, [refresh]);

  const startRun = async () => {
    if (!fy) { toast.error("Choose a financial year"); return; }
    setBusy(true);
    try {
      const { data } = await api.post(`/sessions`, {
        client_id: cid,
        name: `Tax Audit ${fy}`,
        fy: fy,
        ...scopeRequestPayload(urlScope),
      });
      navigate(`/dashboard/clients/${cid}/utilities/msme-43bh/sessions/${data.id}${location.search || ""}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to start run");
    } finally {
      setBusy(false);
    }
  };

  const archiveRun = async (sid) => {
    try {
      await api.delete(`/sessions/${sid}`);
      toast.success("Run archived");
      refresh();
    } catch (e) {
      toast.error("Archive failed");
    }
  };

  // Group runs by FY (most recent FY first; runs newest first)
  const grouped = useMemo(() => {
    const map = new Map();
    for (const s of sessions) {
      const key = s.fy || "—";
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(s);
    }
    const arr = Array.from(map.entries());
    arr.sort((a, b) => b[0].localeCompare(a[0]));
    for (const [, list] of arr) {
      list.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    }
    return arr;
  }, [sessions]);

  return (
    <AppShell>
      <main className="flex-1 px-4 md:px-10 py-8 max-w-[1280px] w-full">
        {/* Breadcrumb */}
        <Link
          to={`/dashboard/clients/${cid}`}
          className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-gray-900 mb-4 font-mono"
          data-testid="back-to-modules"
        >
          <ArrowLeft size={14} /> {client ? client.name : "—"} · Utilities
        </Link>

        {/* Header block */}
        <div className="flex items-center gap-5 mb-3">
          <div
            className="h-[88px] w-[88px] rounded-sm bg-gray-900 text-white flex items-center justify-center font-display tracking-wide"
            data-testid="utility-tile"
          >
            <div className="text-center leading-tight">
              <div className="text-[10px] uppercase tracking-[0.18em] text-gray-300">§43B(h)</div>
              <div className="text-[22px] font-semibold mt-1">43BH</div>
            </div>
          </div>
          <div>
            <h1 className="font-display text-3xl md:text-4xl font-semibold tracking-tight text-gray-900">
              {client?.name || "Loading…"}
            </h1>
            {client && (
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-600 font-mono">
                <span>FILE · {client.file_number}</span>
                <span className="text-gray-300">·</span>
                <span className="px-2 py-0.5 border border-emerald-200 bg-emerald-50 text-emerald-700 rounded-sm uppercase tracking-wider">
                  {client.type}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="border-b border-gray-200 mb-10" />

        {/* Step 01 - Choose Period */}
        <section
          className="border border-gray-200 rounded-sm p-6 md:p-8 mb-12"
          data-testid="choose-period-section"
        >
          <div className="text-[11px] uppercase tracking-[0.12em] text-gray-500 font-semibold mb-2">
            Step 01
          </div>
          <h2 className="font-display text-2xl md:text-3xl font-semibold text-gray-900 mb-6">
            Choose Period
          </h2>

          <div className="flex flex-col md:flex-row md:items-end gap-4 max-w-2xl">
            <div className="flex-1">
              <label className="text-[11px] uppercase tracking-[0.1em] text-gray-500 font-semibold block mb-2">
                Financial Year / Period
              </label>
              <Select value={fy} onValueChange={setFy}>
                <SelectTrigger className="rounded-sm h-11" data-testid="fy-select">
                  <SelectValue placeholder="Select FY" />
                </SelectTrigger>
                <SelectContent>
                  {fyOptions.map((o) => (
                    <SelectItem key={o} value={o}>{o}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <button
              onClick={startRun}
              disabled={busy || !fy}
              className="btn-primary-swiss flex items-center gap-2 h-11 px-6"
              data-testid="start-run-btn"
            >
              {busy ? <Loader2 className="animate-spin" size={14} /> : <ArrowRight size={14} />}
              Start Run
            </button>
          </div>
        </section>

        {/* Runs */}
        <section data-testid="runs-section">
          <h2 className="font-display text-2xl md:text-3xl font-semibold text-gray-900 mb-5">
            Runs
          </h2>

          {loading ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm">
              <Loader2 className="animate-spin" size={14} /> Loading runs…
            </div>
          ) : sessions.length === 0 ? (
            <div className="border border-dashed border-gray-300 rounded-sm p-10 text-center text-sm text-gray-600" data-testid="runs-empty">
              No runs yet. Pick a financial year above and click <span className="font-semibold">Start Run</span>.
            </div>
          ) : (
            <div className="space-y-6">
              {grouped.map(([key, list]) => (
                <div key={key} className="border border-gray-200 rounded-sm" data-testid={`run-group-${key}`}>
                  <div className="flex items-center gap-3 px-4 md:px-5 py-3 border-b border-gray-200 bg-gray-50">
                    <span className="font-mono text-xs text-gray-500 uppercase tracking-wider">FY</span>
                    <span className="font-display font-semibold text-gray-900">{key.replace(/^FY\s*/i, "")}</span>
                    <span className="text-[11px] uppercase tracking-wider px-2 py-0.5 border border-gray-200 bg-white text-gray-700 rounded-sm font-semibold ml-auto">
                      {list.length} {list.length === 1 ? "run" : "runs"}
                    </span>
                  </div>
                  <ul className="divide-y divide-gray-200">
                    {list.map((r) => (
                      <li
                        key={r.id}
                        className="px-4 md:px-5 py-4 flex items-center gap-4 hover:bg-gray-50/60"
                        data-testid={`run-row-${r.id}`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-gray-900 truncate flex items-center gap-2 flex-wrap">
                            <span className="font-medium">{r.scope || "Single scope"}</span>
                            <ScopeChip run={r} isMulti={(r.scope_label && r.scope_label !== "Consolidation")} />
                            <span className="text-gray-300">·</span>
                            <span className="text-gray-700 font-mono text-xs flex items-center gap-1">
                              {r.source_filename ? (
                                <><FileSpreadsheet size={12} /> {r.source_filename}</>
                              ) : r.payments_filename ? (
                                <><FileJson size={12} /> {r.payments_filename}</>
                              ) : (
                                <span className="text-gray-400 italic">No source file uploaded</span>
                              )}
                            </span>
                          </div>
                          <div className="mt-1 text-[11px] uppercase tracking-wider text-gray-500 font-mono">
                            Generated by <span className="text-gray-700">{r.generated_by || "S Dhananjayan"}</span>
                            {" · "}
                            {formatTs(r.created_at)}
                            {r.has_results && (
                              <span className="ml-2 px-1.5 py-0.5 text-[9px] bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-sm">
                                COMPUTED
                              </span>
                            )}
                          </div>
                        </div>
                        <Link
                          to={`/dashboard/clients/${cid}/utilities/msme-43bh/sessions/${r.id}`}
                          className="inline-flex items-center gap-2 border border-gray-200 hover:border-gray-900 px-3 py-2 rounded-sm text-xs font-medium text-gray-900"
                          data-testid={`run-open-${r.id}`}
                        >
                          <BarChart3 size={13} /> Report
                        </Link>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <button
                              className="h-9 w-9 inline-flex items-center justify-center border border-gray-200 hover:border-gray-900 rounded-sm text-gray-600 hover:text-gray-900"
                              title="Archive"
                              data-testid={`run-archive-${r.id}`}
                            >
                              <Archive size={14} />
                            </button>
                          </AlertDialogTrigger>
                          <AlertDialogContent className="rounded-sm">
                            <AlertDialogHeader>
                              <AlertDialogTitle>Archive this run?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This permanently deletes the run and its computed result. The
                                client and other runs are not affected.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel className="rounded-sm">Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                className="rounded-sm bg-rose-600 hover:bg-rose-700"
                                onClick={() => archiveRun(r.id)}
                                data-testid={`run-archive-confirm-${r.id}`}
                              >
                                Archive
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </AppShell>
  );
}
