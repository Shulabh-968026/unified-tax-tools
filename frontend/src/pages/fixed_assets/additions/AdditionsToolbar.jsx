import React, { useEffect, useRef, useState } from "react";
import {
  FileText, Loader2, Search, Settings2,
  CalendarRange, FileSpreadsheet, FileUp, CheckSquare, Square,
} from "lucide-react";
import { Pager } from "./Pager";
import { COLUMN_DEFS, PAGE_SIZE_OPTIONS, inr } from "./utils";

/**
 * Toolbar above the additions table — block / ledger / search / merged
 * filters + pagination + bulk PTU copy + Excel round-trip + column toggle.
 */
export function AdditionsToolbar({
  // filtering
  activeBlock, blockChoices, onPickBlock,
  ledgerFilter, ledgerChoices, onPickLedger,
  search, onSearch,
  showMerged, onShowMerged,
  // pagination
  page, totalPages, pageSize, onPageSize, onPage,
  // counts
  filteredCount, filteredTotal,
  // bulk + excel + col-vis
  bulkMode, onToggleBulk,
  onBulkCopyPTUFromAcc,
  onExportExcel, onImportExcel, importing, exporting,
  colVis, onColVis,
  busy,
}) {
  const [colPopOpen, setColPopOpen] = useState(false);
  const fileRef = useRef(null);

  return (
    <div className="bg-white border border-[#E5E5E0] flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <FileText size={14} className="text-slate-600"/>
        <h2 className="font-heading text-[14px]">Additions Register — {activeBlock || "(no block)"}</h2>
        <span className="font-mono text-[10.5px] text-slate-500">
          {filteredCount} rows · ₹ {inr(filteredTotal)}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {/* Block filter */}
        <select
          data-testid="fa-add-block-filter"
          value={activeBlock}
          onChange={(e) => onPickBlock(e.target.value)}
          className="px-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none"
        >
          {blockChoices.map(b => (
            <option key={b.block_label} value={b.block_label}>
              {b.block_label} · {b.reviewed}/{b.total} done
            </option>
          ))}
        </select>

        {/* Ledger filter (within active block) */}
        {ledgerChoices.length > 1 && (
          <select
            data-testid="fa-add-ledger-filter"
            value={ledgerFilter}
            onChange={(e) => onPickLedger(e.target.value)}
            className="px-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none max-w-[170px]"
            title="Filter by ledger within this block"
          >
            <option value="">All ledgers ({ledgerChoices.length})</option>
            {ledgerChoices.map(l => (
              <option key={l.name} value={l.name}>{l.name} · {l.count}</option>
            ))}
          </select>
        )}

        <label className="text-[11px] flex items-center gap-1 text-slate-600 cursor-pointer">
          <input type="checkbox" checked={showMerged}
                 onChange={(e) => onShowMerged(e.target.checked)}
                 data-testid="fa-add-show-merged"/>
          Show merged
        </label>

        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"/>
          <input
            data-testid="fa-add-search"
            className="pl-7 pr-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 w-56"
            placeholder="Search description, party, voucher…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>

        {/* Rows-per-page select */}
        <select
          data-testid="fa-add-page-size"
          value={pageSize}
          onChange={(e) => onPageSize(parseInt(e.target.value, 10))}
          className="px-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none"
          title="Rows per page"
        >
          {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n} / page</option>)}
        </select>

        <Pager page={page} totalPages={totalPages} onPage={onPage}/>

        <span className="w-px h-5 bg-slate-200 mx-1"/>

        {/* Bulk toggle */}
        <button
          data-testid="fa-add-bulk-toggle"
          onClick={onToggleBulk}
          className={`inline-flex items-center gap-1 px-2 py-1 text-[11.5px] border ${bulkMode ? "bg-slate-900 text-white border-slate-900" : "border-slate-300 hover:bg-slate-50"}`}
          title="Toggle multi-select"
        >
          {bulkMode ? <CheckSquare size={11}/> : <Square size={11}/>} Bulk
        </button>

        {/* Bulk PTU copy from Acc Date */}
        <button
          data-testid="fa-add-fill-ptu"
          onClick={onBulkCopyPTUFromAcc}
          className="inline-flex items-center gap-1 px-2 py-1 text-[11.5px] border border-slate-300 hover:bg-slate-50"
          title={`Copy Acc Date → PTU for every row in ${activeBlock || "this block"} that has no PTU yet`}
        >
          <CalendarRange size={11}/> Fill PTU
        </button>

        {/* Excel round-trip */}
        <button
          data-testid="fa-add-export-xlsx"
          onClick={onExportExcel}
          disabled={exporting}
          className="inline-flex items-center gap-1 px-2 py-1 text-[11.5px] border border-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-900 disabled:opacity-50"
          title="Export every block as a separate Excel sheet (Ledger column included for traceability)"
        >
          {exporting ? <Loader2 size={11} className="animate-spin"/> : <FileSpreadsheet size={11}/>} Export
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) onImportExcel(f);
          }}
          className="hidden"
          data-testid="fa-add-import-file"
        />
        <button
          data-testid="fa-add-import-xlsx"
          onClick={() => fileRef.current?.click()}
          disabled={importing}
          className="inline-flex items-center gap-1 px-2 py-1 text-[11.5px] border border-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-900 disabled:opacity-50"
          title="Re-import the edited Excel — totals will be cross-checked"
        >
          {importing ? <Loader2 size={11} className="animate-spin"/> : <FileUp size={11}/>} Import
        </button>

        {/* Column visibility */}
        <div className="relative">
          <button
            data-testid="fa-add-colvis-toggle"
            onClick={() => setColPopOpen(v => !v)}
            className="p-1.5 border border-slate-300 hover:bg-slate-50"
            title="Show/hide columns"
          >
            <Settings2 size={12}/>
          </button>
          {colPopOpen && (
            <ColVisPopover
              colVis={colVis}
              onChange={onColVis}
              onClose={() => setColPopOpen(false)}
            />
          )}
        </div>

        {busy && <Loader2 size={12} className="animate-spin text-slate-500"/>}
      </div>
    </div>
  );
}

function ColVisPopover({ colVis, onChange, onClose }) {
  const popRef = useRef(null);
  useEffect(() => {
    const onDoc = (e) => { if (!popRef.current?.contains(e.target)) onClose?.(); };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);
  return (
    <div
      ref={popRef}
      className="absolute right-0 mt-1 w-56 bg-white border border-slate-300 shadow-lg z-30 p-3"
      data-testid="fa-add-colvis-popover"
    >
      <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-500 mb-1.5">Columns</div>
      <div className="space-y-1">
        {COLUMN_DEFS.map(c => (
          <label key={c.key} className="flex items-center gap-2 text-[12px] cursor-pointer hover:bg-slate-50 px-1 py-0.5">
            <input
              type="checkbox"
              checked={!!colVis[c.key]}
              onChange={(e) => onChange({ ...colVis, [c.key]: e.target.checked })}
              data-testid={`fa-add-colvis-${c.key}`}
            />
            <span>{c.label}</span>
          </label>
        ))}
      </div>
      <div className="mt-2 text-[10.5px] text-slate-500">
        Acc Date · Description · Invoice Cost · Total · IT Block always shown.
      </div>
    </div>
  );
}
