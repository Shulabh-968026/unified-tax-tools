/**
 * ICAI Para 79.4 Reconciliation — 5-line format.
 *
 *    Total P&L expenditure                    pl_total
 *  + Capex additions                          capex_total
 *  − Non-cash charges                         non_cash_total
 *  − Schedule III items                       sch3_total
 *  − Money / Securities                       money_total
 *  − Other exclusions                         other_total
 *  = Reportable expenditure (Col 2)           reportable_total
 *
 * Every excluded ledger the auditor ticked carries an auto-suggested
 * bucket (from the backend categoriser).  The auditor can override per
 * line via a dropdown; changes are persisted by the parent (which calls
 * `saveSelections({ exclusion_categories })`).
 */
import { useMemo } from "react";
import { formatINR } from "@/lib/format";
import { Receipt, Info } from "@phosphor-icons/react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const ICAI_BUCKETS = [
  { key: "non_cash", label: "Non-cash charges",   hint: "Depreciation, provisions, fair-value losses, impairments" },
  { key: "sch3",     label: "Schedule III items", hint: "Salary, wages, employer PF/ESI, gratuity, dividend declared, sale of land/building" },
  { key: "money",    label: "Money / Securities", hint: "Interest, TDS, discount on issue, investments, share transactions" },
  { key: "other",    label: "Other exclusions",   hint: "Anything the auditor chose to exclude that doesn't fit above" },
];

