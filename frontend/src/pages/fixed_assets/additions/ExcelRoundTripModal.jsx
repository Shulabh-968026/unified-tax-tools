import React from "react";
import { AlertCircle, CheckCircle2, Loader2, Upload, X } from "lucide-react";
import { inr, ADJ_LABELS } from "./utils";

const FIELD_LABELS = {
  description:          "Description",
  party_name:           "Supplier",
  voucher_no:           "Voucher No",
  invoice_no:           "Invoice No",
  invoice_date:         "Inv Date",
  put_to_use_date:      "PTU Date",
  ...ADJ_LABELS,
};

/**
 * Excel re-import preview modal.
 * Receives the dry-run response from POST /additions/import.xlsx?dry_run=true
 * and lets the auditor confirm before applying. When totals drift, a rose
 * banner is shown — the auditor can apply anyway, but the run will get a
 * persistent "drift unreconciled" warning until they explicitly clear it.
 */
export function ExcelImportPreviewModal({ preview, applying, onClose, onApply }) {
  const drifted = !!preview?.drift?.drifted;
  const driftedBlocks = (preview?.drift?.blocks || []).filter(b => Math.abs(b.diff) > 1.0);
  const changes = preview?.changes || [];
  const unknownCount = (preview?.unknown_ids || []).length;
  const sheetErrors = preview?.errors || [];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6"
      data-testid="fa-add-import-modal"
    >
      <div className="bg-white border border-[#E5E5E0] w-full max-w-4xl max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-[#EDEDE7]">
          <div className="min-w-0">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-600">
              Re-import Excel — review changes
            </div>
            <div className="font-heading text-base mt-0.5 truncate">
              {preview?.filename || "additions.xlsx"}
            </div>
            <div className="text-[11.5px] text-slate-500 mt-0.5">
              {changes.length} row{changes.length === 1 ? "" : "s"} edited
              {unknownCount > 0 && ` · ${unknownCount} unknown id${unknownCount === 1 ? "" : "s"} skipped`}
              {sheetErrors.length > 0 && ` · ${sheetErrors.length} sheet error${sheetErrors.length === 1 ? "" : "s"}`}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 p-1" data-testid="fa-add-import-close">
            <X size={16}/>
          </button>
        </div>

        <div className="overflow-y-auto p-4 space-y-3 flex-1">
          {/* Drift banner */}
          {drifted ? (
            <div
              className="border border-rose-300 bg-rose-50 px-4 py-3 text-[12.5px] text-rose-900 flex items-start gap-2"
              data-testid="fa-add-import-drift"
            >
              <AlertCircle size={16} className="text-rose-700 mt-0.5 shrink-0"/>
              <div className="flex-1">
                <div className="font-semibold">Block totals drift detected</div>
                <div className="mt-1 text-[12px]">
                  Applying these changes will alter the capitalised cost of the following block(s).
                  This may be intentional (e.g. you added freight via Other Exp), but if it isn't,
                  cancel and rework the Excel before importing.
                </div>
                <table className="w-full mt-2 text-[11.5px] font-mono">
                  <thead>
                    <tr className="text-left text-rose-800 uppercase tracking-wider text-[10px]">
                      <th className="py-1">Block</th>
                      <th className="py-1 text-right">Current Total</th>
                      <th className="py-1 text-right">After Import</th>
                      <th className="py-1 text-right">Δ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rose-200">
                    {driftedBlocks.map(b => (
                      <tr key={b.block_label}>
                        <td className="py-1">{b.block_label}</td>
                        <td className="py-1 text-right">{inr(b.db_total)}</td>
                        <td className="py-1 text-right">{inr(b.excel_total)}</td>
                        <td className={`py-1 text-right font-bold ${b.diff > 0 ? "text-emerald-700" : "text-rose-700"}`}>
                          {b.diff > 0 ? "+" : ""}{inr(b.diff)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="border border-emerald-300 bg-emerald-50 px-4 py-2.5 text-[12.5px] text-emerald-900 flex items-center gap-2"
                 data-testid="fa-add-import-clean">
              <CheckCircle2 size={14} className="text-emerald-700"/>
              All block totals reconcile after this import — clean apply.
            </div>
          )}

          {/* Sheet errors */}
          {sheetErrors.length > 0 && (
            <div className="border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
              <div className="font-semibold mb-1">Sheet warnings</div>
              <ul className="list-disc pl-5 space-y-0.5">
                {sheetErrors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          {/* Per-row changes */}
          <div>
            <div className="text-[10.5px] font-mono uppercase tracking-wider text-slate-600 mb-1">
              Edited rows ({changes.length})
            </div>
            <div className="border border-[#E5E5E0] max-h-[40vh] overflow-y-auto">
              {changes.length === 0 ? (
                <div className="p-4 text-center text-[12px] text-slate-500">
                  No editable cells changed.
                </div>
              ) : (
                <table className="w-full text-[11.5px]">
                  <thead className="sticky top-0 bg-[#F9F9F8]">
                    <tr className="text-left text-[10px] font-mono uppercase tracking-wider text-slate-600">
                      <th className="px-3 py-1.5">Row</th>
                      <th className="px-3 py-1.5">Field</th>
                      <th className="px-3 py-1.5">From</th>
                      <th className="px-3 py-1.5">To</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EDEDE7]">
                    {changes.flatMap(c => Object.entries(c.changes).map(([f, v], i) => (
                      <tr key={`${c.addition_id}-${f}`} className="hover:bg-[#FBFBF8]"
                          data-testid={`fa-import-change-${c.addition_id}-${f}`}>
                        {i === 0 ? (
                          <td className="px-3 py-1.5" rowSpan={Object.keys(c.changes).length}>
                            <div className="font-medium truncate max-w-[280px]" title={c.description}>
                              {c.description || "(no description)"}
                            </div>
                            <div className="text-[10px] text-slate-500 mt-0.5">
                              {c.ledger_name || c.block_label}
                            </div>
                          </td>
                        ) : null}
                        <td className="px-3 py-1.5">{FIELD_LABELS[f] || f}</td>
                        <td className="px-3 py-1.5 font-mono text-rose-700 max-w-[200px] truncate" title={String(v.old ?? "")}>
                          {fmtCell(f, v.old)}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-emerald-700 max-w-[200px] truncate" title={String(v.new ?? "")}>
                          {fmtCell(f, v.new)}
                        </td>
                      </tr>
                    )))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <div className="text-[11px] text-slate-500">
            {drifted
              ? "A persistent banner will warn you on the Compute tab until you clear the drift."
              : "Changes are saved immediately and the half-rate flag is recomputed where PTU Dates change."}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">
              Cancel
            </button>
            <button
              data-testid="fa-add-import-apply"
              onClick={onApply}
              disabled={applying || changes.length === 0}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] text-white disabled:opacity-50 ${drifted ? "bg-rose-700 hover:bg-rose-800" : "bg-slate-900 hover:bg-slate-800"}`}
            >
              {applying ? <Loader2 size={13} className="animate-spin"/> : <Upload size={13}/>}
              {drifted ? "Apply Anyway" : "Apply Changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function fmtCell(field, v) {
  if (v === undefined || v === null || v === "") return <span className="text-slate-400">—</span>;
  if (typeof v === "number" || /^(other_expenses|itc_reversed|interest_capitalized|forex_fluctuations|discount_credits)$/.test(field)) {
    return inr(v);
  }
  return String(v);
}

/* ---------------- Run-level persistent drift banner ---------------- */
export function DriftBanner({ warning, onClear, clearing }) {
  if (!warning) return null;
  return (
    <div
      className="border border-rose-300 bg-rose-50 px-4 py-2.5 flex items-start gap-2 text-[12.5px] text-rose-900"
      data-testid="fa-drift-banner"
    >
      <AlertCircle size={15} className="text-rose-700 mt-0.5 shrink-0"/>
      <div className="flex-1 min-w-0">
        <div className="font-semibold">
          Excel re-import left this run with unreconciled block totals
        </div>
        <div className="text-[11.5px] text-rose-800 mt-0.5">
          Imported {warning.applied_at ? new Date(warning.applied_at).toLocaleString("en-IN") : ""}
          {warning.applied_by ? ` from ${warning.applied_by}` : ""}
          {" · "}{warning.rows_changed} row{warning.rows_changed === 1 ? "" : "s"} edited
          {" · "}{(warning.blocks || []).length} block{(warning.blocks || []).length === 1 ? "" : "s"} drifted.
          Investigate and reconcile before generating the final report.
        </div>
        {(warning.blocks || []).length > 0 && (
          <ul className="text-[11px] font-mono mt-1 space-y-0.5">
            {warning.blocks.slice(0, 5).map(b => (
              <li key={b.block_label}>
                {b.block_label} — Δ{" "}
                <span className={b.diff > 0 ? "text-emerald-700" : "text-rose-700"}>
                  {b.diff > 0 ? "+" : ""}{inr(b.diff)}
                </span>{" "}
                ({inr(b.db_total)} → {inr(b.excel_total)})
              </li>
            ))}
          </ul>
        )}
      </div>
      <button
        onClick={onClear}
        disabled={clearing}
        data-testid="fa-drift-clear"
        className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 bg-rose-700 hover:bg-rose-800 text-white text-[11.5px] disabled:opacity-50"
      >
        {clearing ? <Loader2 size={11} className="animate-spin"/> : <CheckCircle2 size={11}/>}
        Mark Reconciled
      </button>
    </div>
  );
}
