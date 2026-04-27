import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, DownloadSimple, Stack } from "@phosphor-icons/react";
import { getConsolidated, exportConsolidatedUrl } from "@/lib/api";
import { formatINR, formatDate } from "@/lib/format";
import { toast } from "sonner";
import ReportTable from "@/pages/ReportTable";
import ReconTable from "@/pages/ReconTable";

export default function Consolidated() {
  const { clientId, period } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drill, setDrill] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await getConsolidated(clientId, period);
        setData(d);
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Failed to load consolidated report");
      } finally {
        setLoading(false);
      }
    })();
  }, [clientId, period]);

  const ledgerRows = useMemo(() => {
    if (!data?.by_ledger) return [];
    return Object.entries(data.by_ledger).map(([name, v]) => ({
      name,
      col3: v.col3 || 0, col4: v.col4 || 0, col5: v.col5 || 0, col7: v.col7 || 0,
      col6: (v.col3 || 0) + (v.col4 || 0) + (v.col5 || 0),
      col2_total: v.total != null ? v.total : (v.col3 || 0) + (v.col4 || 0) + (v.col5 || 0) + (v.col7 || 0),
    })).sort((a, b) => b.col2_total - a.col2_total);
  }, [data]);

  const openDrill = (bucket, ledger) => {
    if (!data) return;
    let txns = data.transactions || [];
    if (bucket && bucket !== "col2") {
      if (bucket === "col6") txns = txns.filter((t) => ["col3", "col4", "col5"].includes(t.bucket));
      else txns = txns.filter((t) => t.bucket === bucket);
    }
    if (ledger) txns = txns.filter((t) => t.ledger_name === ledger);
    setDrill({ bucket: bucket || "col2", ledger, txns });
  };

  if (loading || !data) return <AppShell><div className="p-10 font-mono text-sm text-[#8A8A83]">Loading consolidated report…</div></AppShell>;

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate(`/dashboard/clients/${clientId}/utilities/clause-44`)} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>{data.client_name} · Clause 44</button>}
        title={<span className="inline-flex items-center gap-3"><Stack size={22} weight="duotone" className="text-[#0F172A]"/>Consolidated · {/^fy/i.test(period) ? period : `FY ${period}`}</span>}
        subtitle={`Aggregated across ${data.division_summaries?.length || 0} divisions of ${data.client_name}.`}
        actions={
          <Button asChild className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2" data-testid="export-consolidated-btn">
            <a href={exportConsolidatedUrl(clientId, period)} download><DownloadSimple size={14} weight="bold"/>Download Detailed Breakup</a>
          </Button>
        }
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-[1400px]">
        {/* Per-division split */}
        <div className="mb-6 grid md:grid-cols-2 lg:grid-cols-4 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden" data-testid="div-summaries">
          {data.division_summaries?.map((d) => (
            <div key={d.run_id} className="bg-white px-4 py-3">
              <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]">Division</div>
              <div className="text-[14px] font-medium truncate">{d.division_name}</div>
              <div className="num text-[16px] tracking-tight mt-1">{formatINR(d.summary?.col2_total || 0)}</div>
            </div>
          ))}
        </div>

        <Tabs defaultValue="report" className="w-full">
          <TabsList className="bg-[#F3F4F1] border border-[#E5E5E0] rounded-sm p-1 h-auto">
            <TabsTrigger value="report" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-report">Schedule</TabsTrigger>
            <TabsTrigger value="recon" className="font-mono text-[11px] uppercase tracking-[0.12em] data-[state=active]:bg-white" data-testid="tab-recon">Reconciliation</TabsTrigger>
          </TabsList>
          <TabsContent value="report" className="mt-6">
            <ReportTable summary={data.summary} ledgerRows={ledgerRows} openDrill={openDrill}/>
          </TabsContent>
          <TabsContent value="recon" className="mt-6">
            <ReconTable recon={data.recon}/>
          </TabsContent>
        </Tabs>
      </div>

      <DrillSheet drill={drill} onClose={() => setDrill(null)}/>
    </AppShell>
  );
}

function DrillSheet({ drill, onClose }) {
  const BUCKET_LABEL = { col2: "All buckets", col3: "Col 3 · Exempt supply", col4: "Col 4 · Composition dealer", col5: "Col 5 · Other Registered (ITC)", col6: "Col 6 · Aggregate registered (3+4+5)", col7: "Col 7 · Unregistered" };
  return (
    <Sheet open={!!drill} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full sm:max-w-2xl lg:max-w-3xl p-0 bg-white" data-testid="drilldown-sheet">
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-[#E5E5E0]">
          <SheetTitle className="font-heading text-xl tracking-tight">{drill?.ledger || "Aggregate"}</SheetTitle>
          <SheetDescription className="text-[12px] text-[#52524E]">{BUCKET_LABEL[drill?.bucket] || ""}</SheetDescription>
          {drill?.txns && (
            <div className="flex items-center gap-3 mt-2 font-mono text-[11px] text-[#52524E]">
              <Badge className="bg-slate-100 text-slate-800 rounded-sm shadow-none border-slate-200">{drill.txns.length} txns</Badge>
              <span>·</span>
              <span>Σ {formatINR(drill.txns.reduce((a, t) => a + t.amount, 0))}</span>
            </div>
          )}
        </SheetHeader>
        <div className="overflow-y-auto h-[calc(100vh-110px)]">
          {drill?.txns && drill.txns.length === 0 && <div className="p-8 text-sm text-[#8A8A83]">No transactions in this bucket.</div>}
          {drill?.txns && drill.txns.length > 0 && (
            <table className="fiscal-table w-full" data-testid="drilldown-table">
              <thead><tr><th>Date</th><th>Voucher</th><th>Division</th><th>Ledger</th><th>Party</th><th className="text-right">Amount</th><th>Reason</th></tr></thead>
              <tbody>
                {drill.txns.map((t, i) => (
                  <tr key={`${t.voucher_id}_${i}`}>
                    <td className="num text-[12px]">{formatDate(t.date)}</td>
                    <td className="num text-[12px]">{t.voucher_type}<br/><span className="text-[#8A8A83]">{t.voucher_number}</span></td>
                    <td className="text-[12px]">{t.division_name || "—"}</td>
                    <td className="text-[12px] max-w-[160px] truncate">{t.ledger_name}</td>
                    <td className="text-[12px] max-w-[180px]">{t.party_name || <em className="text-[#8A8A83]">—</em>}{t.party_gstin && <div className="font-mono text-[10px] text-[#8A8A83]">{t.party_gstin}</div>}</td>
                    <td className="cell-num text-[12px]">{formatINR(t.amount)}</td>
                    <td className="text-[11px] text-[#52524E] max-w-[260px]">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
