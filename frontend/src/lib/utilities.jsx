import { ArrowRight, Lock, FileText, Scales, Buildings, FileMagnifyingGlass, Wrench, Handshake, CurrencyCircleDollar, ArrowsLeftRight, ChartLine } from "@phosphor-icons/react";
import { ACCENTS } from "@/lib/colors";

// id matches a route under /dashboard/clients/:clientId/utilities/<id>
// `module_key` matches the backend's MODULE_DEPENDENCIES key in
// modules/library/catalog.py — used to join Library status info.
export const UTILITIES = [
  { id: "gst-turnover-recon", module_key: "gst_recon",            title: "GST Turnover Recon", description: "Reconcile turnover declared in books against GSTR-1, GSTR-3B and GSTR-9.", icon: ArrowsLeftRight, status: "active", accent: "indigo" },
  { id: "tds-recon",          module_key: null,                   title: "TDS Reconciliation", description: "Section 40(a)(ia) disallowance, TDS deducted vs deposited, and Clause 34 — 3CD disclosure under one roof.", icon: Scales, status: "soon", accent: "teal" },
  { id: "msme-43bh",          module_key: "msme43bh",             title: "43BH MSME Disallowance", description: "Section 43B(h) disallowance for delayed payments to MSME suppliers.", icon: Buildings, status: "active", accent: "amber" },
  { id: "clause-44",          module_key: "clause44",             title: "Clause 44 — 3CD", description: "Expenditure schedule with ITC + exclusion mapping, drill-down and Excel breakup.", icon: FileText, status: "active", accent: "emerald" },
  { id: "fin-statement",      module_key: "fin_statement",        title: "Financial Statement Designer", description: "Tally JSON → Schedule III Balance Sheet, P&L, Cash Flow & Notes — rendered as a signature-ready PDF in two designer templates.", icon: ChartLine, status: "active", accent: "sky" },
  { id: "ais-tis-26as",       module_key: null,                   title: "AIS / TIS / 26AS Recon", description: "Cross-walk income reported to books across AIS, TIS and Form 26AS.", icon: FileMagnifyingGlass, status: "soon", accent: "violet" },
  { id: "fixed-assets",       module_key: "fixed_assets",         title: "Fixed Assets", description: "Income-tax depreciation: block register, additions, deletions, FY continuity.", icon: Wrench, status: "active", accent: "slate" },
  { id: "balance-confirmation", module_key: "balance_confirmation", title: "Balance Confirmation", description: "Generate and track third-party balance confirmation requests.", icon: Handshake, status: "active", accent: "rose" },
  { id: "gst-refund-31",      module_key: null,                   title: "GST Refund — 3CD Clause 31", description: "Disclosure of refunds claimed and received under GST.", icon: CurrencyCircleDollar, status: "soon", accent: "fuchsia" },
];

