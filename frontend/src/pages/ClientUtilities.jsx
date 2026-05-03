import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Stack, Buildings } from "@phosphor-icons/react";
import { getClient } from "@/lib/api";
import { UTILITIES, UtilityCard } from "@/lib/utilities";
import { toast } from "sonner";

export default function ClientUtilities() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);

  useEffect(() => {
    (async () => {
      try { setClient(await getClient(clientId)); }
      catch { toast.error("Client not found"); navigate("/dashboard", { replace: true }); }
    })();
  }, [clientId, navigate]);

  const onOpen = (u) => {
    if (u.id === "clause-44") {
      navigate(`/dashboard/clients/${clientId}/utilities/clause-44`);
    } else if (u.id === "msme-43bh") {
      navigate(`/dashboard/clients/${clientId}/utilities/msme-43bh`);
    } else if (u.id === "gst-turnover-recon") {
      navigate(`/dashboard/clients/${clientId}/utilities/gst-recon`);
    } else if (u.id === "balance-confirmation") {
      navigate(`/dashboard/clients/${clientId}/utilities/balance-confirmation`);
    } else if (u.id === "fixed-assets") {
      navigate(`/dashboard/clients/${clientId}/utilities/fixed-assets`);
    } else if (u.id === "fin-statement") {
      navigate(`/dashboard/clients/${clientId}/utilities/fin-statement`);
    }
  };

  if (!client) return <AppShell><div className="p-10 font-mono text-sm text-[#8A8A83]">Loading client…</div></AppShell>;
  const isMulti = client.type === "multi";
  const liveCount = UTILITIES.filter((u) => u.status === "active").length;

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate("/dashboard")} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>All clients</button>}
        title={client.name}
        subtitle={
          <span className="inline-flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#52524E]">File · {client.file_number}</span>
            {client.gstin && (
              <>
                <span>·</span>
                <span className="font-mono text-[11px] tracking-[0.12em] text-[#52524E]" data-testid="client-gstin-display">
                  GSTIN · <span className="text-[#0F172A] font-semibold">{client.gstin}</span>
                </span>
              </>
            )}
            <span>·</span>
            <Badge className={`${isMulti ? "bg-amber-50 text-amber-900 border-amber-200" : "bg-emerald-50 text-emerald-900 border-emerald-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
              {isMulti ? <><Stack size={10} className="mr-1"/>Multi · {client.divisions?.length || 0} div</> : <><Buildings size={10} className="mr-1"/>Single</>}
            </Badge>
          </span>
        }
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-[1200px]">
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83]">Utilities Catalog</div>
            <h2 className="mt-1 font-heading text-2xl tracking-tight">Pick a utility</h2>
            <p className="mt-1.5 text-sm text-[#52524E] max-w-2xl">
              The AssureAI utility shelf — small, well-built tools that complement AssureAI for the audit chores nobody enjoys. New utilities ship every few weeks.
            </p>
          </div>
          <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">
            {liveCount} live · {UTILITIES.length - liveCount} coming soon
          </Badge>
        </div>

        <div className="mt-7 grid sm:grid-cols-2 lg:grid-cols-3 gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden" data-testid="utilities-grid">
          {UTILITIES.map((u) => (
            <UtilityCard key={u.id} utility={u} onOpen={onOpen}/>
          ))}
        </div>

        <p className="mt-6 text-[12px] text-[#8A8A83] font-mono">
          Have a utility you'd like to see prioritised? Mention it in the next partner sync.
        </p>
      </div>
    </AppShell>
  );
}
