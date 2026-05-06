/**
 * LedgerTable — 6-column virtualised ledger picker for the Clause 44
 * three-pool model (Release 4.4).
 *
 * Replaces `LedgerList` for Exempt Purchases / ITC Ledgers / Exclusions:
 * shows every eligible ledger up-front and lets the auditor filter,
 * sort, and select via per-column inputs.  Pre-ticked rows still come
 * from the same heuristic engine (`suggested=true`), but the auditor is
 * now in full control of who's in the universe.
 *
 * Column model (left → right):
 *   Head · Subhead · Group Parent · Ledger Name · Closing Balance · ☑
 *
 * Features:
 *   • Per-column filter row (text contains; min/max range on Closing
 *     Balance) — sticky under the header.
 *   • Sortable column headers — click to cycle asc / desc / none.
 *   • Column picker — gear icon top-right.  Hidden columns persist in
 *     localStorage per (testidPrefix).
 *   • Virtualised body via react-window — handles 2000+ rows smoothly.
 *   • Header `Suggested · Clear · Selected` toolstrip stays sticky.
 *   • `headerRight` slot for module-specific controls (ITC's "Show all
 *     BS-side" toggle and quick-filter strip live here).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { List } from "react-window";
import {
  CaretDown, CaretUp, FunnelSimple, Gear, MagnifyingGlass,
  Sparkle, X,
} from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatINR } from "@/lib/format";

// ── column registry ─────────────────────────────────────────────────────
const ALL_COLS = [
  { key: "head",            label: "Head",            grow: 14 },
  { key: "subhead",         label: "Subhead",         grow: 16 },
  { key: "group_parent",    label: "Group Parent",    grow: 14 },
  { key: "name",            label: "Ledger Name",     grow: 30 },
  { key: "closing_balance", label: "Closing Balance", grow: 14, numeric: true },
];
const ALWAYS_ON = new Set(["name"]);
const DEFAULT_HIDDEN = new Set(); // all visible by default

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 76; // sort row (40) + filter row (36)

function _str(v) {
  return v == null ? "" : String(v);
}

export default function LedgerTable({
  items,
  selected,
  setSelected,
  onToggle,
  onSelectAllSuggested,
  onClear,
  testidPrefix,
  // Optional hooks for ITC-specific UI:
  showItcEnrichment = false,
  // Slot above the table for module-specific controls.
  headerRight = null,
  // Empty-state copy.
  emptyHint = "No ledgers in this pool.",
  // Hint about what `suggested` means.
  suggestedLabel = "suggested",
  // Approx. minimum body height in px (one rendered row + chrome).
  minBodyPx = 280,
  maxBodyPx = 560,
}) {
  // ── column-picker preferences (per-table, persisted) ─────────────────
  const storageKey = `clause44.ledgertable.cols.${testidPrefix}`;
  const [hidden, setHidden] = useState(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) return new Set(JSON.parse(raw));
    } catch { /* noop */ }
    return new Set(DEFAULT_HIDDEN);
  });
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(Array.from(hidden))); }
    catch { /* noop */ }
  }, [hidden, storageKey]);
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const colPickerRef = useRef(null);
  useEffect(() => {
    if (!colPickerOpen) return;
    const onClick = (e) => { if (colPickerRef.current && !colPickerRef.current.contains(e.target)) setColPickerOpen(false); };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [colPickerOpen]);

  const visibleCols = useMemo(
    () => ALL_COLS.filter((c) => !hidden.has(c.key) || ALWAYS_ON.has(c.key)),
    [hidden],
  );

  // ── sort state ────────────────────────────────────────────────────────
  // Default: Head asc → Subhead asc → Name asc.
  const [sortKey, setSortKey] = useState("head");
  const [sortDir, setSortDir] = useState("asc");
  const cycleSort = (k) => {
    if (sortKey !== k) { setSortKey(k); setSortDir("asc"); return; }
    setSortDir((d) => (d === "asc" ? "desc" : "asc"));
  };

  // ── per-column filter state ──────────────────────────────────────────
  const [filters, setFilters] = useState({});
  const [cbMin, setCbMin] = useState("");
  const [cbMax, setCbMax] = useState("");
  const [globalQ, setGlobalQ] = useState("");

  // ── filter pipeline ──────────────────────────────────────────────────
  const filtered = useMemo(() => {
    const gq = globalQ.trim().toLowerCase();
    const fEntries = Object.entries(filters).filter(([, v]) => v && v.trim());
    const cbLo = cbMin === "" ? null : Number(cbMin);
    const cbHi = cbMax === "" ? null : Number(cbMax);
    const out = items.filter((it) => {
      if (gq) {
        const blob = `${it.head} ${it.subhead} ${it.group_parent} ${it.name}`.toLowerCase();
        if (!blob.includes(gq)) return false;
      }
      for (const [k, v] of fEntries) {
        if (!_str(it[k]).toLowerCase().includes(v.trim().toLowerCase())) return false;
      }
      if (cbLo != null || cbHi != null) {
        const cb = Math.abs(Number(it.closing_balance || 0));
        if (cbLo != null && cb < cbLo) return false;
        if (cbHi != null && cb > cbHi) return false;
      }
      return true;
    });
    // Sort
    const dirMul = sortDir === "asc" ? 1 : -1;
    const cmpStr = (a, b) => _str(a).localeCompare(_str(b), undefined, { sensitivity: "base" });
    out.sort((a, b) => {
      let primary;
      if (sortKey === "closing_balance") {
        primary = (Math.abs(Number(a.closing_balance || 0)) - Math.abs(Number(b.closing_balance || 0))) * dirMul;
      } else {
        primary = cmpStr(a[sortKey], b[sortKey]) * dirMul;
      }
      if (primary !== 0) return primary;
      // Stable sub-sort: Head → Subhead → Name (asc, regardless of dir).
      if (sortKey !== "head" && cmpStr(a.head, b.head) !== 0) return cmpStr(a.head, b.head);
      if (sortKey !== "subhead" && cmpStr(a.subhead, b.subhead) !== 0) return cmpStr(a.subhead, b.subhead);
      if (sortKey !== "name") return cmpStr(a.name, b.name);
      return 0;
    });
    return out;
  }, [items, globalQ, filters, cbMin, cbMax, sortKey, sortDir]);

  // ── selection helpers ────────────────────────────────────────────────
  const totalCount = items.length;
  const filteredCount = filtered.length;
  const selectedCount = selected.size;
  const suggestedCount = items.filter((x) => x.suggested).length;

  const allFilteredSelected = filteredCount > 0 && filtered.every((it) => selected.has(it.name));
  const onToggleAllFiltered = () => {
    if (!setSelected) return;
    const next = new Set(selected);
    if (allFilteredSelected) filtered.forEach((it) => next.delete(it.name));
    else filtered.forEach((it) => next.add(it.name));
    setSelected(next);
  };

  // ── grid template ────────────────────────────────────────────────────
  // Auto-fit columns at any viewport — last col (☑) is fixed 56px.
  const gridTemplate = useMemo(() => {
    const parts = visibleCols.map((c) => `minmax(0, ${c.grow}fr)`);
    return [...parts, "56px"].join(" ");
  }, [visibleCols]);

  // ── react-window row renderer ────────────────────────────────────────
  const Row = ({ index, style }) => {
    const it = filtered[index];
    if (!it) return null;
    const isSel = selected.has(it.name);
    return (
      <div
        style={style}
        className={`grid items-center border-b border-[#E5E5E0] text-[12.5px] hover:bg-[#F9F9F8] ${isSel ? "bg-emerald-50/50" : ""}`}
        data-testid={`${testidPrefix}-row-${encodeURIComponent(it.name)}`}
      >
        <div className="contents" style={{ display: "contents" }}>
          <div className="grid items-center px-2 gap-0" style={{ gridTemplateColumns: gridTemplate, height: ROW_HEIGHT }}>
            {visibleCols.map((c) => {
              if (c.key === "name") {
                return (
                  <div key={c.key} className="px-2 min-w-0 flex items-center gap-2">
                    <span className="truncate font-medium" title={it.name}>{it.name}</span>
                    {it.suggested && (
                      <Badge className="shrink-0 bg-amber-50 text-amber-900 border border-amber-200 rounded-sm shadow-none px-1.5 py-0 text-[9.5px] font-mono">
                        <Sparkle size={9} weight="fill" className="mr-1"/> {suggestedLabel}
                      </Badge>
                    )}
                    {showItcEnrichment && it.kind === "input" && (
                      <Badge className="shrink-0 bg-emerald-50 text-emerald-900 border border-emerald-200 rounded-sm shadow-none px-1.5 py-0 text-[9.5px] font-mono">INPUT</Badge>
                    )}
                    {showItcEnrichment && it.kind === "output" && (
                      <Badge className="shrink-0 bg-rose-50 text-rose-900 border border-rose-200 rounded-sm shadow-none px-1.5 py-0 text-[9.5px] font-mono">OUTPUT</Badge>
                    )}
                    {showItcEnrichment && it.usage_conflict && (
                      <Badge className="shrink-0 bg-amber-50 text-amber-900 border border-amber-300 rounded-sm shadow-none px-1.5 py-0 text-[9.5px] font-mono" title="Name says INPUT but ledger fired only on sales vouchers">
                        ⚠ name vs usage
                      </Badge>
                    )}
                  </div>
                );
              }
              if (c.key === "closing_balance") {
                const v = it.closing_balance;
                return (
                  <div key={c.key} className="px-2 font-mono text-right tabular-nums" title={String(v ?? "")}>
                    {v == null ? "—" : formatINR(v)}
                  </div>
                );
              }
              return (
                <div key={c.key} className="px-2 min-w-0 truncate text-[#52524E]" title={_str(it[c.key])}>
                  {_str(it[c.key]) || "—"}
                </div>
              );
            })}
            <div className="px-2 flex justify-center">
              <Checkbox
                checked={isSel}
                onCheckedChange={() => onToggle(it.name)}
                data-testid={`${testidPrefix}-checkbox-${encodeURIComponent(it.name)}`}
              />
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ── body height — one viewport-aware band; honours min/max props ────
  const desiredBodyPx = Math.min(
    maxBodyPx,
    Math.max(minBodyPx, Math.min(filteredCount, 12) * ROW_HEIGHT),
  );

  return (
    <div className="border border-[#E5E5E0] rounded-sm bg-white" data-testid={`${testidPrefix}-table`}>
      {/* ── toolstrip ───────────────────────────────────────────────── */}
      <div className="px-3 py-2.5 border-b border-[#E5E5E0] flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <MagnifyingGlass size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8A8A83]"/>
          <Input
            value={globalQ}
            onChange={(e) => setGlobalQ(e.target.value)}
            placeholder="Search across all columns…"
            className="pl-8 h-8 rounded-sm border-[#D4D4D0] font-mono text-[11px]"
            data-testid={`${testidPrefix}-search`}
          />
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={onSelectAllSuggested}
          className="h-8 rounded-sm border-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-900 font-mono text-[10.5px] uppercase tracking-[0.12em]"
          data-testid={`${testidPrefix}-select-suggested`}
        >
          <Sparkle size={11} weight="fill" className="mr-1"/> Select suggested · {suggestedCount}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onClear}
          className="h-8 rounded-sm border-[#D4D4D0] font-mono text-[10.5px] uppercase tracking-[0.12em]"
          data-testid={`${testidPrefix}-clear`}
        >
          Clear
        </Button>
        <span className="font-mono text-[10.5px] text-[#52524E]" data-testid={`${testidPrefix}-counts`}>
          {selectedCount} selected · {filteredCount} of {totalCount} shown
        </span>

        {/* Column picker */}
        <div className="ml-auto relative" ref={colPickerRef}>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setColPickerOpen((v) => !v)}
            className="h-8 rounded-sm border-[#D4D4D0] font-mono text-[10.5px] uppercase tracking-[0.12em]"
            data-testid={`${testidPrefix}-columns-button`}
          >
            <Gear size={12} className="mr-1"/> Columns
          </Button>
          {colPickerOpen && (
            <div className="absolute right-0 top-9 z-20 bg-white border border-[#D4D4D0] rounded-sm shadow-lg p-2 w-56" data-testid={`${testidPrefix}-columns-popover`}>
              <div className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-[#8A8A83] px-2 py-1">Show columns</div>
              {ALL_COLS.map((c) => {
                const locked = ALWAYS_ON.has(c.key);
                const checked = !hidden.has(c.key) || locked;
                return (
                  <label key={c.key} className={`flex items-center gap-2 px-2 py-1.5 rounded-sm ${locked ? "opacity-60" : "hover:bg-[#F3F4F1] cursor-pointer"}`}>
                    <Checkbox
                      checked={checked}
                      disabled={locked}
                      onCheckedChange={() => {
                        if (locked) return;
                        const n = new Set(hidden);
                        n.has(c.key) ? n.delete(c.key) : n.add(c.key);
                        setHidden(n);
                      }}
                      data-testid={`${testidPrefix}-col-toggle-${c.key}`}
                    />
                    <span className="text-[12.5px]">{c.label}</span>
                    {locked && <span className="ml-auto text-[9.5px] font-mono text-[#8A8A83]">always on</span>}
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Optional caller-supplied control row (ITC toggle, kind filter etc.) */}
      {headerRight && (
        <div className="px-3 py-2 border-b border-[#E5E5E0] bg-[#FAFAF7]">
          {headerRight}
        </div>
      )}

      {/* ── selected chip strip ────────────────────────────────────── */}
      {selectedCount > 0 && (
        <div className="px-3 py-2 border-b border-[#E5E5E0] flex flex-wrap gap-1.5 max-h-24 overflow-y-auto" data-testid={`${testidPrefix}-chips`}>
          {Array.from(selected).slice(0, 200).map((n) => (
            <Badge key={n} className="bg-[#0F172A] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
              <span className="truncate max-w-[200px]">{n}</span>
              <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => onToggle(n)} aria-label={`Remove ${n}`}>
                <X size={10} weight="bold"/>
              </button>
            </Badge>
          ))}
          {selectedCount > 200 && (
            <span className="font-mono text-[10.5px] text-[#8A8A83] self-center">… and {selectedCount - 200} more</span>
          )}
        </div>
      )}

      {/* ── header / sort row ──────────────────────────────────────── */}
      <div className="grid items-center bg-[#F3F4F1] border-b border-[#E5E5E0] sticky top-0 z-10" style={{ gridTemplateColumns: gridTemplate, height: 40 }}>
        {visibleCols.map((c) => (
          <button
            key={c.key}
            onClick={() => cycleSort(c.key)}
            className={`px-2 h-full font-mono text-[10px] uppercase tracking-[0.14em] text-[#52524E] flex items-center gap-1 hover:bg-white/60 ${c.numeric ? "justify-end" : ""}`}
            data-testid={`${testidPrefix}-sort-${c.key}`}
          >
            <span className="truncate">{c.label}</span>
            {sortKey === c.key && (sortDir === "asc"
              ? <CaretUp size={10} weight="bold"/>
              : <CaretDown size={10} weight="bold"/>)}
          </button>
        ))}
        <div className="px-2 h-full flex items-center justify-center">
          <Checkbox
            checked={allFilteredSelected}
            onCheckedChange={onToggleAllFiltered}
            disabled={filteredCount === 0 || !setSelected}
            data-testid={`${testidPrefix}-select-all-filtered`}
          />
        </div>
      </div>

      {/* ── filter row ─────────────────────────────────────────────── */}
      <div className="grid items-center bg-white border-b border-[#E5E5E0]" style={{ gridTemplateColumns: gridTemplate, height: 36 }}>
        {visibleCols.map((c) => {
          if (c.key === "closing_balance") {
            return (
              <div key={c.key} className="px-1.5 flex items-center gap-1">
                <Input
                  type="number"
                  placeholder="min"
                  value={cbMin}
                  onChange={(e) => setCbMin(e.target.value)}
                  className="h-7 px-1.5 rounded-sm border-[#E5E5E0] font-mono text-[11px] w-full"
                  data-testid={`${testidPrefix}-filter-cb-min`}
                />
                <Input
                  type="number"
                  placeholder="max"
                  value={cbMax}
                  onChange={(e) => setCbMax(e.target.value)}
                  className="h-7 px-1.5 rounded-sm border-[#E5E5E0] font-mono text-[11px] w-full"
                  data-testid={`${testidPrefix}-filter-cb-max`}
                />
              </div>
            );
          }
          return (
            <div key={c.key} className="px-1.5">
              <div className="relative">
                <FunnelSimple size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#8A8A83]"/>
                <Input
                  value={filters[c.key] || ""}
                  onChange={(e) => setFilters({ ...filters, [c.key]: e.target.value })}
                  placeholder="filter…"
                  className="pl-6 h-7 rounded-sm border-[#E5E5E0] font-mono text-[11px]"
                  data-testid={`${testidPrefix}-filter-${c.key}`}
                />
              </div>
            </div>
          );
        })}
        <div /> {/* checkbox column has no filter */}
      </div>

      {/* ── virtualised body ───────────────────────────────────────── */}
      {filteredCount === 0 ? (
        <div className="px-4 py-12 text-center text-[#8A8A83] text-sm" data-testid={`${testidPrefix}-empty`}>
          {totalCount === 0 ? emptyHint : "No ledgers match the current filters."}
        </div>
      ) : (
        <div style={{ height: desiredBodyPx }}>
          <List
            rowComponent={Row}
            rowCount={filteredCount}
            rowHeight={ROW_HEIGHT}
            rowProps={{}}
            overscanCount={6}
          />
        </div>
      )}

      {/* ── footer summary ─────────────────────────────────────────── */}
      <div className="px-3 py-1.5 border-t border-[#E5E5E0] bg-[#FAFAF7] font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]">
        {filteredCount} of {totalCount} ledger{totalCount === 1 ? "" : "s"} · sorted by {ALL_COLS.find((c) => c.key === sortKey)?.label || sortKey} {sortDir}
      </div>
    </div>
  );
}

export { HEADER_HEIGHT, ROW_HEIGHT };
