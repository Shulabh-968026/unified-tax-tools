import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import AppShell, { PageHeader, StepRail } from "@/components/AppShell";
import StepMapping from "@/pages/StepMapping";
import StepReport from "@/pages/StepReport";
import { getRun } from "@/lib/api";

export function MappingDashboard() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);

  useEffect(() => {
    (async () => {
      try { setRun(await getRun(runId)); } catch {}
    })();
  }, [runId]);

  return (
    <AppShell>
      <PageHeader
        eyebrow={run?.client_name ? `${run.client_name} · FY ${run.period}${run.division_name ? ` · ${run.division_name}` : ""}` : "Run"}
        title="Confirm ITC and Exclusions"
        subtitle="Pre-selected suggestions are based on Balance Sheet vs P&L classification and ledger-name heuristics."
        actions={<StepRail step={2}/>}
      />
      <StepMapping/>
    </AppShell>
  );
}

export function ReportDashboard() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);

  useEffect(() => {
    (async () => {
      try { setRun(await getRun(runId)); } catch {}
    })();
  }, [runId]);

  return (
    <AppShell>
      <PageHeader
        eyebrow={run?.client_name ? `${run.client_name} · FY ${run.period}${run.division_name ? ` · ${run.division_name}` : ""}` : "Run"}
        title="Clause 44 Schedule"
        subtitle="Drill down per cell. Switch to Reconciliation to tie books to the schedule. Export both as a 3-sheet workbook."
        actions={<StepRail step={3}/>}
      />
      <StepReport/>
    </AppShell>
  );
}
