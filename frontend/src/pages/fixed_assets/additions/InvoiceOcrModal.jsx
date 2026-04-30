/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useState } from "react";
import {
  AlertCircle, CheckCircle2, Eye, FileScan, Loader2,
  Paperclip, Sparkles, X,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import { inr } from "./utils";

/**
 * Split-preview modal shown right after the auditor uploads a PDF.
 * Receives the response from POST /upload-invoices and lets the auditor:
 *  - confirm/change the matched addition for each chunk
 *  - tick "Apply description" per chunk
 *  - skip a chunk altogether
 *  - then commit via POST /apply-invoice-uploads
 */
export function InvoiceUploadPreviewModal({
  rid, preview, additions, applying, onClose, onApplied,
}) {
  // Local draft of selections — start with auto-matches checked + apply-desc on
  const [draft, setDraft] = useState(() =>
    (preview?.chunks || []).map(c => ({
      chunk_index:       c.chunk_index,
      addition_id:       c.match?.addition_id || "",
      apply_description: !!(c.match && c.extraction?.description),
      skip:              false,
    })),
  );

  const update = (idx, patch) => setDraft(d => d.map((r, i) => i === idx ? { ...r, ...patch } : r));

  const eligibleAdditions = useMemo(() => additions.filter(a =>
    !a.parent_addition_id && (a.source || "addition") !== "discount_credit"
  ), [additions]);

  const apply = async () => {
    const selections = draft
      .filter(s => !s.skip && s.addition_id)
      .map(({ chunk_index, addition_id, apply_description }) => ({
        chunk_index, addition_id, apply_description,
      }));
    if (!selections.length) {
      toast.error("Pick at least one chunk to attach.");
      return;
    }
    try {
      const { data } = await http.post(
        `/fixed-assets/runs/${rid}/apply-invoice-uploads`,
        { upload_id: preview.upload_id, selections },
      );
      const msg = `${data.attached} attached`
        + (data.descriptions_updated ? ` · ${data.descriptions_updated} description${data.descriptions_updated === 1 ? "" : "s"} updated` : "");
      toast.success(msg);
      onApplied?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Apply failed");
    }
  };

  if (!preview) return null;
  const chunks = preview.chunks || [];
  const summary = preview.summary || {};
  const ledgerNote = (preview.ledger_pages || []).length
    ? `Page ${preview.ledger_pages.join(", ")} detected as Ledger Extract — kept for record but not attached to any row.`
    : null;

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6"
         data-testid="fa-invoice-preview-modal">
      <div className="bg-white border border-[#E5E5E0] w-full max-w-5xl max-h-[88vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-[#EDEDE7]">
          <div className="min-w-0">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-slate-600">
              Invoice OCR · review &amp; attach
            </div>
            <div className="font-heading text-base mt-0.5 truncate">{preview.filename || "invoice.pdf"}</div>
            <div className="text-[11.5px] text-slate-500 mt-0.5">
              {summary.pages_total} page{summary.pages_total === 1 ? "" : "s"} ·
              {" "}{summary.invoices_detected} invoice{summary.invoices_detected === 1 ? "" : "s"} detected ·
              <span className="text-emerald-700"> {summary.matched} auto-matched</span> ·
              <span className="text-amber-700"> {summary.unmatched} need review</span>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 p-1"
                  data-testid="fa-invoice-preview-close">
            <X size={16}/>
          </button>
        </div>

        {ledgerNote && (
          <div className="px-4 py-2 bg-sky-50 border-b border-sky-200 text-[12px] text-sky-900">
            <Sparkles size={12} className="inline mr-1"/> {ledgerNote}
          </div>
        )}

        <div className="overflow-y-auto p-4 space-y-3 flex-1">
          {chunks.length === 0 ? (
            <div className="border border-amber-300 bg-amber-50 px-4 py-3 text-[12.5px] text-amber-900 flex items-center gap-2">
              <AlertCircle size={14}/> No tax invoice pages detected in this PDF.
            </div>
          ) : chunks.map((c, i) => (
            <ChunkCard
              key={c.chunk_index}
              chunk={c}
              draft={draft[i]}
              onUpdate={(p) => update(i, p)}
              additions={eligibleAdditions}
            />
          ))}
        </div>

        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <div className="text-[11px] text-slate-500">
            {draft.filter(s => !s.skip && s.addition_id).length} of {chunks.length} chunk(s) ready to attach.
            Each addition can hold one invoice — re-uploading replaces the existing attachment.
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">
              Cancel
            </button>
            <button
              data-testid="fa-invoice-apply-btn"
              onClick={apply}
              disabled={applying}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12.5px] bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {applying ? <Loader2 size={13} className="animate-spin"/> : <CheckCircle2 size={13}/>}
              Attach &amp; Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChunkCard({ chunk, draft, onUpdate, additions }) {
  const e = chunk.extraction || {};
  const m = chunk.match;
  const matched = !!m;
  const skip = !!draft.skip;

  // Filter additions for the dropdown — show all eligible, with the matched
  // one suggested at top.
  const sorted = useMemo(() => {
    if (!matched) return additions;
    const top = additions.filter(a => a.addition_id === m.addition_id);
    const rest = additions.filter(a => a.addition_id !== m.addition_id);
    return [...top, ...rest];
  }, [additions, matched, m?.addition_id]);

  const selectedAdd = additions.find(a => a.addition_id === draft.addition_id);

  return (
    <div
      data-testid={`fa-invoice-chunk-${chunk.chunk_index}`}
      className={`border ${skip ? "border-slate-200 bg-slate-50/60 opacity-60" : matched ? "border-emerald-300 bg-emerald-50/30" : "border-amber-300 bg-amber-50/30"}`}
    >
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-[#EDEDE7]">
        <div className="flex items-center gap-2">
          <FileScan size={13} className={matched ? "text-emerald-700" : "text-amber-700"}/>
          <span className="font-mono text-[11px] text-slate-700">
            Pages {chunk.page_range[0]}{chunk.page_range[0] !== chunk.page_range[1] ? `–${chunk.page_range[1]}` : ""}
            {" · "}{(chunk.pdf_size / 1024).toFixed(0)} KB
          </span>
          <span className={`text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 border ${matched ? "bg-emerald-100 text-emerald-800 border-emerald-200" : "bg-amber-100 text-amber-800 border-amber-200"}`}>
            {matched ? `Matched · ${m.method}` : "Needs review"}
          </span>
        </div>
        <label className="text-[11px] text-slate-600 flex items-center gap-1 cursor-pointer">
          <input type="checkbox" checked={skip}
                 onChange={(e) => onUpdate({ skip: e.target.checked })}
                 data-testid={`fa-invoice-chunk-skip-${chunk.chunk_index}`}/>
          Skip this chunk
        </label>
      </div>

      <div className="grid grid-cols-12 gap-3 p-3 text-[12px]">
        {/* Extraction summary */}
        <div className="col-span-7 space-y-1.5">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">Extracted from PDF</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11.5px]">
            <KV label="Inv No"     v={e.invoice_no}/>
            <KV label="Date"       v={e.invoice_date_iso}/>
            <KV label="Supplier"   v={e.supplier_name}/>
            <KV label="GSTIN"      v={e.supplier_gstin}/>
            <KV label="Total"      v={`₹ ${inr(e.total_value)}`}/>
            <KV label="Taxable"    v={`₹ ${inr(e.taxable_value)}`}/>
          </div>
          <div className="mt-2">
            <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">
              Asset description (will overwrite if checked below)
            </div>
            <div className="mt-0.5 text-[12.5px] bg-white border border-slate-200 px-2 py-1.5 leading-snug text-slate-800">
              {e.description || <span className="text-slate-400">(no description extracted)</span>}
            </div>
          </div>
        </div>

        {/* Targeting + actions */}
        <div className="col-span-5 space-y-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">Attach to addition row</div>
            <select
              disabled={skip}
              value={draft.addition_id || ""}
              onChange={(ev) => onUpdate({ addition_id: ev.target.value })}
              className="w-full mt-0.5 px-2 py-1.5 text-[11.5px] border border-[#D4D4D0] focus:outline-none focus:border-slate-700 disabled:bg-slate-100 bg-white"
              data-testid={`fa-invoice-chunk-addition-${chunk.chunk_index}`}
            >
              <option value="">— Pick an addition row —</option>
              {sorted.map(a => (
                <option key={a.addition_id} value={a.addition_id}>
                  {(a.invoice_no || "no-inv") + " · " + (a.party_name || "no-party") + " · ₹" + Number(a.invoice_cost || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  {a.addition_id === m?.addition_id ? "  ★" : ""}
                </option>
              ))}
            </select>
            {matched && (
              <div className="text-[10.5px] text-emerald-700 mt-1">
                <CheckCircle2 size={10} className="inline mr-0.5"/> Auto-match: {m.why}
              </div>
            )}
          </div>

          {selectedAdd && (
            <div className="bg-white border border-slate-200 px-2 py-1.5 text-[11px] text-slate-600">
              <div className="text-[9.5px] font-mono uppercase tracking-wider text-slate-500">
                Current row description
              </div>
              <div className="mt-0.5 line-clamp-2 leading-snug">
                {selectedAdd.description || selectedAdd.particulars || "(blank)"}
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-[12px] cursor-pointer mt-1">
            <input
              type="checkbox"
              disabled={skip || !e.description}
              checked={!!draft.apply_description}
              onChange={(ev) => onUpdate({ apply_description: ev.target.checked })}
              data-testid={`fa-invoice-chunk-applydesc-${chunk.chunk_index}`}
            />
            <span>Overwrite Description with extracted asset line</span>
          </label>
        </div>
      </div>
    </div>
  );
}

function KV({ label, v }) {
  return (
    <>
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800 truncate" title={v}>{v || "—"}</span>
    </>
  );
}

/* =========================================================== */
/* Toolbar drop zone — sits at the top of the Additions tab    */
/* =========================================================== */
export function InvoiceUploadDropZone({ rid, onPreview, busy, setBusy }) {
  const [drag, setDrag] = useState(false);
  const onDrop = async (ev) => {
    ev.preventDefault();
    setDrag(false);
    const f = ev.dataTransfer?.files?.[0];
    if (f) await uploadOne(f);
  };
  const onPick = async (ev) => {
    const f = ev.target.files?.[0];
    ev.target.value = "";
    if (f) await uploadOne(f);
  };
  const uploadOne = async (f) => {
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Only .pdf files are supported.");
      return;
    }
    if (f.size > 25 * 1024 * 1024) {
      toast.error("PDF exceeds 25 MB.");
      return;
    }
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const { data } = await http.post(
        `/fixed-assets/runs/${rid}/upload-invoices`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      onPreview?.({ ...data, filename: f.name });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally { setBusy(false); }
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      className={`border border-dashed px-4 py-2.5 flex items-center justify-between gap-3 ${drag ? "border-sky-500 bg-sky-50" : "border-[#D4D4D0] bg-[#FAFAF7]"}`}
      data-testid="fa-invoice-dropzone"
    >
      <div className="flex items-center gap-2 text-[12px] text-[#52524E]">
        <FileScan size={14} className="text-sky-700"/>
        <span className="font-semibold text-slate-800">Attach invoice PDFs</span>
        <span className="text-slate-500">— drop a single invoice or a combined ledger+invoices PDF.
          The OCR splits it, matches each invoice to a row, and fills the asset description.</span>
      </div>
      <label className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12.5px] border border-sky-300 bg-white hover:bg-sky-50 text-sky-900 cursor-pointer">
        {busy ? <Loader2 size={13} className="animate-spin"/> : <Paperclip size={13}/>}
        Choose PDF
        <input type="file" accept=".pdf,application/pdf"
               onChange={onPick} className="hidden" data-testid="fa-invoice-upload-input"/>
      </label>
    </div>
  );
}

/* =========================================================== */
/* Tiny per-row paperclip indicator + view/delete actions      */
/* =========================================================== */
export function RowAttachmentIcon({ rid, addition, attachment, onDeleted }) {
  const [busy, setBusy] = useState(false);
  if (!attachment) return null;
  const view = async () => {
    try {
      const res = await http.get(
        `/fixed-assets/runs/${rid}/additions/${addition.addition_id}/invoice`,
        { responseType: "blob" },
      );
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      window.open(url, "_blank", "noopener");
      // Don't revokeObjectURL immediately — let the new tab use it.
      setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load PDF");
    }
  };
  const detach = async () => {
    if (!window.confirm("Detach this invoice from the row? The Description column won't be touched.")) return;
    setBusy(true);
    try {
      await http.delete(`/fixed-assets/runs/${rid}/additions/${addition.addition_id}/invoice`);
      toast.success("Detached");
      onDeleted?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Detach failed");
    } finally { setBusy(false); }
  };
  return (
    <span className="inline-flex items-center gap-0.5 ml-1" data-testid={`fa-attachment-${addition.addition_id}`}>
      <button
        title={`View invoice (${(attachment.pdf_size/1024).toFixed(0)} KB)`}
        onClick={view}
        className="text-emerald-700 hover:text-emerald-900"
      >
        <Paperclip size={11}/>
      </button>
      <button
        title="Detach invoice"
        onClick={detach}
        disabled={busy}
        className="text-slate-400 hover:text-rose-700 disabled:opacity-40"
      >
        {busy ? <Loader2 size={9} className="animate-spin"/> : <X size={9}/>}
      </button>
    </span>
  );
}
