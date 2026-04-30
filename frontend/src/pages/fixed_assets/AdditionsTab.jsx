/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Loader2, Search, Save, CalendarDays, Calendar, FileText } from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

const ADJ_FIELDS = [
  { key: "discount_credits",     label: "Discount/Credits", sign: "−" },
  { key: "other_expenses",       label: "Other Exp",        sign: "+" },
  { key: "itc_reversed",         label: "ITC Reversed",     sign: "−" },
  { key: "interest_capitalized", label: "Interest Cap",     sign: "+" },
  { key: "forex_fluctuations",   label: "Forex",            sign: "+" },
];

const capitalised = (a) =>
  Number(a.invoice_cost || 0) - Number(a.discount_credits || 0) + Number(a.other_expenses || 0)
  - Number(a.itc_reversed || 0) + Number(a.interest_capitalized || 0) + Number(a.forex_fluctuations || 0);

export default function AdditionsTab({ rid, blocks }) {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [groupByBlock, setGroupByBlock] = useState(true);

  const refresh = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/additions`);
      setRows(data?.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load additions");
    } finally { setBusy(false); }
  }, [rid]);

  useEffect(() => { refresh(); }, [refresh]);

  const patchRow = async (a, patch) => {
    setRows(rs => rs.map(r => r.addition_id === a.addition_id ? { ...r, ...patch } : r));
    try {
      await http.patch(`/fixed-assets/runs/${rid}/additions/${a.addition_id}`, patch);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refresh();
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(r => `${r.particulars} ${r.party_name} ${r.voucher_no} ${r.ledger_name}`.toLowerCase().includes(q));
  }, [rows, search]);

  const grouped = useMemo(() => {
    if (!groupByBlock) return [["", filtered]];
    const m = new Map();
    for (const r of filtered) {
      const k = r.block_label || "(unclassified)";
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(r);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered, groupByBlock]);

  const grandTotal = useMemo(() => filtered.reduce((s, a) => s + capitalised(a), 0), [filtered]);

  return (
    <div className="bg-white border border-[#E5E5E0]">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#EDEDE7]">
        <div className="flex items-center gap-2">
          <FileText size={15} className="text-slate-600"/>
          <h2 className="font-heading text-base">Additions Register</h2>
          <span className="font-mono text-[11px] text-slate-500">{filtered.length} rows · ₹ {inr(grandTotal)}</span>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] flex items-center gap-1.5 text-slate-600">
            <input type="checkbox" checked={groupByBlock} onChange={(e) => setGroupByBlock(e.target.checked)}/>
            Group by block
          </label>
          <div className="relative">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"/>
            <input
              data-testid="fa-add-search"
              className="pl-7 pr-2 py-1.5 text-[12px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 w-64"
              placeholder="Search particulars / party / voucher…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {busy && <Loader2 size={13} className="animate-spin text-slate-500"/>}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="p-10 text-center text-[13px] text-slate-500">
          No additions match the filter.
        </div>
      ) : (
        <div className="overflow-x-auto">
          {grouped.map(([blockLabel, list]) => (
            <div key={blockLabel || "ALL"}>
              {groupByBlock && (
                <div className="bg-[#F2F2EE] px-4 py-1.5 text-[11px] font-mono uppercase tracking-wider text-slate-700 border-b border-[#E5E5E0]">
                  {blockLabel || "Unclassified"}  ·  {list.length} rows  ·  ₹ {inr(list.reduce((s, a) => s + capitalised(a), 0))}
                </div>
              )}
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                    <th className="px-3 py-2">Voucher</th>
                    <th className="px-3 py-2">Acc Date</th>
                    <th className="px-3 py-2">Inv Date</th>
                    <th className="px-3 py-2">PTU Date</th>
                    <th className="px-3 py-2 text-center">½ Rate?</th>
                    <th className="px-3 py-2">Particulars / Party</th>
                    <th className="px-3 py-2 text-right">Invoice Cost</th>
                    {ADJ_FIELDS.map(f => (
                      <th key={f.key} className="px-2 py-2 text-right" title={f.label}>{f.sign} {f.label}</th>
                    ))}
                    <th className="px-3 py-2 text-right">Capitalised</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EDEDE7]">
                  {list.map(a => (
                    <AdditionRow key={a.addition_id} a={a} blocks={blocks} onPatch={(p) => patchRow(a, p)}/>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AdditionRow({ a, blocks, onPatch }) {
  const [local, setLocal] = useState(a);
  useEffect(() => setLocal(a), [a.addition_id]);

  const setF = (k, v) => setLocal(s => ({ ...s, [k]: v }));
  const flush = (k) => {
    const v = local[k];
    if (a[k] === v) return;
    onPatch({ [k]: v });
  };
  const copyDate = (from) => {
    const v = local[from] || "";
    if (!v) return;
    setLocal(s => ({ ...s, put_to_use_date: v }));
    onPatch({ put_to_use_date: v });
  };

  const cap = capitalised(local);
  const halfRate = local.put_to_use_date ? !!local.half_rate : false;
  // Server flag is authoritative; reflect local PTU edits optimistically
  const dispHalf = local.half_rate;

  return (
    <tr className="hover:bg-[#FBFBF8]" data-testid={`fa-addition-${a.addition_id}`}>
      <td className="px-3 py-1.5 align-top">
        <div className="font-mono text-[11px] text-slate-700">{a.voucher_no || "—"}</div>
        <div className="text-[10.5px] text-slate-500">{a.voucher_type}</div>
      </td>
      <td className="px-3 py-1.5 font-mono text-[11.5px]">{a.accounting_date || "—"}</td>
      <td className="px-3 py-1.5 font-mono text-[11.5px]">
        <input
          type="date"
          value={local.invoice_date || ""}
          onChange={(e) => setF("invoice_date", e.target.value)}
          onBlur={() => flush("invoice_date")}
          className="w-[125px] px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px]"
        />
        {a.invoice_date_source === "narration" && (
          <div className="text-[9.5px] text-emerald-700 mt-0.5">via narration</div>
        )}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1">
          <input
            type="date"
            value={local.put_to_use_date || ""}
            onChange={(e) => setF("put_to_use_date", e.target.value)}
            onBlur={() => flush("put_to_use_date")}
            className="w-[125px] px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px]"
          />
          <button
            type="button"
            title="Copy from Accounting Date"
            onClick={() => copyDate("accounting_date")}
            className="text-slate-500 hover:text-slate-900 p-0.5"
          >
            <Calendar size={11}/>
          </button>
          <button
            type="button"
            title="Copy from Invoice Date"
            onClick={() => copyDate("invoice_date")}
            className="text-slate-500 hover:text-slate-900 p-0.5"
          >
            <CalendarDays size={11}/>
          </button>
        </div>
      </td>
      <td className="px-3 py-1.5 text-center">
        {dispHalf ? <span className="font-mono text-[10px] bg-amber-50 border border-amber-200 px-1 py-0.5 text-amber-800">YES</span> : <span className="text-slate-300 text-[11px]">—</span>}
      </td>
      <td className="px-3 py-1.5">
        <div className="text-[11.5px] truncate max-w-[280px]" title={a.particulars}>{a.particulars}</div>
        <div className="text-[10.5px] text-slate-500 truncate max-w-[280px]">{a.party_name} · <span className="italic">{a.ledger_name}</span></div>
      </td>
      <td className="px-3 py-1.5 text-right font-mono">{inr(local.invoice_cost)}</td>
      {ADJ_FIELDS.map(f => (
        <td key={f.key} className="px-1 py-1.5">
          <input
            type="number"
            step="0.01"
            value={local[f.key] || 0}
            onChange={(e) => setF(f.key, parseFloat(e.target.value || 0))}
            onBlur={() => flush(f.key)}
            className="w-[88px] px-1 py-0.5 text-right border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11.5px] font-mono"
          />
        </td>
      ))}
      <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(cap)}</td>
    </tr>
  );
}
