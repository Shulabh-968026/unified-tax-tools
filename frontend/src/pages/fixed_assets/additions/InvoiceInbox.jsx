/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useState } from "react";
import {
  Inbox, Loader2, FileScan, AlertCircle, CheckCircle2, Trash2,
  RotateCw, ChevronDown, ChevronRight, BookMarked,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";

/**
 * Persistent invoice inbox shown above the additions table.
 *
 * - Lists every pending upload for the current run (Mongo-backed).
 * - Auto-polls every 4 s while ANY row is in 'processing' state.
 * - "Resume" opens the existing preview modal pre-loaded with that upload.
 * - "Discard" deletes the pending row + sidecar chunk PDFs (already-applied
 *   attachments survive on the rows themselves).
 */
export function InvoiceInbox({ rid, refreshKey, onResume, refreshAdditions }) {
  const [rows, setRows] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const refresh = async () => {
    if (!rid) return;
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/invoice-inbox`);
      setRows(data?.rows || []);
    } catch (e) {
      // Silent — inbox is non-critical UI; surface only if explicitly missing.
      if (e?.response?.status && e.response.status !== 404) {
        toast.error(e?.response?.data?.detail || "Could not load invoice inbox");
      }
    } finally {
      setLoaded(true);
    }
  };

  // Initial + reactive load
  useEffect(() => { refresh(); }, [rid, refreshKey]);

  // Auto-poll while anything is processing
  useEffect(() => {
    const anyProcessing = rows.some(r => r.status === "processing");
    if (!anyProcessing) return undefined;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [rows]);

  if (!loaded || rows.length === 0) return null;

  const total   = rows.length;
  const pending = rows.reduce((s, r) => s + (r.pending || 0), 0);
  const proc    = rows.filter(r => r.status === "processing").length;

  const discard = async (uid, filename) => {
    if (!window.confirm(`Discard "${filename}"? Already-attached chunks stay on their rows; only the inbox entry + un-attached chunks are removed.`)) return;
    setBusyId(uid);
    try {
      await http.delete(`/fixed-assets/runs/${rid}/invoice-inbox/${uid}`);
      toast.success("Removed from inbox");
      refresh();
      refreshAdditions?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not discard");
    } finally { setBusyId(null); }
  };

  return (
    <div className="border border-[#E5E5E0] bg-white" data-testid="fa-invoice-inbox">
      <button
        type="button"
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-[#FAFAF7] text-left"
        data-testid="fa-invoice-inbox-toggle"
      >
        <div className="flex items-center gap-2 text-[12.5px]">
          {collapsed ? <ChevronRight size={13} className="text-slate-500"/> : <ChevronDown size={13} className="text-slate-500"/>}
          <Inbox size={14} className="text-sky-700"/>
          <span className="font-semibold text-slate-800">Invoice Inbox</span>
          <span className="text-slate-500">·</span>
          <span className="font-mono text-[11px] text-slate-600">
            {total} upload{total === 1 ? "" : "s"}
            {proc > 0 && (
              <span className="ml-2 text-amber-700">
                <Loader2 size={10} className="inline animate-spin mr-0.5"/>
                {proc} processing
              </span>
            )}
            {pending > 0 && (
              <span className="ml-2 text-rose-700">
                {pending} chunk{pending === 1 ? "" : "s"} unattached
              </span>
            )}
          </span>
        </div>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); refresh(); }}
          className="text-slate-400 hover:text-slate-700 p-1"
          title="Refresh"
        >
          <RotateCw size={11}/>
        </button>
      </button>

      {!collapsed && (
        <div className="border-t border-[#EDEDE7]">
          <ul className="divide-y divide-[#EDEDE7]">
            {rows.map(r => (
              <li key={r.upload_id} className="px-4 py-2.5 flex items-center gap-3 hover:bg-[#FBFBF8]"
                  data-testid={`fa-inbox-row-${r.upload_id}`}>
                <FileScan size={14} className={
                  r.status === "failed" ? "text-rose-600"
                  : r.status === "processing" ? "text-amber-600"
                  : r.pending === 0 ? "text-emerald-600"
                  : "text-sky-700"
                }/>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium truncate" title={r.filename}>
                    {r.filename}
                  </div>
                  <div className="text-[10.5px] font-mono text-slate-500 mt-0.5 flex items-center flex-wrap gap-2">
                    <span>{(r.pdf_size / 1024).toFixed(0)} KB</span>
                    {r.detected_ledger_name && (
                      <span className="inline-flex items-center gap-0.5 text-sky-700">
                        <BookMarked size={9}/>
                        {r.detected_ledger_name}
                      </span>
                    )}
                    {r.status === "processing" && (
                      <span className="text-amber-700">
                        <Loader2 size={10} className="inline animate-spin mr-0.5"/>
                        Analysing…
                      </span>
                    )}
                    {r.status === "failed" && (
                      <span className="text-rose-700 truncate">
                        <AlertCircle size={10} className="inline mr-0.5"/>
                        Failed: {r.error || "Unknown error"}
                      </span>
                    )}
                    {r.status === "done" && (
                      <>
                        <span>{r.total_chunks} chunk{r.total_chunks === 1 ? "" : "s"}</span>
                        {r.applied > 0 && (
                          <span className="text-emerald-700">
                            <CheckCircle2 size={10} className="inline mr-0.5"/>
                            {r.applied} attached
                          </span>
                        )}
                        {r.pending > 0 && (
                          <span className="text-rose-700">{r.pending} pending</span>
                        )}
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {r.status === "done" && (
                    <button
                      onClick={() => onResume?.(r.upload_id)}
                      data-testid={`fa-inbox-resume-${r.upload_id}`}
                      className="px-2 py-1 text-[11.5px] border border-sky-300 bg-sky-50 hover:bg-sky-100 text-sky-900"
                    >
                      {r.pending > 0 ? "Resume" : "Review"}
                    </button>
                  )}
                  <button
                    onClick={() => discard(r.upload_id, r.filename)}
                    disabled={busyId === r.upload_id}
                    data-testid={`fa-inbox-discard-${r.upload_id}`}
                    className="text-slate-400 hover:text-rose-700 p-1 disabled:opacity-50"
                    title="Remove from inbox"
                  >
                    {busyId === r.upload_id
                      ? <Loader2 size={11} className="animate-spin"/>
                      : <Trash2 size={11}/>}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
