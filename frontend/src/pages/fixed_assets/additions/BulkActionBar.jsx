import React from "react";
import { CheckSquare, Tag, X, CalendarRange } from "lucide-react";

/** Floating bulk-action bar — appears at the bottom when one or more rows
 *  are selected via the per-row checkboxes. */
export function BulkActionBar({
  count, blocks, onSetBlock, onMarkReviewed, onCopyPTUFromAcc, onClear, busy,
}) {
  if (!count) return null;
  return (
    <div
      data-testid="fa-add-bulk-bar"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 bg-slate-900 text-white shadow-2xl border border-slate-800 px-4 py-2.5 flex items-center gap-3 text-[12.5px]"
    >
      <CheckSquare size={14} className="text-emerald-300"/>
      <span><strong>{count}</strong> selected</span>
      <span className="w-px h-5 bg-slate-700"/>
      <select
        onChange={(e) => { if (e.target.value) { onSetBlock(e.target.value); e.target.value = ""; } }}
        className="bg-slate-800 text-white border border-slate-700 px-2 py-1 text-[11.5px] focus:outline-none"
        data-testid="fa-add-bulk-set-block"
      >
        <option value="">Set Block to…</option>
        {(blocks || []).map(b => <option key={b.block_label} value={b.block_label}>{b.block_label}</option>)}
      </select>
      <button
        onClick={onMarkReviewed}
        disabled={busy}
        data-testid="fa-add-bulk-reviewed"
        className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50"
      >
        <Tag size={11}/> Mark Reviewed
      </button>
      <button
        onClick={onCopyPTUFromAcc}
        disabled={busy}
        data-testid="fa-add-bulk-ptu"
        className="inline-flex items-center gap-1 px-2 py-1 bg-sky-700 hover:bg-sky-600 disabled:opacity-50"
      >
        <CalendarRange size={11}/> PTU = Acc Date
      </button>
      <button
        onClick={onClear}
        data-testid="fa-add-bulk-clear"
        className="ml-1 text-slate-300 hover:text-white"
        title="Clear selection"
      >
        <X size={14}/>
      </button>
    </div>
  );
}
