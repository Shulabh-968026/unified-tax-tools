import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { getClient, listRuns, updateClient, archiveRun } from "@/lib/api";
import { ArrowLeft, ArrowRight, Plus, Stack, ChartBar, FileArrowDown, Archive } from "@phosphor-icons/react";
import { formatDate, formatDateTime } from "@/lib/format";
import { toast } from "sonner";
import StepUpload from "@/pages/StepUpload";
import { BookOpen } from "lucide-react";
import { FY_OPTIONS, DEFAULT_FY } from "@/lib/fy";
import { readScopeFromUrl } from "@/lib/scope";
import ScopeChip from "@/components/ScopeChip";

const PERIOD_PRESETS = FY_OPTIONS;

export default function ClientHome() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const urlScope = readScopeFromUrl(location.search);
  const [client, setClient] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  const [period, setPeriod] = useState(urlScope.fy || DEFAULT_FY);
  const [customPeriod, setCustomPeriod] = useState("");
  const [divisionId, setDivisionId] = useState(
    urlScope.scopeKind === "division" ? (urlScope.divisionIds[0] || "") : "",
  );
  const [showAddDiv, setShowAddDiv] = useState(false);
  const [newDiv, setNewDiv] = useState("");

  const [showUpload, setShowUpload] = useState(false);
  // Phase D — library readiness for the current scope (so "Start a new
  // run" can pull from the Library instead of re-prompting for files).
  const [libStatus, setLibStatus] = useState(null);
  const [starting, setStarting] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const c = await getClient(clientId);
      setClient(c);
      const d = await listRuns({ client_id: clientId });
      setRuns(d.runs || []);
      if (c.type === "multi" && c.divisions?.length && !divisionId) {
        setDivisionId(c.divisions[0].division_id);
      }
    } catch (e) {
      toast.error("Failed to load client");
      navigate("/dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [clientId]);

  const effectivePeriod = (period === "__custom" ? customPeriod : period).trim();

  // Phase D — refresh Library status whenever the active scope changes
  // so the "Start a new run" CTA knows whether to call from-library or
  // open the upload modal.
  useEffect(() => {
    let cancel = false;
    if (!clientId || !effectivePeriod) { setLibStatus(null); return; }
    import("@/lib/api").then(({ getLibraryStatus }) =>
      getLibraryStatus(clientId, effectivePeriod, divisionId || null)
        .then((s) => { if (!cancel) setLibStatus(s); })
        .catch(() => { if (!cancel) setLibStatus(null); })
    );
    return () => { cancel = true; };
  }, [clientId, divisionId, effectivePeriod]);

  const onAddDivision = async () => {
    if (!newDiv.trim()) return;
    try {
      const c = await updateClient(clientId, { add_divisions: [newDiv.trim()] });
      setClient(c);
      setNewDiv("");
      setShowAddDiv(false);
      toast.success("Division added");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  /**
   * Phase D — smart "Start a new run" handler.  When both required
   * Library files (books_json + ledger_mapping_xlsx) are already
   * uploaded for the current scope, call the new ``POST /runs/from-library``
   * endpoint and skip the upload modal.  Otherwise fall back to the
   * legacy upload flow.
   */
  const onStartRun = async () => {
    const lib = libStatus?.files || [];
    const findKey = (k) => lib.find((f) => f.key === k && f.uploaded);
    const hasBooks = !!findKey("books_json");
    const hasMap   = !!findKey("ledger_mapping_xlsx");

    if (hasBooks && hasMap) {
      setStarting(true);
      try {
        const { http } = await import("@/lib/api");
        const body = {
          client_id: clientId,
          period: effectivePeriod,
          division_id: divisionId || null,
        };
        if (urlScope?.scopeKind) body.scope_kind = urlScope.scopeKind;
        if (urlScope?.divisionIds?.length) body.division_ids = urlScope.divisionIds;
        if (urlScope?.gstinGroupId) body.gstin_group_id = urlScope.gstinGroupId;
        const { data } = await http.post("/runs/from-library", body);
        toast.success(`Run ready · ${data.vouchers_count} vouchers · ${data.ledgers_count} ledgers`);
        navigate(`/dashboard/runs/${data.run_id}`);
        return;
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Failed to start run from Library");
      } finally {
        setStarting(false);
      }
    }

    // Library is missing one or both files — open the legacy upload modal.
    if (libStatus) {
      const missing = [
        !hasBooks && "Books JSON",
        !hasMap   && "Ledger Mapping",
      ].filter(Boolean).join(" and ");
      toast.message(`Upload ${missing} to start.`, {
        description: "These files will be saved into the Library and reused next time.",
      });
    }
    setShowUpload(true);
  };

  const onArchive = async (id) => {
    try {
      await archiveRun(id);
      toast.success("Run archived");
      refresh();
    } catch { toast.error("Archive failed"); }
  };

  if (loading || !client) return <AppShell><div className="p-10 font-mono text-sm text-[#8A8A83]">Loading client…</div></AppShell>;

  const isMulti = client.type === "multi";
  // Phase D refinement (2026-05-08) — when the parent ClientUtilities
  // page already pinned both a Working Period and a Division/Scope via
  // URL, suppress the duplicate Step-01 form on this page and just
  // surface "Start a new run" as a one-click action.  The auditor can
  // change period/division by going back to the parent page.
  const scopePinned = Boolean(urlScope.fy) && (
    !isMulti || urlScope.scopeKind === "division" || urlScope.scopeKind === "consolidation"
  );
  const activeDivisionName = (client.divisions || []).find(
    (d) => d.division_id === divisionId,
  )?.name || "";
  const activeScopeLabel = isMulti
    ? (urlScope.scopeKind === "consolidation" ? "Consolidation" : (activeDivisionName || "Division"))
    : "";

  // Phase D — runs filtered to the active period+scope so the list
  // matches what the upper bar describes.
  const filteredRuns = scopePinned
    ? runs.filter((r) => {
        if (effectivePeriod && r.period !== effectivePeriod) return false;
        if (isMulti) {
          if (urlScope.scopeKind === "division") {
            if ((r.division_id || "") !== (divisionId || "")) return false;
          } else if (urlScope.scopeKind === "consolidation") {
            if (r.division_id) return false;
          }
        }
        return true;
      })
    : runs;
  const grouped = (() => {
    const map = new Map();
    filteredRuns.forEach((r) => {
      if (!map.has(r.period)) map.set(r.period, []);
      map.get(r.period).push(r);
    });
    return Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  })();

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate(`/dashboard/clients/${clientId}${location.search || ""}`)} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>{client.name} · Utilities</button>}
        title={<span className="inline-flex items-center gap-3"><span className="font-mono text-[11px] uppercase tracking-[0.18em] bg-[#0F172A] text-white px-2 py-0.5">Clause 44</span>{client.name}</span>}
        subtitle={
          <span className="inline-flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">File · {client.file_number}</span>
            <span>·</span>
            <Badge className={`${isMulti ? "bg-amber-50 text-amber-900 border-amber-200" : "bg-emerald-50 text-emerald-900 border-emerald-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
              {isMulti ? `Multi · ${client.divisions?.length || 0} div` : "Single"}
            </Badge>
            {scopePinned && (
              <>
                <span>·</span>
                <Badge data-testid="header-period-chip" className="bg-slate-50 text-slate-800 border-slate-200 border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">
                  FY {effectivePeriod}
                </Badge>
                {isMulti && (
                  <Badge
                    data-testid="header-scope-chip"
                    className={`${urlScope.scopeKind === "consolidation" ? "bg-emerald-50 text-emerald-900 border-emerald-200" : "bg-slate-50 text-slate-800 border-slate-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}
                  >
                    {activeScopeLabel}
                  </Badge>
                )}
              </>
            )}
          </span>
        }
        actions={
          <a
            href="/api/docs/clause-44"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 h-9 px-3 border border-[#E5E5E0] rounded-sm bg-white hover:bg-[#0F172A] hover:text-white hover:border-[#0F172A] text-[#0F172A] font-mono text-[10.5px] uppercase tracking-[0.1em] transition-colors"
            data-testid="readme-clause-44"
            title="Open the user guide for this module in a new tab"
          >
            <BookOpen size={13}/> Readme
          </a>
        }
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-6xl">
        {scopePinned ? (
          /* Phase D — scope pre-pinned from parent ClientUtilities page.
             No duplicate selectors here; just a one-click "Start a new
             run" CTA scoped to the active period+division.  Auditor goes
             back via the breadcrumb to change the scope. */
          (() => {
            const lib = libStatus?.files || [];
            const findKey = (k) => lib.find((f) => f.key === k && f.uploaded);
            const hasBooks = !!findKey("books_json");
            const hasMap   = !!findKey("ledger_mapping_xlsx");
            const ready = hasBooks && hasMap;
            // Release 4.4.12 — in Consolidation scope view, the CTA is
            // "View Consolidated Report" (computed from division runs),
            // NOT "Start a new run".  Uploads only happen at division
            // scope.
            const isConsolidationView = isMulti && urlScope.scopeKind === "consolidation";
            const generatedDivCount = runs.filter(
              (r) => r.period === effectivePeriod && r.generated && r.division_id,
            ).length;
            return (
              <section
                data-testid="clause44-quick-start"
                className="border border-[#E5E5E0] bg-white rounded-sm p-5 flex items-center justify-between gap-4 flex-wrap"
              >
                <div className="flex items-center gap-3 flex-wrap min-w-0">
                  <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83]">Working scope</div>
                  <Badge className="bg-slate-50 text-slate-800 border-slate-200 border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">FY {effectivePeriod}</Badge>
                  {isMulti && (
                    <Badge className={`${urlScope.scopeKind === "consolidation" ? "bg-emerald-50 text-emerald-900 border-emerald-200" : "bg-slate-50 text-slate-800 border-slate-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
                      {activeScopeLabel}
                    </Badge>
                  )}
                  {!isConsolidationView && (
                    <Badge
                      data-testid="lib-readiness-chip"
                      className={`${ready ? "bg-emerald-50 text-emerald-900 border-emerald-200" : "bg-amber-50 text-amber-900 border-amber-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}
                      title={ready
                        ? "Books + Ledger Mapping are pinned in the Library; the run will use them directly."
                        : "Books JSON and/or Ledger Mapping not yet uploaded for this scope."}
                    >
                      {ready ? "Library ready" : "Library partial"}
                    </Badge>
                  )}
                  {isConsolidationView && (
                    <Badge
                      data-testid="consolidation-info-chip"
                      className="bg-slate-50 text-slate-800 border-slate-200 border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]"
                      title="Consolidated Report is the computed sum of per-division runs — there is no upload at Consolidation scope."
                    >
                      Σ {generatedDivCount} division run{generatedDivCount === 1 ? "" : "s"} · Auto-computed
                    </Badge>
                  )}
                </div>
                {isConsolidationView ? (
                  <Button
                    data-testid="open-consolidated-btn"
                    onClick={() => navigate(`/dashboard/clients/${clientId}/utilities/clause-44/consolidated/${encodeURIComponent(effectivePeriod)}`)}
                    disabled={generatedDivCount < 1}
                    className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 disabled:opacity-60"
                    title={generatedDivCount < 1
                      ? "Generate at least one division run first"
                      : "Open the computed Consolidated Report"}
                  >
                    <Stack size={12} weight="bold"/>
                    {generatedDivCount < 1 ? "Generate a division first" : "View Consolidated Report"}
                    <ArrowRight size={14} weight="bold"/>
                  </Button>
                ) : (
                  <Button
                    data-testid="start-run-btn"
                    onClick={onStartRun}
                    disabled={starting}
                    className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 disabled:opacity-60"
                    title={ready ? "Start a run using the Library files" : "Upload required files to start"}
                  >
                    {starting ? "Starting…" : (ready ? "Start a new run" : "Upload to start run")}
                    <ArrowRight size={14} weight="bold"/>
                  </Button>
                )}
              </section>
            );
          })()
        ) : (
          /* Legacy direct-deep-link flow (no parent scope) — keep the
             full Step-01 picker so users who land here directly can
             still pick period + division. */
          <section className="border border-[#E5E5E0] bg-white rounded-sm p-6">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83]">Step 01</div>
          <h2 className="mt-1 font-heading text-xl tracking-tight">Choose Period {isMulti && "& Division"}</h2>
          <div className="mt-5 grid md:grid-cols-3 gap-4">
            <div>
              <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Financial Year / Period</Label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger data-testid="period-select" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"><SelectValue/></SelectTrigger>
                <SelectContent>
                  {PERIOD_PRESETS.map((p) => <SelectItem key={p} value={p} data-testid={`period-${p}`}>FY {p}</SelectItem>)}
                  <SelectItem value="__custom" data-testid="period-custom">Custom…</SelectItem>
                </SelectContent>
              </Select>
              {period === "__custom" && (
                <Input
                  data-testid="period-custom-input"
                  className="mt-2 rounded-sm shadow-none border-[#D4D4D0]"
                  placeholder="Enter period label, e.g. Q1-2024-25"
                  value={customPeriod}
                  onChange={(e) => setCustomPeriod(e.target.value)}
                />
              )}
            </div>
            {isMulti && (
              <div>
                <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Division</Label>
                <Select value={divisionId} onValueChange={setDivisionId}>
                  <SelectTrigger data-testid="division-select" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"><SelectValue placeholder="Pick division"/></SelectTrigger>
                  <SelectContent>
                    {(client.divisions || []).map((d) => (
                      <SelectItem key={d.division_id} value={d.division_id} data-testid={`division-opt-${d.division_id}`}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <button onClick={() => setShowAddDiv(true)} className="mt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-[#0F172A] hover:underline inline-flex items-center gap-1" data-testid="add-division-open">
                  <Plus size={12} weight="bold"/> Add another division
                </button>
              </div>
            )}
            <div className="flex items-end">
              <Button
                data-testid="start-run-btn"
                disabled={!effectivePeriod || (isMulti && !divisionId)}
                onClick={() => setShowUpload(true)}
                className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 disabled:opacity-50"
              >
                Start Run <ArrowRight size={14} weight="bold"/>
              </Button>
            </div>
          </div>
        </section>
        )}

        {/* Runs grouped by period */}
        <section className="mt-10">
          <h3 className="font-heading text-lg tracking-tight">Runs</h3>
          {grouped.length === 0 ? (
            <div className="mt-3 border border-dashed border-[#D4D4D0] bg-white rounded-sm p-8 text-center text-sm text-[#52524E]">
              No runs yet for this client.
            </div>
          ) : (
            grouped.map(([per, list]) => {
              // Release 4.4.12 — Consolidated Report is a computed merge
              // of per-division runs.  Only show the button when the
              // auditor is in Consolidation scope view (never inside a
              // specific division's view).  Requires ≥1 generated
              // division run for the period.
              const generatedDivs = list.filter((r) => r.generated && r.division_id);
              const showConsolidated =
                isMulti &&
                urlScope.scopeKind === "consolidation" &&
                generatedDivs.length >= 1;
              return (
                <div key={per} className="mt-5 border border-[#E5E5E0] bg-white rounded-sm">
                  <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
                    <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">FY · {per}</div>
                    <Badge className="bg-slate-100 text-slate-800 border-slate-200 rounded-sm shadow-none">{list.length} runs</Badge>
                    {showConsolidated && (
                      <Button
                        data-testid={`open-consolidated-${per}`}
                        onClick={() => navigate(`/dashboard/clients/${clientId}/utilities/clause-44/consolidated/${encodeURIComponent(per)}`)}
                        className="ml-auto h-8 px-3 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 text-xs"
                      >
                        <Stack size={12} weight="bold"/> Consolidated Report
                      </Button>
                    )}
                  </div>
                  <ul>
                    {list.map((r) => (
                      <li key={r.run_id} className="px-4 py-3 border-b border-[#E5E5E0] last:border-b-0 flex items-center gap-3 hover:bg-[#F9F9F8]" data-testid={`run-${r.run_id}`}>
                        <div className="flex-1 min-w-0">
                          <div className="text-[14px] font-medium truncate flex items-center gap-2 flex-wrap">
                            <span>{r.division_name || "Single scope"}</span>
                            <ScopeChip run={r} isMulti={isMulti} />
                            <span className="text-[#8A8A83]">·</span>
                            <span className="font-normal text-[#52524E]">{r.company_name}</span>
                          </div>
                          <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#8A8A83] mt-0.5">
                            {r.generated && r.generated_by_name ? (
                              <>
                                Generated by <span className="text-[#0F172A]">{r.generated_by_name}</span> · {formatDateTime(r.generated_at)}
                              </>
                            ) : r.created_by_name ? (
                              <>
                                Uploaded by <span className="text-[#52524E]">{r.created_by_name}</span> · {formatDateTime(r.created_at)} · Draft
                              </>
                            ) : (
                              <>{formatDate(r.created_at)} · {r.generated ? "Generated" : "Draft"}</>
                            )}
                          </div>
                        </div>
                        {r.generated ? (
                          <Button onClick={() => navigate(`/dashboard/runs/${r.run_id}/report`)} variant="outline" className="h-8 px-3 border-[#D4D4D0] rounded-sm shadow-none gap-2 text-xs" data-testid={`open-report-${r.run_id}`}>
                            <ChartBar size={12} weight="bold"/> Report
                          </Button>
                        ) : (
                          <Button onClick={() => navigate(`/dashboard/runs/${r.run_id}`)} variant="outline" className="h-8 px-3 border-[#D4D4D0] rounded-sm shadow-none gap-2 text-xs" data-testid={`open-mapping-${r.run_id}`}>
                            <FileArrowDown size={12} weight="bold"/> Continue
                          </Button>
                        )}
                        <button onClick={() => onArchive(r.run_id)} className="text-[#8A8A83] hover:text-[#991B1B]" title="Archive" data-testid={`archive-run-${r.run_id}`}>
                          <Archive size={14}/>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </section>
      </div>

      {/* Add division dialog */}
      <Dialog open={showAddDiv} onOpenChange={setShowAddDiv}>
        <DialogContent className="bg-white border border-[#E5E5E0] rounded-sm" data-testid="add-division-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Add Division</DialogTitle>
          </DialogHeader>
          <div>
            <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Division Name</Label>
            <Input data-testid="new-division-input" value={newDiv} onChange={(e) => setNewDiv(e.target.value)} className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"/>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowAddDiv(false)}>Cancel</Button>
            <Button data-testid="submit-new-division" onClick={onAddDivision} className="bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none">Add</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upload dialog */}
      <Dialog open={showUpload} onOpenChange={setShowUpload}>
        <DialogContent className="bg-white border border-[#E5E5E0] rounded-sm max-w-3xl p-0" data-testid="upload-dialog">
          <DialogHeader className="px-6 pt-5 pb-3 border-b border-[#E5E5E0]">
            <DialogTitle className="font-heading text-xl">Upload Books</DialogTitle>
            <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">
              {client.name} · FY {effectivePeriod}{isMulti ? ` · ${(client.divisions || []).find((d) => d.division_id === divisionId)?.name || "—"}` : ""}
            </div>
          </DialogHeader>
          <StepUpload
            clientId={clientId}
            period={effectivePeriod}
            divisionId={isMulti ? divisionId : null}
            /* Release 4.4.12 (Clause 44) — Consolidated view is a
               computed merge, not an upload target.  Never request
               scope_kind="consolidation" on upload. */
            scopeKind={null}
            onUploaded={(runId) => {
              setShowUpload(false);
              navigate(`/dashboard/runs/${runId}`);
            }}
          />
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
