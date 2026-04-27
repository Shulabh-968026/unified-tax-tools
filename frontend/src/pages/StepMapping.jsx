import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { generateRun, getRun } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { MagnifyingGlass, Sparkle, X, Lightning } from "@phosphor-icons/react";
import { toast } from "sonner";

function LedgerList({ items, selected, onToggle, onSelectAll, onClear, query, setQuery, emptyHint, testidPrefix }) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => (it.name || "").toLowerCase().includes(q) || (it.groupParent || "").toLowerCase().includes(q));
  }, [items, query]);

  return (
    <div className="border border-[#E5E5E0] rounded-sm bg-white" data-testid={`${testidPrefix}-panel`}>
      <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3">
        <MagnifyingGlass size={14} className="text-[#8A8A83]"/>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ledgers…"
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
      <div className="max-h-[420px] overflow-y-auto">
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
                            <Sparkle size={10} weight="fill" className="mr-1"/> suggested
                          </Badge>
                        )}
                      </div>
                      <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-[#8A8A83] mt-0.5">
                        {it.groupParent || "—"} {it.closingBalance != null ? `· bal ${formatINR(it.closingBalance)}` : ""}
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

export default function StepMapping() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [itcSelected, setItcSelected] = useState(new Set());
  const [excSelected, setExcSelected] = useState(new Set());
  const [itcQuery, setItcQuery] = useState("");
  const [excQuery, setExcQuery] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await getRun(runId);
        setRun(r);
        // Pre-select suggested
        const itc = new Set((r.itc_candidates || []).filter((x) => x.suggested).map((x) => x.name));
        const exc = new Set((r.pl_ledgers || []).filter((x) => x.suggested).map((x) => x.name));
        // If user previously generated, restore their actual selections
        if (r.generated) {
          (r.itc_selection || []).forEach((n) => itc.add(n));
          (r.exclusion_selection || []).forEach((n) => exc.add(n));
        }
        setItcSelected(itc);
        setExcSelected(exc);
      } catch (e) {
        toast.error("Failed to load run");
      } finally {
        setLoading(false);
      }
    })();
  }, [runId]);

  const toggle = (set, setter, name) => {
    const n = new Set(set);
    if (n.has(name)) n.delete(name);
    else n.add(name);
    setter(n);
  };

  const continueGenerate = async () => {
    setBusy(true);
    try {
      await generateRun(runId, {
        itc_ledgers: Array.from(itcSelected),
        excluded_ledgers: Array.from(excSelected),
      });
      toast.success("Clause 44 generated");
      navigate(`/dashboard/runs/${runId}/report`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="p-10 font-mono text-sm text-[#8A8A83]">Loading run…</div>;
  if (!run) return null;

  return (
    <div className="px-6 md:px-10 py-8 pb-40 max-w-6xl">
      <div className="font-mono text-[11px] uppercase tracking-[0.15em] text-[#8A8A83]">Step 02 / 03</div>
      <h2 className="mt-1 font-heading text-2xl tracking-tight">Confirm the mapping.</h2>
      <p className="mt-2 text-sm text-[#52524E] max-w-3xl">
        We pre-selected obvious matches based on ledger names and Balance Sheet vs P&amp;L classification. Please review and adjust before generating the schedule.
      </p>

      <div className="mt-8 grid lg:grid-cols-2 gap-6">
        <section data-testid="itc-section">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <div className="font-heading text-lg tracking-tight">ITC Ledgers</div>
              <div className="text-xs text-[#52524E]">Balance-sheet ledgers representing Input Tax Credit (CGST / SGST / IGST). Selecting one routes vouchers that touch it to <span className="font-mono">Col 5 — Other Registered</span>.</div>
            </div>
            <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
              {itcSelected.size}/{run.itc_candidates?.length || 0}
            </Badge>
          </div>

          {itcSelected.size > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3" data-testid="itc-chips">
              {Array.from(itcSelected).map((n) => (
                <Badge key={n} className="bg-[#0F172A] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
                  {n}
                  <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => toggle(itcSelected, setItcSelected, n)}>
                    <X size={10} weight="bold"/>
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <LedgerList
            items={run.itc_candidates || []}
            selected={itcSelected}
            onToggle={(n) => toggle(itcSelected, setItcSelected, n)}
            onSelectAll={() => setItcSelected(new Set((run.itc_candidates || []).filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setItcSelected(new Set())}
            query={itcQuery}
            setQuery={setItcQuery}
            emptyHint="No GST/Input ledgers detected on the Balance Sheet side."
            testidPrefix="itc"
          />
        </section>

        <section data-testid="exclusion-section">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <div className="font-heading text-lg tracking-tight">Expenditure Exclusions</div>
              <div className="text-xs text-[#52524E]">P&amp;L ledgers that are <strong>not supplies</strong> (e.g. Depreciation, Salary, Interest, PF/ESI). Selected ledgers are skipped in Clause 44 totals.</div>
            </div>
            <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm font-mono shadow-none">
              {excSelected.size}/{run.pl_ledgers?.length || 0}
            </Badge>
          </div>

          {excSelected.size > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3" data-testid="exclusion-chips">
              {Array.from(excSelected).map((n) => (
                <Badge key={n} className="bg-[#991B1B] text-white rounded-sm shadow-none px-2 py-0.5 text-[11px] font-mono">
                  {n}
                  <button className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => toggle(excSelected, setExcSelected, n)}>
                    <X size={10} weight="bold"/>
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <LedgerList
            items={run.pl_ledgers || []}
            selected={excSelected}
            onToggle={(n) => toggle(excSelected, setExcSelected, n)}
            onSelectAll={() => setExcSelected(new Set((run.pl_ledgers || []).filter((x) => x.suggested).map((x) => x.name)))}
            onClear={() => setExcSelected(new Set())}
            query={excQuery}
            setQuery={setExcQuery}
            emptyHint="No P&L ledgers detected."
            testidPrefix="exclusion"
          />
        </section>
      </div>

      <div className="mt-10 flex items-center justify-between border-t border-[#E5E5E0] pt-6">
        <Button
          variant="ghost"
          onClick={() => run?.client_id ? navigate(`/dashboard/clients/${run.client_id}`) : navigate("/dashboard")}
          className="font-mono text-xs uppercase tracking-[0.1em] text-[#52524E]"
          data-testid="back-to-upload-btn"
        >← Back</Button>
        <Button
          onClick={continueGenerate}
          disabled={busy}
          data-testid="generate-btn"
          className="h-10 px-5 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2"
        >
          <Lightning size={14} weight="fill"/>{busy ? "Generating…" : "Generate Clause 44"}
        </Button>
      </div>
    </div>
  );
}
