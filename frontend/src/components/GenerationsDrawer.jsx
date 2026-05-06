/**
 * Release 4.5 — Generation History Drawer (shared across all 6 modules).
 *
 * Calls `GET {endpoint}/{rid}/generations` (or `/sessions/{sid}/generations`
 * for msme43bh) and renders the append-only generation log — the audit trail
 * of every Generate / Compute / Send action on this working document.
 *
 * Usage:
 *   <GenerationsDrawer
 *     open={showHistory}
 *     onClose={() => setShowHistory(false)}
 *     endpoint={`/balance-confirmation/runs/${rid}`}
 *     moduleLabel="Balance Confirmation"
 *   />
 */
import React, { useEffect, useState } from "react";
import { http } from "@/lib/api";
import { History, X, Loader2 } from "lucide-react";

const formatDate = (iso) => (iso || "").slice(0, 19).replace("T", " ");

const summaryLines = (snap, module) => {
  if (!snap) return [];
  const out = [];
  if (module === "clause44") {
    if (snap.col_2_total != null) out.push(["Col 2", snap.col_2_total]);
    if (snap.col_6_total != null) out.push(["Col 6", snap.col_6_total]);
    if (snap.col_8_total != null) out.push(["Col 8", snap.col_8_total]);
  } else if (module === "msme43bh") {
    if (snap.final_disallowance != null) out.push(["Final Disallowance", snap.final_disallowance]);
    if (snap.bill_count != null) out.push(["Bills", snap.bill_count]);
    if (snap.disallowed_count != null) out.push(["Disallowed", snap.disallowed_count]);
  } else if (module === "balance_confirmation") {
    if (snap.sent != null) out.push(["Sent", snap.sent]);
    if (snap.failed != null) out.push(["Failed", snap.failed]);
    if (snap.skipped != null) out.push(["Skipped", snap.skipped]);
    if (snap.kind) out.push(["Kind", snap.kind]);
  } else if (module === "fixed_assets") {
    if (snap.row_count != null) out.push(["Rows", snap.row_count]);
    const t = snap.totals || {};
    if (t.opening != null) out.push(["Opening", t.opening]);
    if (t.depreciation != null) out.push(["Depreciation", t.depreciation]);
  } else if (module === "fin_statement") {
    if (snap.note_count != null) out.push(["Notes", snap.note_count]);
    if (snap.detail_count != null) out.push(["Details", snap.detail_count]);
  } else if (module === "gst_recon") {
    const s = snap.summary || {};
    if (s.total_books != null) out.push(["Books", s.total_books]);
    if (s.total_portal != null) out.push(["Portal", s.total_portal]);
  }
  return out;
};

const fmt = (v) => {
  if (v == null) return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return String(v);
};

export default function GenerationsDrawer({
  open,
  onClose,
  endpoint,        // e.g. "/balance-confirmation/runs/<rid>" or "/msme/sessions/<sid>"
  moduleLabel,
  module,          // backend module key: clause44 | balance_confirmation | ...
}) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!open || !endpoint) return;
    let cancelled = false;
    setLoading(true);
    http.get(`${endpoint}/generations`)
      .then(({ data }) => { if (!cancelled) setRows(data?.generations || []); })
      .catch(() => { if (!cancelled) setRows([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, endpoint]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        data-testid="generations-drawer-backdrop"
      />
      <div
        className="fixed top-0 right-0 h-screen w-[min(95vw,720px)] bg-white shadow-2xl z-50 flex flex-col"
        data-testid="generations-drawer"
      >
        <div className="p-5 border-b border-gray-200 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500 inline-flex items-center gap-1.5">
              <History size={11}/> Generation History
            </div>
            <h2 className="text-lg font-semibold mt-1">{moduleLabel}</h2>
            <div className="text-xs text-gray-500 mt-0.5">
              Append-only audit trail of every Generate/Compute action on this working document.
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 p-1.5 hover:bg-gray-100 rounded-sm"
            data-testid="generations-drawer-close"
          >
            <X size={16}/>
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-10 text-center text-sm text-gray-500 inline-flex items-center gap-2 justify-center w-full">
              <Loader2 size={14} className="animate-spin"/> Loading history…
            </div>
          ) : rows.length === 0 ? (
            <div className="p-10 text-center" data-testid="generations-empty">
              <div className="text-3xl mb-3">📜</div>
              <div className="text-sm text-gray-600 font-medium">No generations yet</div>
              <div className="text-xs text-gray-500 mt-1">
                Each time you Generate / Compute the report, a row will land here.
              </div>
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {rows.map((g) => {
                const lines = summaryLines(g.summary_snapshot || {}, module);
                return (
                  <li
                    key={g.gen_id}
                    className="p-4 hover:bg-gray-50"
                    data-testid={`generation-row-${g.gen_id}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-mono text-[12px] text-gray-700">
                          {formatDate(g.generated_at)}
                        </div>
                        <div className="text-[11px] text-gray-500 font-mono mt-0.5">
                          {g.generated_by_email || "—"}
                          {g.synthesised && (
                            <span className="ml-2 px-1.5 py-0.5 bg-amber-50 text-amber-800 border border-amber-200 rounded-sm text-[10px]">
                              migration
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-[10px] font-mono text-gray-400">
                        {g.gen_id?.split("_").pop()}
                      </div>
                    </div>
                    {lines.length > 0 && (
                      <div className="mt-2 grid grid-cols-3 gap-2">
                        {lines.map(([k, v]) => (
                          <div
                            key={k}
                            className="bg-gray-50 px-2.5 py-1.5 border border-gray-200 rounded-sm"
                          >
                            <div className="text-[9px] uppercase tracking-wider text-gray-500 font-mono">{k}</div>
                            <div className="text-[12px] font-mono text-gray-900">{fmt(v)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
