/**
 * Phase A — GSTIN Groups Manager (multi-division support).
 *
 * Lets the auditor define labelled groups of divisions sharing a single
 * GST registration.  Used by the GST Recon module (Phase C) and as a
 * scope option in the page-level Working Period selector (Phase B).
 *
 * Visible only when the client has 2 or more divisions.
 */
import { useEffect, useState } from "react";
import { http } from "@/lib/api";
import { toast } from "sonner";
import {
  Plus, Trash2, Pencil, Check, X, Loader2, Building2,
} from "lucide-react";

const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

export default function GstinGroupsManager({ clientId, divisions = [] }) {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({ label: "", gstin: "", division_ids: [] });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await http.get(`/library/clients/${clientId}/gstin-groups`);
      setGroups(data?.groups || []);
    } catch (e) {
      toast.error("Could not load GSTIN groups");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { if (clientId && divisions.length >= 2) load(); }, [clientId, divisions.length]);  // eslint-disable-line

  // Hide entirely for single-division (or zero-division) clients.
  if (divisions.length < 2) return null;

  const startCreate = () => {
    setEditingId(null);
    setDraft({ label: "", gstin: "", division_ids: [] });
    setAdding(true);
  };
  const startEdit = (g) => {
    setAdding(false);
    setEditingId(g.group_id);
    setDraft({ label: g.label, gstin: g.gstin || "", division_ids: [...g.division_ids] });
  };
  const cancel = () => { setAdding(false); setEditingId(null); setDraft({ label: "", gstin: "", division_ids: [] }); };

  const save = async () => {
    const label = (draft.label || "").trim();
    const gstin = (draft.gstin || "").trim().toUpperCase();
    if (!label) return toast.error("Label is required");
    if (gstin && !GSTIN_RE.test(gstin)) return toast.error("Invalid GSTIN format (expect 15-char pattern e.g. 27ABCDE1234F1Z5)");
    if (!draft.division_ids.length) return toast.error("Select at least one division");
    setBusy(true);
    try {
      const payload = { label, gstin, division_ids: draft.division_ids };
      if (editingId) {
        await http.patch(`/library/clients/${clientId}/gstin-groups/${editingId}`, payload);
        toast.success("Group updated");
      } else {
        await http.post(`/library/clients/${clientId}/gstin-groups`, payload);
        toast.success("Group created");
      }
      cancel();
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (g) => {
    if (!window.confirm(`Delete GSTIN group "${g.label}"?`)) return;
    setBusy(true);
    try {
      await http.delete(`/library/clients/${clientId}/gstin-groups/${g.group_id}`);
      toast.success("Group deleted");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleDiv = (divId) => {
    setDraft((d) => ({
      ...d,
      division_ids: d.division_ids.includes(divId)
        ? d.division_ids.filter((x) => x !== divId)
        : [...d.division_ids, divId],
    }));
  };

  return (
    <div
      className="border border-[#E5E5E0] bg-white p-5 mt-6"
      data-testid="gstin-groups-manager"
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[#8A8A83] inline-flex items-center gap-1.5">
            <Building2 size={12}/> GSTIN Groups
          </div>
          <h3 className="text-sm font-semibold mt-1">
            Group divisions sharing a GST registration
          </h3>
          <p className="text-[11.5px] text-[#6B7280] mt-0.5 max-w-prose">
            Define one group per GSTIN. The GST Reconciliation module
            (and other module rolls-ups in upcoming releases) will
            operate on these groups instead of individual divisions.
          </p>
        </div>
        {!adding && !editingId && (
          <button
            onClick={startCreate}
            className="text-xs px-3 h-8 rounded-sm border border-[#0F172A] text-[#0F172A] inline-flex items-center gap-1.5 hover:bg-[#0F172A] hover:text-white transition-colors"
            data-testid="gstin-group-add-btn"
          >
            <Plus size={12}/> Add group
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-xs text-gray-500 py-4 inline-flex items-center gap-2">
          <Loader2 size={12} className="animate-spin"/> Loading groups…
        </div>
      ) : (
        <>
          {/* Existing groups */}
          {groups.length > 0 && (
            <ul className="divide-y divide-[#F0F0EC]" data-testid="gstin-groups-list">
              {groups.map((g) => (
                <li key={g.group_id} className="py-3" data-testid={`gstin-group-row-${g.group_id}`}>
                  {editingId === g.group_id ? (
                    <EditForm
                      draft={draft} setDraft={setDraft}
                      divisions={divisions} toggleDiv={toggleDiv}
                      onSave={save} onCancel={cancel} busy={busy}
                    />
                  ) : (
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[13px] font-medium text-[#0F172A]">
                          {g.label}
                          {g.gstin && (
                            <span className="ml-2 font-mono text-[10.5px] px-1.5 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-sm">
                              {g.gstin}
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-[#6B7280] mt-1 flex flex-wrap gap-1.5">
                          {g.division_ids.map((id) => {
                            const d = divisions.find((x) => x.division_id === id);
                            return (
                              <span
                                key={id}
                                className="inline-block px-2 py-0.5 bg-[#F8F8F5] border border-[#E5E5E0] text-[#0F172A] font-mono text-[10.5px]"
                              >
                                {d?.name || id}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          onClick={() => startEdit(g)}
                          className="p-1.5 text-gray-500 hover:text-[#0F172A] hover:bg-gray-100 rounded-sm"
                          data-testid={`gstin-group-edit-${g.group_id}`}
                        >
                          <Pencil size={13}/>
                        </button>
                        <button
                          onClick={() => remove(g)}
                          className="p-1.5 text-gray-500 hover:text-rose-700 hover:bg-rose-50 rounded-sm"
                          data-testid={`gstin-group-delete-${g.group_id}`}
                        >
                          <Trash2 size={13}/>
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {/* Inline add form */}
          {adding && (
            <div className="mt-3 pt-3 border-t border-[#F0F0EC]">
              <EditForm
                draft={draft} setDraft={setDraft}
                divisions={divisions} toggleDiv={toggleDiv}
                onSave={save} onCancel={cancel} busy={busy}
                isCreate
              />
            </div>
          )}

          {!loading && !groups.length && !adding && (
            <div className="text-[12px] text-[#6B7280] py-4 italic" data-testid="gstin-groups-empty">
              No GSTIN groups defined yet. Add one for each GST registration the client holds.
            </div>
          )}
        </>
      )}
    </div>
  );
}


function EditForm({ draft, setDraft, divisions, toggleDiv, onSave, onCancel, busy, isCreate = false }) {
  return (
    <div className="space-y-2.5" data-testid="gstin-group-form">
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[10.5px] font-mono uppercase tracking-wider text-[#8A8A83]">Label *</span>
          <input
            type="text" value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            placeholder="e.g. Tamilnadu GSTIN"
            data-testid="gstin-group-label-input"
            className="mt-1 w-full text-[12.5px] px-2.5 py-1.5 border border-[#D4D4D0] rounded-sm focus:outline-none focus:border-[#0F172A]"
          />
        </label>
        <label className="block">
          <span className="text-[10.5px] font-mono uppercase tracking-wider text-[#8A8A83]">GSTIN (optional)</span>
          <input
            type="text" value={draft.gstin}
            onChange={(e) => setDraft({ ...draft, gstin: e.target.value.toUpperCase() })}
            placeholder="33ABCDE1234F1Z5"
            data-testid="gstin-group-gstin-input"
            className="mt-1 w-full text-[12.5px] font-mono px-2.5 py-1.5 border border-[#D4D4D0] rounded-sm focus:outline-none focus:border-[#0F172A]"
          />
        </label>
      </div>
      <div>
        <span className="text-[10.5px] font-mono uppercase tracking-wider text-[#8A8A83]">Divisions in this group *</span>
        <div className="mt-1 flex flex-wrap gap-1.5" data-testid="gstin-group-divisions-picker">
          {divisions.map((d) => {
            const on = draft.division_ids.includes(d.division_id);
            return (
              <button
                key={d.division_id}
                type="button"
                onClick={() => toggleDiv(d.division_id)}
                className={`px-2.5 py-1 text-[11.5px] border rounded-sm font-mono transition-colors ${on
                  ? "bg-[#0F172A] text-white border-[#0F172A]"
                  : "bg-white text-[#0F172A] border-[#D4D4D0] hover:border-[#0F172A]"}`}
                data-testid={`gstin-group-div-${d.division_id}`}
              >
                {on && <Check size={11} className="inline mr-1 -mt-px"/>}
                {d.name}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={onSave}
          disabled={busy}
          className="text-xs px-3 h-8 rounded-sm bg-[#0F172A] text-white inline-flex items-center gap-1.5 hover:bg-[#1F2937] disabled:opacity-50"
          data-testid="gstin-group-save-btn"
        >
          {busy ? <Loader2 size={12} className="animate-spin"/> : <Check size={12}/>}
          {isCreate ? "Create" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={busy}
          className="text-xs px-3 h-8 rounded-sm border border-[#D4D4D0] inline-flex items-center gap-1.5 hover:bg-gray-50 disabled:opacity-50"
          data-testid="gstin-group-cancel-btn"
        >
          <X size={12}/> Cancel
        </button>
      </div>
    </div>
  );
}
