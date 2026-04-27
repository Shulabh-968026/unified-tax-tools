import { useEffect, useMemo, useRef, useState } from "react";
import { Download, Save, UploadCloud, Search, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, MSME_API as API } from "@/lib/msme-api";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const SECTORS = ["", "Manufacturing", "Services", "Trading"];
const TYPES = ["", "Micro", "Small", "Medium"];
const YN = ["", "Yes", "No"];

export default function ProfilesEditor({ session, onUpdated }) {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    setRows((session?.profiles || []).map((p) => ({ ...p })));
  }, [session?.id, session?.profiles]);

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return rows;
    return rows.filter((r) => (r.ledger_name || "").toLowerCase().includes(f));
  }, [rows, filter]);

  const updateRow = (idx, field, value) => {
    setRows((prev) => {
      const next = [...prev];
      const realIdx = prev.indexOf(filtered[idx]);
      next[realIdx] = { ...next[realIdx], [field]: value };
      return next;
    });
  };

  const save = async () => {
    if (!session?.id) return;
    setBusy(true);
    try {
      await api.put(`/sessions/${session.id}/profiles`, { profiles: rows });
      toast.success("Profiles saved");
      onUpdated && onUpdated();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = () => {
    if (!session?.id) return;
    window.location.href = `${API}/sessions/${session.id}/template`;
  };

  const uploadProfileXlsx = async (file) => {
    if (!file || !session?.id) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/sessions/${session.id}/profiles/upload`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Imported ${data.profile_count} profiles`);
      onUpdated && onUpdated();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const completeness = useMemo(() => {
    const total = rows.length || 1;
    const done = rows.filter(
      (r) => r.sector && r.msme_type && r.capital_goods,
    ).length;
    return { total, done, pct: Math.round((done / total) * 100) };
  }, [rows]);

  return (
    <div className="space-y-4" data-testid="profile-editor-section">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl md:text-2xl font-semibold text-gray-900">
            Step 2 · MSME Profile &amp; Exclusions
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Classify each creditor. Disallowance auto-zeros for{" "}
            <span className="font-semibold text-gray-900">Trading</span>,{" "}
            <span className="font-semibold text-gray-900">Medium</span>, or{" "}
            <span className="font-semibold text-gray-900">Capital Goods / Fund Creditor = Yes</span>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={downloadTemplate}
            className="btn-outline-swiss flex items-center gap-2"
            data-testid="download-template-btn"
            disabled={!session?.has_yearend}
          >
            <Download size={14} /> Download Template
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            className="btn-outline-swiss flex items-center gap-2"
            data-testid="upload-profiles-btn"
            disabled={!session?.has_yearend}
          >
            <UploadCloud size={14} /> Upload Filled
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => uploadProfileXlsx(e.target.files?.[0])}
            data-testid="profiles-file-input"
          />
          <button
            onClick={save}
            className="btn-primary-swiss flex items-center gap-2"
            data-testid="save-profiles-btn"
            disabled={busy || !rows.length}
          >
            {busy ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
            Save
          </button>
        </div>
      </div>

      {!session?.has_yearend ? (
        <div className="border border-gray-200 bg-gray-50 rounded-sm p-6 text-sm text-gray-600 text-center">
          Upload the year-end Excel first to populate the creditor list.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 justify-between">
            <div className="relative max-w-xs w-full">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search creditor…"
                className="pl-9 rounded-sm"
                data-testid="profile-search-input"
              />
            </div>
            <div className="text-xs text-gray-600 font-mono">
              <span data-testid="profile-completeness">
                {completeness.done}/{completeness.total} classified ({completeness.pct}%)
              </span>
            </div>
          </div>

          <div className="border border-gray-200 rounded-sm overflow-hidden">
            <div className="max-h-[560px] overflow-auto">
              <table className="audit-table" data-testid="profile-grid">
                <thead>
                  <tr>
                    <th style={{ width: "30%" }}>Creditor</th>
                    <th style={{ width: "18%" }}>MSME Number</th>
                    <th style={{ width: "16%" }}>Sector</th>
                    <th style={{ width: "16%" }}>MSME Type</th>
                    <th style={{ width: "20%" }}>Capital Goods / Fund Creditor</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row, i) => (
                    <tr key={`${row.ledger_name}-${i}`} data-testid={`profile-row-${i}`}>
                      <td className="font-medium">{row.ledger_name}</td>
                      <td>
                        <Input
                          value={row.msme_number || ""}
                          onChange={(e) => updateRow(i, "msme_number", e.target.value)}
                          placeholder="UDYAM-…"
                          className="h-8 rounded-sm font-mono text-xs"
                          data-testid={`profile-msme-${i}`}
                        />
                      </td>
                      <td>
                        <Select
                          value={row.sector || ""}
                          onValueChange={(v) => updateRow(i, "sector", v === "__none__" ? "" : v)}
                        >
                          <SelectTrigger className="h-8 rounded-sm text-xs" data-testid={`profile-sector-${i}`}>
                            <SelectValue placeholder="—" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__">—</SelectItem>
                            {SECTORS.filter(Boolean).map((s) => (
                              <SelectItem key={s} value={s}>{s}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td>
                        <Select
                          value={row.msme_type || ""}
                          onValueChange={(v) => updateRow(i, "msme_type", v === "__none__" ? "" : v)}
                        >
                          <SelectTrigger className="h-8 rounded-sm text-xs" data-testid={`profile-type-${i}`}>
                            <SelectValue placeholder="—" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__">—</SelectItem>
                            {TYPES.filter(Boolean).map((s) => (
                              <SelectItem key={s} value={s}>{s}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td>
                        <Select
                          value={row.capital_goods || ""}
                          onValueChange={(v) => updateRow(i, "capital_goods", v === "__none__" ? "" : v)}
                        >
                          <SelectTrigger className="h-8 rounded-sm text-xs" data-testid={`profile-capital-${i}`}>
                            <SelectValue placeholder="—" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__">—</SelectItem>
                            {YN.filter(Boolean).map((s) => (
                              <SelectItem key={s} value={s}>{s}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-center text-gray-500 py-8 text-sm">
                        No creditors match.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
