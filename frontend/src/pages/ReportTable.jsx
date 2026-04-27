import { Input } from "@/components/ui/input";
import { useState } from "react";
import { formatINR } from "@/lib/format";
import { ACCENTS, COL_ACCENTS } from "@/lib/colors";
import { MagnifyingGlass, ChartPieSlice } from "@phosphor-icons/react";

const COLS = [
  { key: "col2_total", label: "Col 2 — Total", desc: "Total expenditure incurred", bucket: "col2" },
  { key: "col3", label: "Col 3 — Exempt", desc: "Registered party (with GSTIN), exempt supply", bucket: "col3" },
  { key: "col4", label: "Col 4 — Composition", desc: "Composition dealer", bucket: "col4" },
  { key: "col5", label: "Col 5 — Other Registered", desc: "Voucher carries an ITC ledger", bucket: "col5" },
  { key: "col6", label: "Col 6 — Total (3+4+5)", desc: "Aggregate registered", bucket: "col6" },
  { key: "col7", label: "Col 7 — Unregistered", desc: "No GSTIN / consumer", bucket: "col7" },
];

export default function ReportTable({ summary, ledgerRows, openDrill }) {
  const [q, setQ] = useState("");
  const filtered = ledgerRows.filter((r) => !q.trim() || r.name.toLowerCase().includes(q.toLowerCase()));
  const s = summary || {};

  return (
    <div data-testid="report-table-block">
      {/* Summary tiles - colour-coded */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden" data-testid="summary-tiles">
        {COLS.map((c) => {
          const a = ACCENTS[COL_ACCENTS[c.key]] || ACCENTS.slate;
          return (
            <button
              key={c.key}
              onClick={() => openDrill(c.bucket)}
              className={`${a.bg} px-4 py-4 text-left hover:brightness-95 transition-all`}
              data-testid={`tile-${c.bucket}`}
              style={{ borderTop: `2px solid ${a.fg}` }}
            >
              <div className={`font-mono text-[10px] uppercase tracking-[0.12em] ${a.text}`}>{c.label}</div>
              <div className="mt-2 num text-[20px] tracking-tight font-medium">{formatINR(s[c.key])}</div>
              <div className="mt-1 text-[10.5px] text-[#52524E] leading-snug line-clamp-2">{c.desc}</div>
            </button>
          );
        })}
      </div>

      <div className="mt-8 border border-[#E5E5E0] rounded-sm bg-white">
        <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
          <ChartPieSlice size={14} className="text-[#52524E]"/>
          <h3 className="font-heading text-base">Per-Ledger Breakdown</h3>
          <div className="ml-auto flex items-center gap-2 border border-[#E5E5E0] rounded-sm px-2 h-8 w-full sm:w-72">
            <MagnifyingGlass size={14} className="text-[#8A8A83]"/>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter ledger…" className="h-7 border-0 shadow-none focus-visible:ring-0 px-0 text-sm" data-testid="ledger-search"/>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="fiscal-table w-full" data-testid="ledger-table">
            <thead>
              <tr>
                <th className="min-w-[260px]">Ledger</th>
                {COLS.map((c) => <th key={c.key} className="text-right whitespace-nowrap">{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && <tr><td colSpan={7} className="text-center py-10 text-[#8A8A83] text-sm">No expenditure ledgers in this run.</td></tr>}
              {filtered.map((row) => (
                <tr key={row.name} data-testid={`ledger-row-${encodeURIComponent(row.name)}`}>
                  <td className="font-medium">
                    <button className="text-left hover:underline" onClick={() => openDrill("col2", row.name)}>{row.name}</button>
                  </td>
                  {COLS.map((c) => {
                    const v = row[c.key] || 0;
                    return (
                      <td key={c.key} className="cell-num">
                        <button className={`cell-clickable px-1 py-0.5 ${v === 0 ? "text-[#8A8A83]" : ""}`} onClick={() => openDrill(c.bucket, row.name)} data-testid={`cell-${c.bucket}-${encodeURIComponent(row.name)}`}>
                          {formatINR(v)}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            {filtered.length > 0 && (
              <tfoot><tr className="bg-[#F3F4F1]"><td className="font-medium">Aggregate</td>{COLS.map((c) => <td key={c.key} className="cell-num font-medium">{formatINR(s[c.key])}</td>)}</tr></tfoot>
            )}
          </table>
        </div>
      </div>
    </div>
  );
}
