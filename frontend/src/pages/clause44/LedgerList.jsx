/**
 * Shared ledger picker — used by the ITC step and the Exclusion step of
 * the Clause 44 stepper.  Kept visually identical to the legacy
 * StepMapping pane so the transition feels like a polish, not a rewrite.
 */
import { useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { formatINR } from "@/lib/format";
import { MagnifyingGlass, Sparkle } from "@phosphor-icons/react";

export default function LedgerList({
  items, selected, onToggle, onSelectAll, onClear,
  query, setQuery, emptyHint, testidPrefix,
  suggestedLabel = "suggested",
  showSubhead = false,
}) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) =>
      (it.name || "").toLowerCase().includes(q) ||
      (it.groupParent || "").toLowerCase().includes(q) ||
      (it.subhead || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  return (
    <div className="border border-[#E5E5E0] rounded-sm bg-white" data-testid={`${testidPrefix}-panel`}>
      <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3">
        <MagnifyingGlass size={14} className="text-[#8A8A83]"/>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ledger, subhead or group…"
          className="h-8 border-0 shadow-none focus-visible:ring-0 px-0 text-sm"
          data-testid={`${testidPrefix}-search`}
        />
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
        ) : (
          <ul>
            {filtered.map((it) => {
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
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium truncate">{it.name}</span>
                        {it.suggested && (
                          <Badge className="bg-amber-50 text-amber-900 border border-amber-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">
                            <Sparkle size={10} weight="fill" className="mr-1"/> {suggestedLabel}
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
            })}
          </ul>
        )}
      </div>
      <div className="px-4 py-2 border-t border-[#E5E5E0] flex items-center justify-between text-[11px] font-mono uppercase tracking-[0.12em] text-[#8A8A83]">
        <span>{filtered.length} of {items.length} ledgers</span>
        <span>{selected.size} selected</span>
      </div>
    </div>
  );
}
