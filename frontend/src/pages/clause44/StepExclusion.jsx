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
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Recon Adjustments</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        This step builds the bridge between your <strong>P&amp;L expenditure</strong> and the
        Clause 44 <strong>Col 2 reportable expenditure</strong>.  Two kinds of ticks here, marked per row:
      </p>
      <ul className="mt-2 text-sm text-[#52524E] max-w-3xl space-y-1.5">
        <li><span className="inline-block px-1.5 py-0.5 mr-1 bg-slate-50 border border-slate-200 rounded-sm font-mono text-[10px]">↓ SUBTRACT</span>
          ledgers that aren't supplies — depreciation, salaries, interest on tax dues, PF/ESI, drawings, capital A/c, etc.  We've pre-ticked obvious matches.</li>
        <li><span className="inline-block px-1.5 py-0.5 mr-1 bg-violet-50 border border-violet-200 rounded-sm font-mono text-[10px]">↑ ADD-BACK</span>
          capex ledgers (Fixed Assets &amp; Intangibles).  Capex purchases <em>are</em> reportable in Col 2 but don't sit in P&amp;L — tick to bring them into the recon as an add-back.  <strong>Not pre-ticked</strong> by design; review and pick per audit judgement.</li>
      </ul>
      <p className="mt-3 text-sm text-[#52524E] max-w-3xl">
        Your picks here populate the 5-line ICAI recon and the Excel "Reconciliation" sheet.
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