export default function ReconTable({ recon, onUpdateCategory }) {
  // Backward-compat: if only the legacy `excluded_lines` shape is present
  // (no per-bucket breakdown), synthesise one bucket-at-a-time from the
  // line-level `bucket` hints returned by the backend.
  const bucketLines = useMemo(() => {
    if (!recon) {
      return { non_cash: [], sch3: [], money: [], other: [] };
    }
    const collected = {
      non_cash: recon.non_cash_lines || [],
      sch3: recon.sch3_lines || [],
      money: recon.money_lines || [],
      other: recon.other_lines || [],
    };
    if (Object.values(collected).every((arr) => arr.length === 0)) {
      (recon.excluded_lines || []).forEach((l) => {
        const b = collected[l.bucket] ? l.bucket : "other";
        collected[b].push(l);
      });
    }
    return collected;
  }, [recon]);

  if (!recon) {
    return <div className="text-sm text-[#52524E]">No reconciliation data available.</div>;
  }

  const { pl_total = 0, capex_total = 0, reportable_total = 0 } = recon;

  const bucketTotals = {
    non_cash: recon.non_cash_total ?? bucketLines.non_cash.reduce((s, l) => s + (l.amount || 0), 0),
    sch3:     recon.sch3_total     ?? bucketLines.sch3.reduce((s, l) => s + (l.amount || 0), 0),
    money:    recon.money_total    ?? bucketLines.money.reduce((s, l) => s + (l.amount || 0), 0),
    other:    recon.other_total    ?? bucketLines.other.reduce((s, l) => s + (l.amount || 0), 0),
  };

  const subtractTotal = Object.values(bucketTotals).reduce((a, b) => a + b, 0);
  const computedReportable = pl_total + capex_total - subtractTotal;
  const balanced = Math.abs(computedReportable - reportable_total) < 0.5;

  const handleChange = (ledgerName, newBucket) => {
    if (typeof onUpdateCategory === "function") {
      onUpdateCategory(ledgerName, newBucket);
    }
  };

  return (
    <div className="border border-[#E5E5E0] bg-white rounded-sm" data-testid="recon-table-block">
      <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3">
        <Receipt size={14} className="text-[#52524E]"/>
        <h3 className="font-heading text-base">Reconciliation — Books to Clause 44</h3>
        <span className="ml-auto font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]" data-testid="recon-balance-chip">
          ICAI Para 79.4 · {balanced ? "Balanced" : "Out of balance"}
        </span>
      </div>

      <div className="px-4 py-3 border-b border-[#E5E5E0] bg-[#FAFAF7]">
        <div className="flex items-start gap-2 text-[11.5px] text-[#52524E] leading-snug">
          <Info size={14} className="text-[#8A8A83] flex-shrink-0 mt-0.5"/>
          <div>
            ICAI Guidance Note Para 79.4 prescribes a 5-line reconciliation.
            Each exclusion carries an auto-suggested ICAI bucket — override the dropdown on any
            line to re-categorise. The arrival number on the last row must tie to Col 2 on the Schedule tab.
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="fiscal-table w-full" data-testid="recon-table">
          <thead>
            <tr>
              <th className="min-w-[420px]">Particulars</th>
              <th className="text-right w-[180px]">Amount</th>
            </tr>
          </thead>
          <tbody>
            {/* P&L Total (headline) */}
            <tr data-testid="recon-pl-total">
              <td className="font-medium">Total Expenditure as per Profit &amp; Loss</td>
              <td className="cell-num font-medium">{formatINR(pl_total)}</td>
            </tr>

            {/* + Capex */}
            <tr data-testid="recon-capex-total">
              <td className="font-medium">
                <span className="text-emerald-800 mr-1">+</span> Capital expenditure additions
                <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-[#8A8A83] mt-0.5 ml-4">
                  Fixed-asset ledgers flowed into Col 2 per ICAI Para 79.18
                </span>
              </td>
              <td className="cell-num font-medium text-emerald-800">{formatINR(capex_total)}</td>
            </tr>

            {/* − Four deduction buckets */}
            {ICAI_BUCKETS.map((bucket) => (
              <BucketBlock
                key={bucket.key}
                bucket={bucket}
                lines={bucketLines[bucket.key]}
                total={bucketTotals[bucket.key]}
                allBuckets={ICAI_BUCKETS}
                onChange={handleChange}
              />
            ))}

            {/* = Reportable */}
            <tr className="bg-[#F3F4F1]" data-testid="recon-reportable">
              <td className="font-medium">
                = Reportable Expenditure (Col 2 of Clause 44)
              </td>
              <td className="cell-num font-medium">{formatINR(computedReportable)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="px-4 py-2 border-t border-[#E5E5E0] font-mono text-[10.5px] text-[#8A8A83]">
        Tip · Auto-categorisation is keyword-driven.  Override any line above to re-assign — changes persist on Generate.
      </div>
    </div>
  );
}

function BucketBlock({ bucket, lines, total, allBuckets, onChange }) {
  const hasLines = lines && lines.length > 0;
  return (
    <>
      <tr className="bg-[#F9F9F8]" data-testid={`recon-bucket-${bucket.key}`}>
        <td className="font-medium pl-4">
          <span className="text-rose-800 mr-1">−</span> {bucket.label}
          <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-[#8A8A83] mt-0.5 ml-4">
            {bucket.hint}
          </span>
        </td>
        <td className="cell-num font-medium text-rose-800" data-testid={`recon-bucket-total-${bucket.key}`}>
          {hasLines ? `(${formatINR(total)})` : "—"}
        </td>
      </tr>
      {hasLines && lines.map((line) => (
        <tr
          key={`${bucket.key}::${line.name}`}
          data-testid={`recon-line-${encodeURIComponent(line.name)}`}
          className="hover:bg-[#FDFDFC]"
        >
          <td className="pl-10 text-[13px] text-[#52524E]">
            <div className="flex items-center gap-3">
              <span className="flex-1 min-w-0 truncate">• {line.name}</span>
              {typeof onChange === "function" && (
                <Select
                  value={bucket.key}
                  onValueChange={(val) => onChange(line.name, val)}
                >
                  <SelectTrigger
                    className="h-6 rounded-sm shadow-none border-[#E5E5E0] font-mono text-[10px] uppercase tracking-[0.1em] w-[160px] px-2"
                    data-testid={`recon-line-bucket-${encodeURIComponent(line.name)}`}
                  >
                    <SelectValue/>
                  </SelectTrigger>
                  <SelectContent>
                    {allBuckets.map((b) => (
                      <SelectItem key={b.key} value={b.key} className="font-mono text-[10.5px] uppercase">
                        {b.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </td>
          <td className="cell-num text-[#52524E]">({formatINR(line.amount)})</td>
        </tr>
      ))}
    </>
  );
}
