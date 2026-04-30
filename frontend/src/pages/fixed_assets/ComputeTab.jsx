/* eslint-disable react-hooks/exhaustive-deps */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Loader2, Calculator, Download, Sparkles, FileUp, RotateCw, X, Check, AlertCircle,
} from "lucide-react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import { DriftBanner } from "./additions/ExcelRoundTripModal";

const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "–";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

const SOURCE_META = {
  manual:     { label: "Manual",      cls: "bg-slate-100 text-slate-700 border-slate-200" },
  prior_3cd:  { label: "Prior 3CD",   cls: "bg-amber-50 text-amber-800 border-amber-200" },
  prior_run:  { label: "Rolled fwd",  cls: "bg-emerald-50 text-emerald-800 border-emerald-200" },
};

export default function ComputeTab({ rid }) {
  const [openings, setOpenings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [computing, setComputing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState(null);

  // Phase 1D — Prior 3CD Import
  const priorFileRef = useRef(null);
  const [priorUploading, setPriorUploading] = useState(false);
  const [priorModal, setPriorModal] = useState(null); // {filename, rows: [{rate, closing_wdv, suggested_block_label, candidate_block_labels, needs_review, desc_block_assets}]}

  // Phase 1H — Roll forward preview
  const [rollSource, setRollSource] = useState(null); // {ok, src_fy, src_name, src_run_id, items}
  const [rollApplying, setRollApplying] = useState(false);
  const [rollModalOpen, setRollModalOpen] = useState(false);

  // Drift banner (carried over from Excel re-import on Additions tab)
  const [driftWarning, setDriftWarning] = useState(null);
  const [clearingDrift, setClearingDrift] = useState(false);

  const refreshRun = useCallback(async () => {
    if (!rid) return;
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}`);
      setDriftWarning(data?.excel_drift_warning || null);
    } catch { /* swallow */ }
  }, [rid]);

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

  const refreshOpening = useCallback(async () => {
    if (!rid) return;
    setBusy(true);
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/block-opening`);
      setOpenings(data?.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load opening WDV");
    } finally { setBusy(false); }
  }, [rid]);

  const refreshRollSource = useCallback(async () => {
    if (!rid) return;
    try {
      const { data } = await http.get(`/fixed-assets/runs/${rid}/roll-forward-source`);
      setRollSource(data || null);
    } catch {
      setRollSource(null);
    }
  }, [rid]);

  useEffect(() => { refreshOpening(); refreshRollSource(); refreshRun(); }, [refreshOpening, refreshRollSource, refreshRun]);

  const saveOpening = async (block_label, opening_wdv, description) => {
    setOpenings(rs => rs.map(r => r.block_label === block_label
      ? { ...r, opening_wdv: parseFloat(opening_wdv || 0), description: description ?? r.description, source: "manual" }
      : r));
    try {
      await http.post(`/fixed-assets/runs/${rid}/block-opening`, {
        block_label,
        opening_wdv: parseFloat(opening_wdv || 0),
        description: description || "",
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
      refreshOpening();
    }
  };

  // ---------- Prior 3CD upload ----------
  const on3CDPick = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    e.target.value = "";
    setPriorUploading(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/ingest-prior-3cd`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPriorModal({ filename: f.name, rows: data?.rows || [] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not parse 3CD JSON");
    } finally { setPriorUploading(false); }
  };

  const apply3CD = async (items) => {
    const payload = {
      items: items
        .filter(r => r.block_label && Number(r.opening_wdv) >= 0)
        .map(r => ({ rate: Number(r.rate || 0), block_label: r.block_label, opening_wdv: Number(r.opening_wdv || 0) })),
    };
    if (!payload.items.length) {
      toast.error("Pick a block for at least one row before applying.");
      return;
    }
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/apply-prior-3cd`, payload);
      toast.success(`Opening WDV applied for ${data.applied} block${data.applied === 1 ? "" : "s"}`);
      setPriorModal(null);
      refreshOpening();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Apply failed");
    }
  };

  // ---------- Roll forward ----------
  const applyRollForward = async () => {
    setRollApplying(true);
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/roll-forward`);
      toast.success(`Rolled forward ${data.applied} block${data.applied === 1 ? "" : "s"} from FY ${data.src_fy}`);
      setRollModalOpen(false);
      refreshOpening();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Roll-forward failed");
    } finally { setRollApplying(false); }
  };

  const compute = async () => {
    setComputing(true); setResult(null);
    try {
      const { data } = await http.post(`/fixed-assets/runs/${rid}/compute`);
      setResult(data);
      toast.success(`Depreciation ₹ ${inr(data.totals.depreciation)}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Compute failed");
    } finally { setComputing(false); }
  };

  const download = async () => {
    setDownloading(true);
    try {
      const res = await http.get(`/fixed-assets/runs/${rid}/export.xlsx`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      const cd = res.headers["content-disposition"] || "";
      const m = /filename="?([^";]+)"?/i.exec(cd);
      a.href = url;
      a.download = m?.[1] || `IT_Depreciation.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Download failed");
    } finally { setDownloading(false); }
  };

  const totalOpening = useMemo(() => openings.reduce((s, r) => s + Number(r.opening_wdv || 0), 0), [openings]);
  const rollAvailable = rollSource?.ok && (rollSource.items || []).length > 0;

  return (
    <div className="space-y-5">
      <DriftBanner warning={driftWarning} onClear={clearDrift} clearing={clearingDrift}/>

      {/* Opening WDV import toolbar (Phase 1D + 1H) */}
      <div className="bg-[#FAFAF7] border border-[#E5E5E0] p-3 flex flex-wrap items-center gap-2">
        <div className="flex-1 min-w-[220px] text-[12px] text-[#52524E]">
          <span className="font-semibold text-slate-800">Import Opening WDV</span>
          <span className="ml-2 text-slate-500">
            Start from prior year's 3CD or roll forward last year's closing WDV.
          </span>
        </div>
        <input
          ref={priorFileRef}
          type="file"
          accept=".json,application/json"
          onChange={on3CDPick}
          className="hidden"
          data-testid="fa-3cd-file-input"
        />
        <button
          data-testid="fa-3cd-import-btn"
          onClick={() => priorFileRef.current?.click()}
          disabled={priorUploading}
          className="inline-flex items-center gap-2 px-3 py-1.5 border border-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-900 text-[12.5px] disabled:opacity-60"
        >
          {priorUploading ? <Loader2 size={13} className="animate-spin"/> : <FileUp size={13}/>}
          Import from Prior 3CD
        </button>
        <button
          data-testid="fa-roll-forward-btn"
          onClick={() => rollAvailable && setRollModalOpen(true)}
          disabled={!rollAvailable}
          title={rollAvailable
            ? `Roll forward closing WDV from FY ${rollSource.src_fy}`
            : "No prior FY run found for this client"}
          className="inline-flex items-center gap-2 px-3 py-1.5 border border-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-900 text-[12.5px] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <RotateCw size={13}/>
          {rollAvailable ? `Roll forward from FY ${rollSource.src_fy}` : "Roll forward (no prior FY)"}
        </button>
      </div>

      {/* Opening WDV table */}
      <div className="bg-white border border-[#E5E5E0]">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#EDEDE7]">
          <div className="flex items-center gap-2">
            <Sparkles size={15} className="text-amber-600"/>
            <h2 className="font-heading text-base">Opening WDV by Block</h2>
            <span className="font-mono text-[11px] text-slate-500">Total ₹ {inr(totalOpening)}</span>
          </div>
          {busy && <Loader2 size={13} className="animate-spin text-slate-500"/>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                <th className="px-4 py-2">Block</th>
                <th className="px-3 py-2 text-center">Rate</th>
                <th className="px-3 py-2 text-right w-[180px]">Opening WDV (₹)</th>
                <th className="px-3 py-2 w-[120px]">Source</th>
                <th className="px-3 py-2">Note (optional)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EDEDE7]">
              {openings.map(b => <OpeningRow key={b.block_label} row={b} onSave={saveOpening}/>)}
            </tbody>
          </table>
        </div>
      </div>

      {/* Compute & download */}
      <div className="bg-white border border-[#E5E5E0] p-4 flex items-center justify-between gap-3">
        <div>
          <div className="font-heading text-base">Run Computation</div>
          <p className="text-[12px] text-[#52524E] mt-0.5 max-w-3xl">
            Aggregates Opening WDV + every confirmed addition (with adjustment columns) − every credit marked
            as Sale, applies the 180-day half-rate rule, and produces the IT Depreciation Schedule.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="fa-compute-btn"
            onClick={compute}
            disabled={computing}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-slate-900 text-white text-[13px] hover:bg-slate-800 disabled:opacity-60"
          >
            {computing ? <Loader2 size={14} className="animate-spin"/> : <Calculator size={14}/>}
            Compute
          </button>
          <button
            data-testid="fa-export-btn"
            onClick={download}
            disabled={downloading}
            className="inline-flex items-center gap-2 px-3.5 py-2 border border-slate-300 hover:bg-slate-100 text-[13px] disabled:opacity-60"
          >
            {downloading ? <Loader2 size={14} className="animate-spin"/> : <Download size={14}/>}
            Download Excel
          </button>
        </div>
      </div>

      {/* Result table */}
      {result && (
        <div className="bg-white border border-[#E5E5E0]">
          <div className="px-4 py-3 border-b border-[#EDEDE7]">
            <h2 className="font-heading text-base">Depreciation Schedule</h2>
            <div className="text-[11.5px] text-slate-500 mt-0.5">
              {result.rows.length} blocks active · Depreciation ₹ {inr(result.totals.depreciation)} · Closing WDV ₹ {inr(result.totals.closing_wdv)}
              {result.totals.stcg_sec50 > 0 && <> · STCG u/s 50: ₹ {inr(result.totals.stcg_sec50)}</>}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
                  <th className="px-3 py-2">Block</th>
                  <th className="px-3 py-2 text-center">Rate</th>
                  <th className="px-3 py-2 text-right">Opening WDV</th>
                  <th className="px-3 py-2 text-right">Adds ≥ 180d</th>
                  <th className="px-3 py-2 text-right">Adds &lt; 180d</th>
                  <th className="px-3 py-2 text-right">Sales</th>
                  <th className="px-3 py-2 text-right">Total</th>
                  <th className="px-3 py-2 text-right">Depn</th>
                  <th className="px-3 py-2 text-right">STCG u/s 50</th>
                  <th className="px-3 py-2 text-right">Closing WDV</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EDEDE7]">
                {result.rows.map(r => (
                  <tr key={r.block_label} className={r.block_extinguished ? "bg-rose-50" : ""}>
                    <td className="px-3 py-1.5 font-medium">{r.block_label}</td>
                    <td className="px-3 py-1.5 text-center font-mono">{r.rate}%</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.opening_wdv)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.adds_full)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.adds_half)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.deletions)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{inr(r.total_block)}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(r.depreciation)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{r.stcg_sec50 ? inr(r.stcg_sec50) : "–"}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold">{inr(r.closing_wdv)}</td>
                  </tr>
                ))}
                <tr className="bg-[#F2F2EE] font-semibold">
                  <td className="px-3 py-2" colSpan={2}>TOTAL</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.opening_wdv)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.adds_full)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.adds_half)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.deletions)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.total_block)}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.depreciation)}</td>
                  <td className="px-3 py-2 text-right font-mono">{result.totals.stcg_sec50 ? inr(result.totals.stcg_sec50) : "–"}</td>
                  <td className="px-3 py-2 text-right font-mono">{inr(result.totals.closing_wdv)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modals */}
      {priorModal && (
        <Prior3CDModal
          filename={priorModal.filename}
          rows={priorModal.rows}
          onClose={() => setPriorModal(null)}
          onApply={apply3CD}
        />
      )}
      {rollModalOpen && rollSource?.ok && (
        <RollForwardModal
          source={rollSource}
          applying={rollApplying}
          onClose={() => setRollModalOpen(false)}
          onApply={applyRollForward}
        />
      )}
    </div>
  );
}

function OpeningRow({ row, onSave }) {
  const [v, setV] = useState(row.opening_wdv || 0);
  const [n, setN] = useState(row.description || "");
  useEffect(() => { setV(row.opening_wdv || 0); setN(row.description || ""); }, [row.block_label, row.opening_wdv, row.description]);
  const meta = SOURCE_META[row.source] || SOURCE_META.manual;
  return (
    <tr className="hover:bg-[#FBFBF8]" data-testid={`fa-opening-${row.block_label}`}>
      <td className="px-4 py-1.5 font-medium">{row.block_label}</td>
      <td className="px-3 py-1.5 text-center font-mono">{row.rate}%</td>
      <td className="px-3 py-1.5">
        <input
          type="number"
          step="0.01"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={() => onSave(row.block_label, v, n)}
          className="w-full text-right px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12.5px] font-mono"
        />
      </td>
      <td className="px-3 py-1.5">
        <span
          className={`inline-block text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 border ${meta.cls}`}
          data-testid={`fa-opening-source-${row.block_label}`}
        >
          {meta.label}
        </span>
      </td>
      <td className="px-3 py-1.5">
        <input
          type="text"
          value={n}
          onChange={(e) => setN(e.target.value)}
          onBlur={() => onSave(row.block_label, v, n)}
          placeholder="e.g. carried from FY 2023-24 closing WDV (3CD AY24-25)"
          className="w-full px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12px]"
        />
      </td>
    </tr>
  );
}

/* ==================== Prior 3CD import modal ==================== */
function Prior3CDModal({ filename, rows, onClose, onApply }) {
  // local editable draft of each staged row — auditor can override block
  // and fine-tune the opening WDV before committing.
  const [draft, setDraft] = useState(() => rows.map(r => ({
    rate:                    Number(r.rate || 0),
    desc_block_assets:       r.desc_block_assets || "",
    prior_closing_wdv:       Number(r.closing_wdv || 0),
    prior_opening_wdv:       Number(r.opening_wdv || 0),
    opening_wdv:             Number(r.closing_wdv || 0), // prior closing = current opening
    suggested_block_label:   r.suggested_block_label || "",
    candidate_block_labels:  r.candidate_block_labels || [],
    block_label:             r.suggested_block_label || "",
    needs_review:            !!r.needs_review,
  })));

  const total = draft.reduce((s, r) => s + (r.block_label ? Number(r.opening_wdv || 0) : 0), 0);
  const readyCount = draft.filter(r => r.block_label).length;

  const update = (idx, patch) => setDraft(d => d.map((r, i) => i === idx ? { ...r, ...patch } : r));

  return (
    <ModalShell title="Import Opening WDV from Prior Year 3CD" subtitle={filename} onClose={onClose} maxW="max-w-5xl">
      <div className="px-5 py-3 text-[12.5px] text-[#52524E] bg-amber-50 border-b border-amber-200 flex items-start gap-2">
        <AlertCircle size={14} className="text-amber-700 mt-0.5 shrink-0"/>
        <div>
          Each rate row in the uploaded 3CD maps to one or more IT blocks that share that rate. When the mapping
          isn't unique, pick the correct block from the dropdown. <b>Prior year's Closing WDV becomes current year's Opening WDV.</b>
        </div>
      </div>

      <div className="overflow-x-auto max-h-[55vh]">
        <table className="w-full text-[12.5px]">
          <thead className="sticky top-0">
            <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
              <th className="px-4 py-2 text-center">Rate</th>
              <th className="px-3 py-2">Description (3CD)</th>
              <th className="px-3 py-2 text-right">Prior Closing WDV</th>
              <th className="px-3 py-2 text-right w-[170px]">→ Opening WDV (₹)</th>
              <th className="px-3 py-2 w-[260px]">Target IT Block</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EDEDE7]">
            {draft.map((r, i) => (
              <tr
                key={`${r.rate}-${i}`}
                className={r.needs_review && !r.block_label ? "bg-amber-50/40" : ""}
                data-testid={`fa-3cd-staged-row-${i}`}
              >
                <td className="px-4 py-1.5 text-center font-mono font-semibold">{r.rate}%</td>
                <td className="px-3 py-1.5 text-[12px] text-slate-700 max-w-[260px] truncate" title={r.desc_block_assets}>
                  {r.desc_block_assets || <span className="text-slate-400">—</span>}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">{inr(r.prior_closing_wdv)}</td>
                <td className="px-3 py-1.5">
                  <input
                    type="number"
                    step="0.01"
                    value={r.opening_wdv}
                    onChange={(e) => update(i, { opening_wdv: parseFloat(e.target.value || 0) })}
                    className="w-full text-right px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12.5px] font-mono"
                    data-testid={`fa-3cd-opening-input-${i}`}
                  />
                </td>
                <td className="px-3 py-1.5">
                  {r.candidate_block_labels.length === 0 ? (
                    <span className="text-[11px] text-rose-600">No block at rate {r.rate}%</span>
                  ) : (
                    <select
                      value={r.block_label}
                      onChange={(e) => update(i, { block_label: e.target.value })}
                      className="w-full px-2 py-1 border border-[#E5E5E0] focus:border-slate-700 focus:outline-none text-[12px] bg-white"
                      data-testid={`fa-3cd-block-select-${i}`}
                    >
                      <option value="">— Skip —</option>
                      {r.candidate_block_labels.map(bl => (
                        <option key={bl} value={bl}>
                          {bl}{bl === r.suggested_block_label ? " ★" : ""}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-[#EDEDE7] bg-[#FAFAF7] flex items-center justify-between">
        <div className="text-[12px] text-[#52524E] font-mono">
          {readyCount} of {draft.length} ready · Total Opening WDV ₹ {inr(total)}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 border border-slate-300 hover:bg-slate-100 text-[13px]"
          >
            Cancel
          </button>
          <button
            onClick={() => onApply(draft)}
            disabled={!readyCount}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-amber-700 hover:bg-amber-800 text-white text-[13px] disabled:opacity-50"
            data-testid="fa-3cd-apply-btn"
          >
            <Check size={14}/> Apply to Opening WDV
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

/* ==================== Roll-forward preview modal ==================== */
function RollForwardModal({ source, applying, onClose, onApply }) {
  const items = source.items || [];
  const total = items.reduce((s, r) => s + Number(r.closing_wdv || 0), 0);
  return (
    <ModalShell
      title={`Roll forward from FY ${source.src_fy}`}
      subtitle={source.src_name ? `Source run: ${source.src_name}` : `Source run: ${source.src_run_id}`}
      onClose={onClose}
    >
      <div className="px-5 py-3 text-[12.5px] text-[#52524E] bg-emerald-50 border-b border-emerald-200 flex items-start gap-2">
        <AlertCircle size={14} className="text-emerald-700 mt-0.5 shrink-0"/>
        <div>
          This copies the <b>Closing WDV</b> of each block from the previous year's computed run into this run's
          Opening WDV. Any existing opening values for the listed blocks will be <b>overwritten</b>.
        </div>
      </div>

      <div className="overflow-x-auto max-h-[55vh]">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="text-left bg-[#F9F9F8] text-[10.5px] font-mono uppercase tracking-wider text-slate-600">
              <th className="px-4 py-2">Block</th>
              <th className="px-3 py-2 text-right">Prior Closing WDV (₹)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EDEDE7]">
            {items.length === 0 ? (
              <tr><td colSpan={2} className="px-4 py-4 text-center text-[12.5px] text-slate-500">
                No blocks with positive closing WDV in the prior run.
              </td></tr>
            ) : items.map((r, i) => (
              <tr key={r.block_label} data-testid={`fa-roll-row-${i}`}>
                <td className="px-4 py-1.5 font-medium">{r.block_label}</td>
                <td className="px-3 py-1.5 text-right font-mono">{inr(r.closing_wdv)}</td>
              </tr>
            ))}
            <tr className="bg-[#F2F2EE] font-semibold">
              <td className="px-4 py-2">TOTAL</td>
              <td className="px-3 py-2 text-right font-mono">{inr(total)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-[#EDEDE7] bg-[#FAFAF7] flex items-center justify-end gap-2">
        <button
          onClick={onClose}
          className="px-3.5 py-1.5 border border-slate-300 hover:bg-slate-100 text-[13px]"
        >
          Cancel
        </button>
        <button
          onClick={onApply}
          disabled={applying || items.length === 0}
          className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-emerald-700 hover:bg-emerald-800 text-white text-[13px] disabled:opacity-50"
          data-testid="fa-roll-apply-btn"
        >
          {applying ? <Loader2 size={14} className="animate-spin"/> : <RotateCw size={14}/>}
          Roll forward {items.length} block{items.length === 1 ? "" : "s"}
        </button>
      </div>
    </ModalShell>
  );
}

/* ==================== Shared modal shell ==================== */
function ModalShell({ title, subtitle, children, onClose, maxW = "max-w-3xl" }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-y-auto py-10">
      <div className={`bg-white shadow-xl w-full ${maxW} mx-4 border border-[#E5E5E0]`}>
        <div className="flex items-start justify-between px-5 py-3 border-b border-[#EDEDE7]">
          <div>
            <div className="font-heading text-base">{title}</div>
            {subtitle && <div className="text-[11.5px] text-slate-500 mt-0.5">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="fa-modal-close">
            <X size={18}/>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
