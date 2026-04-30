/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

export default function CreditsTab({ rid }) {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/credits`);
      setRows(data?.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load credits");
    } finally { setBusy(false); }
  }, [rid]);

  useEffect(() => { refresh(); }, [refresh]);

  const classify = async (cr, payload) => {
    setRows(rs => rs.map(r => r.credit_id === cr.credit_id ? { ...r, ...payload, classification: payload.classification } : r));
    try {
      await http.post(`/fixed-assets/runs/${rid}/credits/${cr.credit_id}/classify`, payload);
      toast.success(payload.classification === "sale" ? "Marked as Sale" : payload.classification === "discount" ? "Marked as Discount" : "Reset");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refresh();
    }
  };

  const stats = useMemo(() => {
    const acc = { pending: 0, sale: 0, discount: 0, sale_value_total: 0 };
    for (const r of rows) {
      acc[r.classification || "pending"] = (acc[r.classification || "pending"] || 0) + 1;
      if (r.classification === "sale") acc.sale_value_total += Number(r.sale_value || 0);
    }
    return acc;
  }, [rows]);

  return (
    <div className="bg-white border border-[#E5E5E0]">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#EDEDE7]">
        <div className="flex items-center gap-2">
          <ArrowDown size={15} className="text-rose-600"/>
          <h2 className="font-heading text-base">Credit Entries — Sale or Discount?</h2>
          <span className="font-mono text-[11px] text-slate-500">
            {stats.pending || 0} pending · {stats.sale || 0} sales (₹ {inr(stats.sale_value_total)}) · {stats.discount || 0} discounts
          </span>
        </div>
        {busy && <Loader2 size={13} className="animate-spin text-slate-500"/>}
      </div>

      {rows.length === 0 ? (
        <div className="p-10 text-center text-[13px] text-slate-500">
          No credit entries in fixed-asset ledgers — nothing to classify.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                <th className="px-3 py-2">Voucher</th>
                <th className="px-3 py-2">Acc Date</th>
                <th className="px-3 py-2">Block · Ledger</th>
                <th className="px-3 py-2">Particulars / Party</th>
                <th className="px-3 py-2 text-right">Cr Amount</th>
                <th className="px-3 py-2">Classification</th>
                <th className="px-3 py-2">Sale Details (if Sale)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EDEDE7]">
              {rows.map(cr => <CreditRow key={cr.credit_id} cr={cr} onClassify={(p) => classify(cr, p)}/>)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CreditRow({ cr, onClassify }) {
  const [saleValue, setSaleValue] = useState(cr.sale_value ?? cr.amount ?? 0);
  const [saleDate, setSaleDate] = useState(cr.sale_date || cr.accounting_date || "");
  const [buyer, setBuyer] = useState(cr.buyer_name || cr.party_name || "");

  const cls = cr.classification || "pending";

  return (
    <tr className="hover:bg-[#FBFBF8]" data-testid={`fa-credit-${cr.credit_id}`}>
      <td className="px-3 py-1.5 align-top">
        <div className="font-mono text-[11px] text-slate-700">{cr.voucher_no || "—"}</div>
        <div className="text-[10.5px] text-slate-500">{cr.voucher_type}</div>
      </td>
      <td className="px-3 py-1.5 font-mono text-[11.5px]">{cr.accounting_date}</td>
      <td className="px-3 py-1.5">
        <div className="font-mono text-[10.5px] text-slate-700">{cr.block_label || "—"}</div>
        <div className="text-[10.5px] text-slate-500 italic">{cr.ledger_name}</div>
      </td>
      <td className="px-3 py-1.5">
        <div className="text-[11.5px] truncate max-w-[260px]" title={cr.particulars}>{cr.particulars || "—"}</div>
        <div className="text-[10.5px] text-slate-500">{cr.party_name}</div>
      </td>
      <td className="px-3 py-1.5 text-right font-mono">{inr(cr.amount)}</td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1">
          <button
            data-testid={`fa-credit-mark-sale-${cr.credit_id}`}
            onClick={() => onClassify({ classification: "sale", sale_value: parseFloat(saleValue || 0), sale_date: saleDate, buyer_name: buyer })}
            className={`text-[10.5px] px-1.5 py-0.5 border ${cls === "sale" ? "bg-rose-100 border-rose-300 text-rose-900 font-semibold" : "border-slate-300 hover:bg-slate-100"}`}
          >
            Sale
          </button>
          <button
            data-testid={`fa-credit-mark-disc-${cr.credit_id}`}
            onClick={() => onClassify({ classification: "discount" })}
            className={`text-[10.5px] px-1.5 py-0.5 border ${cls === "discount" ? "bg-sky-100 border-sky-300 text-sky-900 font-semibold" : "border-slate-300 hover:bg-slate-100"}`}
          >
            Discount
          </button>
          {cls !== "pending" && (
            <button
              onClick={() => onClassify({ classification: "pending" })}
              className="text-[10.5px] px-1.5 py-0.5 border border-slate-200 text-slate-500 hover:bg-slate-100"
              title="Reset"
            >
              ×
            </button>
          )}
        </div>
      </td>
      <td className="px-3 py-1.5">
        {cls === "sale" ? (
          <div className="flex items-center gap-1">
            <input
              type="number"
              step="0.01"
              value={saleValue}
              onChange={(e) => setSaleValue(e.target.value)}
              onBlur={() => onClassify({ classification: "sale", sale_value: parseFloat(saleValue || 0), sale_date: saleDate, buyer_name: buyer })}
              placeholder="Sale Value"
              className="w-[100px] px-1 py-0.5 text-right border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px] font-mono"
            />
            <input
              type="date"
              value={saleDate}
              onChange={(e) => setSaleDate(e.target.value)}
              onBlur={() => onClassify({ classification: "sale", sale_value: parseFloat(saleValue || 0), sale_date: saleDate, buyer_name: buyer })}
              className="w-[125px] px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px]"
            />
            <input
              type="text"
              value={buyer}
              onChange={(e) => setBuyer(e.target.value)}
              onBlur={() => onClassify({ classification: "sale", sale_value: parseFloat(saleValue || 0), sale_date: saleDate, buyer_name: buyer })}
              placeholder="Buyer"
              className="w-[140px] px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px]"
            />
          </div>
        ) : (
          <span className="text-slate-300 text-[11px]">—</span>
        )}
      </td>
    </tr>
  );
}
