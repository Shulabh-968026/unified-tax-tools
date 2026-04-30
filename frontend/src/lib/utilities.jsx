import { ArrowRight, Lock, FileText, Receipt, Scales, Buildings, FileMagnifyingGlass, Wrench, Handshake, CurrencyCircleDollar, ArrowsLeftRight } from "@phosphor-icons/react";
import { ACCENTS } from "@/lib/colors";

// id matches a route under /dashboard/clients/:clientId/utilities/<id>
export const UTILITIES = [
  { id: "gst-turnover-recon", title: "GST Turnover Recon", description: "Reconcile turnover declared in books against GSTR-1, GSTR-3B and GSTR-9.", icon: ArrowsLeftRight, status: "active", accent: "indigo" },
  { id: "tds-disallowance",   title: "TDS Disallowance & Recon", description: "Identify Section 40(a)(ia) disallowances; reconcile TDS deducted vs deposited.", icon: Scales, status: "soon", accent: "teal" },
  { id: "msme-43bh",          title: "43BH MSME Disallowance", description: "Section 43B(h) disallowance for delayed payments to MSME suppliers.", icon: Buildings, status: "active", accent: "amber" },
  { id: "clause-44",          title: "Clause 44 — 3CD", description: "Expenditure schedule with ITC + exclusion mapping, drill-down and Excel breakup.", icon: FileText, status: "active", accent: "emerald" },
  { id: "clause-34",          title: "TDS Clause 34 — 3CD", description: "Tax deducted/collected at source disclosure with section-wise summary.", icon: Receipt, status: "soon", accent: "sky" },
  { id: "ais-tis-26as",       title: "AIS / TIS / 26AS Recon", description: "Cross-walk income reported to books across AIS, TIS and Form 26AS.", icon: FileMagnifyingGlass, status: "soon", accent: "violet" },
  { id: "fixed-assets",       title: "Fixed Assets", description: "Income-tax depreciation: block register, additions, deletions, FY continuity.", icon: Wrench, status: "active", accent: "slate" },
  { id: "balance-confirmation", title: "Balance Confirmation", description: "Generate and track third-party balance confirmation requests.", icon: Handshake, status: "active", accent: "rose" },
  { id: "gst-refund-31",      title: "GST Refund — 3CD Clause 31", description: "Disclosure of refunds claimed and received under GST.", icon: CurrencyCircleDollar, status: "soon", accent: "fuchsia" },
];

export function UtilityCard({ utility, onOpen }) {
  const Icon = utility.icon;
  const active = utility.status === "active";
  const inProgress = utility.status === "in_progress";
  const a = ACCENTS[utility.accent] || ACCENTS.slate;
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
