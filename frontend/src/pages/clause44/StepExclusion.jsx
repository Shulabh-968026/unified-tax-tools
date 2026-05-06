/**
 * Step 3 — Expense Exclusions (Release 4.4 — three-pool model).
 *
 * Pool: every P-side ledger plus capex (B-side under
 * Property/Plant/Equipment + Intangible Fixed Assets), excluding
 * Revenue from Operations / Other Income.  Auditor ticks ledgers that
 * are not supplies — depreciation, salaries, interest, PF/ESI, income
 * tax, capex, etc.  Anything ticked is removed from Clause 44 totals.
 */
import LedgerTable from "./LedgerTable";

export default function StepExclusion({
  run, selected, setSelected,
}) {
  const items = run?.exclusion_ledgers || [];
  const toggle = (name) => {
    const n = new Set(selected);
    n.has(name) ? n.delete(name) : n.add(name);
    setSelected(n);
  };
  return (
    <section className="mx-auto max-w-7xl" data-testid="step-exclusion">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 03 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Select Expense Exclusions</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        Tick ledgers that are <strong>not supplies of goods or services</strong> —
        depreciation, salaries &amp; wages, interest, PF/ESI, income tax, bonus,
        drawings, capital expenditure, etc.  We've pre-ticked obvious name
        matches and capex (Fixed Assets &amp; Intangibles); please review before
        proceeding.  Excluded ledgers are removed from Clause 44 totals and
        reconciled separately in Step 04.
      </p>

      <div className="mt-6">
        <LedgerTable
          items={items}
          selected={selected}
          setSelected={setSelected}
          onToggle={toggle}
          onSelectAllSuggested={() => setSelected(new Set(items.filter((x) => x.suggested).map((x) => x.name)))}
          onClear={() => setSelected(new Set())}
          testidPrefix="exclusion"
          emptyHint="No exclusion-eligible ledgers in this run."
          suggestedLabel="exclusion-hint"
        />
      </div>
    </section>
  );
}
