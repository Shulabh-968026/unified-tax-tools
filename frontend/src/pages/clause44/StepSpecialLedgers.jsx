/**
 * Step 2 — Special Ledgers (replaces old "ITC Ledgers" step).
 *
 * Tab A · Exempt Purchases — auditor ticks P&L purchase ledgers whose
 *   underlying supplies are exempt-from-GST by nature (petroleum, alcohol,
 *   life insurance premium, etc.).  Every voucher line hitting these
 *   ledgers is forced to Col 3 (Input A).  Takes precedence over Tab B.
 *
 * Tab B · ITC Ledgers — same picker as the legacy StepItc.  ITC ledger
 *   presence no longer drives Col 5 classification; it now acts as an
 *   "ITC-inference" signal for Col 3:
 *     If toggle is ON, a Regular-registered voucher with NO ITC ledger
 *     is presumed to be an exempt supply → Col 3 (Input B).
 *     If toggle is OFF, those vouchers go to Col 5 (strict ICAI).
 *   De-dup is automatic because Input A fires per-line before Input B.
 */
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { X, Info } from "@phosphor-icons/react";
import LedgerList from "./LedgerList";
import { formatINR } from "@/lib/format";

export default function StepSpecialLedgers({
  run,
  itcSelected, setItcSelected, itcQuery, setItcQuery,
  exemptSelected, setExemptSelected, exemptQuery, setExemptQuery,
  useItcInference, setUseItcInference,
}) {
  const itcItems = run?.itc_candidates || [];
  const plItems = run?.pl_ledgers || [];

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

  // Rough live-preview counts — only approximate, the real number surfaces
  // on the report screen after classification.
  const exemptLedgerTotals = plItems
    .filter((x) => exemptSelected.has(x.name))
    .reduce((a, x) => a + Math.abs(Number(x.closingBalance || 0)), 0);

  return (
    <section className="mx-auto max-w-4xl" data-testid="step-special-ledgers">
      <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#8A8A83]">Step 02 / 04</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Special Ledgers</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        The books JSON carries no tax-rate or nature-of-supply signal.
        Tag here what the auditor knows from context — <strong>Exempt
        purchase ledgers</strong> always flow to <span className="font-mono">Col 3</span>,
        and <strong>ITC ledgers</strong> (if the inference toggle is on)
        help detect <em>additional</em> Col 3 candidates where a Regular-
        registered vendor sold without charging GST.
      </p>

      <Tabs defaultValue="exempt" className="mt-6">
        <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
          <TabsTrigger
            value="exempt"
            className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white data-[state=active]:text-[#0F172A]"
            data-testid="tab-exempt"
          >
            Exempt Purchases · Input A
            {exemptSelected.size > 0 && (
              <Badge className="ml-2 bg-emerald-50 text-emerald-900 border border-emerald-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">
                {exemptSelected.size}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger
            value="itc"
            className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white data-[state=active]:text-[#0F172A]"
            data-testid="tab-itc"
          >
            ITC Ledgers · Input B
            {itcSelected.size > 0 && (
              <Badge className="ml-2 bg-sky-50 text-sky-900 border border-sky-200 rounded-sm shadow-none px-1.5 py-0 text-[10px] font-mono">
                {itcSelected.size}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* ─── Tab A · Exempt-supply purchase ledgers ─── */}
        <TabsContent value="exempt" className="mt-5">
          <div className="mb-3 flex items-baseline justify-between">
            <div className="text-[12px] text-[#52524E] max-w-2xl">
              Tick purchase ledgers whose underlying supplies are <strong>exempt from GST by nature</strong>.
              Typical examples: petroleum-product purchases, alcohol stocks, life insurance premiums,
              specified agricultural produce, notified exempt services. Every voucher line on these
              ledgers lands in <span className="font-mono">Col 3</span>, regardless of vendor status.
            </div>
            <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
              {exemptSelected.size} / {plItems.length}
            </Badge>
          </div>

          {exemptSelected.size > 0 && (
            <div className="mb-3 p-3 bg-emerald-50 border border-emerald-200 rounded-sm" data-testid="exempt-preview">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-emerald-900">Flowing to Col 3 · Input A</span>
                <span className="font-mono text-[11px] text-emerald-800">≈ {formatINR(exemptLedgerTotals)} (ledger balances)</span>
              </div>
              <div className="flex flex-wrap gap-1.5 mt-2" data-testid="exempt-chips">
                {Array.from(exemptSelected).map((n) => (
                  <Badge key={n} className="bg-emerald-700 text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
                    {n}
                    <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => toggleExempt(n)} aria-label={`Remove ${n}`}>
                      <X size={10} weight="bold"/>
                    </button>
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <LedgerList
            items={plItems}
            selected={exemptSelected}
            onToggle={toggleExempt}
            onSelectAll={() => setExemptSelected(new Set(plItems.filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setExemptSelected(new Set())}
            query={exemptQuery}
            setQuery={setExemptQuery}
            emptyHint="No P&L expenditure ledgers available — check your books upload."
            testidPrefix="exempt"
            suggestedLabel="flagged"
            showSubhead={false}
          />
        </TabsContent>

        {/* ─── Tab B · ITC Ledgers ─── */}
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
                  <strong>When ON</strong> (default): a voucher from a Regular-registered vendor
                  that carries <em>no</em> ITC-ledger entry is presumed to be an exempt supply and
                  routes to <span className="font-mono">Col 3</span>. This reflects the long-standing
                  CA practice of using ITC availment as a proxy for taxability — the books don't tag
                  nature-of-supply per voucher.
                  <br/>
                  <strong>When OFF</strong>: only Input A (above) drives Col 3. All Regular vendors go
                  to <span className="font-mono">Col 5</span> — the strict ICAI position per Para 79.13.
                  The working-paper disclaimer will flag whichever mode you used.
                </p>
              </div>
            </div>
          </div>

          <div className="mb-3 flex items-baseline justify-between">
            <div className="text-[12px] text-[#52524E]">
              Pre-ticked: BS ledgers mapped to <span className="font-mono">Balance with Revenue Authorities</span> or <span className="font-mono">Statutory Dues Payable</span>.
            </div>
            <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
              {itcSelected.size} / {itcItems.length}
            </Badge>
          </div>

          {itcSelected.size > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3" data-testid="itc-chips">
              {Array.from(itcSelected).map((n) => (
                <Badge key={n} className="bg-[#0F172A] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
                  {n}
                  <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => toggleItc(n)} aria-label={`Remove ${n}`}>
                    <X size={10} weight="bold"/>
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <LedgerList
            items={itcItems}
            selected={itcSelected}
            onToggle={toggleItc}
            onSelectAll={() => setItcSelected(new Set(itcItems.filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setItcSelected(new Set())}
            query={itcQuery}
            setQuery={setItcQuery}
            emptyHint="No BS-side ledgers available — check your books upload."
            testidPrefix="itc"
            showSubhead={true}
          />
        </TabsContent>
      </Tabs>
    </section>
  );
}
