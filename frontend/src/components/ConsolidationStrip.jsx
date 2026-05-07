import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Stack, Plus, ArrowRight } from "@phosphor-icons/react";
import { http } from "@/lib/api";
import ScopeChip from "@/components/ScopeChip";

/**
 * ConsolidationStrip — Phase C.2 scaffold
 *
 * Renders a per-division progress strip ABOVE a module's past-runs list
 * when the auditor has selected ``?scope=consolidation`` on a multi-
 * division client.  It pulls every run (any scope) for the current
 * (client_id, fy) via the module's existing GET /runs endpoint and
 * groups the rows by ``scope_label`` so the auditor can see at a glance:
 *
 *   • which divisions already have a working doc started
 *   • which still show "Not started"
 *   • a placeholder "Generate Consolidated Report" CTA (wired up in
 *     Phase C.4 — disabled here with a tooltip).
 *
 * Intentionally read-only (no compute / no ingest) — it just composes
 * the existing per-division docs into one view.  Drop into any module
 * that exposes ``GET <listPath>?client_id=`` returning rows with
 * ``fy``, ``scope_kind``, ``scope_label``, ``status``, and ``id``.
 */
export default function ConsolidationStrip({
  clientId, fy, divisions, scope, listPath, runHrefBase, runIdField = "id",
}) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  const isConsolidationOnMulti =
    scope?.scopeKind === "consolidation" &&
    Array.isArray(divisions) && divisions.length >= 2;

  useEffect(() => {
    if (!isConsolidationOnMulti) return;
    let cancel = false;
    setLoading(true);
    http.get(listPath, { params: { client_id: clientId } })
      .then((r) => { if (!cancel) setRows(r.data || []); })
      .catch(() => { if (!cancel) setRows([]); })
      .finally(() => { if (!cancel) setLoading(false); });
    return () => { cancel = true; };
  }, [clientId, isConsolidationOnMulti, listPath]);

  // Group runs of the current FY by scope_kind/division.
  const grouped = useMemo(() => {
    const inFy = (rows || []).filter((r) => (r.fy || "") === fy);
    const byDiv = new Map();
    let consolidationRun = null;
    for (const r of inFy) {
      if (r.scope_kind === "division") {
        const k = (r.division_ids && r.division_ids[0]) || "?";
        byDiv.set(k, r);
      } else if (r.scope_kind === "consolidation") {
        consolidationRun = r;
      }
    }
    return { byDiv, consolidationRun };
  }, [rows, fy]);

  if (!isConsolidationOnMulti) return null;

  return (
    <div data-testid="consolidation-strip" className="mb-4 border border-emerald-200 bg-emerald-50/40">
      <div className="px-4 py-2.5 border-b border-emerald-200 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Stack size={14} className="text-emerald-700" weight="bold" />
          <span className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-emerald-900">
            Consolidation View · FY {fy} · {divisions.length} divisions
          </span>
        </div>
        <button
          type="button"
          data-testid="generate-consolidated-btn"
          disabled
          className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-emerald-300 bg-white text-[11.5px] font-medium text-emerald-900 hover:bg-emerald-100 disabled:opacity-60 disabled:cursor-not-allowed rounded-sm"
          title="Available in Phase C.4 — will compose per-division reports + Totals."
        >
          <ArrowRight size={11} /> Generate Consolidated
        </button>
      </div>
      {loading ? (
        <div className="px-4 py-6 text-center text-[12px] text-emerald-900/70 font-mono">
          Loading per-division progress…
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 p-3">
          {divisions.map((d) => {
            const run = grouped.byDiv.get(d.division_id);
            return (
              <div
                key={d.division_id}
                data-testid={`consolidation-div-${d.division_id}`}
                className="bg-white border border-emerald-100 hover:border-emerald-300 transition rounded-sm px-3 py-2.5"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="font-medium text-[12.5px] text-slate-900 truncate">{d.name}</span>
                </div>
                {run ? (
                  <div className="flex items-center justify-between gap-2">
                    <span className={`font-mono text-[10px] uppercase tracking-[0.14em] px-1.5 py-0.5 border rounded-sm ${
                      run.status === "ingested" || run.status === "summarised"
                        ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                        : run.status === "draft" || run.status === "created"
                        ? "border-slate-300 bg-slate-50 text-slate-700"
                        : "border-amber-300 bg-amber-50 text-amber-800"
                    }`}>{run.status || "draft"}</span>
                    {runHrefBase && (
                      <Link
                        to={`${runHrefBase}/${run[runIdField]}?scope=div_${d.division_id}&fy=${fy}`}
                        className="text-[11px] text-sky-700 hover:text-sky-900"
                        data-testid={`consolidation-div-${d.division_id}-open`}
                      >
                        Open →
                      </Link>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500 border border-slate-200 bg-slate-50 px-1.5 py-0.5 rounded-sm">
                      Not started
                    </span>
                    <span className="font-mono text-[10px] text-slate-400">—</span>
                  </div>
                )}
              </div>
            );
          })}
          {grouped.consolidationRun && (
            <div className="col-span-full mt-1 px-3 py-2 bg-emerald-50/80 border border-emerald-200 rounded-sm flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <ScopeChip run={grouped.consolidationRun} isMulti />
                <span className="text-[11.5px] text-emerald-950 font-mono">
                  {grouped.consolidationRun.name || "Consolidation"} · {grouped.consolidationRun.status}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
