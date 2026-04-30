/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Calculator, Download, Sparkles } from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

export default function ComputeTab({ rid }) {
  const [openings, setOpenings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [computing, setComputing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState(null);

  const refreshOpening = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/block-opening`);
      setOpenings(data?.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load opening WDV");
    } finally { setBusy(false); }
  }, [rid]);

  useEffect(() => { refreshOpening(); }, [refreshOpening]);

  const saveOpening = async (block_label, opening_wdv, description) => {
    setOpenings(rs => rs.map(r => r.block_label === block_label ? { ...r, opening_wdv: parseFloat(opening_wdv || 0), description: description ?? r.description } : r));
    try {
      await http.post(`/fixed-assets/runs/${rid}/block-opening`, {
        block_label,
        opening_wdv: parseFloat(opening_wdv || 0),
        description: description || "",
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refreshOpening();
    }
  };

  const compute = async () => {
    setComputing(true); setResult(null);
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/compute`);
      setResult(data);
      toast.success(`Depreciation ₹ ${inr(data.totals.depreciation)}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Compute failed");
    } finally { setComputing(false); }
  };

  const download = async () => {
    setDownloading(true);
    try {
      const res = await http.get(`/fixed-assets/runs/${rid}/export.xlsx`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      const cd = res.headers["content-disposition"] || "";
      const m = /filename="?([^";]+)"?/i.exec(cd);
      a.href = url;
      a.download = m?.[1] || `IT_Depreciation.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Download failed");
    } finally { setDownloading(false); }
  };

  const totalOpening = useMemo(() => openings.reduce((s, r) => s + Number(r.opening_wdv || 0), 0), [openings]);

  return (
    <div className="space-y-5">
      {/* Opening WDV table */}
      <div className="bg-white border border-[#E5E5E0]">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#EDEDE7]">
          <div className="flex items-center gap-2">
            <Sparkles size={15} className="text-amber-600"/>
            <h2 className="font-heading text-base">Opening WDV by Block</h2>
            <span className="font-mono text-[11px] text-slate-500">Total ₹ {inr(totalOpening)}</span>
          </div>
          {busy && <Loader2 size={13} className="animate-spin text-slate-500"/>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                <th className="px-4 py-2">Block</th>
                <th className="px-3 py-2 text-center">Rate</th>
                <th className="px-3 py-2 text-right w-[180px]">Opening WDV (₹)</th>
                <th className="px-3 py-2">Note (optional)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EDEDE7]">
              {openings.map(b => <OpeningRow key={b.block_label} row={b} onSave={saveOpening}/>)}
            </tbody>
          </table>
        </div>
      </div>

      {/* Compute & download */}
      <div className="bg-white border border-[#E5E5E0] p-4 flex items-center justify-between gap-3">
        <div>
          <div className="font-heading text-base">Run Computation</div>
          <p className="text-[12px] text-[#52524E] mt-0.5 max-w-3xl">
            Aggregates Opening WDV + every confirmed addition (with adjustment columns) − every credit marked
            as Sale, applies the 180-day half-rate rule, and produces the IT Depreciation Schedule.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="fa-compute-btn"
            onClick={compute}
            disabled={computing}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-slate-900 text-white text-[13px] hover:bg-slate-800 disabled:opacity-60"
          >
            {computing ? <Loader2 size={14} className="animate-spin"/> : <Calculator size={14}/>}
            Compute
          </button>
          <button
            data-testid="fa-export-btn"
            onClick={download}
            disabled={downloading}
            className="inline-flex items-center gap-2 px-3.5 py-2 border border-slate-300 hover:bg-slate-100 text-[13px] disabled:opacity-60"
          >
            {downloading ? <Loader2 size={14} className="animate-spin"/> : <Download size={14}/>}
            Download Excel
          </button>
        </div>
      </div>

      {/* Result table */}
      {result && (
        <div className="bg-white border border-[#E5E5E0]">
          <div className="px-4 py-3 border-b border-[#EDEDE7]">
            <h2 className="font-heading text-base">Depreciation Schedule</h2>
            <div className="text-[11.5px] text-slate-500 mt-0.5">
              {result.rows.length} blocks active · Depreciation ₹ {inr(result.totals.depreciation)} · Closing WDV ₹ {inr(result.totals.closing_wdv)}
              {result.totals.stcg_sec50 > 0 && <> · STCG u/s 50: ₹ {inr(result.totals.stcg_sec50)}</>}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                  <th className="px-3 py-2">Block</th>
                  <th className="px-3 py-2 text-center">Rate</th>
                  <th className="px-3 py-2 text-right">Opening WDV</th>
                  <th className="px-3 py-2 text-right">Adds ≥ 180d</th>
                  <th className="px-3 py-2 text-right">Adds &lt; 180d</th>
                  <th className="px-3 py-2 text-right">Sales</th>
                  <th className="px-3 py-2 text-right">Total</th>
                  <th className="px-3 py-2 text-right">Depn</th>
                  <th className="px-3 py-2 text-right">STCG u/s 50</th>
                  <th className="px-3 py-2 text-right">Closing WDV</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EDEDE7]">
                {result.rows.map(r => (
                  <tr key={r.block_label} className={r.block_extinguished ? "bg-rose-50" : ""}>
                    <td className="px-3 py-1.5 font-medium">{r.block_label}</td>
                    <td className="px-3 py-1.5 text-center font-mono">{r.rate}%</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.opening_wdv)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.adds_full)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.adds_half)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.deletions)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.total_block)}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(r.depreciation)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{r.stcg_sec50 ? inr(r.stcg_sec50) : "–"}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(r.closing_wdv)}</td>
                  </tr>
                ))}
                <tr className="bg-[#F2F2EE] font-semibold">
                  <td className="px-3 py-2" colSpan={2}>TOTAL</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.opening_wdv)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.adds_full)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.adds_half)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.deletions)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.total_block)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.depreciation)}</td>
                  <td className="px-3 py-2 text-right font-mono">{result.totals.stcg_sec50 ? inr(result.totals.stcg_sec50) : "–"}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.closing_wdv)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function OpeningRow({ row, onSave }) {
  const [v, setV] = useState(row.opening_wdv || 0);
  const [n, setN] = useState(row.description || "");
  useEffect(() => { setV(row.opening_wdv || 0); setN(row.description || ""); }, [row.block_label]);
  return (
    <tr className="hover:bg-[#FBFBF8]" data-testid={`fa-opening-${row.block_label}`}>
      <td className="px-4 py-1.5 font-medium">{row.block_label}</td>
      <td className="px-3 py-1.5 text-center font-mono">{row.rate}%</td>
      <td className="px-3 py-1.5">
        <input
          type="number"
          step="0.01"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={() => onSave(row.block_label, v, n)}
          className="w-full text-right px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12.5px] font-mono"
        />
      </td>
      <td className="px-3 py-1.5">
        <input
          type="text"
          value={n}
          onChange={(e) => setN(e.target.value)}
          onBlur={() => onSave(row.block_label, v, n)}
          placeholder="e.g. carried from FY 2023-24 closing WDV (3CD AY24-25)"
          className="w-full px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12px]"
        />
      </td>
    </tr>
  );
}
