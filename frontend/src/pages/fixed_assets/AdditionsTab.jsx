/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft, ChevronRight, FileText, Loader2,
  CheckCircle2, Circle, CircleDot, Search, Calendar, CalendarDays,
  Split, X,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

const ADJ_FIELDS = ["other_expenses", "itc_reversed", "interest_capitalized", "forex_fluctuations", "discount_credits"];
const PAGE_SIZE = 10;

function capitalised(a) {
  return Number(a.invoice_cost || 0)
    + Number(a.other_expenses || 0)
    - Number(a.itc_reversed || 0)
    + Number(a.interest_capitalized || 0)
    + Number(a.forex_fluctuations || 0)
    - Number(a.discount_credits || 0);
}

export default function AdditionsTab({ rid, blocks }) {
  const [rows, setRows] = useState([]);
  const [progress, setProgress] = useState({ rows: [], summary: {} });
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [activeBlock, setActiveBlock] = useState(""); // first block selected on first load
  const [page, setPage] = useState(1);

  const refresh = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const [r, p] = await Promise.all([
        http.get(`/fixed-assets/runs/${rid}/additions`),
        http.get(`/fixed-assets/runs/${rid}/additions/progress`),
      ]);
      setRows(r.data?.rows || []);
      setProgress(p.data || { rows: [], summary: {} });
      // Initialise the active block to the first block that actually has rows
      if (!activeBlock && p.data?.rows?.length) {
        setActiveBlock(p.data.rows[0].block_label);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load additions");
    } finally { setBusy(false); }
  }, [rid, activeBlock]);
  useEffect(() => { refresh(); }, [refresh]);

  /* ---------------- Patch ---------------- */
  const patchRow = async (a, patch) => {
    if (a.source === "discount_credit") return;        // locked
    setRows(rs => rs.map(r => r.addition_id === a.addition_id ? { ...r, ...patch, reviewed: true } : r));
    try {
      await http.patch(`/fixed-assets/runs/${rid}/additions/${a.addition_id}`, patch);
      refresh();   // pulls progress strip + recomputes Total
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refresh();
    }
  };

  /* Split modal — auditor enters how the invoice cost is broken up */
  const [splitFor, setSplitFor] = useState(null);   // addition row
  const closeSplit = () => setSplitFor(null);
  const applySplit = async (a, values) => {
    closeSplit();
    await patchRow(a, values);
    toast.success("Split applied");
  };

  /* ---------------- Filtering / pagination ---------------- */
  const blockChoices = progress.rows || [];

  const filtered = useMemo(() => {
    let xs = rows;
    if (activeBlock) xs = xs.filter(r => r.block_label === activeBlock);
    const q = search.trim().toLowerCase();
    if (q) xs = xs.filter(r => `${r.description || r.particulars} ${r.party_name} ${r.voucher_no} ${r.invoice_no}`.toLowerCase().includes(q));
    return xs;
  }, [rows, activeBlock, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  useEffect(() => { if (page > totalPages) setPage(1); }, [totalPages, page]);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  /* ---------------- Render ---------------- */
  return (
    <div className="space-y-3">
      {/* Progress strip */}
      <ProgressStrip
        progress={progress}
        active={activeBlock}
        onPick={(bl) => { setActiveBlock(bl); setPage(1); }}
      />

      {/* Toolbar */}
      <div className="bg-white border border-[#E5E5E0] flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <FileText size={14} className="text-slate-600"/>
          <h2 className="font-heading text-[14px]">Additions Register — {activeBlock || "(no block)"}</h2>
          <span className="font-mono text-[10.5px] text-slate-500">
            {filtered.length} rows · ₹ {inr(filtered.reduce((s, a) => s + capitalised(a), 0))}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <select
            data-testid="fa-add-block-filter"
            value={activeBlock}
            onChange={(e) => { setActiveBlock(e.target.value); setPage(1); }}
            className="px-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none"
          >
            {blockChoices.map(b => (
              <option key={b.block_label} value={b.block_label}>
                {b.block_label} · {b.reviewed}/{b.total} done
              </option>
            ))}
          </select>
          <div className="relative">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"/>
            <input
              data-testid="fa-add-search"
              className="pl-7 pr-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 w-56"
              placeholder="Search description, party, voucher…"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
          </div>
          <Pager page={page} totalPages={totalPages} onPage={setPage}/>
          {busy && <Loader2 size={12} className="animate-spin text-slate-500"/>}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E5E5E0] overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left bg-[#F9F9F8] text-[9.5px] font-mono uppercase tracking-wider text-slate-600">
              <th className="px-2 py-2 w-[88px]">Acc Date</th>
              <th className="px-2 py-2 w-[110px]">PTU Date</th>
              <th className="px-2 py-2 min-w-[210px]">Description of Asset</th>
              <th className="px-2 py-2 text-right w-[95px]">Invoice Cost</th>
              <th className="px-1 py-2 text-right w-[78px]">Other Exp</th>
              <th className="px-1 py-2 text-right w-[78px]">ITC Reversed</th>
              <th className="px-1 py-2 text-right w-[78px]">Interest Cap</th>
              <th className="px-1 py-2 text-right w-[68px]">Forex</th>
              <th className="px-1 py-2 text-right w-[80px]">Discounts</th>
              <th className="px-2 py-2 text-right w-[100px]">Total</th>
              <th className="px-2 py-2 w-[150px]">IT Block</th>
              <th className="px-2 py-2 w-[140px]">Supplier</th>
              <th className="px-2 py-2 w-[80px]">Voucher No</th>
              <th className="px-2 py-2 w-[90px]">Invoice No</th>
              <th className="px-2 py-2 w-[100px]">Inv Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EDEDE7]">
            {paged.length === 0 ? (
              <tr><td colSpan={15} className="px-4 py-10 text-center text-slate-500 text-[12px]">
                No additions in this block match the filter.
              </td></tr>
            ) : paged.map(a => (
              <Row key={a.addition_id} a={a} blocks={blocks}
                   onPatch={(p) => patchRow(a, p)}
                   onOpenSplit={() => setSplitFor(a)}/>
            ))}
          </tbody>
        </table>
      </div>

      {/* Bottom pager */}
      <div className="flex items-center justify-end gap-2">
        <span className="text-[11px] text-slate-500">Page {page} of {totalPages}</span>
        <Pager page={page} totalPages={totalPages} onPage={setPage}/>
      </div>

      {splitFor && (
        <SplitModal addition={splitFor} onClose={closeSplit} onApply={(v) => applySplit(splitFor, v)}/>
      )}
    </div>
  );
}

