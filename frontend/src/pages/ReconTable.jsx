import { formatINR } from "@/lib/format";
import { Receipt } from "@phosphor-icons/react";

export default function ReconTable({ recon }) {
  if (!recon) {
    return <div className="text-sm text-[#52524E]">No reconciliation data available.</div>;
  }
  const balanced = Math.abs((recon.total_books - recon.excluded_total) - recon.balance) < 0.01;

  return (
    <div className="border border-[#E5E5E0] bg-white rounded-sm" data-testid="recon-table-block">
      <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3">
        <Receipt size={14} className="text-[#52524E]"/>
        <h3 className="font-heading text-base">Reconciliation — Books to Clause 44</h3>
        <span className="ml-auto font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">
          {balanced ? "Balanced" : "Out of balance"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="fiscal-table w-full" data-testid="recon-table">
          <thead>
            <tr>
              <th className="min-w-[420px]">Particulars</th>
              <th className="text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr data-testid="recon-total-books">
              <td className="font-medium">Total Expenditure as per Books</td>
              <td className="cell-num font-medium">{formatINR(recon.total_books)}</td>
            </tr>
            <tr className="bg-[#F9F9F8]">
              <td className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">
                Less : Expenditures excluded from Clause 44 Report
              </td>
              <td className="cell-num text-[#52524E]">— ({formatINR(recon.excluded_total)})</td>
            </tr>
            {(recon.excluded_lines || []).length === 0 && (
              <tr><td className="text-[#8A8A83] italic" colSpan={2}>No exclusions selected.</td></tr>
            )}
            {(recon.excluded_lines || []).map((line) => (
              <tr key={line.name} data-testid={`recon-excluded-${encodeURIComponent(line.name)}`}>
                <td className="pl-8 text-[13px] text-[#52524E]">• {line.name}</td>
                <td className="cell-num text-[#52524E]">({formatINR(line.amount)})</td>
              </tr>
            ))}
            <tr className="bg-[#F3F4F1]" data-testid="recon-balance">
              <td className="font-medium">Expenditure as per Clause 44 Report</td>
              <td className="cell-num font-medium">{formatINR(recon.balance)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 border-t border-[#E5E5E0] font-mono text-[10.5px] text-[#8A8A83]">
        Tip · Closing balance is the sum of voucher-level debits on each ledger. Balance ties to the Clause 44 total.
      </div>
    </div>
  );
}
