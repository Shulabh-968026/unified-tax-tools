import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { getClient, listRuns, updateClient, archiveRun } from "@/lib/api";
import { ArrowLeft, ArrowRight, Plus, Stack, ChartBar, FileArrowDown, Archive } from "@phosphor-icons/react";
import { formatDate, formatDateTime } from "@/lib/format";
import { toast } from "sonner";
import StepUpload from "@/pages/StepUpload";

const PERIOD_PRESETS = ["2024-25", "2023-24", "2022-23", "2021-22", "2020-21"];

export default function ClientHome() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  const [period, setPeriod] = useState(PERIOD_PRESETS[1]);
  const [customPeriod, setCustomPeriod] = useState("");
  const [divisionId, setDivisionId] = useState("");
  const [showAddDiv, setShowAddDiv] = useState(false);
  const [newDiv, setNewDiv] = useState("");

  const [showUpload, setShowUpload] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const c = await getClient(clientId);
      setClient(c);
      const d = await listRuns({ client_id: clientId });
      setRuns(d.runs || []);
      if (c.type === "multi" && c.divisions?.length && !divisionId) {
        setDivisionId(c.divisions[0].division_id);
      }
    } catch (e) {
      toast.error("Failed to load client");
      navigate("/dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [clientId]);

  const effectivePeriod = (period === "__custom" ? customPeriod : period).trim();

  const onAddDivision = async () => {
    if (!newDiv.trim()) return;
    try {
      const c = await updateClient(clientId, { add_divisions: [newDiv.trim()] });
      setClient(c);
      setNewDiv("");
      setShowAddDiv(false);
      toast.success("Division added");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const onArchive = async (id) => {
    try {
      await archiveRun(id);
      toast.success("Run archived");
      refresh();
    } catch { toast.error("Archive failed"); }
  };

  // Group runs by period
  const grouped = useMemo(() => {
    const map = new Map();
    runs.forEach((r) => {
      if (!map.has(r.period)) map.set(r.period, []);
      map.get(r.period).push(r);
    });
    return Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  }, [runs]);

  if (loading || !client) return <AppShell><div className="p-10 font-mono text-sm text-[#8A8A83]">Loading client…</div></AppShell>;

  const isMulti = client.type === "multi";

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate(`/dashboard/clients/${clientId}`)} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>{client.name} · Utilities</button>}
        title={<span className="inline-flex items-center gap-3"><span className="font-mono text-[11px] uppercase tracking-[0.18em] bg-[#0F172A] text-white px-2 py-0.5">Clause 44</span>{client.name}</span>}
        subtitle={
          <span className="inline-flex items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">File · {client.file_number}</span>
            <span>·</span>
            <Badge className={`${isMulti ? "bg-amber-50 text-amber-900 border-amber-200" : "bg-emerald-50 text-emerald-900 border-emerald-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
              {isMulti ? `Multi · ${client.divisions?.length || 0} div` : "Single"}
            </Badge>
          </span>
        }
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-6xl">
        {/* Start a new run */}
        <section className="border border-[#E5E5E0] bg-white rounded-sm p-6">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83]">Step 01</div>
          <h2 className="mt-1 font-heading text-xl tracking-tight">Choose Period {isMulti && "& Division"}</h2>
          <div className="mt-5 grid md:grid-cols-3 gap-4">
            <div>
              <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Financial Year / Period</Label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger data-testid="period-select" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"><SelectValue/></SelectTrigger>
                <SelectContent>
                  {PERIOD_PRESETS.map((p) => <SelectItem key={p} value={p} data-testid={`period-${p}`}>FY {p}</SelectItem>)}
                  <SelectItem value="__custom" data-testid="period-custom">Custom…</SelectItem>
                </SelectContent>
              </Select>
              {period === "__custom" && (
                <Input
                  data-testid="period-custom-input"
                  className="mt-2 rounded-sm shadow-none border-[#D4D4D0]"
                  placeholder="Enter period label, e.g. Q1-2024-25"
                  value={customPeriod}
                  onChange={(e) => setCustomPeriod(e.target.value)}
                />
              )}
            </div>
            {isMulti && (
              <div>
                <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Division</Label>
                <Select value={divisionId} onValueChange={setDivisionId}>
                  <SelectTrigger data-testid="division-select" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"><SelectValue placeholder="Pick division"/></SelectTrigger>
                  <SelectContent>
                    {(client.divisions || []).map((d) => (
                      <SelectItem key={d.division_id} value={d.division_id} data-testid={`division-opt-${d.division_id}`}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <button onClick={() => setShowAddDiv(true)} className="mt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-[#0F172A] hover:underline inline-flex items-center gap-1" data-testid="add-division-open">
                  <Plus size={12} weight="bold"/> Add another division
                </button>
              </div>
            )}
            <div className="flex items-end">
              <Button
                data-testid="start-run-btn"
                disabled={!effectivePeriod || (isMulti && !divisionId)}
                onClick={() => setShowUpload(true)}
                className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 disabled:opacity-50"
              >
                Start Run <ArrowRight size={14} weight="bold"/>
              </Button>
            </div>
          </div>
        </section>

        {/* Runs grouped by period */}
        <section className="mt-10">
          <h3 className="font-heading text-lg tracking-tight">Runs</h3>
          {grouped.length === 0 ? (
            <div className="mt-3 border border-dashed border-[#D4D4D0] bg-white rounded-sm p-8 text-center text-sm text-[#52524E]">
              No runs yet for this client.
            </div>
          ) : (
            grouped.map(([per, list]) => {
              const generatedDivs = list.filter((r) => r.generated && r.division_id);
              const showConsolidated = isMulti && generatedDivs.length >= 2;
              return (
                <div key={per} className="mt-5 border border-[#E5E5E0] bg-white rounded-sm">
                  <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
                    <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">FY · {per}</div>
                    <Badge className="bg-slate-100 text-slate-800 border-slate-200 rounded-sm shadow-none">{list.length} runs</Badge>
                    {showConsolidated && (
                      <Button
                        data-testid={`open-consolidated-${per}`}
                        onClick={() => navigate(`/dashboard/clients/${clientId}/utilities/clause-44/consolidated/${encodeURIComponent(per)}`)}
                        className="ml-auto h-8 px-3 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 text-xs"
                      >
                        <Stack size={12} weight="bold"/> Consolidated Report
                      </Button>
                    )}
                  </div>
                  <ul>
                    {list.map((r) => (
                      <li key={r.run_id} className="px-4 py-3 border-b border-[#E5E5E0] last:border-b-0 flex items-center gap-3 hover:bg-[#F9F9F8]" data-testid={`run-${r.run_id}`}>
                        <div className="flex-1 min-w-0">
                          <div className="text-[14px] font-medium truncate">
                            {r.division_name || "Single scope"} <span className="text-[#8A8A83]">·</span> <span className="font-normal text-[#52524E]">{r.company_name}</span>
                          </div>
                          <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#8A8A83] mt-0.5">
                            {r.generated && r.generated_by_name ? (
                              <>
                                Generated by <span className="text-[#0F172A]">{r.generated_by_name}</span> · {formatDateTime(r.generated_at)}
                              </>
                            ) : r.created_by_name ? (
                              <>
                                Uploaded by <span className="text-[#52524E]">{r.created_by_name}</span> · {formatDateTime(r.created_at)} · Draft
                              </>
                            ) : (
                              <>{formatDate(r.created_at)} · {r.generated ? "Generated" : "Draft"}</>
                            )}
                          </div>
                        </div>
                        {r.generated ? (
                          <Button onClick={() => navigate(`/dashboard/runs/${r.run_id}/report`)} variant="outline" className="h-8 px-3 border-[#D4D4D0] rounded-sm shadow-none gap-2 text-xs" data-testid={`open-report-${r.run_id}`}>
                            <ChartBar size={12} weight="bold"/> Report
                          </Button>
                        ) : (
                          <Button onClick={() => navigate(`/dashboard/runs/${r.run_id}`)} variant="outline" className="h-8 px-3 border-[#D4D4D0] rounded-sm shadow-none gap-2 text-xs" data-testid={`open-mapping-${r.run_id}`}>
                            <FileArrowDown size={12} weight="bold"/> Continue
                          </Button>
                        )}
                        <button onClick={() => onArchive(r.run_id)} className="text-[#8A8A83] hover:text-[#991B1B]" title="Archive" data-testid={`archive-run-${r.run_id}`}>
                          <Archive size={14}/>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </section>
      </div>

      {/* Add division dialog */}
      <Dialog open={showAddDiv} onOpenChange={setShowAddDiv}>
        <DialogContent className="bg-white border border-[#E5E5E0] rounded-sm" data-testid="add-division-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Add Division</DialogTitle>
          </DialogHeader>
          <div>
            <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Division Name</Label>
            <Input data-testid="new-division-input" value={newDiv} onChange={(e) => setNewDiv(e.target.value)} className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"/>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowAddDiv(false)}>Cancel</Button>
            <Button data-testid="submit-new-division" onClick={onAddDivision} className="bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none">Add</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upload dialog */}
      <Dialog open={showUpload} onOpenChange={setShowUpload}>
        <DialogContent className="bg-white border border-[#E5E5E0] rounded-sm max-w-3xl p-0" data-testid="upload-dialog">
          <DialogHeader className="px-6 pt-5 pb-3 border-b border-[#E5E5E0]">
            <DialogTitle className="font-heading text-xl">Upload Books</DialogTitle>
            <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">
              {client.name} · FY {effectivePeriod}{isMulti ? ` · ${(client.divisions || []).find((d) => d.division_id === divisionId)?.name || "—"}` : ""}
            </div>
          </DialogHeader>
          <StepUpload
            clientId={clientId}
            period={effectivePeriod}
            divisionId={isMulti ? divisionId : null}
            onUploaded={(runId) => {
              setShowUpload(false);
              navigate(`/dashboard/runs/${runId}`);
            }}
          />
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