export function UtilityCard({ utility, onOpen, libraryStatus = null }) {
  const Icon = utility.icon;
  const active = utility.status === "active";
  const inProgress = utility.status === "in_progress";
  const a = ACCENTS[utility.accent] || ACCENTS.slate;
  // Library-driven 4-state catalog status:
  //   data_missing       (red)    — no primary deps uploaded
  //   partial_data_ready (amber)  — some but not all deps uploaded
  //   data_ready         (yellow) — all deps uploaded but no run yet OR run is outdated
  //   report_ready       (green)  — has_run AND fresh (not outdated, not missing)
  let dataChip = null;
  if (active && libraryStatus && Array.isArray(libraryStatus.dependencies)) {
    const deps = libraryStatus.dependencies;
    const total = deps.length;
    const uploaded = deps.filter((d) => !!d.current_file_id).length;
    let state, label, klass, title;
    if (total === 0) {
      // Defensive: module declares no deps — fall back to a neutral
      // "Open" cue so the tile still feels actionable.
      state = null;
    } else if (uploaded === 0) {
      state = "data_missing";
      label = "⊘ Data Missing";
      klass = "bg-rose-50 text-rose-900 border-rose-200";
      title = `Required input files have not been uploaded to the Library yet (${uploaded} of ${total} dependencies in place).`;
    } else if (uploaded < total) {
      state = "partial_data_ready";
      label = `▲ Partial Data Ready · ${uploaded}/${total}`;
      klass = "bg-amber-50 text-amber-900 border-amber-300";
      title = `${uploaded} of ${total} required inputs uploaded — please complete the remaining ${total - uploaded} to unlock this utility.`;
    } else if (libraryStatus.has_run && !libraryStatus.outdated && !libraryStatus.missing) {
      state = "report_ready";
      label = "✓ Report Ready";
      klass = "bg-emerald-50 text-emerald-900 border-emerald-200";
      title = "All inputs uploaded and the latest report is in sync with them.";
    } else {
      state = "data_ready";
      label = libraryStatus.outdated ? "◆ Data Ready · Rerun pending" : "◆ Data Ready";
      klass = "bg-yellow-50 text-yellow-900 border-yellow-300";
      title = libraryStatus.outdated
        ? "All inputs are present but the last run was pinned to an older version — rerun to refresh the report."
        : "All inputs uploaded.  Open the utility to generate the report.";
    }
    if (state) {
      dataChip = (
        <span
          data-testid={`utility-data-${state}-${utility.id}`}
          className={`font-mono text-[10px] uppercase tracking-[0.16em] border px-1.5 py-0.5 rounded-sm ${klass}`}
          title={title}
        >
          {label}
        </span>
      );
    }
  }
  return (
    <button
      data-testid={`utility-card-${utility.id}`}
      disabled={!active}
      onClick={() => active && onOpen(utility)}
      className={`group relative text-left bg-white p-5 transition-all ${
        active ? "hover:bg-[#F9F9F8] cursor-pointer hover:-translate-y-[1px]" : "cursor-not-allowed opacity-[0.78]"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className={`w-10 h-10 grid place-items-center border ${active || inProgress ? `${a.bg} ${a.border} ${a.text}` : "border-[#D4D4D0] text-[#52524E]"}`}>
          <Icon size={18} weight={active || inProgress ? "duotone" : "regular"}/>
        </div>
        <div className="flex flex-col items-end gap-1">
          {active ? (
            <span className={`font-mono text-[10px] uppercase tracking-[0.18em] ${a.text} ${a.chip} ${a.border} border px-1.5 py-0.5 rounded-sm`}>Live</span>
          ) : inProgress ? (
            <span className={`font-mono text-[10px] uppercase tracking-[0.18em] ${a.text} ${a.chip} ${a.border} border px-1.5 py-0.5 rounded-sm inline-flex items-center gap-1`}>
              <span className={`w-1.5 h-1.5 rounded-full ${a.bg} animate-pulse`}/> In Progress
            </span>
          ) : (
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#8A8A83] bg-[#F3F4F1] border border-[#E5E5E0] px-1.5 py-0.5 rounded-sm inline-flex items-center gap-1">
              <Lock size={9} weight="fill"/> Coming Soon
            </span>
          )}
          {dataChip}
        </div>
      </div>
      <div className="mt-5 font-heading text-[17px] tracking-tight leading-tight">{utility.title}</div>
      <p className="mt-1.5 text-[12.5px] text-[#52524E] leading-relaxed">{utility.description}</p>
      <div className={`mt-5 inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.12em] ${active ? a.text : inProgress ? a.text : "text-[#8A8A83]"}`}>
        {active ? (
          <>Open utility <ArrowRight size={11} weight="bold" className="transition-transform group-hover:translate-x-0.5"/></>
        ) : inProgress ? (
          <>Being built — available soon</>
        ) : (
          <>Not yet available</>
        )}
      </div>
    </button>
  );
}
