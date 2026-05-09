import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ArrowLeft, Stack, Buildings, Folder, AppWindow, CalendarBlank } from "@phosphor-icons/react";
import { getClient, http, listRuns } from "@/lib/api";
import { UTILITIES, UtilityCard } from "@/lib/utilities";
import { toast } from "sonner";
import ClientLibraryPanel from "@/components/ClientLibraryPanel";
import { FY_OPTIONS, DEFAULT_FY, isValidFy } from "@/lib/fy";
import { encodeScope, decodeScope, isMultiDiv } from "@/lib/scope";

export default function ClientUtilities() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [client, setClient] = useState(null);
  const [libByModule, setLibByModule] = useState({});
  // Release 4.4.13 — Mode-A consolidation tile status.  At Consolidation
  // scope, the Clause 44 tile's data-status chip can't be derived from
  // Library uploads (there are none — Mode A ships division-scoped
  // uploads only).  Instead we drive it from the per-division generation
  // coverage for the working FY.  Cached in this state.
  const [clause44RunsByDivision, setClause44RunsByDivision] = useState(null);
  // Tab persistence — `?tab=library` opens straight into the data
  // library, default `utilities`.  Lets us deep-link from elsewhere.
  const tab = searchParams.get("tab") === "library" ? "library" : "utilities";
  const setTab = (v) => {
    const next = new URLSearchParams(searchParams);
    if (v === "utilities") next.delete("tab"); else next.set("tab", v);
    setSearchParams(next, { replace: true });
  };

  // FY persistence — `?fy=2025-26` is respected; otherwise we default to
  // the most-recently-concluded audit FY (see @/lib/fy).  Changing the
  // selector rewrites the URL so the Library panel + utility tiles
  // recompute from the same period.
  const urlFy = searchParams.get("fy");
  const fy = urlFy && isValidFy(urlFy) ? urlFy : DEFAULT_FY;
  const setFy = (v) => {
    const next = new URLSearchParams(searchParams);
    if (!v || v === DEFAULT_FY) next.delete("fy"); else next.set("fy", v);
    setSearchParams(next, { replace: true });
  };

  // Phase B — Scope persistence (`?scope=consolidation | div_xxx | gstin_xxx`).
  // Default scope is "consolidation" for multi-div clients, ignored for
  // single-div (where there's only one effective scope).
  const [gstinGroups, setGstinGroups] = useState([]);
  const divisions = client?.divisions || [];
  const scope = decodeScope(
    searchParams.get("scope"),
    { divisions, gstinGroups },
  ) || { kind: "consolidation", id: null, label: "Consolidation" };
  const setScope = (s) => {
    const next = new URLSearchParams(searchParams);
    const enc = encodeScope(s);
    if (!enc || enc === "consolidation") next.delete("scope"); else next.set("scope", enc);
    setSearchParams(next, { replace: true });
  };
  // Load GSTIN groups (only for multi-div clients).
  useEffect(() => {
    if (!clientId || !isMultiDiv(divisions)) { setGstinGroups([]); return; }
    let cancelled = false;
    http.get(`/library/clients/${clientId}/gstin-groups`)
      .then(({ data }) => { if (!cancelled) setGstinGroups(data?.groups || []); })
      .catch(() => { if (!cancelled) setGstinGroups([]); });
    return () => { cancelled = true; };
  }, [clientId, divisions.length]);  // eslint-disable-line

  useEffect(() => {
    (async () => {
      try { setClient(await getClient(clientId)); }
      catch { toast.error("Client not found"); navigate("/dashboard", { replace: true }); }
    })();
  }, [clientId, navigate]);

  // Release 4.4.13 — fetch Clause 44 runs for the FY when the auditor is
  // in Consolidation scope on a multi-division client.  Used to compute
  // the data-status chip on the Clause 44 tile (Mode A — Consolidated is
  // a computed merge of generated division runs).
  useEffect(() => {
    if (!clientId || !client) return;
    const isMultiClient = client.type === "multi";
    const inConsolidation = !isMultiClient || scope.kind === "consolidation";
    if (!isMultiClient || !inConsolidation) {
      setClause44RunsByDivision(null);
      return;
    }
    let cancelled = false;
    listRuns({ client_id: clientId, period: fy })
      .then((resp) => {
        if (cancelled) return;
        const rows = Array.isArray(resp) ? resp : (resp?.runs || []);
        const byDiv = {};
        for (const r of rows) {
          if (!r.division_id) continue;            // skip stray non-division
          // Track best-of (generated > non-generated) per division.
          const cur = byDiv[r.division_id];
          if (!cur || (r.generated && !cur.generated)) {
            byDiv[r.division_id] = r;
          }
        }
        setClause44RunsByDivision(byDiv);
      })
      .catch(() => { if (!cancelled) setClause44RunsByDivision({}); });
    return () => { cancelled = true; };
  }, [clientId, client, fy, scope.kind]);

  // Release 4.4.13 — synthesise a `libraryStatus` payload for the
  // Clause 44 tile when in Consolidation scope.  Each division becomes
  // a "dependency"; current_file_id is set ⇔ that division has a
  // generated run for this FY.  This piggybacks on the existing 4-state
  // chip logic in `UtilityCard` (Data Missing → Partial → Data Ready →
  // Report Ready) without requiring any change to that component.
  const synthClause44ConsolidationStatus = useMemo(() => {
    if (!client) return null;
    const isMultiClient = client.type === "multi";
    if (!isMultiClient) return null;
    if (scope.kind !== "consolidation") return null;
    if (clause44RunsByDivision === null) return null;
    const divs = client.divisions || [];
    if (divs.length === 0) return null;
    const allGenerated = divs.every(
      (d) => clause44RunsByDivision[d.division_id]?.generated,
    );
    return {
      dependencies: divs.map((d) => {
        const r = clause44RunsByDivision[d.division_id];
        return {
          key:             `division_${d.division_id}_run`,
          label:           `${d.name} run`,
          current_file_id: r?.generated ? d.division_id : null,
        };
      }),
      // Once every division has a generated run, the Consolidated view
      // is a one-click read.  Treat that as "Report Ready" so the chip
      // turns green — matches the auditor's mental model that "all
      // divisions reported = consolidated is ready".
      report_generated: allGenerated,
      outdated:         false,
      missing:          false,
    };
  }, [client, scope.kind, clause44RunsByDivision]);

  const onLibraryChange = (status) => {
    const map = {};
    (status?.modules || []).forEach((m) => { map[m.module_key] = m; });
    setLibByModule(map);
  };

  const onOpen = (u) => {
    // Forward FY + scope to the module so it can pick up the same
    // working period + scope without re-reading client/state.
    const qs = new URLSearchParams();
    if (fy && fy !== DEFAULT_FY) qs.set("fy", fy);
    const enc = encodeScope(scope);
    if (enc && enc !== "consolidation") qs.set("scope", enc);
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    if (u.id === "clause-44") {
      navigate(`/dashboard/clients/${clientId}/utilities/clause-44${tail}`);
    } else if (u.id === "msme-43bh") {
      navigate(`/dashboard/clients/${clientId}/utilities/msme-43bh${tail}`);
    } else if (u.id === "gst-turnover-recon") {
      navigate(`/dashboard/clients/${clientId}/utilities/gst-recon${tail}`);
    } else if (u.id === "balance-confirmation") {
      navigate(`/dashboard/clients/${clientId}/utilities/balance-confirmation${tail}`);
    } else if (u.id === "fixed-assets") {
      navigate(`/dashboard/clients/${clientId}/utilities/fixed-assets${tail}`);
    } else if (u.id === "fin-statement") {
      navigate(`/dashboard/clients/${clientId}/utilities/fin-statement${tail}`);
    }
  };

  if (!client) return <AppShell><div className="p-10 font-mono text-sm text-[#8A8A83]">Loading client…</div></AppShell>;
  const isMulti = client.type === "multi";
  const liveCount = UTILITIES.filter((u) => u.status === "active").length;

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate("/dashboard")} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>All clients</button>}
        title={client.name}
        subtitle={
          <span className="inline-flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">File · {client.file_number}</span>
            {client.gstin && (
              <>
                <span>·</span>
                <span className="font-mono text-[11px] tracking-[0.12em] text-[#52524E]" data-testid="client-gstin-display">
                  GSTIN · <span className="text-[#0F172A] font-semibold">{client.gstin}</span>
                </span>
              </>
            )}
            <span>·</span>
            <Badge className={`${isMulti ? "bg-amber-50 text-amber-900 border-amber-200" : "bg-emerald-50 text-emerald-900 border-emerald-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
              {isMulti ? <><Stack size={10} className="mr-1"/>Multi · {client.divisions?.length || 0} div</> : <><Buildings size={10} className="mr-1"/>Single</>}
            </Badge>
          </span>
        }
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-[1200px]">
        {/* FY selector — single source of truth for the page.  Both Library
            panels (visible + hidden) and any utility status chip read off this. */}
        <div
          className="mb-6 flex items-center gap-3 flex-wrap"
          data-testid="client-fy-bar"
        >
          <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83] inline-flex items-center gap-1.5">
            <CalendarBlank size={12}/> Working Period
          </span>
          <select
            value={fy}
            onChange={(e) => setFy(e.target.value)}
            data-testid="client-fy-select"
            className="font-mono text-[12px] tracking-wide border border-[#E5E5E0] bg-white rounded-sm px-3 py-1.5 hover:border-[#0F172A] focus:outline-none focus:border-[#0F172A]"
          >
            {FY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>FY {opt}</option>
            ))}
          </select>
          {isMultiDiv(divisions) && (
            <>
              <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83] inline-flex items-center gap-1.5 ml-2">
                Scope
              </span>
              <select
                value={encodeScope(scope) || "consolidation"}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "consolidation") setScope({ kind: "consolidation" });
                  else if (v.startsWith("div_")) {
                    const id = v.slice(4);
                    const d = divisions.find((x) => x.division_id === id);
                    if (d) setScope({ kind: "division", id, label: d.name, divisions: [id] });
                  } else if (v.startsWith("gstin_")) {
                    const id = v.slice(6);
                    const g = gstinGroups.find((x) => x.group_id === id);
                    if (g) setScope({ kind: "gstin_group", id, label: g.label, gstin: g.gstin || "", divisions: g.division_ids });
                  }
                }}
                data-testid="client-scope-select"
                className="font-mono text-[12px] tracking-wide border border-[#E5E5E0] bg-white rounded-sm px-3 py-1.5 hover:border-[#0F172A] focus:outline-none focus:border-[#0F172A]"
              >
                <optgroup label="Divisions">
                  {divisions.map((d) => (
                    <option key={d.division_id} value={`div_${d.division_id}`} data-testid={`scope-opt-div-${d.division_id}`}>
                      {d.name}
                    </option>
                  ))}
                </optgroup>
                {gstinGroups.length > 0 && (
                  <optgroup label="GSTIN Groups">
                    {gstinGroups.map((g) => (
                      <option key={g.group_id} value={`gstin_${g.group_id}`} data-testid={`scope-opt-gstin-${g.group_id}`}>
                        {g.label}{g.gstin ? ` (${g.gstin})` : ""}
                      </option>
                    ))}
                  </optgroup>
                )}
                <option value="consolidation" data-testid="scope-opt-consolidation">Consolidation (all divisions)</option>
              </select>
            </>
          )}
          <span className="text-[11px] text-[#8A8A83] font-mono">
            — Default: most recently concluded FY ({DEFAULT_FY}). All utilities &amp; the Library on this page reflect this period.
          </span>
        </div>

        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList
            data-testid="client-tabs"
            className="bg-white border border-[#E5E5E0] rounded-sm p-1 h-auto inline-flex gap-1"
          >
            <TabsTrigger
              value="utilities"
              data-testid="tab-utilities"
              className="px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] data-[state=active]:bg-[#0F172A] data-[state=active]:text-white rounded-sm shadow-none gap-2"
            >
              <AppWindow size={12}/> Utilities Catalog
            </TabsTrigger>
            <TabsTrigger
              value="library"
              data-testid="tab-library"
              className="px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] data-[state=active]:bg-[#0F172A] data-[state=active]:text-white rounded-sm shadow-none gap-2"
            >
              <Folder size={12}/> Data Library
            </TabsTrigger>
          </TabsList>

          {/* Utilities — the daily workflow.  Tile chips reflect Library
              status under the hood (see `libByModule`). */}
          <TabsContent value="utilities" className="mt-6">
            <div className="flex items-baseline justify-between flex-wrap gap-2">
              <div>
                <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83]">Utilities Catalog</div>
                <h2 className="mt-1 font-heading text-2xl tracking-tight">Pick a utility</h2>
                <p className="mt-1.5 text-sm text-[#52524E] max-w-2xl">
                  The AssureAI utility shelf — small, well-built tools that complement AssureAI for the audit chores nobody enjoys. New utilities ship every few weeks.
                </p>
              </div>
              <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">
                {liveCount} live · {UTILITIES.length - liveCount} coming soon
              </Badge>
            </div>

            <div className="mt-7 grid sm:grid-cols-2 lg:grid-cols-3 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden" data-testid="utilities-grid">
              {UTILITIES.map((u) => {
                // Release 4.4.13 — Clause 44 in Consolidation scope uses
                // a synthesised, division-coverage-driven libraryStatus
                // (see `synthClause44ConsolidationStatus`).  All other
                // tiles continue to use the Library-deps payload.
                const libStatus =
                  (u.module_key === "clause44" && synthClause44ConsolidationStatus)
                    ? synthClause44ConsolidationStatus
                    : (u.module_key ? libByModule[u.module_key] : null);
                return (
                  <UtilityCard
                    key={u.id}
                    utility={u}
                    onOpen={onOpen}
                    libraryStatus={libStatus}
                    scope={isMultiDiv(divisions) ? scope : null}
                  />
                );
              })}
            </div>

            <p className="mt-6 text-[12px] text-[#8A8A83] font-mono">
              Have a utility you'd like to see prioritised? Mention it in the next partner sync.
            </p>
          </TabsContent>

          {/* Data Library — engagement setup workflow.  Mounted in BOTH
              tabs so the status payload (driving Utility chips) is
              fetched once on mount regardless of which tab is active. */}
          <TabsContent value="library" className="mt-6">
            <ClientLibraryPanel
              clientId={clientId}
              divisions={client.divisions || []}
              initialPeriod={fy}
              periodLocked
              scope={scope}
              onChange={onLibraryChange}
            />
          </TabsContent>
        </Tabs>

        {/* Hidden mount of the library when on the Utilities tab — keeps
            the status payload fresh so the Utility tiles show correct
            chips on first paint. */}
        {tab !== "library" && (
          <div className="hidden">
            <ClientLibraryPanel
              clientId={clientId}
              divisions={client.divisions || []}
              initialPeriod={fy}
              periodLocked
              scope={scope}
              onChange={onLibraryChange}
            />
          </div>
        )}
      </div>
    </AppShell>
  );
}