/* ============================================================ */
/* Sub-components                                               */
/* ============================================================ */
function ProgressStrip({ progress, active, onPick }) {
  const { rows = [], summary = {} } = progress;
  if (!rows.length) {
    return (
      <div className="bg-white border border-[#E5E5E0] px-4 py-2.5 text-[11.5px] text-slate-500">
        No classified additions yet — go to <strong>Ledgers</strong> tab to confirm IT-Block per ledger first.
      </div>
    );
  }
  return (
    <div className="bg-white border border-[#E5E5E0] px-4 py-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mr-1">
          Block progress · {summary.done || 0} done · {summary.in_progress || 0} in progress · {summary.not_started || 0} not started
        </div>
        {rows.map(b => {
          const isActive = b.block_label === active;
          const Icon = b.status === "done" ? CheckCircle2 : b.status === "in_progress" ? CircleDot : Circle;
          const cls = b.status === "done"
            ? "text-emerald-700 bg-emerald-50 border-emerald-200"
            : b.status === "in_progress"
              ? "text-amber-700 bg-amber-50 border-amber-200"
              : "text-slate-600 bg-slate-50 border-slate-200";
          return (
            <button
              key={b.block_label}
              data-testid={`fa-progress-${b.block_label.replace(/\W+/g, "-")}`}
              onClick={() => onPick(b.block_label)}
              className={`inline-flex items-center gap-1.5 px-2 py-1 border text-[11px] ${cls} ${isActive ? "ring-2 ring-slate-900 ring-offset-1" : ""}`}
            >
              <Icon size={11}/>
              <span className="truncate max-w-[180px]">{b.block_label}</span>
              <span className="font-mono text-[10px]">{b.reviewed}/{b.total}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Pager({ page, totalPages, onPage }) {
  return (
    <div className="flex items-center gap-1">
      <button
        data-testid="fa-add-page-prev"
        onClick={() => onPage(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="p-1 border border-slate-300 disabled:opacity-40 hover:bg-slate-50">
        <ChevronLeft size={12}/>
      </button>
      <button
        data-testid="fa-add-page-next"
        onClick={() => onPage(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="p-1 border border-slate-300 disabled:opacity-40 hover:bg-slate-50">
        <ChevronRight size={12}/>
      </button>
    </div>
  );
}

function Row({ a, blocks, onPatch, onOpenSplit }) {
  const [local, setLocal] = useState(a);
  useEffect(() => setLocal(a), [a.addition_id, a.invoice_cost, a.other_expenses, a.itc_reversed,
                                a.interest_capitalized, a.forex_fluctuations, a.discount_credits,
                                a.put_to_use_date, a.invoice_date, a.invoice_no, a.description, a.party_name,
                                a.voucher_no, a.block_label]);
  const setF = (k, v) => setLocal(s => ({ ...s, [k]: v }));
  const flush = (k, ov) => {
    const v = local[k];
    if ((ov ?? a[k]) === v) return;
    onPatch({ [k]: v });
  };

  const locked = a.source === "discount_credit";
  const total = capitalised(local);
  const halfRate = !!local.half_rate;

  const baseInput = "w-full px-1 py-0.5 text-right border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11px] font-mono";
  const txtInput  = "w-full px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[11px]";

  const NumberCell = ({ field }) => (
    <td className={`px-1 py-1 ${locked ? "bg-slate-50" : ""}`}>
      <input
        type="number" step="0.01"
        value={local[field] || 0}
        disabled={locked}
        onChange={(e) => setF(field, parseFloat(e.target.value || 0))}
        onFocus={(e) => e.target.select()}
        onBlur={() => flush(field, a[field])}
        className={baseInput}
        data-testid={`fa-add-${field}-${a.addition_id}`}
      />
    </td>
  );

  return (
    <tr
      className={locked ? "bg-rose-50/50" : "hover:bg-[#FBFBF8]"}
      data-testid={`fa-addition-${a.addition_id}`}
    >
      <td className="px-2 py-1 font-mono text-[10.5px]">{(a.accounting_date || "").slice(0, 10)}</td>
      <td className="px-2 py-1">
        <div className="flex items-center gap-0.5">
          <input type="date" value={local.put_to_use_date || ""}
                 disabled={locked}
                 onChange={(e) => setF("put_to_use_date", e.target.value)}
                 onBlur={() => flush("put_to_use_date", a.put_to_use_date)}
                 className="w-[88px] px-0.5 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[10.5px]"/>
          {!locked && (
            <>
              <button title="Copy from Acc Date" type="button"
                      onClick={() => { setF("put_to_use_date", a.accounting_date || ""); onPatch({ put_to_use_date: a.accounting_date || "" }); }}
                      className="text-slate-400 hover:text-slate-900 p-0.5"><Calendar size={10}/></button>
              <button title="Copy from Inv Date" type="button"
                      onClick={() => { setF("put_to_use_date", a.invoice_date || ""); onPatch({ put_to_use_date: a.invoice_date || "" }); }}
                      className="text-slate-400 hover:text-slate-900 p-0.5"><CalendarDays size={10}/></button>
            </>
          )}
        </div>
        {halfRate && !locked && (
          <span className="font-mono text-[8.5px] bg-amber-50 border border-amber-200 px-0.5 py-0 text-amber-800">½ rate</span>
        )}
      </td>
      <td className="px-2 py-1">
        <textarea
          value={local.description || ""}
          disabled={locked}
          onChange={(e) => setF("description", e.target.value)}
          onBlur={() => flush("description", a.description)}
          rows={2}
          className={txtInput + " resize-y"}
          placeholder={a.particulars || "Description"}
        />
      </td>
      {/* Invoice Cost — read-only display from books, with a Split-helper button */}
      <td className={`px-2 py-1 ${locked ? "bg-slate-50" : "bg-[#F9F9F8]"}`}>
        <div className="flex items-center gap-1">
          <div
            className="flex-1 px-1 py-0.5 text-right text-[11px] font-mono text-slate-900"
            title="Read-only — sourced from Tally Books"
            data-testid={`fa-add-invoice-cost-${a.addition_id}`}
          >
            {inr(local.invoice_cost)}
          </div>
          {!locked && (
            <button
              type="button"
              title="Split — enter Other Exp / ITC / Interest / Forex / Discounts in one go"
              onClick={onOpenSplit}
              className="text-slate-400 hover:text-slate-900 p-0.5"
              data-testid={`fa-add-split-${a.addition_id}`}
            >
              <Split size={11}/>
            </button>
          )}
        </div>
      </td>
      <NumberCell field="other_expenses"/>
      <NumberCell field="itc_reversed"/>
      <NumberCell field="interest_capitalized"/>
      <NumberCell field="forex_fluctuations"/>
      <NumberCell field="discount_credits"/>
      <td className="px-2 py-1 text-right font-mono font-semibold">{inr(total)}</td>
      <td className="px-2 py-1">
        <select
          value={local.block_label || ""}
          disabled={locked}
          onChange={(e) => { setF("block_label", e.target.value); onPatch({ block_label: e.target.value }); }}
          className="w-full px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[10.5px]"
        >
          <option value="">— Block —</option>
          {(blocks || []).map(b => (
            <option key={b.block_label} value={b.block_label}>{b.block_label}</option>
          ))}
        </select>
      </td>
      <td className="px-2 py-1">
        <input type="text" value={local.party_name || ""} disabled={locked}
               onChange={(e) => setF("party_name", e.target.value)}
               onBlur={() => flush("party_name", a.party_name)}
               className={txtInput}/>
      </td>
      <td className="px-2 py-1">
        <input type="text" value={local.voucher_no || ""} disabled={locked}
               onChange={(e) => setF("voucher_no", e.target.value)}
               onBlur={() => flush("voucher_no", a.voucher_no)}
               className={txtInput + " font-mono"}/>
      </td>
      <td className="px-2 py-1">
        <input type="text" value={local.invoice_no || ""} disabled={locked}
               onChange={(e) => setF("invoice_no", e.target.value)}
               onBlur={() => flush("invoice_no", a.invoice_no)}
               placeholder="—"
               className={txtInput + " font-mono"}/>
      </td>
      <td className="px-2 py-1">
        <input type="date" value={local.invoice_date || ""} disabled={locked}
               onChange={(e) => setF("invoice_date", e.target.value)}
               onBlur={() => flush("invoice_date", a.invoice_date)}
               className="w-[90px] px-0.5 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[10.5px]"/>
        {a.invoice_date_source === "narration" && !locked && (
          <div className="text-[8.5px] text-emerald-700 mt-0.5">via narration</div>
        )}
      </td>
    </tr>
  );
}

function round2(n) { return Math.round(n * 100) / 100; }

/* --------------------------------------------------------------- */
/* Split modal — replaces the awkward drag-drop                    */
/* --------------------------------------------------------------- */
const SPLIT_FIELDS = [
  { key: "other_expenses",       label: "Other Expenses",      sign: "+" },
  { key: "itc_reversed",         label: "ITC Reversed",        sign: "−" },
  { key: "interest_capitalized", label: "Interest Capitalised", sign: "+" },
  { key: "forex_fluctuations",   label: "Forex Fluctuations",  sign: "+" },
  { key: "discount_credits",     label: "Discounts/Credits",   sign: "−" },
];

function SplitModal({ addition, onClose, onApply }) {
  const a = addition;
  const [vals, setVals] = useState(() => {
    const out = {};
    for (const f of SPLIT_FIELDS) out[f.key] = Number(a[f.key] || 0);
    return out;
  });
  const setF = (k, v) => setVals(s => ({ ...s, [k]: v }));

  const baseAmount = Number(a.invoice_cost || 0);
  const adjPositive = Number(vals.other_expenses) + Number(vals.interest_capitalized) + Number(vals.forex_fluctuations);
  const adjNegative = Number(vals.itc_reversed) + Number(vals.discount_credits);
  const newTotal = baseAmount + adjPositive - adjNegative;

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6"
         data-testid="fa-split-modal">
      <div className="bg-white border border-[#E5E5E0] w-full max-w-xl">
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-[#EDEDE7]">
          <div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-600">Split Invoice Cost</div>
            <div className="font-heading text-base mt-0.5 truncate">
              {a.description || a.particulars || a.party_name}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              Voucher {a.voucher_no} · Invoice Cost (read-only) ₹ {Math.abs(baseAmount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 p-1"
                  data-testid="fa-split-close">
            <X size={16}/>
          </button>
        </div>

        <div className="p-4 space-y-2">
          <p className="text-[11.5px] text-slate-600 mb-2">
            Enter how the invoice splits across each component. Invoice Cost stays as captured from the books;
            these values flow into the Total used for depreciation.
          </p>
          {SPLIT_FIELDS.map(f => (
            <div key={f.key} className="grid grid-cols-[160px_60px_1fr] items-center gap-2">
              <label className="text-[12px] text-slate-700">{f.label}</label>
              <span className={`text-[11px] font-mono ${f.sign === "−" ? "text-rose-700" : "text-emerald-700"}`}>{f.sign}</span>
              <input
                type="number" step="0.01"
                value={vals[f.key]}
                onChange={(e) => setF(f.key, parseFloat(e.target.value || 0))}
                onFocus={(e) => e.target.select()}
                className="px-2 py-1 text-right border border-[#D4D4D0] focus:border-slate-700 focus:outline-none text-[12.5px] font-mono"
                data-testid={`fa-split-${f.key}`}
              />
            </div>
          ))}

          <div className="border-t border-[#EDEDE7] pt-3 mt-2 grid grid-cols-[160px_60px_1fr] items-center gap-2">
            <label className="text-[12px] text-slate-700 font-semibold">Capitalised Total</label>
            <span/>
            <div className="px-2 py-1 text-right font-mono text-[13px] font-semibold">
              ₹ {newTotal.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">Cancel</button>
          <button
            data-testid="fa-split-apply"
            onClick={() => onApply({
              other_expenses:       round2(vals.other_expenses),
              itc_reversed:         round2(vals.itc_reversed),
              interest_capitalized: round2(vals.interest_capitalized),
              forex_fluctuations:   round2(vals.forex_fluctuations),
              discount_credits:     round2(vals.discount_credits),
            })}
            className="px-3 py-1.5 text-[12.5px] bg-slate-900 text-white hover:bg-slate-800"
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
