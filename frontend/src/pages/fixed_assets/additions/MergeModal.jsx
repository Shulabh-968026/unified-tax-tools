import React, { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { ADJ_LABELS } from "./utils";

export function MergeModal({ child, candidates, onClose, onApply }) {
  const [parentId, setParentId] = useState(child.parent_addition_id || "");
  const [linkedAs, setLinkedAs] = useState(child.linked_as || "other_expenses");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let xs = candidates.filter(c => c.addition_id !== child.addition_id);
    if (q) xs = xs.filter(c => `${c.description || c.particulars} ${c.party_name} ${c.voucher_no} ${c.invoice_no}`.toLowerCase().includes(q));
    return xs.slice(0, 200);
  }, [candidates, search, child.addition_id]);

  const parent = candidates.find(c => c.addition_id === parentId);

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6"
         data-testid="fa-link-modal">
      <div className="bg-white border border-[#E5E5E0] w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-[#EDEDE7]">
          <div className="min-w-0">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-600">Merge line item</div>
            <div className="font-heading text-base mt-0.5 truncate">
              {child.description || child.particulars || child.party_name}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              ₹ {Math.abs(Number(child.invoice_cost || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })} ·
              Voucher {child.voucher_no} · Block {child.block_label}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 p-1" data-testid="fa-link-close">
            <X size={16}/>
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-y-auto">
          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600">
              Parent asset (in same IT Block) — search and pick one
            </label>
            <div className="relative mt-1">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"/>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by description, voucher, invoice, party…"
                className="pl-7 pr-2 py-1.5 text-[12px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 w-full"
                data-testid="fa-link-search"
              />
            </div>
            <div className="mt-1 border border-[#E5E5E0] max-h-[280px] overflow-y-auto bg-[#FBFBF8]">
              {filtered.length === 0 ? (
                <div className="p-4 text-center text-[12px] text-slate-500">
                  {candidates.length === 0
                    ? "No candidate parent assets in this block."
                    : "No matches — try a different search."}
                </div>
              ) : filtered.map(c => (
                <label
                  key={c.addition_id}
                  data-testid={`fa-link-candidate-${c.addition_id}`}
                  className={`flex items-start gap-2 px-3 py-2 cursor-pointer border-b border-[#EDEDE7] hover:bg-white ${parentId === c.addition_id ? "bg-sky-50" : ""}`}
                >
                  <input type="radio" name="parent" className="mt-1"
                         checked={parentId === c.addition_id}
                         onChange={() => setParentId(c.addition_id)}/>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] truncate" title={c.description || c.particulars}>
                      {c.description || c.particulars || c.party_name || "(no description)"}
                    </div>
                    <div className="text-[10.5px] text-slate-500 truncate">
                      ₹ {Number(c.invoice_cost || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })} ·
                      Vch {c.voucher_no} · {c.invoice_no || "no inv#"} · {(c.invoice_date || "").slice(0, 10)} ·
                      {c.party_name}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[11px] font-mono uppercase tracking-wider text-slate-600">
              Add to which column on the parent?
            </label>
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              {Object.entries(ADJ_LABELS).map(([k, label]) => (
                <button
                  key={k}
                  data-testid={`fa-link-as-${k}`}
                  onClick={() => setLinkedAs(k)}
                  className={`px-2 py-1 text-[11.5px] border ${linkedAs === k ? "bg-slate-900 text-white border-slate-900" : "border-slate-300 hover:bg-slate-100"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {parent && (
            <div className="bg-emerald-50 border border-emerald-200 px-3 py-2 text-[11.5px]">
              <strong>₹ {Math.abs(Number(child.invoice_cost || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
              {" "}will be added to <strong>{parent.description || parent.particulars || parent.party_name}</strong>'s
              {" "}<strong>{ADJ_LABELS[linkedAs]}</strong> column.
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">Cancel</button>
          <button
            data-testid="fa-link-apply"
            onClick={() => onApply({ parent_addition_id: parentId, linked_as: linkedAs })}
            disabled={!parentId}
            className="px-3 py-1.5 text-[12.5px] bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Merge
          </button>
        </div>
      </div>
    </div>
  );
}
