/**
 * Step 3 — Expense Exclusions
 * P&L ledgers that are not supplies (salaries, interest, depreciation, …).
 * Anything ticked here is removed from Clause 44 totals.  The reconciliation
 * tab later shows exactly what was excluded and how it ties to books.
 */
import { Badge } from "@/components/ui/badge";
import { X } from "@phosphor-icons/react";
import LedgerList from "./LedgerList";

export default function StepExclusion({
  run, selected, setSelected, query, setQuery,
}) {
  const items = run?.pl_ledgers || [];
  const toggle = (name) => {
    const n = new Set(selected);
    n.has(name) ? n.delete(name) : n.add(name);
    setSelected(n);
  };
  return (
    <section className="mx-auto max-w-4xl" data-testid="step-exclusion">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 03 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Select Expense Exclusions</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-2xl">
        Tick P&amp;L ledgers that are <strong>not supplies of goods or services</strong> —
        depreciation, salaries &amp; wages, interest, PF/ESI, income tax, bonus,
        drawings, capital charges. We've pre-ticked obvious name matches; please
        review before proceeding. Excluded ledgers are removed from Clause 44
        totals and reconciled separately in Step 04.
      </p>

      <div className="mt-6 flex items-baseline justify-between mb-3">
        <div className="text-xs text-[#52524E]">Exclusions never appear in columns 3–7 of the schedule.</div>
        <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
          {selected.size}/{items.length}
        </Badge>
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3" data-testid="exclusion-chips">
          {Array.from(selected).map((n) => (
            <Badge key={n} className="bg-[#991B1B] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
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
        emptyHint="No P&L ledgers detected."
        testidPrefix="exclusion"
        showSubhead={false}
      />
    </section>
  );
}
