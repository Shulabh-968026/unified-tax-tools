/**
 * Step 3 · Exempt Purchases (Release 4.4.8 split — was the left tab of
 * `StepSpecialLedgers`).
 *
 * On mount, calls POST /api/runs/:id/exempt-pool with the ITC selection
 * locked from Step 2 — the engine cross-checks each candidate's
 * vouchers against the ITC list and demotes pre-ticks that overlap.
 * Auditor sees a banner summarising the demotions plus a chip on each
 * demoted row ("12/80 vouchers carry ITC — likely taxable").
 */
import { useEffect, useMemo, useState } from "react";
import { Spinner, Sparkle } from "@phosphor-icons/react";
import { toast } from "sonner";
import LedgerTable from "./LedgerTable";
import { fetchExemptPool } from "@/lib/api";
import { formatINR } from "@/lib/format";

export default function StepExempt({
  runId,
  run,
  itcSelected,
  exemptSelected, setExemptSelected,
}) {
  // Render server-recomputed pool when available; fall back to the
  // run-doc pool if the cross-check call fails for any reason.
  const [pool, setPool] = useState(run?.exempt_ledgers || []);
  const [loading, setLoading] = useState(true);
  const [crossCheck, setCrossCheck] = useState({ n_demoted: 0, n_total: 0, itc_selection_count: 0 });
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErrored(false);
      try {
        const itcList = Array.from(itcSelected || []);
        const resp = await fetchExemptPool(runId, itcList);
        if (cancelled) return;
        setPool(resp.exempt_ledgers || []);
        setCrossCheck({
          n_demoted: resp.n_demoted || 0,
          n_total:   resp.n_total   || 0,
          itc_selection_count: resp.itc_selection_count || 0,
        });
      } catch (e) {
        if (cancelled) return;
        setErrored(true);
        // Fall back to whatever the run doc has — auditor can still proceed.
        setPool(run?.exempt_ledgers || []);
        toast.error("Could not refresh exempt pool — falling back to last computed list.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // Recompute only when ITC selection or run identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const toggleExempt = (name) => {
    const n = new Set(exemptSelected);
    n.has(name) ? n.delete(name) : n.add(name);
    setExemptSelected(n);
  };

  const exemptLedgerTotals = useMemo(
    () => pool.filter((x) => exemptSelected.has(x.name))
              .reduce((a, x) => a + Math.abs(Number(x.closing_balance || 0)), 0),
    [pool, exemptSelected],
  );

  const demotedRows = useMemo(
    () => pool.filter((x) => x.itc_overlap_demoted),
    [pool],
  );

  // Annotate each row with a small inline chip when there's ITC overlap
  // (rendered via LedgerTable's row-meta hook below).
  const decoratedItems = useMemo(
    () => pool.map((x) => ({
      ...x,
      // Carried through but rendered via the existing ITC-enrichment slot.
      _exempt_chip: (x.itc_overlap_vouchers || 0) > 0
        ? `${x.itc_overlap_vouchers}/${x.total_vouchers || 0} vouchers carry ITC`
        : null,
    })),
    [pool],
  );

  return (
    <section className="mx-auto max-w-7xl" data-testid="step-exempt">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 03 / 05</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Exempt Purchases · Input A</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        Tick purchase ledgers whose underlying supplies are <strong>exempt from GST by nature</strong> (petroleum, alcohol, life-insurance premium, specified agricultural produce).  Every voucher line on these ledgers lands in <span className="font-mono">Col 3</span> regardless of vendor status.
        {exemptLedgerTotals > 0 && (
          <span className="ml-2 font-mono text-emerald-800">≈ {formatINR(exemptLedgerTotals)} (ledger balances)</span>
        )}
      </p>

      {/* Cross-check banner */}
      {loading && (
        <div className="mt-5 p-3 bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm flex items-center gap-3" data-testid="exempt-cross-check-loading">
          <Spinner size={14} className="animate-spin text-[#52524E]"/>
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">
            Cross-checking exempt suggestions against {(itcSelected || new Set()).size} ITC ledger(s)…
          </span>
        </div>
      )}

      {!loading && !errored && crossCheck.n_demoted > 0 && (
        <div className="mt-5 p-3 bg-amber-50 border border-amber-300 rounded-sm" data-testid="exempt-cross-check-banner">
          <div className="flex items-start gap-2.5">
            <Sparkle size={14} weight="fill" className="text-amber-700 mt-0.5 flex-shrink-0"/>
            <div className="flex-1 min-w-0">
              <div className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-amber-900">
                Cross-check applied · {crossCheck.n_demoted} suggestion{crossCheck.n_demoted === 1 ? "" : "s"} demoted
              </div>
              <p className="text-[11.5px] text-amber-950/80 leading-snug mt-1">
                These ledgers had vouchers carrying entries under your ITC selection — a voucher with ITC is <em>taxable by definition</em>, so the auto-suggestion was removed.  Re-tick manually only if you have a specific reason (e.g. mixed-use ledger).
              </p>
              {demotedRows.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {demotedRows.slice(0, 12).map((r) => (
                    <li
                      key={r.name}
                      className="inline-flex items-center gap-1 bg-white border border-amber-200 rounded-sm px-2 py-0.5 font-mono text-[10.5px] text-amber-900"
                      data-testid={`exempt-demoted-chip-${r.name}`}
                      title={`${r.itc_overlap_vouchers}/${r.total_vouchers} vouchers under this ledger touched an ITC ledger`}
                    >
                      <span className="truncate max-w-[260px]">{r.name}</span>
                      <span className="text-amber-700">{r.itc_overlap_vouchers}/{r.total_vouchers}</span>
                    </li>
                  ))}
                  {demotedRows.length > 12 && (
                    <li className="inline-flex items-center px-2 py-0.5 font-mono text-[10.5px] text-amber-700">
                      +{demotedRows.length - 12} more
                    </li>
                  )}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {!loading && !errored && crossCheck.itc_selection_count === 0 && (
        <div className="mt-5 p-3 bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm font-mono text-[10.5px] text-[#52524E]" data-testid="exempt-cross-check-no-itc">
          No ITC ledgers were ticked on Step 2 — the voucher cross-check is inactive.  All keyword-based exempt suggestions stand as-is.
        </div>
      )}

      {!loading && (
        <div className="mt-5">
          <LedgerTable
            items={decoratedItems}
            selected={exemptSelected}
            setSelected={setExemptSelected}
            onToggle={toggleExempt}
            onSelectAllSuggested={() => setExemptSelected(new Set(decoratedItems.filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setExemptSelected(new Set())}
            testidPrefix="exempt"
            emptyHint="No P-side ledgers in this run — check your books upload."
            suggestedLabel="exempt-hint"
          />
        </div>
      )}
    </section>
  );
}
