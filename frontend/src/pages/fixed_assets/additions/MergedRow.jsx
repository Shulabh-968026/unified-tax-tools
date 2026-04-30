import React from "react";
import { Link2, Link2Off } from "lucide-react";
import { ADJ_LABELS } from "./utils";

export function MergedRow({ a, parent, onUnlink, totalCols }) {
  const parentDesc = (parent?.description || parent?.particulars || parent?.party_name || "(parent)").slice(0, 90);
  return (
    <tr className="bg-slate-50/70 text-slate-500" data-testid={`fa-merged-${a.addition_id}`}>
      <td colSpan={totalCols} className="px-2 py-1.5">
        <div className="flex items-center gap-2 text-[11px]">
          <Link2 size={11} className="text-sky-600"/>
          <span className="font-mono text-[10px] uppercase tracking-wider text-sky-700">↳ Merged</span>
          <span className="truncate max-w-[260px]" title={a.description || a.particulars}>
            {a.description || a.particulars || "(no description)"}
          </span>
          <span className="text-slate-400">·</span>
          <span className="font-mono">₹ {Math.abs(Number(a.invoice_cost || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
          <span className="text-slate-400">·</span>
          <span>into <strong className="text-slate-700">{parentDesc}</strong></span>
          <span className="text-slate-400">·</span>
          <span>as <strong className="text-slate-700">{ADJ_LABELS[a.linked_as] || a.linked_as}</strong></span>
          <button onClick={onUnlink}
                  data-testid={`fa-add-unlink-${a.addition_id}`}
                  className="ml-auto inline-flex items-center gap-1 text-[11px] px-2 py-0.5 border border-slate-300 hover:bg-white text-slate-700">
            <Link2Off size={10}/> Unlink
          </button>
        </div>
      </td>
    </tr>
  );
}
