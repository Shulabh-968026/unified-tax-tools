import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, Play, Plus, Zap } from "lucide-react";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { api, http } from "@/lib/msme-api";
import AppShell from "@/components/AppShell";
import Footer from "@/components/msme43bh/Footer";
import YearEndUpload from "@/components/msme43bh/YearEndUpload";
import ProfilesEditor from "@/components/msme43bh/ProfilesEditor";
import PaymentsUpload from "@/components/msme43bh/PaymentsUpload";
import ResultsView from "@/components/msme43bh/ResultsView";

export default function Msme43bhSessionDashboard() {
  const { clientId: cid, sid } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [session, setSession] = useState(null);
  const [results, setResults] = useState(null);
  const [tab, setTab] = useState("yearend");
  const [busy, setBusy] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [forceFifo, setForceFifo] = useState(false);

  const loadSession = useCallback(async (id) => {
    const { data } = await api.get(`/sessions/${id}`);
    setSession(data);
    setResults(data.results || null);
    // Sync forceFifo from the most recent computation if any
    if (data.results?.summary?.force_fifo !== undefined) {
      setForceFifo(!!data.results.summary.force_fifo);
    }
    return data;
  }, []);

  // Load client metadata
  useEffect(() => {
    if (!cid) return;
    (async () => {
      try {
        const { data } = await http.get(`/clients/${cid}`);
        setClient(data);
      } catch {
        navigate("/dashboard", { replace: true });
      }
    })();
  }, [cid, navigate]);

  // Bootstrap: require explicit sid; otherwise bounce to Landing
  useEffect(() => {
    (async () => {
      try {
        if (sid) {
          await loadSession(sid);
        } else if (cid) {
          navigate(`/dashboard/clients/${cid}/utilities/msme-43bh`, { replace: true });
          return;
        }
      } catch (e) {
        toast.error("Failed to load session");
      } finally {
        setBootstrapping(false);
      }
    })();
  }, [sid, cid, loadSession, navigate]);

  // Auto-switch to Results only on the very first session load, not after refreshes
  const initialSwitchDone = useRef(false);
  useEffect(() => {
    if (!session?.id) return;
    if (!initialSwitchDone.current) {
      initialSwitchDone.current = true;
      if (session.has_results) setTab("results");
    }
  }, [session?.id, session?.has_results]);

  const onYearEndUploaded = async () => {
    if (!sid) return;
    await loadSession(sid);
    setTab("profiles");
  };
  const onProfilesUpdated = async () => {
    if (!sid) return;
    await loadSession(sid);
  };
  const onPaymentsUploaded = async () => {
    if (!sid) return;
    await loadSession(sid);
  };

  const runCompute = async () => {
    if (!sid) return;
    if (!session?.has_yearend) {
      toast.error("Upload year-end Excel first");
      setTab("yearend");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post(`/sessions/${sid}/compute`, null, {
        params: { force_fifo: forceFifo },
      });
      setResults(data);
      await loadSession(sid);
      setTab("results");
      const forced = data.summary?.fifo_forced_count || 0;
      toast.success(
        `Computed · ${data.summary.disallowed_count} disallowed${forceFifo ? ` · ${forced} FIFO forced` : ""}`,
      );
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Computation failed");
    } finally {
      setBusy(false);
    }
  };

  if (bootstrapping) {
    return (
      <AppShell>
        <div className="flex-1 flex items-center justify-center text-gray-500">
          <Loader2 className="animate-spin mr-2" /> Loading…
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <main className="flex-1 px-4 md:px-10 py-8 max-w-[1600px] w-full">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-xs text-gray-500 mb-3">
          <Link to="/dashboard" className="hover:text-gray-900" data-testid="crumb-clients">All clients</Link>
          <span className="text-gray-300">/</span>
          <Link to={`/dashboard/clients/${cid}`} className="hover:text-gray-900" data-testid="crumb-client">
            {client?.name || "…"}
          </Link>
          <span className="text-gray-300">/</span>
          <Link
            to={`/dashboard/clients/${cid}/utilities/msme-43bh`}
            className="hover:text-gray-900"
            data-testid="crumb-runs"
          >
            43BH MSME Disallowance
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-gray-900 font-medium font-mono">
            {session?.fy || "Run"} · {session?.id?.slice(0, 8) || "…"}
          </span>
        </div>

        <Link
          to={`/dashboard/clients/${cid}/utilities/msme-43bh`}
          className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-gray-900 mb-4"
          data-testid="back-to-runs"
        >
          <ArrowLeft size={14} /> Back to runs
        </Link>

        {/* Page header */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8">
          <div>
            <div className="section-label mb-2">Tax Audit Utility</div>
            <h1 className="font-display text-3xl md:text-4xl font-semibold tracking-tight text-gray-900">
              §43B(h) MSME Disallowance Workbench
            </h1>
            <p className="text-sm text-gray-600 mt-2 max-w-2xl">
              Quantify the exact statutory disallowance under Section 43B(h) of the Income
              Tax Act by reconciling year-end MSME outstandings with subsequent-FY payments.
            </p>
            {client && (
              <div className="mt-3 text-xs text-gray-600 font-mono">
                Client: <span className="font-semibold text-gray-900">{client.name}</span>{" "}
                · FILE {client.file_number} · {client.type}
                {session?.fy && (
                  <>
                    {" "}· <span className="text-gray-900">{session.fy}</span>
                  </>
                )}
                {session?.id && (
                  <>
                    {" "}· SID <span className="text-gray-900">{session.id.slice(0, 8)}</span>
                  </>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Link
              to={`/dashboard/clients/${cid}/utilities/msme-43bh`}
              className="btn-outline-swiss flex items-center gap-2"
              data-testid="new-session-btn"
            >
              <Plus size={14} /> New Run
            </Link>
            <div
              className={`flex items-center gap-2 px-3 h-[42px] rounded-sm border cursor-pointer select-none transition ${
                forceFifo
                  ? "border-amber-500 bg-amber-50 text-amber-900"
                  : "border-gray-200 bg-white text-gray-700 hover:border-gray-900"
              }`}
              onClick={() => setForceFifo((v) => !v)}
              role="checkbox"
              aria-checked={forceFifo}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  setForceFifo((v) => !v);
                }
              }}
              data-testid="force-fifo-toggle"
              title="Ignore source Due Date and apply Voucher Date + 45 days for all bills"
            >
              <Checkbox
                checked={forceFifo}
                tabIndex={-1}
                className="rounded-sm border-gray-400 data-[state=checked]:bg-amber-600 data-[state=checked]:border-amber-600 pointer-events-none"
                data-testid="force-fifo-checkbox"
              />
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <Zap size={13} className={forceFifo ? "text-amber-600" : "text-gray-500"} />
                Force FIFO
              </span>
            </div>
            <button
              onClick={runCompute}
              disabled={busy || !session?.has_yearend}
              className="btn-primary-swiss flex items-center gap-2"
              data-testid="run-compute-btn"
            >
              {busy ? <Loader2 className="animate-spin" size={14} /> : <Play size={14} />}
              {session?.has_results ? "Rerun Computation" : "Run Computation"}
            </button>
          </div>
        </div>

        {/* Status strip */}
        <div className="grid grid-cols-3 gap-2 md:gap-4 mb-6 text-xs" data-testid="status-strip">
          <StatusPill n={1} label="Year-End Bills" value={session?.has_yearend ? `${session.yearend_count} bills` : "Not uploaded"} done={!!session?.has_yearend} />
          <StatusPill n={2} label="MSME Profile" value={session?.has_profiles ? `${session.profile_count} creditors` : "Pending"} done={!!session?.has_profiles} />
          <StatusPill n={3} label="Payments" value={session?.has_payments ? `${session.payment_count} entries` : "Not uploaded"} done={!!session?.has_payments} />
        </div>

        <Tabs value={tab} onValueChange={setTab} className="tabs-swiss" data-testid="main-tabs">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="yearend" data-testid="tab-yearend">1 · Year-End</TabsTrigger>
            <TabsTrigger value="profiles" data-testid="tab-profiles">2 · MSME Profile</TabsTrigger>
            <TabsTrigger value="payments" data-testid="tab-payments">3 · Payments</TabsTrigger>
            <TabsTrigger value="results" data-testid="tab-results">4 · Results</TabsTrigger>
          </TabsList>

          <TabsContent value="yearend" className="pt-6">
            <YearEndUpload session={session} onUploaded={onYearEndUploaded} />
          </TabsContent>
          <TabsContent value="profiles" className="pt-6">
            <ProfilesEditor session={session} onUpdated={onProfilesUpdated} />
          </TabsContent>
          <TabsContent value="payments" className="pt-6">
            <PaymentsUpload session={session} onUploaded={onPaymentsUploaded} />
          </TabsContent>
          <TabsContent value="results" className="pt-6">
            <ResultsView session={session} results={results} onRecompute={runCompute} />
          </TabsContent>
        </Tabs>
      </main>

      <Footer />
    </AppShell>
  );
}

function StatusPill({ n, label, value, done }) {
  return (
    <div
      className={`border rounded-sm p-3 flex items-center gap-3 ${done ? "border-gray-900" : "border-gray-200 bg-gray-50"}`}
      data-testid={`status-pill-${n}`}
    >
      <div className={`h-7 w-7 rounded-sm flex items-center justify-center font-mono text-xs font-semibold ${done ? "bg-gray-900 text-white" : "bg-white text-gray-700 border border-gray-200"}`}>
        {n}
      </div>
      <div className="flex-1 min-w-0">
        <div className="section-label">{label}</div>
        <div className={`text-sm truncate ${done ? "text-gray-900 font-medium" : "text-gray-500"}`}>{value}</div>
      </div>
    </div>
  );
}
