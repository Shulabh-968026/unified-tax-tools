/**
 * Step 2 — Special Ledgers (Release 4.4 — three-pool model).
 *
 * Tab A · Exempt Purchases — every P-side ledger except those under
 *   `Revenue from Operations` / `Other Income`.  Auditor ticks
 *   exempt-by-nature purchases (petroleum, alcohol, life insurance, etc.).
 *
 * Tab B · ITC Ledgers — default view shows BS-side ledgers under the two
 *   Schedule III ITC subheads (Balance with Revenue Authorities,
 *   Statutory Dues Payable).  Toggle "Show all BS-side ledgers" expands
 *   to every B-side ledger so firms with bespoke Schedule III taxonomy
 *   can still pick their ITC ledgers.
 */
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Info } from "@phosphor-icons/react";
import LedgerTable from "./LedgerTable";
import { formatINR } from "@/lib/format";

export default function StepSpecialLedgers({
  run,
  itcSelected, setItcSelected,
  exemptSelected, setExemptSelected,
  useItcInference, setUseItcInference,
  itcKindFilter, setItcKindFilter,
}) {
  const exemptItems     = run?.exempt_ledgers     || [];
  const itcDefault      = run?.itc_ledgers        || [];
  const itcAllBs        = run?.itc_ledgers_all_bs || [];

  // "Show all BS-side ledgers" toggle — defaults to OFF (focused view).
  const [showAllBs, setShowAllBs] = useState(false);

  const itcUniverse = showAllBs ? itcAllBs : itcDefault;
  const itcItems = useMemo(() => {
    if (!itcKindFilter || itcKindFilter === "all") return itcUniverse;
    return itcUniverse.filter((x) => (x.kind || "other") === itcKindFilter);
  }, [itcUniverse, itcKindFilter]);

  const toggleItc = (name) => {
    const n = new Set(itcSelected);
    n.has(name) ? n.delete(name) : n.add(name);
    setItcSelected(n);
  };
  const toggleExempt = (name) => {
    const n = new Set(exemptSelected);
    n.has(name) ? n.delete(name) : n.add(name);
    setExemptSelected(n);
  };

  // Approximate live preview total for the exempt picker.
  const exemptLedgerTotals = exemptItems
    .filter((x) => exemptSelected.has(x.name))
    .reduce((a, x) => a + Math.abs(Number(x.closing_balance || 0)), 0);

  // Selections that exist in expanded mode but lie outside default-view
  // subheads — surface as a hint so auditors don't silently lose them.
  const outsideDefaultSelected = useMemo(() => {
    const defaultSet = new Set(itcDefault.map((x) => x.name));
    return Array.from(itcSelected).filter((n) => !defaultSet.has(n));
  }, [itcDefault, itcSelected]);

  const outputPicked = itcAllBs.filter((x) => x.kind === "output" && itcSelected.has(x.name));

  return (
    <section className="mx-auto max-w-7xl" data-testid="step-special-ledgers">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 02 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Special Ledgers</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        Tag what the auditor knows from context. <strong>Exempt purchase ledgers</strong> always flow to <span className="font-mono">Col 3</span>; <strong>ITC ledgers</strong> (with the inference toggle on) help detect additional Col 3 candidates where a Regular-registered vendor sold without charging GST.
      </p>

      <Tabs defaultValue="exempt" className="mt-6">
        <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
          <TabsTrigger value="exempt" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-exempt">
            Exempt Purchases · Input A
            {exemptSelected.size > 0 && (
              <Badge className="ml-2 bg-emerald-50 text-emerald-900 border border-emerald-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">{exemptSelected.size}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="itc" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-itc">
            ITC Ledgers · Input B
            {itcSelected.size > 0 && (
              <Badge className="ml-2 bg-sky-50 text-sky-900 border border-sky-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">{itcSelected.size}</Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* ───── Tab A · Exempt Purchases ───── */}
        <TabsContent value="exempt" className="mt-5">
          <div className="mb-3 text-[12px] text-[#52524E] max-w-3xl">
            Tick purchase ledgers whose underlying supplies are <strong>exempt from GST by nature</strong>.
            Typical examples: petroleum-product purchases, alcohol stocks, life-insurance premium, specified
            agricultural produce.  Every voucher line on these ledgers lands in <span className="font-mono">Col 3</span> regardless of vendor status.
            {exemptLedgerTotals > 0 && (
              <span className="ml-2 font-mono text-emerald-800">≈ {formatINR(exemptLedgerTotals)} (ledger balances)</span>
            )}
          </div>
          <LedgerTable
            items={exemptItems}
            selected={exemptSelected}
            setSelected={setExemptSelected}
            onToggle={toggleExempt}
            onSelectAllSuggested={() => setExemptSelected(new Set(exemptItems.filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setExemptSelected(new Set())}
            testidPrefix="exempt"
            emptyHint="No P-side ledgers in this run — check your books upload."
            suggestedLabel="exempt-hint"
          />
        </TabsContent>

        {/* ───── Tab B · ITC Ledgers ───── */}
        <TabsContent value="itc" className="mt-5">
          <div className="mb-3 p-3 bg-sky-50 border border-sky-200 rounded-sm" data-testid="itc-inference-toggle-row">
            <div className="flex items-start gap-3">
              <Info size={16} weight="bold" className="text-sky-900 flex-shrink-0 mt-0.5"/>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-4 flex-wrap">
                  <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-sky-900">
                    Use ITC inference for Col 3 (Input B)
                  </div>
                  <Switch
                    checked={useItcInference}
                    onCheckedChange={setUseItcInference}
                    data-testid="itc-inference-toggle"
                  />
                </div>
                <p className="text-[11.5px] text-sky-950/80 mt-1.5 leading-snug">
                  <strong>When ON</strong> (default): a voucher from a Regular-registered vendor that carries <em>no</em> ITC-ledger entry is presumed to be an exempt supply and routes to <span className="font-mono">Col 3</span>. <strong>When OFF</strong>: only Input A drives Col 3 — strict ICAI position per Para 79.13.
                </p>
              </div>
            </div>
          </div>

          {outputPicked.length > 0 && (
            <div className="mb-3 p-3 bg-rose-50 border border-rose-200 rounded-sm" data-testid="itc-output-warning">
              <div className="flex items-start gap-2.5">
                <span className="text-rose-700 font-mono text-[10.5px] uppercase tracking-[0.12em] mt-0.5">⚠ Heads up</span>
                <p className="text-[11.5px] text-rose-950/80 leading-snug flex-1 min-w-0">
                  You've ticked <strong>{outputPicked.length}</strong> Output-side tax ledger(s).  Output ledgers fire on <em>sales</em> vouchers, not purchases — they will <strong>not</strong> mark a purchase as having ITC, so Input B will continue treating those purchases as exempt and route them to Col 3.  Untick them unless you have a specific reason, or turn the inference toggle OFF above.
                </p>
              </div>
            </div>
          )}

          {showAllBs && outsideDefaultSelected.length > 0 && (
            <div className="mb-3 p-3 bg-amber-50 border border-amber-300 rounded-sm font-mono text-[10.5px] text-amber-900" data-testid="itc-outside-default">
              {outsideDefaultSelected.length} selected from outside the suggested ITC subheads — they will be retained when you toggle back to the focused view.
            </div>
          )}

          <LedgerTable
            items={itcItems}
            selected={itcSelected}
            setSelected={setItcSelected}
            onToggle={toggleItc}
            onSelectAllSuggested={() => setItcSelected(new Set(itcUniverse.filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setItcSelected(new Set())}
            testidPrefix="itc"
            showItcEnrichment={true}
            emptyHint="No BS-side ledgers in this run — check your books upload."
            suggestedLabel="itc-hint"
            headerRight={(
              <div className="flex items-center gap-3 flex-wrap">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Switch
                    checked={showAllBs}
                    onCheckedChange={setShowAllBs}
                    data-testid="itc-show-all-bs-toggle"
                  />
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.12em]">
                    Show all BS-side ledgers
                  </span>
                </label>
                <span className={`font-mono text-[10.5px] uppercase tracking-[0.12em] ${showAllBs ? "text-amber-800" : "text-[#8A8A83]"}`} data-testid="itc-mode-indicator">
                  {showAllBs
                    ? `Expanded · ${itcAllBs.length} BS ledgers · subhead filter off`
                    : `Focused · ${itcDefault.length} ledgers under Schedule III ITC subheads · ${itcAllBs.length - itcDefault.length} hidden`}
                </span>

                {/* kind quick-filter strip */}
                <div className="ml-auto flex items-center gap-1.5" data-testid="itc-kind-filter">
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E]">View</span>
                  {[
                    { v: "all",    label: "All" },
                    { v: "input",  label: "Input" },
                    { v: "output", label: "Output" },
                    { v: "other",  label: "Other" },
                  ].map((opt) => (
                    <button
                      key={opt.v}
                      onClick={() => setItcKindFilter(opt.v)}
                      data-testid={`itc-kind-filter-${opt.v}`}
                      className={`px-2 py-1 rounded-sm border font-mono text-[10px] uppercase tracking-[0.12em] ${
                        (itcKindFilter || "all") === opt.v
                          ? "bg-[#0F172A] text-white border-[#0F172A]"
                          : "bg-white text-[#52524E] border-[#E5E5E0] hover:bg-[#F3F4F1]"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          />
        </TabsContent>
      </Tabs>
    </section>
  );
}
