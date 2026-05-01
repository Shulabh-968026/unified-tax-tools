import React, { useEffect, useRef, useState } from "react";
import { Calendar, CalendarDays, Link2, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { inr, capitalised } from "./utils";
import { RowAttachmentIcon } from "./InvoiceOcrModal";

/**
 * AdditionRow — full editable line with:
 *  - Per-row save indicator (saving/saved/error) driven by onPatch's promise
 *  - Auto-growing description textarea
 *  - Optional bulk-select checkbox (only when bulkMode is true)
 *  - Column visibility honors the parent-supplied colVis map
 */
export function AdditionRow({
  a, blocks, colVis, bulkMode, selected, onToggleSelect, onPatch, onOpenLink,
  attachment, onAttachmentChanged, rid,
}) {
  const [local, setLocal] = useState(a);
  const [status, setStatus] = useState("idle"); // idle | saving | saved | error
  const clearRef = useRef(null);

  useEffect(() => setLocal(a),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [a.addition_id, a.invoice_cost, a.other_expenses, a.itc_reversed,
      a.interest_capitalized, a.forex_fluctuations, a.discount_credits,
      a.put_to_use_date, a.invoice_date, a.invoice_no, a.description, a.party_name,
      a.voucher_no, a.block_label]);

  const setF = (k, v) => setLocal(s => ({ ...s, [k]: v }));

  const triggerPatch = async (patch) => {
    setStatus("saving");
    try {
      await onPatch(patch);
      setStatus("saved");
      if (clearRef.current) clearTimeout(clearRef.current);
      clearRef.current = setTimeout(() => setStatus("idle"), 2200);
    } catch {
      setStatus("error");
    }
  };

  const flush = (k, ov) => {
    const v = local[k];
    if ((ov ?? a[k]) === v) return;
    triggerPatch({ [k]: v });
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
      className={locked ? "bg-rose-50/50" : (selected ? "bg-sky-50/60" : "hover:bg-[#FBFBF8]")}
      data-testid={`fa-addition-${a.addition_id}`}
    >
      {/* Bulk checkbox column (only when bulkMode active) */}
      {bulkMode && (
        <td className="px-1.5 py-1">
          <input
            type="checkbox"
            disabled={locked}
            checked={!!selected}
            onChange={(e) => onToggleSelect?.(a.addition_id, e.target.checked)}
            data-testid={`fa-add-select-${a.addition_id}`}
          />
        </td>
      )}

      {/* Save indicator + Acc Date */}
      <td className="px-2 py-1 font-mono text-[10.5px] whitespace-nowrap">
        <div className="flex items-center gap-1.5">
          <SaveDot status={status}/>
          <span>{(a.accounting_date || "").slice(0, 10)}</span>
        </div>
      </td>

      {colVis.ptu_date && (
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
                        onClick={() => { setF("put_to_use_date", a.accounting_date || ""); triggerPatch({ put_to_use_date: a.accounting_date || "" }); }}
                        className="text-slate-400 hover:text-slate-900 p-0.5"><Calendar size={10}/></button>
                <button title="Copy from Inv Date" type="button"
                        onClick={() => { setF("put_to_use_date", a.invoice_date || ""); triggerPatch({ put_to_use_date: a.invoice_date || "" }); }}
                        className="text-slate-400 hover:text-slate-900 p-0.5"><CalendarDays size={10}/></button>
              </>
            )}
          </div>
          {halfRate && !locked && (
            <span className="font-mono text-[8.5px] bg-amber-50 border border-amber-200 px-0.5 py-0 text-amber-800">½ rate</span>
          )}
        </td>
      )}

      <td className="px-2 py-1">
        <div className="flex items-start gap-1">
          <AutoGrowTextarea
            value={local.description || ""}
            disabled={locked}
            onChange={(v) => setF("description", v)}
            onBlur={() => flush("description", a.description)}
            placeholder={a.particulars || "Description"}
            className={txtInput + " resize-none"}
          />
          <RowAttachmentIcon
            rid={rid}
            addition={a}
            attachment={attachment}
            onDeleted={onAttachmentChanged}
          />
        </div>
      </td>

      {/* Invoice Cost — read-only display, with merge button */}
      <td className={`px-2 py-1 ${locked ? "bg-slate-50" : "bg-[#F9F9F8]"}`}>
        <div className="flex items-center gap-1">
          <div
            className="flex-1 px-1 py-0.5 text-right text-[11px] font-mono text-slate-900"
            title="Read-only — sourced from Tally Books"
            data-testid={`fa-add-invoice-cost-${a.addition_id}`}
          >
            {inr(local.invoice_cost)}
          </div>
          <button
            type="button"
            title={locked
              ? "Net this discount/credit against a specific asset purchase (populates parent's Discounts/Credits column)"
              : "Merge this line into another asset (e.g. freight, installation, GST etc.)"}
            onClick={onOpenLink}
            className={locked
              ? "text-rose-400 hover:text-rose-700 p-0.5"
              : "text-slate-400 hover:text-sky-700 p-0.5"}
            data-testid={`fa-add-link-${a.addition_id}`}
          >
            <Link2 size={11}/>
          </button>
        </div>
      </td>

      {colVis.other_expenses       && <NumberCell field="other_expenses"/>}
      {colVis.itc_reversed         && <NumberCell field="itc_reversed"/>}
      {colVis.interest_capitalized && <NumberCell field="interest_capitalized"/>}
      {colVis.forex_fluctuations   && <NumberCell field="forex_fluctuations"/>}
      {colVis.discount_credits     && <NumberCell field="discount_credits"/>}

      <td className="px-2 py-1 text-right font-mono font-semibold">{inr(total)}</td>

      <td className="px-2 py-1">
        <select
          value={local.block_label || ""}
          disabled={locked}
          onChange={(e) => { setF("block_label", e.target.value); triggerPatch({ block_label: e.target.value }); }}
          className="w-full px-1 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[10.5px]"
        >
          <option value="">— Block —</option>
          {(blocks || []).map(b => (
            <option key={b.block_label} value={b.block_label}>{b.block_label}</option>
          ))}
        </select>
      </td>

      {colVis.supplier && (
        <td className="px-2 py-1">
          <input type="text" value={local.party_name || ""} disabled={locked}
                 onChange={(e) => setF("party_name", e.target.value)}
                 onBlur={() => flush("party_name", a.party_name)}
                 className={txtInput}/>
        </td>
      )}

      {colVis.voucher_no && (
        <td className="px-2 py-1">
          <input type="text" value={local.voucher_no || ""} disabled={locked}
                 onChange={(e) => setF("voucher_no", e.target.value)}
                 onBlur={() => flush("voucher_no", a.voucher_no)}
                 className={txtInput + " font-mono"}/>
        </td>
      )}

      {colVis.invoice_no && (
        <td className="px-2 py-1">
          <input type="text" value={local.invoice_no || ""} disabled={locked}
                 onChange={(e) => setF("invoice_no", e.target.value)}
                 onBlur={() => flush("invoice_no", a.invoice_no)}
                 placeholder="—"
                 className={txtInput + " font-mono"}/>
        </td>
      )}

      {colVis.invoice_date && (
        <td className="px-2 py-1">
          <input type="date" value={local.invoice_date || ""} disabled={locked}
                 onChange={(e) => setF("invoice_date", e.target.value)}
                 onBlur={() => flush("invoice_date", a.invoice_date)}
                 className="w-[90px] px-0.5 py-0.5 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[10.5px]"/>
          {a.invoice_date_source === "narration" && !locked && (
            <div className="text-[8.5px] text-emerald-700 mt-0.5">via narration</div>
          )}
        </td>
      )}
    </tr>
  );
}

function SaveDot({ status }) {
  if (status === "saving") {
    return <Loader2 size={11} className="animate-spin text-slate-500" data-testid="fa-row-saving"/>;
  }
  if (status === "saved") {
    return <CheckCircle2 size={11} className="text-emerald-600" data-testid="fa-row-saved"/>;
  }
  if (status === "error") {
    return <AlertCircle size={11} className="text-rose-600" data-testid="fa-row-save-error"/>;
  }
  return <span className="inline-block w-[11px] h-[11px]"/>; // spacer keeps alignment
}

function AutoGrowTextarea({ value, disabled, onChange, onBlur, placeholder, className }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    // Cap growth so single-row tables don't visually explode on long text
    const next = Math.min(180, Math.max(34, el.scrollHeight));
    el.style.height = `${next}px`;
  }, [value]);
  return (
    <textarea
      ref={ref}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      rows={2}
      className={className}
      placeholder={placeholder}
      style={{ minHeight: "34px", overflow: "hidden" }}
    />
  );
}
