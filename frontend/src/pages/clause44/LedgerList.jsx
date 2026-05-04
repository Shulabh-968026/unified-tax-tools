/**
 * Shared ledger picker — used by the ITC step and the Exclusion step of
 * the Clause 44 stepper.  Kept visually identical to the legacy
 * StepMapping pane so the transition feels like a polish, not a rewrite.
 *
 * Release 3.2 additions (Option D — manual override UI):
 *   • Provenance chip per row (`kind_source`: name / group / subhead /
 *     usage) so the auditor sees *why* the engine pre-ticked it.
 *   • Voucher-usage chip ("fires on N purchase vouchers · 0 sales") —
 *     gives auditor evidence-based confidence on bespoke ledger names.
 *   • "Used in vouchers only" filter — hides dormant ledgers that bloat
 *     the picker on large datasets (often >50% of the BS pool).
 *   • Group-level bulk select — clicking the group label ticks/un-ticks
 *     every ledger under that parent group in one shot.
 */
import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { formatINR } from "@/lib/format";
import { MagnifyingGlass, Sparkle } from "@phosphor-icons/react";

const SOURCE_LABEL = {
  name: "name match",
  group: "group match",
  subhead: "subhead match",
  usage: "voucher usage",
};

export default function LedgerList({
  items, selected, onToggle, onSelectAll, onClear,
  query, setQuery, emptyHint, testidPrefix,
  suggestedLabel = "suggested",
  showSubhead = false,
  // Release 3.2 — option D enrichments (only used by the ITC tab; safe
  // defaults keep the Exempt tab unchanged).
  showUsageControls = false,
  showGroupBulk = false,
  setSelected = null,  // required for group-bulk action
}) {
  const [usedOnly, setUsedOnly] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (q) {
        const hay = `${it.name || ""} ${it.groupParent || ""} ${it.subhead || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (usedOnly && (it.n_voucher == null || it.n_voucher === 0)) return false;
      return true;
    });
  }, [items, query, usedOnly]);

  // Group filtered rows by parentGroup for the optional group-bulk UI.
  const grouped = useMemo(() => {
    if (!showGroupBulk) return null;
    const m = new Map();
    filtered.forEach((it) => {
      const k = it.groupParent || "—";
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(it);
    });
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered, showGroupBulk]);

  const toggleGroup = (rows) => {
    if (!setSelected) return;
    const allSelected = rows.every((r) => selected.has(r.name));
    const next = new Set(selected);
    rows.forEach((r) => allSelected ? next.delete(r.name) : next.add(r.name));
    setSelected(next);
  };

  const renderRow = (it) => {
    const isSel = selected.has(it.name);
    return (
      <li key={it.name} className="border-b border-[#E5E5E0] last:border-b-0">
        <label className="flex items-start gap-3 px-4 py-2.5 cursor-pointer hover:bg-[#F9F9F8]" data-testid={`${testidPrefix}-row-${encodeURIComponent(it.name)}`}>
          <Checkbox
            checked={isSel}
            onCheckedChange={() => onToggle(it.name)}
            className="mt-0.5"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[13px] font-medium truncate">{it.name}</span>
              {it.suggested && (
                <Badge className="bg-amber-50 text-amber-900 border border-amber-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">
                  <Sparkle size={10} weight="fill" className="mr-1"/> {suggestedLabel}
                </Badge>
              )}
              {it.kind === "input" && (
                <Badge className="bg-emerald-50 text-emerald-900 border border-emerald-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono" data-testid={`itc-kind-input-${encodeURIComponent(it.name)}`}>
                  INPUT
                </Badge>
              )}
              {it.kind === "output" && (
                <Badge className="bg-rose-50 text-rose-900 border border-rose-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono" data-testid={`itc-kind-output-${encodeURIComponent(it.name)}`}>
                  OUTPUT · sales-side
                </Badge>
              )}
              {/* Provenance chip — explains WHY the engine flagged this row. */}
              {it.kind_source && SOURCE_LABEL[it.kind_source] && (
                <Badge
                  className="bg-slate-50 text-slate-700 border border-slate-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono"
                  title={`Detected via ${SOURCE_LABEL[it.kind_source]}`}
                  data-testid={`itc-source-${it.kind_source}-${encodeURIComponent(it.name)}`}
                >
                  via {SOURCE_LABEL[it.kind_source]}
                </Badge>
              )}
              {/* Usage telemetry chip. */}
              {showUsageControls && it.n_voucher != null && it.n_voucher > 0 && (
                <Badge
                  className="bg-sky-50 text-sky-900 border border-sky-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono"
                  data-testid={`itc-usage-${encodeURIComponent(it.name)}`}
                >
                  {it.n_purchase || 0} purchase · {it.n_sales || 0} sales
                </Badge>
              )}
              {showUsageControls && it.n_voucher === 0 && (
                <Badge className="bg-[#F3F4F1] text-[#8A8A83] border border-[#E5E5E0] rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">
                  unused
                </Badge>
              )}
              {/* Conflict advisory: name says 'input' but vouchers say sales-only. */}
              {showUsageControls && it.usage_conflict && (
                <Badge className="bg-amber-50 text-amber-900 border border-amber-300 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono" title="Name says INPUT but ledger fired only on sales vouchers">
                  ⚠ name vs usage
                </Badge>
              )}
              {isSel && it.kind === "output" && (
                <Badge className="bg-rose-700 text-white rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono" data-testid={`itc-kind-output-warn-${encodeURIComponent(it.name)}`}>
                  ⚠ may misclassify Col 5
                </Badge>
              )}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-[#8A8A83] mt-0.5">
              {showSubhead && it.subhead ? `${it.subhead} · ` : ""}{it.groupParent || "—"}{it.closingBalance != null ? ` · bal ${formatINR(it.closingBalance)}` : ""}
            </div>
          </div>
        </label>
      </li>
    );
  };

  return (
    <div className="border border-[#E5E5E0] rounded-sm bg-white" data-testid={`${testidPrefix}-panel`}>
      <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
        <MagnifyingGlass size={14} className="text-[#8A8A83]"/>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ledger, subhead or group…"
          className="h-8 border-0 shadow-none focus-visible:ring-0 px-0 text-sm flex-1 min-w-[160px]"
          data-testid={`${testidPrefix}-search`}
        />
        {showUsageControls && (
          <button
            onClick={() => setUsedOnly((v) => !v)}
            data-testid={`${testidPrefix}-used-only-toggle`}
            className={`px-2 py-1 rounded-sm border font-mono text-[10px] uppercase tracking-[0.12em] ${
              usedOnly
                ? "bg-[#0F172A] text-white border-[#0F172A]"
                : "bg-white text-[#52524E] border-[#E5E5E0] hover:bg-[#F3F4F1]"
            }`}
            title="Hide ledgers that never appeared in any voucher"
          >
            Used in vouchers only
          </button>
        )}
        <button onClick={onSelectAll} className="font-mono text-[10px] uppercase tracking-[0.12em] text-[#52524E] hover:text-[#0F172A]" data-testid={`${testidPrefix}-select-suggested`}>
          Select Suggested
        </button>
        <span className="text-[#D4D4D0]">·</span>
        <button onClick={onClear} className="font-mono text-[10px] uppercase tracking-[0.12em] text-[#52524E] hover:text-[#991B1B]" data-testid={`${testidPrefix}-clear`}>
          Clear
        </button>
      </div>
      <div className="max-h-[56vh] overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#8A8A83]">{emptyHint}</div>
        ) : showGroupBulk && grouped ? (
          <ul>
            {grouped.map(([gname, rows]) => {
              const allSel = rows.every((r) => selected.has(r.name));
              const partSel = !allSel && rows.some((r) => selected.has(r.name));
              return (
                <li key={gname}>
                  <div
                    className="px-4 py-1.5 bg-[#FAFAF7] border-b border-[#E5E5E0] flex items-center gap-3 sticky top-0 z-[1]"
                    data-testid={`${testidPrefix}-group-header-${encodeURIComponent(gname)}`}
                  >
                    <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] flex-1 truncate">
                      {gname} <span className="text-[#8A8A83] normal-case">· {rows.length} ledger{rows.length === 1 ? "" : "s"}</span>
                    </span>
                    <button
                      onClick={() => toggleGroup(rows)}
                      data-testid={`${testidPrefix}-group-toggle-${encodeURIComponent(gname)}`}
                      className={`px-2 py-0.5 rounded-sm border font-mono text-[10px] uppercase tracking-[0.12em] ${
                        allSel
                          ? "bg-[#0F172A] text-white border-[#0F172A]"
                          : partSel
                            ? "bg-amber-100 text-amber-900 border-amber-300"
                            : "bg-white text-[#52524E] border-[#E5E5E0] hover:bg-[#F3F4F1]"
                      }`}
                    >
                      {allSel ? "Untick all" : "Tick all"}
                    </button>
                  </div>
                  <ul>{rows.map(renderRow)}</ul>
                </li>
              );
            })}
          </ul>
        ) : (
          <ul>{filtered.map(renderRow)}</ul>
        )}
      </div>
      <div className="px-4 py-2 border-t border-[#E5E5E0] flex items-center justify-between text-[11px] font-mono uppercase tracking-[0.12em] text-[#8A8A83]">
        <span>{filtered.length} of {items.length} ledgers</span>
        <span>{selected.size} selected</span>
      </div>
    </div>
  );
}
