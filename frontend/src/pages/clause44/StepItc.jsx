/**
 * Step 2 — ITC Ledgers
 * Single-column layout.  Selected chips, then the full BS ITC candidate
 * pool with the two pre-selected subheads marked "suggested".
 */
import { Badge } from "@/components/ui/badge";
import { X } from "@phosphor-icons/react";
import LedgerList from "./LedgerList";

export default function StepItc({
  run, selected, setSelected, query, setQuery,
}) {
  const items = run?.itc_candidates || [];
  const toggle = (name) => {
    const n = new Set(selected);
    n.has(name) ? n.delete(name) : n.add(name);
    setSelected(n);
  };
  return (
    <section className="mx-auto max-w-4xl" data-testid="step-itc">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 02 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Select ITC Ledgers</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-2xl">
        We pre-ticked every balance-sheet ledger whose mapping subhead is
        <strong> Balance with Revenue Authorities</strong> or
        <strong> Statutory Dues Payable</strong>. All other BS ledgers — minus
        Trade Payables, Receivables, Fixed Assets, Cash and Bank — are shown
        unticked; use the search box to add any ITC ledger that was mis-classified.
      </p>

      <div className="mt-6 flex items-baseline justify-between mb-3">
        <div className="text-xs text-[#52524E]">Each selected ledger routes its vouchers to <span className="font-mono">Col 5 · Other Registered (with ITC)</span>.</div>
        <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
          {selected.size}/{items.length}
        </Badge>
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3" data-testid="itc-chips">
          {Array.from(selected).map((n) => (
            <Badge key={n} className="bg-[#0F172A] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
              {n}
              <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => toggle(n)} aria-label={`Remove ${n}`}>
                <X size={10} weight="bold"/>
              </button>
            </Badge>
          ))}
        </div>
      )}

      <LedgerList
        items={items}
        selected={selected}
        onToggle={toggle}
        onSelectAll={() => setSelected(new Set(items.filter((x) => x.suggested).map((x) => x.name)))}
        onClear={() => setSelected(new Set())}
        query={query}
        setQuery={setQuery}
        emptyHint="No BS-side ledgers available. Check your books upload."
        testidPrefix="itc"
        showSubhead={true}
      />
    </section>
  );
}
