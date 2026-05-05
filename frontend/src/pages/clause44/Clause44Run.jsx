/**
 * Clause 44 stepper shell — owns run state, current step, navigation
 * and the "Proceed" / export actions.  Replaces the old StepMapping +
 * StepReport pages.
 *
 *   URL         :  /dashboard/runs/:runId?step=<key>
 *   step keys   :  itc | exclusion | report
 *                  (import happens on ClientHome; arriving here means
 *                   the books have been ingested and the run exists)
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle, DownloadSimple, Lightning, BookOpen } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import AppShell from "@/components/AppShell";
import { generateRun, getRun, saveSelections, exportRunUrl, rerunRun } from "@/lib/api";
import StepSpecialLedgers from "./StepSpecialLedgers";
import StepExclusion from "./StepExclusion";
import StepReport from "./StepReport";

const STEPS = [
  { key: "import",    label: "Import" },             // shown as completed — import happens on ClientHome
  { key: "special",   label: "Special Ledgers" },    // renamed from "itc" (was narrower)
  { key: "exclusion", label: "Exclusions" },
  { key: "report",    label: "Report" },
];

// Legacy URL shim — `?step=itc` → `special`.
function normaliseStepKey(raw) {
  if (raw === "itc") return "special";
  return raw;
}

export default function Clause44Run() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  // Legacy /runs/:runId/report URLs → default to the report step.
  const rawStep = params.get("step") || (location.pathname.endsWith("/report") ? "report" : "special");
  const step = normaliseStepKey(rawStep);

  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // Step 2 — Special Ledgers (two tabs + toggle)
  const [itc, setItc] = useState(new Set());
  const [exempt, setExempt] = useState(new Set());
  const [useItcInf, setUseItcInf] = useState(true);
  const [itcQuery, setItcQuery] = useState("");
  const [exemptQuery, setExemptQuery] = useState("");
  const [itcKindFilter, setItcKindFilter] = useState("all");

  // Step 3 — Exclusions
  const [exc, setExc] = useState(new Set());
  const [excQuery, setExcQuery] = useState("");

  // Load run + seed selections.
  useEffect(() => {
    (async () => {
      try {
        const r = await getRun(runId);
        setRun(r);
        // Silent ITC selection cleanup (Release 3.1 Fix #3a): a saved
        // selection from before the seeding fix may include Output-kind
        // ledgers that were wrongly auto-ticked.  Drop them on first
        // load so the user sees the corrected default; we tag the run
        // doc with `itc_selection_cleaned_at` to avoid double-cleaning.
        const candidatesByName = new Map((r.itc_candidates || []).map((c) => [c.name, c]));
        const rawItc = r.itc_selection || [];
        const cleanedItc = rawItc.filter((n) => {
          const c = candidatesByName.get(n);
          return !c || c.kind !== "output";
        });
        const droppedOutput = rawItc.filter((n) => candidatesByName.get(n)?.kind === "output");
        const itcSeed = new Set(cleanedItc);
        const exemptSeed = new Set(r.exempt_selection || []);
        const excSeed = new Set(r.exclusion_selection || []);
        // First-load heuristic: if user hasn't made any explicit selection
        // yet AND run has not been generated, pre-tick "suggested" rows.
        const noPriorItc = !(r.itc_selection && r.itc_selection.length) && !r.generated;
        const noPriorExc = !(r.exclusion_selection && r.exclusion_selection.length) && !r.generated;
        if (noPriorItc) {
          (r.itc_candidates || []).forEach((x) => { if (x.suggested) itcSeed.add(x.name); });
        }
        if (noPriorExc) {
          (r.pl_ledgers || []).forEach((x) => { if (x.suggested) excSeed.add(x.name); });
        }
        // Release 3.2 — fold in newly-detected usage-based ITC ledgers
        // for runs uploaded under the older heuristic.  These are rows
        // whose engine-suggested flag is NOW true via voucher-usage but
        // weren't in the auditor's saved selection (the engine simply
        // didn't know about them).  We add silently and notify.
        const newlyDetectedFromUsage = (r.itc_candidates || []).filter(
          (x) => x.suggested && x.kind_source === "usage" && !rawItc.includes(x.name),
        );
        newlyDetectedFromUsage.forEach((x) => itcSeed.add(x.name));
        // Exempt purchases — never pre-ticked; auditor must opt-in consciously.
        setItc(itcSeed);
        setExempt(exemptSeed);
        setExc(excSeed);
        setUseItcInf(r.use_itc_inference !== false);  // default true
        const needsPersist = droppedOutput.length > 0 || newlyDetectedFromUsage.length > 0;
        if (needsPersist) {
          await saveSelections(runId, { itc_ledgers: Array.from(itcSeed) }).catch(() => {});
        }
        if (droppedOutput.length > 0) {
          toast.message("ITC selection auto-corrected", {
            description: `Removed ${droppedOutput.length} Output-side ledger(s) that were auto-ticked under the older heuristic. Re-generate the report to refresh totals.`,
            duration: 8000,
          });
        }
        if (newlyDetectedFromUsage.length > 0) {
          toast.message("Additional ITC ledgers detected", {
            description: `Auto-tagged ${newlyDetectedFromUsage.length} ledger(s) as ITC based on voucher usage: ${newlyDetectedFromUsage.slice(0,3).map(x => x.name).join(", ")}${newlyDetectedFromUsage.length > 3 ? "…" : ""}. Re-generate the report to refresh totals.`,
            duration: 9000,
          });
        }
      } catch (e) {
        toast.error("Failed to load run");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const goTo = (key) => setParams({ step: key });

  const proceedSpecial = async () => {
    setBusy(true);
    try {
      await saveSelections(runId, {
        itc_ledgers: Array.from(itc),
        exempt_ledgers: Array.from(exempt),
        use_itc_inference: useItcInf,
      });
      goTo("exclusion");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  const proceedExclusion = async () => {
    setBusy(true);
    try {
      // If the Library has newer versions of our pinned files, re-pin
      // and re-parse FIRST, then run classification on the fresh data.
      // Single button, single click — but the auditor's selections
      // (ITC / exempt / exclusion / disclaimer) are preserved across
      // the rerun.
      const isOutdated = !!run?.library_status?.outdated;
      if (isOutdated) {
        await rerunRun(runId);
        toast.message("Library data refreshed", {
          description: "Re-pinned to the latest Books JSON / Ledger Map. Now generating on fresh data…",
        });
      }
      await generateRun(runId, {
        itc_ledgers: Array.from(itc),
        exempt_ledgers: Array.from(exempt),
        excluded_ledgers: Array.from(exc),
        use_itc_inference: useItcInf,
        exclusion_categories: run?.exclusion_categories || {},
      });
      // Re-fetch — the backend now has by_ledger / by_party etc.
      const r = await getRun(runId);
      setRun(r);
      toast.success(isOutdated ? "Clause 44 rerun on latest data" : "Clause 44 generated");
      goTo("report");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  const backToClient = () => run?.client_id
    ? navigate(`/dashboard/clients/${run.client_id}/utilities/clause-44`)
    : navigate("/dashboard");
  const backFromExclusion = () => goTo("special");
  const backFromReport = () => goTo("exclusion");

  // Header meta for the fixed top strip
  const currentStepIdx = Math.max(0, STEPS.findIndex((s) => s.key === step));
  const periodTag = run?.period ? `FY ${run.period}` : "";
  const divisionTag = run?.division_name ? ` · ${run.division_name}` : "";

  if (loading) {
    return (
      <AppShell>
        <div className="p-10 font-mono text-sm text-[#8A8A83]">Loading run…</div>
      </AppShell>
    );
  }
  if (!run) {
    return (
      <AppShell>
        <div className="p-10 font-mono text-sm text-[#991B1B]">Run not found.</div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      {/* ───── Sticky top bar — breadcrumb · stepper · action ───── */}
      <div className="sticky top-0 z-20 bg-white/92 backdrop-blur border-b border-[#E5E5E0]" data-testid="clause44-stepper-bar">
        <div className="px-6 md:px-10 py-3 flex flex-wrap items-center gap-4">
          <button
            onClick={backToClient}
            className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] hover:text-[#0F172A]"
            data-testid="back-to-client"
          >
            <ArrowLeft size={12}/> {run.client_name}
          </button>
          <span className="text-[#D4D4D0]">·</span>
          <div className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">
            Clause 44 {periodTag}{divisionTag}
          </div>
          <a
            href="/api/docs/clause-44"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 h-7 px-2.5 border border-[#E5E5E0] rounded-sm bg-white hover:bg-[#0F172A] hover:text-white hover:border-[#0F172A] text-[#0F172A] font-mono text-[10px] uppercase tracking-[0.1em] transition-colors"
            data-testid="readme-clause-44-run"
            title="Open the Clause 44 user guide in a new tab"
          >
            <BookOpen size={11}/> Readme
          </a>
          {/* Outdated chip — Library detected a newer Books JSON or
              Ledger Map than this run is pinned to.  Generate button
              below morphs to "Rerun on Latest Data". */}
          {run?.library_status?.outdated && (
            <span
              data-testid="run-data-outdated-chip"
              className="inline-flex items-center gap-1.5 h-7 px-2.5 border border-amber-300 bg-amber-50 text-amber-900 rounded-sm font-mono text-[10px] uppercase tracking-[0.12em]"
              title="A newer version of one of this run's source files is available in the Library. Click Rerun on Latest Data to refresh."
            >
              ⚠ Data Outdated
            </span>
          )}
          {run?.library_status?.missing && (
            <span
              data-testid="run-data-missing-chip"
              className="inline-flex items-center gap-1.5 h-7 px-2.5 border border-rose-200 bg-rose-50 text-rose-900 rounded-sm font-mono text-[10px] uppercase tracking-[0.12em]"
            >
              ⊘ Files Not in Library
            </span>
          )}

          {/* Stepper pills */}
          <ol className="hidden md:flex items-center gap-1 ml-auto mr-auto">
            {STEPS.map((s, idx) => {
              const active = s.key === step;
              const done = idx < currentStepIdx || (s.key === "import");
              return (
                <li key={s.key} className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      if (s.key === "import") return;                   // noop
                      if (s.key === "report" && !run.generated) return; // gate
                      goTo(s.key);
                    }}
                    className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border font-mono text-[10.5px] uppercase tracking-[0.12em] ${
                      active
                        ? "bg-[#0F172A] text-white border-[#0F172A]"
                        : done
                          ? "bg-white text-[#0F172A] border-[#E5E5E0] hover:bg-[#F3F4F1]"
                          : "bg-[#FAFAF7] text-[#8A8A83] border-[#E5E5E0]"
                    }`}
                    data-testid={`step-pill-${s.key}`}
                  >
                    <span className={`w-4 h-4 inline-flex items-center justify-center rounded-full text-[9px] ${
                      active ? "bg-white text-[#0F172A]" : done ? "bg-emerald-600 text-white" : "bg-[#E5E5E0] text-[#8A8A83]"
                    }`}>
                      {done && !active ? <CheckCircle size={10} weight="fill"/> : String(idx + 1).padStart(2, "0")}
                    </span>
                    {s.label}
                  </button>
                  {idx < STEPS.length - 1 && <span className="text-[#D4D4D0]">—</span>}
                </li>
              );
            })}
          </ol>

          {/* Action cluster — top right */}
          <div className="ml-auto flex items-center gap-2">
            {step === "special" && (
              <Button
                onClick={proceedSpecial}
                disabled={busy}
                data-testid="proceed-special"
                className="h-9 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-1.5"
              >
                Proceed <ArrowLeft size={12} weight="bold" style={{ transform: "rotate(180deg)" }}/>
              </Button>
            )}
            {step === "exclusion" && (
              <>
                <Button
                  variant="ghost"
                  onClick={backFromExclusion}
                  disabled={busy}
                  className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] h-9"
                  data-testid="back-from-exclusion"
                >
                  ← Back
                </Button>
                <Button
                  onClick={proceedExclusion}
                  disabled={busy}
                  data-testid="proceed-exclusion"
                  className={`h-9 px-4 rounded-sm shadow-none gap-1.5 text-white ${
                    run?.library_status?.outdated
                      ? "bg-amber-700 hover:bg-amber-800"
                      : "bg-[#0F172A] hover:bg-[#1E293B]"
                  }`}
                >
                  <Lightning size={12} weight="fill"/>
                  {busy
                    ? (run?.library_status?.outdated ? "Rerunning…" : "Generating…")
                    : (run?.library_status?.outdated ? "Rerun on Latest Data" : "Generate Report")}
                </Button>
              </>
            )}
            {step === "report" && (
              <>
                <Button
                  variant="ghost"
                  onClick={backFromReport}
                  className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] h-9"
                  data-testid="back-from-report"
                >
                  ← Refine
                </Button>
                <a
                  href={exportRunUrl(runId)}
                  className="inline-flex items-center gap-1.5 h-9 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white font-mono text-[10.5px] uppercase tracking-[0.12em] rounded-sm"
                  data-testid="export-excel"
                >
                  <DownloadSimple size={12}/> Export Excel
                </a>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ───── Step content ───── */}
      <div className="px-6 md:px-10 py-8 pb-40">
        {step === "special" && (
          <StepSpecialLedgers
            run={run}
            itcSelected={itc}
            setItcSelected={setItc}
            itcQuery={itcQuery}
            setItcQuery={setItcQuery}
            exemptSelected={exempt}
            setExemptSelected={setExempt}
            exemptQuery={exemptQuery}
            setExemptQuery={setExemptQuery}
            useItcInference={useItcInf}
            setUseItcInference={setUseItcInf}
            itcKindFilter={itcKindFilter}
            setItcKindFilter={setItcKindFilter}
          />
        )}
        {step === "exclusion" && (
          <StepExclusion
            run={run}
            selected={exc}
            setSelected={setExc}
            query={excQuery}
            setQuery={setExcQuery}
          />
        )}
        {step === "report" && (
          <StepReport run={run}/>
        )}
      </div>
    </AppShell>
  );
}
