import { Stack } from "@phosphor-icons/react";

/**
 * ScopeChip — small read-only pill that surfaces a working doc's
 * scope (Consolidation / Division name / GSTIN-group label).
 *
 * Phase C.2 — used in every module's "Past runs" list and any other
 * place a working-doc summary card is rendered.  Returns null when:
 *   - the run has no scope_label (very old pre-Phase-C row), OR
 *   - the run is on a single-entity client (auto-resolved to
 *     consolidation; rendering "Consolidation" everywhere on a
 *     single-div client is just noise).
 */
export default function ScopeChip({ run, isMulti = true, className = "" }) {
  const label = run?.scope_label;
  if (!label) return null;
  if (!isMulti && label === "Consolidation") return null;
  const tone =
    run?.scope_kind === "consolidation"
      ? "bg-emerald-50 text-emerald-900 border-emerald-200"
      : run?.scope_kind === "gstin_group"
      ? "bg-violet-50 text-violet-900 border-violet-200"
      : "bg-slate-50 text-slate-800 border-slate-200";
  return (
    <span
      data-testid={`scope-chip-${run?.id || run?.run_id || "x"}`}
      className={`inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.12em] border px-1.5 py-0.5 rounded-sm ${tone} ${className}`}
      title={`Scope · ${label}`}
    >
      <Stack size={10}/>
      <span className="max-w-[120px] truncate">{label}</span>
    </span>
  );
}
