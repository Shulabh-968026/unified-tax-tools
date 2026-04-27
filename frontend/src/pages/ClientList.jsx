import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { listClients, archiveClient } from "@/lib/api";
import CreateClientDialog from "@/pages/CreateClientDialog";
import { Plus, MagnifyingGlass, Buildings, ArrowRight, Stack, Archive, ArrowCounterClockwise } from "@phosphor-icons/react";
import { formatDate } from "@/lib/format";
import { toast } from "sonner";

export default function ClientList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openCreate, setOpenCreate] = useState(false);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState("active"); // active | archived

  const refresh = async () => {
    setLoading(true);
    try {
      const d = await listClients(tab === "archived");
      setClients(d.clients || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [tab]);

  const filtered = clients.filter((c) => {
    if (!q.trim()) return true;
    const s = q.toLowerCase();
    return (c.name || "").toLowerCase().includes(s) || (c.file_number || "").toLowerCase().includes(s);
  });

  const onArchive = async (e, id, archived) => {
    e.stopPropagation();
    try {
      await archiveClient(id, !archived);
      toast.success(archived ? "Client unarchived" : "Client archived");
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action failed");
    }
  };

  return (
    <AppShell>
      <PageHeader
        eyebrow="Workspace"
        title="Select a Client"
        subtitle="Pick a client to open the utilities catalog. Active clients show up first; archived clients live behind the toggle."
        actions={
          <Button data-testid="open-create-client-btn" onClick={() => setOpenCreate(true)} className="h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2">
            <Plus size={14} weight="bold"/> New Client
          </Button>
        }
      />
      <div className="px-6 md:px-10 py-8 pb-40 max-w-6xl">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1 border border-[#E5E5E0] rounded-sm bg-white p-1" data-testid="clients-tabs">
            <button
              data-testid="clients-tab-active"
              className={`px-3 h-8 font-mono text-[11px] uppercase tracking-[0.12em] rounded-sm ${tab === "active" ? "bg-[#0F172A] text-white" : "text-[#52524E] hover:text-[#0F172A]"}`}
              onClick={() => setTab("active")}
            >Active</button>
            <button
              data-testid="clients-tab-archived"
              className={`px-3 h-8 font-mono text-[11px] uppercase tracking-[0.12em] rounded-sm ${tab === "archived" ? "bg-[#0F172A] text-white" : "text-[#52524E] hover:text-[#0F172A]"}`}
              onClick={() => setTab("archived")}
            >Archived</button>
          </div>

          <div className="flex items-center gap-3 border border-[#E5E5E0] bg-white rounded-sm px-3 h-10 max-w-md flex-1">
            <MagnifyingGlass size={14} className="text-[#8A8A83]"/>
            <Input
              data-testid="client-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by client name or file no."
              className="h-9 border-0 shadow-none focus-visible:ring-0 px-0 text-sm"
            />
          </div>
        </div>

        {loading ? (
          <div className="mt-12 font-mono text-sm text-[#8A8A83]">Loading clients…</div>
        ) : filtered.length === 0 ? (
          <div className="mt-10 border border-dashed border-[#D4D4D0] bg-white rounded-sm p-10 text-center">
            <Buildings size={28} className="mx-auto text-[#8A8A83]" weight="duotone"/>
            <div className="mt-3 font-heading text-lg">{tab === "archived" ? "No archived clients" : "No clients yet"}</div>
            <p className="mt-1 text-sm text-[#52524E]">{tab === "archived" ? "Archived clients you can restore will appear here." : "Add your first client to begin building a Clause 44 schedule."}</p>
            {tab !== "archived" && (
              <Button data-testid="empty-add-client-btn" onClick={() => setOpenCreate(true)} className="mt-4 h-10 px-4 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2">
                <Plus size={14} weight="bold"/> Add Client
              </Button>
            )}
          </div>
        ) : (
          <ul className="mt-6 grid gap-px bg-[#E5E5E0] border border-[#E5E5E0] rounded-sm overflow-hidden" data-testid="clients-list">
            {filtered.map((c) => (
              <li key={c.client_id}>
                <div
                  className="bg-white px-5 py-4 hover:bg-[#F9F9F8] transition-colors flex items-center gap-5"
                >
                  <button
                    data-testid={`client-card-${c.client_id}`}
                    onClick={() => navigate(`/dashboard/clients/${c.client_id}`)}
                    disabled={tab === "archived"}
                    className="flex items-center gap-5 flex-1 min-w-0 text-left disabled:cursor-not-allowed"
                  >
                    <div className="w-9 h-9 border border-[#E5E5E0] grid place-items-center text-[#52524E]">
                      {c.type === "multi" ? <Stack size={16}/> : <Buildings size={16}/>}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-[15px]">{c.name}</span>
                        <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">
                          File · {c.file_number}
                        </Badge>
                        <Badge className={`${c.type === "multi" ? "bg-amber-50 text-amber-900 border-amber-200" : "bg-emerald-50 text-emerald-900 border-emerald-200"} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
                          {c.type === "multi" ? `Multi · ${c.divisions?.length || 0} div` : "Single"}
                        </Badge>
                        {c.archived && (
                          <Badge className="bg-[#F3F4F1] text-[#52524E] border-[#D4D4D0] rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]">Archived</Badge>
                        )}
                      </div>
                      <div className="mt-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#8A8A83]">
                        Created {formatDate(c.created_at)}
                      </div>
                    </div>
                    {tab !== "archived" && <ArrowRight size={16} weight="bold" className="text-[#8A8A83]"/>}
                  </button>
                  <button
                    data-testid={`archive-toggle-${c.client_id}`}
                    onClick={(e) => onArchive(e, c.client_id, c.archived)}
                    title={c.archived ? "Restore" : "Archive"}
                    className="text-[#8A8A83] hover:text-[#0F172A] p-1.5 border border-transparent hover:border-[#E5E5E0] rounded-sm shrink-0"
                  >
                    {c.archived ? <ArrowCounterClockwise size={14}/> : <Archive size={14}/>}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <CreateClientDialog open={openCreate} onOpenChange={setOpenCreate} onCreated={(c) => { refresh(); navigate(`/dashboard/clients/${c.client_id}`); }} />
    </AppShell>
  );
}
