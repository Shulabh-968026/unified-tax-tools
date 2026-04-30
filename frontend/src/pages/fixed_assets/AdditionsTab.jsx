/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { http } from "@/lib/api";
import { toast } from "sonner";

import {
  capitalised, DEFAULT_COL_VIS, LS_COL_VIS, LS_PAGE_SIZE,
} from "./additions/utils";
import { ProgressStrip } from "./additions/ProgressStrip";
import { Pager } from "./additions/Pager";
import { AdditionRow } from "./additions/AdditionRow";
import { MergedRow } from "./additions/MergedRow";
import { MergeModal } from "./additions/MergeModal";
import { AdditionsToolbar } from "./additions/AdditionsToolbar";
import { BulkActionBar } from "./additions/BulkActionBar";
import {
  DriftBanner, ExcelImportPreviewModal,
} from "./additions/ExcelRoundTripModal";
import {
  InvoiceUploadDropZone, InvoiceUploadPreviewModal,
} from "./additions/InvoiceOcrModal";

const lsGet = (k, fb) => {
  try { const v = localStorage.getItem(k); return v == null ? fb : JSON.parse(v); }
  catch { return fb; }
};
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* noop */ } };

export default function AdditionsTab({ rid, blocks }) {
  const [rows, setRows] = useState([]);
  const [progress, setProgress] = useState({ rows: [], summary: {} });
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [activeBlock, setActiveBlock] = useState("");
  const [ledgerFilter, setLedgerFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(lsGet(LS_PAGE_SIZE, 10)) || 10);
  const [showMerged, setShowMerged] = useState(true);
  const [colVis, setColVis] = useState(() => ({ ...DEFAULT_COL_VIS, ...lsGet(LS_COL_VIS, {}) }));

  const [bulkMode, setBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());

  const [linkFor, setLinkFor] = useState(null);

  // Excel round-trip + drift banner state
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importPreview, setImportPreview] = useState(null);
  const [importFile, setImportFile] = useState(null);
  const [driftWarning, setDriftWarning] = useState(null);
  const [clearingDrift, setClearingDrift] = useState(false);

  // Invoice OCR (Phase 1.5)
  const [ocrBusy, setOcrBusy]           = useState(false);
  const [ocrPreview, setOcrPreview]     = useState(null);
  const [ocrApplying, setOcrApplying]   = useState(false);
  const [attachments, setAttachments]   = useState({});  // {addition_id: {filename, pdf_size, ...}}

  // Persist UI prefs
  useEffect(() => lsSet(LS_PAGE_SIZE, pageSize), [pageSize]);
  useEffect(() => lsSet(LS_COL_VIS, colVis), [colVis]);

  // ---------------- Data ----------------
  const refresh = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const [r, p, runRes, atts] = await Promise.all([
        http.get(`/fixed-assets/runs/${rid}/additions`),
        http.get(`/fixed-assets/runs/${rid}/additions/progress`),
        http.get(`/fixed-assets/runs/${rid}`),
        http.get(`/fixed-assets/runs/${rid}/invoice-attachments`),
      ]);
      setRows(r.data?.rows || []);
      setProgress(p.data || { rows: [], summary: {} });
      setDriftWarning(runRes.data?.excel_drift_warning || null);
      const map = {};
      for (const a of (atts.data?.rows || [])) map[a.addition_id] = a;
      setAttachments(map);
      if (!activeBlock && p.data?.rows?.length) {
        setActiveBlock(p.data.rows[0].block_label);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load additions");
    } finally { setBusy(false); }
  }, [rid, activeBlock]);
  useEffect(() => { refresh(); }, [refresh]);

  const patchRow = async (a, patch) => {
    if (a.source === "discount_credit") return;
    setRows(rs => rs.map(r => r.addition_id === a.addition_id ? { ...r, ...patch, reviewed: true } : r));
    try {
      await http.patch(`/fixed-assets/runs/${rid}/additions/${a.addition_id}`, patch);
      // Refresh progress strip + Total derived elsewhere — but keep row's
      // local "Saved" indicator clean by NOT re-fetching the whole row list
      // here. We refresh the progress only.
      const p = await http.get(`/fixed-assets/runs/${rid}/additions/progress`);
      setProgress(p.data || { rows: [], summary: {} });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refresh();
      throw e;
    }
  };

  // ---------------- Merge / Unlink ----------------
  const closeLink = () => setLinkFor(null);
  const applyLink = async (child, { parent_addition_id, linked_as }) => {
    closeLink();
    try {
      await http.post(`/fixed-assets/runs/${rid}/additions/${child.addition_id}/link`,
                      { parent_addition_id, linked_as });
      toast.success("Line item merged");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Link failed");
    }
  };
  const unlink = async (child) => {
    try {
      await http.post(`/fixed-assets/runs/${rid}/additions/${child.addition_id}/unlink`);
      toast.success("Unlinked");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Unlink failed");
    }
  };

  // ---------------- Filtering ----------------
  const blockChoices = progress.rows || [];

  const ledgerChoices = useMemo(() => {
    const counts = new Map();
    for (const r of rows) {
      if (activeBlock && r.block_label !== activeBlock) continue;
      if (r.parent_addition_id) continue;
      const n = r.ledger_name || "(unmapped)";
      counts.set(n, (counts.get(n) || 0) + 1);
    }
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
  }, [rows, activeBlock]);

  // Reset ledger filter when active block changes
  useEffect(() => { setLedgerFilter(""); setPage(1); }, [activeBlock]);

  const filtered = useMemo(() => {
    let xs = rows;
    if (activeBlock) xs = xs.filter(r => r.block_label === activeBlock);
    if (ledgerFilter) xs = xs.filter(r => (r.ledger_name || "(unmapped)") === ledgerFilter);
    const q = search.trim().toLowerCase();
    if (q) xs = xs.filter(r => `${r.description || r.particulars} ${r.party_name} ${r.voucher_no} ${r.invoice_no}`.toLowerCase().includes(q));
    if (!showMerged) xs = xs.filter(r => !r.parent_addition_id);

    // Order children directly after their parent
    const byId = new Map(xs.map(r => [r.addition_id, r]));
    const childrenByParent = new Map();
    for (const r of xs) {
      const p = r.parent_addition_id;
      if (p && byId.has(p)) {
        if (!childrenByParent.has(p)) childrenByParent.set(p, []);
        childrenByParent.get(p).push(r);
      }
    }
    const ordered = [];
    const seen = new Set();
    for (const r of xs) {
      if (r.parent_addition_id && byId.has(r.parent_addition_id)) continue;
      if (seen.has(r.addition_id)) continue;
      ordered.push(r); seen.add(r.addition_id);
      for (const c of childrenByParent.get(r.addition_id) || []) {
        if (!seen.has(c.addition_id)) { ordered.push(c); seen.add(c.addition_id); }
      }
    }
    for (const r of xs) if (!seen.has(r.addition_id)) ordered.push(r);
    return ordered;
  }, [rows, activeBlock, ledgerFilter, search, showMerged]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  useEffect(() => { if (page > totalPages) setPage(1); }, [totalPages, page]);
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize);

  const parentCandidates = useMemo(() => {
    if (!activeBlock) return [];
    return rows.filter(r => r.source !== "discount_credit"
                            && r.block_label === activeBlock
                            && !r.parent_addition_id);
  }, [rows, activeBlock]);

  const rowsById = useMemo(() => {
    const m = new Map();
    for (const r of rows) m.set(r.addition_id, r);
    return m;
  }, [rows]);

  // ---------------- Bulk actions ----------------
  const toggleSelect = (id, checked) => {
    setSelectedIds(prev => {
      const n = new Set(prev);
      if (checked) n.add(id); else n.delete(id);
      return n;
    });
  };
  const clearSelection = () => setSelectedIds(new Set());
  const toggleBulkMode = () => {
    setBulkMode(v => {
      if (v) clearSelection();
      return !v;
    });
  };

  const bulkPatch = async (patch) => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/additions/bulk-patch`,
                                       { addition_ids: ids, patch });
      toast.success(`Updated ${data.updated} row${data.updated === 1 ? "" : "s"}`);
      clearSelection();
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk update failed");
    }
  };
  const bulkSetBlock      = (bl)  => bulkPatch({ block_label: bl });
  const bulkMarkReviewed  = ()    => bulkPatch({ reviewed: true });
  const bulkCopyPTU       = ()    => bulkPatch({ __copy_ptu_from_acc: true });

  // Toolbar "Fill PTU" applies to the entire active block (every row that
  // currently has no PTU date) — quick mass-action without entering bulk mode.
  const blockBulkCopyPTU = async () => {
    const ids = filtered
      .filter(r => !r.parent_addition_id && r.source !== "discount_credit"
                   && !(r.put_to_use_date || "").trim()
                   && (r.accounting_date || "").trim())
      .map(r => r.addition_id);
    if (!ids.length) {
      toast.info("Every row in this view already has a PTU date.");
      return;
    }
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/additions/bulk-patch`,
                                       { addition_ids: ids, patch: { __copy_ptu_from_acc: true } });
      toast.success(`Filled PTU for ${data.updated} row${data.updated === 1 ? "" : "s"}`);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Fill PTU failed");
    }
  };

  // ---------------- Excel Round-trip ----------------
  const exportXlsx = async () => {
    setExporting(true);
    try {
      const res = await http.get(`/fixed-assets/runs/${rid}/additions/export.xlsx`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      const cd = res.headers["content-disposition"] || "";
      const m = /filename="?([^";]+)"?/i.exec(cd);
      a.href = url;
      a.download = m?.[1] || "Additions.xlsx";
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Export failed");
    } finally { setExporting(false); }
  };

  const importDryRun = async (f) => {
    setImporting(true);
    setImportFile(f);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const { data } = await http.post(
        `/fixed-assets/runs/${rid}/additions/import.xlsx?dry_run=true`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setImportPreview({ ...data, filename: f.name });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not parse Excel");
    } finally { setImporting(false); }
  };

  const importApply = async () => {
    if (!importFile) return;
    setImporting(true);
    const fd = new FormData();
    fd.append("file", importFile);
    try {
      const { data } = await http.post(
        `/fixed-assets/runs/${rid}/additions/import.xlsx?dry_run=false`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      const msg = `${data.applied} row${data.applied === 1 ? "" : "s"} updated`
        + (data.drift?.drifted ? " · drift warning persisted" : "");
      toast.success(msg);
      setImportPreview(null);
      setImportFile(null);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Apply failed");
    } finally { setImporting(false); }
  };

  const clearDrift = async () => {
    setClearingDrift(true);
    try {
      await http.post(`/fixed-assets/runs/${rid}/clear-excel-drift`);
      setDriftWarning(null);
      toast.success("Drift warning cleared");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not clear");
    } finally { setClearingDrift(false); }
  };

  // ---------------- Layout ----------------
  // Total visible columns = 1 (Acc Date) + 1 (Description) + 1 (Invoice Cost)
  // + visible adjustments + 1 (Total) + 1 (IT Block) + visible right columns
  // + (bulk checkbox if bulkMode)
  const visibleCols = useMemo(() => {
    let n = 4; // Acc Date, Description, Invoice Cost, Total, IT Block
    n += 1; // IT Block
    if (colVis.ptu_date) n += 1;
    if (colVis.other_expenses) n += 1;
    if (colVis.itc_reversed) n += 1;
    if (colVis.interest_capitalized) n += 1;
    if (colVis.forex_fluctuations) n += 1;
    if (colVis.discount_credits) n += 1;
    if (colVis.supplier) n += 1;
    if (colVis.voucher_no) n += 1;
    if (colVis.invoice_no) n += 1;
    if (colVis.invoice_date) n += 1;
    if (bulkMode) n += 1;
    return n;
  }, [colVis, bulkMode]);

  const filteredTotal = useMemo(() => filtered.reduce((s, a) => s + capitalised(a), 0), [filtered]);

  return (
    <div className="space-y-3">
      <DriftBanner warning={driftWarning} onClear={clearDrift} clearing={clearingDrift}/>

      <InvoiceUploadDropZone
        rid={rid}
        busy={ocrBusy}
        setBusy={setOcrBusy}
        onPreview={setOcrPreview}
      />

      <ProgressStrip
        progress={progress}
        active={activeBlock}
        onPick={(bl) => { setActiveBlock(bl); setPage(1); }}
      />

      <AdditionsToolbar
        activeBlock={activeBlock}
        blockChoices={blockChoices}
        onPickBlock={(bl) => { setActiveBlock(bl); setPage(1); }}
        ledgerFilter={ledgerFilter}
        ledgerChoices={ledgerChoices}
        onPickLedger={(v) => { setLedgerFilter(v); setPage(1); }}
        search={search}
        onSearch={(v) => { setSearch(v); setPage(1); }}
        showMerged={showMerged}
        onShowMerged={setShowMerged}
        page={page}
        totalPages={totalPages}
        pageSize={pageSize}
        onPageSize={setPageSize}
        onPage={setPage}
        filteredCount={filtered.length}
        filteredTotal={filteredTotal}
        bulkMode={bulkMode}
        onToggleBulk={toggleBulkMode}
        onBulkCopyPTUFromAcc={blockBulkCopyPTU}
        onExportExcel={exportXlsx}
        onImportExcel={importDryRun}
        importing={importing}
        exporting={exporting}
        colVis={colVis}
        onColVis={setColVis}
        busy={busy}
      />

      {/* Table */}
      <div className="bg-white border border-[#E5E5E0] overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left bg-[#F9F9F8] text-[9.5px] font-mono uppercase tracking-wider text-slate-600">
              {bulkMode && <th className="px-1.5 py-2 w-[24px]"/>}
              <th className="px-2 py-2 w-[105px]">Acc Date</th>
              {colVis.ptu_date && <th className="px-2 py-2 w-[110px]">PTU Date</th>}
              <th className="px-2 py-2 min-w-[210px]">Description of Asset</th>
              <th className="px-2 py-2 text-right w-[95px]">Invoice Cost</th>
              {colVis.other_expenses       && <th className="px-1 py-2 text-right w-[78px]">Other Exp</th>}
              {colVis.itc_reversed         && <th className="px-1 py-2 text-right w-[78px]">ITC Reversed</th>}
              {colVis.interest_capitalized && <th className="px-1 py-2 text-right w-[78px]">Interest Cap</th>}
              {colVis.forex_fluctuations   && <th className="px-1 py-2 text-right w-[68px]">Forex</th>}
              {colVis.discount_credits     && <th className="px-1 py-2 text-right w-[80px]">Discounts</th>}
              <th className="px-2 py-2 text-right w-[100px]">Total</th>
              <th className="px-2 py-2 w-[150px]">IT Block</th>
              {colVis.supplier     && <th className="px-2 py-2 w-[140px]">Supplier</th>}
              {colVis.voucher_no   && <th className="px-2 py-2 w-[80px]">Voucher No</th>}
              {colVis.invoice_no   && <th className="px-2 py-2 w-[90px]">Invoice No</th>}
              {colVis.invoice_date && <th className="px-2 py-2 w-[100px]">Inv Date</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EDEDE7]">
            {paged.length === 0 ? (
              <tr><td colSpan={visibleCols} className="px-4 py-10 text-center text-slate-500 text-[12px]">
                No additions in this block match the filter.
              </td></tr>
            ) : paged.map(a => (
              a.parent_addition_id ? (
                <MergedRow key={a.addition_id} a={a}
                           parent={rowsById.get(a.parent_addition_id)}
                           onUnlink={() => unlink(a)}
                           totalCols={visibleCols}/>
              ) : (
                <AdditionRow key={a.addition_id} a={a} blocks={blocks}
                             colVis={colVis}
                             bulkMode={bulkMode}
                             selected={selectedIds.has(a.addition_id)}
                             attachment={attachments[a.addition_id]}
                             onAttachmentChanged={refresh}
                             rid={rid}
                             onToggleSelect={toggleSelect}
                             onPatch={(p) => patchRow(a, p)}
                             onOpenLink={() => setLinkFor(a)}/>
              )
            ))}
          </tbody>
        </table>
      </div>

      {/* Bottom pager */}
      <div className="flex items-center justify-end gap-2">
        <span className="text-[11px] text-slate-500">Page {page} of {totalPages}</span>
        <Pager page={page} totalPages={totalPages} onPage={setPage}/>
      </div>

      <BulkActionBar
        count={selectedIds.size}
        blocks={blocks}
        onSetBlock={bulkSetBlock}
        onMarkReviewed={bulkMarkReviewed}
        onCopyPTUFromAcc={bulkCopyPTU}
        onClear={clearSelection}
        busy={busy}
      />

      {linkFor && (
        <MergeModal child={linkFor} candidates={parentCandidates}
                    onClose={closeLink} onApply={(p) => applyLink(linkFor, p)}/>
      )}

      {importPreview && (
        <ExcelImportPreviewModal
          preview={importPreview}
          applying={importing}
          onClose={() => { setImportPreview(null); setImportFile(null); }}
          onApply={importApply}
        />
      )}

      {ocrPreview && (
        <InvoiceUploadPreviewModal
          rid={rid}
          preview={ocrPreview}
          additions={rows}
          applying={ocrApplying}
          onClose={() => setOcrPreview(null)}
          onApplied={async () => {
            setOcrApplying(true);
            try { await refresh(); } finally { setOcrApplying(false); setOcrPreview(null); }
          }}
        />
      )}
    </div>
  );
}
