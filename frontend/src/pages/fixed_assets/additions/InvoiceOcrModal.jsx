/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useState } from "react";
import {
  AlertCircle, CheckCircle2, FileScan, Loader2,
  Paperclip, Sparkles, X, BookMarked, Zap,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import { inr } from "./utils";

/**
 * Split-preview modal — opens when the auditor clicks "Resume" / "Review"
 * on an inbox row. Receives the upload-status payload (Mongo-backed) and
 * lets the auditor:
 *  - confirm/change the matched addition for each pending chunk
 *  - tick "Apply description" per chunk
 *  - skip a chunk altogether
 *  - filter the target dropdown by the auto-detected ledger (or any ledger)
 */
export function InvoiceUploadPreviewModal({
  rid, preview, additions, ledgers, applying, onClose, onApplied,
}) {
  // Auto-restrict-by-ledger when the OCR detected one. Auditor can flip
  // to "All ledgers" via the toggle.
  const detectedLedgerId = preview?.detected_fa_ledger_id || "";
  const detectedLedgerName = preview?.detected_ledger_name || "";

  const [restrictLedgerId, setRestrictLedgerId] = useState(detectedLedgerId);

  // Local draft of selections — start with auto-matches checked + apply-desc on
  // (skip already-applied chunks).
  const [draft, setDraft] = useState(() =>
    (preview?.chunks || []).map(c => ({
      chunk_index:       c.chunk_index,
      addition_id:       c.match?.addition_id || "",
      apply_description: !c.applied && !!(c.match && c.extraction?.description),
      skip:              !!c.applied,   // already-applied chunks default to "skip"
    })),
  );

  const update = (idx, patch) => setDraft(d => d.map((r, i) => i === idx ? { ...r, ...patch } : r));

  // High-confidence pending chunks — eligible for one-click bulk apply.
  const highConfChunks = useMemo(
    () => (preview?.chunks || []).filter(c =>
      !c.applied
      && c.match?.confidence === "high"
      && c.match?.addition_id,
    ),
    [preview?.chunks],
  );

  const applyAllHighConf = async () => {
    if (!highConfChunks.length) return;
    const ledgerLabel = detectedLedgerName ? ` across ${detectedLedgerName} ledger` : "";
    const confirmMsg =
      `${highConfChunks.length} high-confidence match${highConfChunks.length === 1 ? "" : "es"} will be attached and `
      + `${highConfChunks.length} asset description${highConfChunks.length === 1 ? "" : "s"} overwritten${ledgerLabel}.\n\nApply all?`;
    if (!window.confirm(confirmMsg)) return;
    const selections = highConfChunks.map(c => ({
      chunk_index:       c.chunk_index,
      addition_id:       c.match.addition_id,
      apply_description: !!c.extraction?.description,
    }));
    try {
      const { data } = await http.post(
        `/fixed-assets/runs/${rid}/apply-invoice-uploads`,
        { upload_id: preview.upload_id, selections },
      );
      toast.success(`${data.attached} attached · ${data.descriptions_updated} descriptions updated`);
      onApplied?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Apply failed");
    }
  };

  // Build the list of additions the dropdown shows — filter by ledger if set.
  const eligibleAdditions = useMemo(() => {
    let xs = additions.filter(a =>
      !a.parent_addition_id && (a.source || "addition") !== "discount_credit"
    );
    if (restrictLedgerId) {
      xs = xs.filter(a => a.fa_ledger_id === restrictLedgerId);
    }
    return xs;
  }, [additions, restrictLedgerId]);

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
  const chunks       = preview.chunks || [];
  const summary      = preview.summary || {};
  const appliedCount = chunks.filter(c => c.applied).length;
  const pendingCount = chunks.length - appliedCount;
  const ledgerForDetected = ledgers?.find(L => L.fa_ledger_id === detectedLedgerId);

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
              {appliedCount > 0 && <span className="text-emerald-700"> {appliedCount} already attached ·</span>}
              <span className="text-amber-700"> {pendingCount} pending</span>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900 p-1"
                  data-testid="fa-invoice-preview-close">
            <X size={16}/>
          </button>
        </div>

        {/* Ledger filter strip — auto-detect + manual override + escape hatch */}
        <div className="px-4 py-2 bg-[#FAFAF7] border-b border-[#EDEDE7] flex items-center flex-wrap gap-3 text-[12px]">
          <BookMarked size={13} className="text-sky-700"/>
          <span className="font-mono text-[10.5px] uppercase tracking-wider text-slate-500">
            Limit dropdowns to ledger
          </span>
          <select
            data-testid="fa-invoice-ledger-filter"
            value={restrictLedgerId}
            onChange={(e) => setRestrictLedgerId(e.target.value)}
            className="px-2 py-1 text-[11.5px] border border-[#D4D4D0] focus:outline-none max-w-[280px]"
          >
            <option value="">All ledgers ({(ledgers || []).length})</option>
            {(ledgers || []).map(L => (
              <option key={L.fa_ledger_id} value={L.fa_ledger_id}>
                {L.name}
                {L.fa_ledger_id === detectedLedgerId ? "  ★ detected" : ""}
              </option>
            ))}
          </select>
          {detectedLedgerName && (
            <span className="text-[11px] text-slate-600">
              Detected on the ledger pages:
              <span className="ml-1 font-medium text-slate-800">{detectedLedgerName}</span>
              {ledgerForDetected
                ? <span className="ml-1 text-emerald-700">(auto-mapped)</span>
                : <span className="ml-1 text-amber-700">(no run-ledger match — using "All ledgers")</span>}
            </span>
          )}
        </div>

        {ledgerNote && (
          <div className="px-4 py-2 bg-sky-50 border-b border-sky-200 text-[12px] text-sky-900">
            <Sparkles size={12} className="inline mr-1"/> {ledgerNote}
          </div>
        )}

        {highConfChunks.length > 0 && (
          <div
            className="px-4 py-2.5 bg-emerald-50 border-b border-emerald-300 flex items-center gap-3 text-[12.5px] text-emerald-900"
            data-testid="fa-invoice-highconf-banner"
          >
            <Zap size={14} className="text-emerald-700 shrink-0"/>
            <div className="flex-1 min-w-0">
              <span className="font-semibold">
                {highConfChunks.length} high-confidence match{highConfChunks.length === 1 ? "" : "es"} found
              </span>
              <span className="text-emerald-800 ml-2">
                · pre-selected with description overwrite. Click below to apply all in one go.
              </span>
            </div>
            <button
              onClick={applyAllHighConf}
              disabled={applying}
              data-testid="fa-invoice-apply-highconf-btn"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-700 hover:bg-emerald-800 text-white text-[12px] disabled:opacity-50 shrink-0"
            >
              {applying ? <Loader2 size={12} className="animate-spin"/> : <Zap size={12}/>}
              Apply all {highConfChunks.length}
            </button>
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
              allAdditions={additions}
              restrictLedgerId={restrictLedgerId}
            />
          ))}
        </div>

        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-[#EDEDE7] bg-[#FBFBF8]">
          <div className="text-[11px] text-slate-500">
            {draft.filter(s => !s.skip && s.addition_id).length} of {pendingCount || chunks.length} pending chunk(s) ready to attach.
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-[12.5px] border border-slate-300 hover:bg-slate-100">
              Close
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

function ChunkCard({ chunk, draft, onUpdate, additions, allAdditions, restrictLedgerId }) {
  const e = chunk.extraction || {};
  const m = chunk.match;
  const matched = !!m;
  const isApplied = !!chunk.applied;
  const skip = !!draft.skip;

  // Sort: matched-and-eligible first, then the rest.
  const sorted = useMemo(() => {
    if (!matched) return additions;
    const top = additions.filter(a => a.addition_id === m.addition_id);
    const rest = additions.filter(a => a.addition_id !== m.addition_id);
    return [...top, ...rest];
  }, [additions, matched, m?.addition_id]);

  const matchOutOfFilter = matched && restrictLedgerId
    && !additions.some(a => a.addition_id === m.addition_id);
  const selectedAdd = (allAdditions || additions).find(a => a.addition_id === draft.addition_id);

  // Already-applied chunks are rendered as compact ✓ rows
  if (isApplied) {
    const appliedRow = chunk.applied_preview || {};
    return (
      <div
        data-testid={`fa-invoice-chunk-${chunk.chunk_index}`}
        className="border border-emerald-300 bg-emerald-50/60"
      >
        <div className="flex items-center gap-3 px-3 py-2 text-[12.5px]">
          <CheckCircle2 size={14} className="text-emerald-700 shrink-0"/>
          <span className="font-mono text-[11px] text-emerald-900">
            Pages {chunk.page_range[0]}{chunk.page_range[0] !== chunk.page_range[1] ? `–${chunk.page_range[1]}` : ""}
            {" · "}#{e.invoice_no || "?"}
            {" · "}₹ {inr(e.total_value)}
          </span>
          <span className="text-slate-400">→</span>
          <span className="text-slate-800 truncate flex-1">
            {appliedRow.description || appliedRow.party_name || appliedRow.invoice_no || "(applied row)"}
          </span>
          <span className="text-[10.5px] font-mono uppercase tracking-wider text-emerald-800 bg-emerald-100 border border-emerald-200 px-1.5 py-0.5 shrink-0">
            Already attached
          </span>
        </div>
      </div>
    );
  }

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
          {m?.confidence && (
            <span
              className={`text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 border ${
                m.confidence === "high"
                  ? "bg-emerald-700 text-white border-emerald-700"
                  : m.confidence === "medium"
                    ? "bg-amber-100 text-amber-800 border-amber-300"
                    : "bg-slate-100 text-slate-600 border-slate-200"
              }`}
              data-testid={`fa-invoice-conf-${chunk.chunk_index}`}
              title={`Match confidence: ${m.confidence}`}
            >
              {m.confidence === "high" ? "★ High" : m.confidence}
            </span>
          )}
          {matchOutOfFilter && (
            <span className="text-[10px] text-amber-700">
              <AlertCircle size={9} className="inline mr-0.5"/>
              Match is in another ledger — pick from current filter or switch to "All ledgers"
            </span>
          )}
        </div>
        <label className="text-[11px] text-slate-600 flex items-center gap-1 cursor-pointer">
          <input type="checkbox" checked={skip}
                 onChange={(e) => onUpdate({ skip: e.target.checked })}
                 data-testid={`fa-invoice-chunk-skip-${chunk.chunk_index}`}/>
          Skip this chunk
        </label>
      </div>

      <div className="grid grid-cols-12 gap-3 p-3 text-[12px]">
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

        <div className="col-span-5 space-y-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">
              Attach to addition row
              {restrictLedgerId && (
                <span className="ml-1 normal-case text-slate-400">
                  ({additions.length} from selected ledger)
                </span>
              )}
            </div>
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
            {matched && !matchOutOfFilter && (
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
/* Toolbar drop zone — multi-file, fire-and-forget into inbox  */
/* =========================================================== */
export function InvoiceUploadDropZone({ rid, onUploaded, busy, setBusy }) {
  const [drag, setDrag]         = useState(false);
  const [queue, setQueue]       = useState([]); // [{name, status, error?}]

  const onDrop = async (ev) => {
    ev.preventDefault();
    setDrag(false);
    const files = Array.from(ev.dataTransfer?.files || []);
    if (files.length) await uploadAll(files);
  };
  const onPick = async (ev) => {
    const files = Array.from(ev.target.files || []);
    ev.target.value = "";
    if (files.length) await uploadAll(files);
  };

  const uploadAll = async (files) => {
    const validFiles = files.filter(f => {
      const ok = f.name.toLowerCase().endsWith(".pdf");
      if (!ok) toast.error(`Skipped non-PDF: ${f.name}`);
      const small = f.size <= 25 * 1024 * 1024;
      if (!small) toast.error(`${f.name} exceeds 25 MB`);
      return ok && small;
    });
    if (!validFiles.length) return;

    setBusy(true);
    const initial = validFiles.map(f => ({ name: f.name, status: "uploading" }));
    setQueue(initial);

    // Fire all uploads in parallel — backend kicks off OCR per file in the
    // background, returns upload_id immediately. The Inbox panel polls.
    const results = await Promise.allSettled(validFiles.map((f, idx) => uploadOne(f, idx)));
    const okCount = results.filter(r => r.status === "fulfilled").length;
    const failCount = results.length - okCount;

    if (okCount > 0) {
      toast.success(`${okCount} PDF${okCount === 1 ? "" : "s"} uploaded — Gemini is analysing in the background. Check the Invoice Inbox below.`);
    }
    if (failCount > 0) {
      toast.error(`${failCount} upload${failCount === 1 ? "" : "s"} failed — see queue.`);
    }
    onUploaded?.();
    // Auto-clear the in-flight queue after a few seconds; the Inbox below
    // takes over the visibility.
    setTimeout(() => setQueue([]), 3500);
    setBusy(false);
  };

  const uploadOne = async (f, idx) => {
    const fd = new FormData();
    fd.append("file", f);
    try {
      await http.post(
        `/fixed-assets/runs/${rid}/upload-invoices`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 },
      );
      setQueue(q => q.map((row, i) => i === idx ? { ...row, status: "queued" } : row));
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Upload failed";
      setQueue(q => q.map((row, i) => i === idx ? { ...row, status: "failed", error: msg } : row));
      throw e;
    }
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      className={`border border-dashed px-4 py-2.5 ${drag ? "border-sky-500 bg-sky-50" : "border-[#D4D4D0] bg-[#FAFAF7]"}`}
      data-testid="fa-invoice-dropzone"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[12px] text-[#52524E] flex-1 min-w-0">
          <FileScan size={14} className="text-sky-700 shrink-0"/>
          {queue.length > 0 ? (
            <UploadQueueLine queue={queue}/>
          ) : (
            <>
              <span className="font-semibold text-slate-800">Attach invoice PDFs</span>
              <span className="text-slate-500 truncate">— drop one or many PDFs.
                Each is queued into the Invoice Inbox below; review &amp; attach at your own pace.</span>
            </>
          )}
        </div>
        <label className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12.5px] border border-sky-300 bg-white hover:bg-sky-50 text-sky-900 cursor-pointer disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin"/> : <Paperclip size={13}/>}
          {busy ? "Uploading…" : "Choose PDFs"}
          <input type="file" accept=".pdf,application/pdf" multiple
                 onChange={onPick} disabled={busy}
                 className="hidden" data-testid="fa-invoice-upload-input"/>
        </label>
      </div>
    </div>
  );
}

function UploadQueueLine({ queue }) {
  const ok = queue.filter(r => r.status === "queued").length;
  const failed = queue.filter(r => r.status === "failed").length;
  const inFlight = queue.filter(r => r.status === "uploading").length;
  return (
    <div className="flex items-center gap-2 min-w-0 text-[11.5px]" data-testid="fa-invoice-progress">
      {inFlight > 0
        ? <><Loader2 size={13} className="animate-spin text-sky-700"/> Uploading {inFlight} of {queue.length}…</>
        : (
          <>
            <CheckCircle2 size={13} className="text-emerald-700"/>
            {ok} of {queue.length} sent to Inbox
            {failed > 0 && <span className="text-rose-700">· {failed} failed</span>}
          </>
        )}
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
