/**
 * ClientLibraryPanel — central per-engagement file store UI.
 *
 * Renders one chip per file-type (from the backend catalog) showing
 * upload status + version metadata.  Auditor uploads / replaces /
 * downloads / soft-deletes from here, and every utility tile below
 * picks up the freshness changes in real-time (through the parent's
 * `onChange` callback that re-fetches `library_status`).
 *
 * Design choice (Option C from product discussion 2026-05-04): the
 * Library is shown above the Utilities Catalog AND each utility's
 * Import step is Library-aware — both write to the same store.  This
 * panel is the central / engagement-health view; the module-side
 * upload chips are the fast-path view.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  CheckCircle, Circle, WarningCircle, ArrowClockwise, UploadSimple,
  DownloadSimple, Trash, Folder, Lightning,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import {
  getLibraryStatus, uploadLibraryFile, deleteLibraryFile,
  downloadLibraryFileUrl,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const PERIOD_PRESETS = ["2024-25", "2023-24", "2022-23", "2021-22", "2020-21"];

export default function ClientLibraryPanel({
  clientId, divisions = [],
  initialPeriod = "2023-24",
  onChange,
}) {
  const [period, setPeriod] = useState(initialPeriod);
  const [division, setDivision] = useState(divisions[0]?.division_id || "");
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);
  const [showSecondary, setShowSecondary] = useState(false);
  const fileInputs = useRef({});

  const refresh = async () => {
    setLoading(true);
    try {
      const s = await getLibraryStatus(clientId, period, division || null);
      setStatus(s);
      onChange?.(s);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load library");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh(); /* eslint-disable-next-line */
  }, [clientId, period, division]);

  const onPickFile = (fileType) => (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    onUpload(file, fileType);
    e.target.value = "";  // reset for re-upload of same name
  };

  const onUpload = async (file, fileType) => {
    setBusyKey(fileType);
    try {
      await uploadLibraryFile({
        file, clientId, period, division: division || null, fileType,
      });
      toast.success(`${fileType.replace(/_/g, " ")} uploaded`);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusyKey(null);
    }
  };

  const onDelete = async (fileType, fileId) => {
    if (!confirm("Soft-delete this file? It will be auto-pruned in 30 days unless restored.")) return;
    setBusyKey(fileType);
    try {
      await deleteLibraryFile(fileId);
      toast.success("File soft-deleted (30-day grace)");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally {
      setBusyKey(null);
    }
  };

  const triggerInput = (fileType) => fileInputs.current[fileType]?.click();

  const primary = useMemo(
    () => (status?.files || []).filter((f) => f.kind === "primary"),
    [status],
  );
  const secondary = useMemo(
    () => (status?.files || []).filter((f) => f.kind === "secondary"),
    [status],
  );
  const completeness = useMemo(() => {
    const all = status?.files || [];
    const required = all.filter((f) => f.kind === "primary");
    const have = required.filter((f) => f.uploaded).length;
    return { have, total: required.length };
  }, [status]);

  return (
    <section
      data-testid="client-library-panel"
      className="border border-[#E5E5E0] bg-white rounded-sm overflow-hidden"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#E5E5E0] bg-[#FAFAF7] flex items-center gap-3 flex-wrap">
        <Folder size={16} className="text-[#52524E]"/>
        <h3 className="font-heading text-base tracking-tight">Client Library</h3>
        <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">
          Source files for every utility · upload once · pinned to runs
        </span>
        <div className="ml-auto flex items-center gap-3">
          <Badge
            data-testid="library-completeness"
            className={`rounded-sm shadow-none border font-mono text-[10px] uppercase tracking-[0.12em] ${
              completeness.have === completeness.total
                ? "bg-emerald-50 text-emerald-900 border-emerald-200"
                : "bg-amber-50 text-amber-900 border-amber-200"
            }`}
          >
            {completeness.have} of {completeness.total} primary uploaded
          </Badge>
          <button
            onClick={refresh}
            data-testid="library-refresh"
            className="inline-flex items-center gap-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] hover:text-[#0F172A]"
            title="Refresh library status"
          >
            <ArrowClockwise size={12}/> Refresh
          </button>
        </div>
      </div>

      {/* Period + Division selectors */}
      <div className="px-5 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">For</span>
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger data-testid="library-period-select" className="h-8 w-[140px] rounded-sm shadow-none border-[#D4D4D0] text-xs font-mono"><SelectValue/></SelectTrigger>
          <SelectContent>
            {PERIOD_PRESETS.map((p) => (
              <SelectItem key={p} value={p} data-testid={`library-period-${p}`}>FY {p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {divisions.length > 1 && (
          <>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">·</span>
            <Select value={division || "all"} onValueChange={(v) => setDivision(v === "all" ? "" : v)}>
              <SelectTrigger data-testid="library-division-select" className="h-8 w-[180px] rounded-sm shadow-none border-[#D4D4D0] text-xs font-mono"><SelectValue/></SelectTrigger>
              <SelectContent>
                <SelectItem value="all" data-testid="library-division-all">All divisions</SelectItem>
                {divisions.map((d) => (
                  <SelectItem key={d.division_id} value={d.division_id} data-testid={`library-division-${d.division_id}`}>{d.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        )}
      </div>

      {/* File chips */}
      {loading && !status ? (
        <div className="p-8 text-center text-sm text-[#8A8A83] font-mono">Loading library…</div>
      ) : (
        <div>
          <FileGrid
            label="Primary inputs · required by most utilities"
            files={primary}
            busyKey={busyKey}
            fileInputs={fileInputs}
            onPickFile={onPickFile}
            triggerInput={triggerInput}
            onDelete={onDelete}
          />
          <button
            onClick={() => setShowSecondary((v) => !v)}
            data-testid="library-toggle-secondary"
            className="w-full px-5 py-2 border-t border-[#E5E5E0] bg-[#FAFAF7] hover:bg-[#F3F4F1] font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#52524E] text-left"
          >
            {showSecondary ? "▾" : "▸"} Secondary inputs · {secondary.length} ({secondary.filter((f) => f.uploaded).length} uploaded)
          </button>
          {showSecondary && (
            <FileGrid
              files={secondary}
              busyKey={busyKey}
              fileInputs={fileInputs}
              onPickFile={onPickFile}
              triggerInput={triggerInput}
              onDelete={onDelete}
            />
          )}
        </div>
      )}
    </section>
  );
}

function FileGrid({ label, files, busyKey, fileInputs, onPickFile, triggerInput, onDelete }) {
  return (
    <div>
      {label && (
        <div className="px-5 pt-3 pb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-[#8A8A83]">
          {label}
        </div>
      )}
      <ul className="divide-y divide-[#E5E5E0]">
        {files.map((f) => (
          <FileChipRow
            key={f.key}
            file={f}
            busy={busyKey === f.key}
            inputRef={(el) => (fileInputs.current[f.key] = el)}
            onPick={onPickFile(f.key)}
            onUploadClick={() => triggerInput(f.key)}
            onDelete={onDelete}
          />
        ))}
      </ul>
    </div>
  );
}

function FileChipRow({ file, busy, inputRef, onPick, onUploadClick, onDelete }) {
  const isUploaded = file.uploaded;
  return (
    <li
      data-testid={`library-file-${file.key}`}
      className="px-5 py-3 flex items-start gap-4 hover:bg-[#F9F9F8]"
    >
      <div className="mt-0.5">
        {isUploaded ? (
          <CheckCircle size={16} weight="duotone" className="text-emerald-700"/>
        ) : (
          <Circle size={16} className="text-[#D4D4D0]"/>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13.5px] font-medium">{file.label}</span>
          {isUploaded && (
            <Badge className="bg-slate-50 text-slate-700 border border-slate-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0">
              v{file.version_no}
            </Badge>
          )}
          {file.kind === "primary" && !isUploaded && (
            <Badge className="bg-rose-50 text-rose-900 border border-rose-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0">
              Required
            </Badge>
          )}
        </div>
        <div className="font-mono text-[10.5px] tracking-[0.06em] text-[#8A8A83] mt-0.5 truncate">
          {isUploaded ? (
            <>
              {file.filename_original} · {(file.size_bytes / 1024).toFixed(0)} KB
              · uploaded {formatDateTime(file.uploaded_at)}
              {file.uploaded_by_email ? ` by ${file.uploaded_by_email}` : ""}
            </>
          ) : (
            file.description
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          ref={inputRef}
          type="file"
          accept={file.ext.join(",")}
          onChange={onPick}
          className="hidden"
          data-testid={`library-file-input-${file.key}`}
        />
        {isUploaded && (
          <a
            href={downloadLibraryFileUrl(file.file_id)}
            data-testid={`library-download-${file.key}`}
            className="h-8 w-8 grid place-items-center border border-[#E5E5E0] rounded-sm bg-white hover:bg-[#F3F4F1] text-[#52524E]"
            title="Download current version"
          >
            <DownloadSimple size={13}/>
          </a>
        )}
        <Button
          data-testid={`library-upload-${file.key}`}
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={onUploadClick}
          className="h-8 px-2.5 rounded-sm shadow-none border-[#D4D4D0] font-mono text-[10.5px] uppercase tracking-[0.12em]"
        >
          {busy ? <><Lightning size={11} className="animate-pulse mr-1"/> Uploading</> : (
            <>
              <UploadSimple size={11} className="mr-1"/> {isUploaded ? "Replace" : "Upload"}
            </>
          )}
        </Button>
        {isUploaded && (
          <button
            onClick={() => onDelete(file.key, file.file_id)}
            data-testid={`library-delete-${file.key}`}
            className="h-8 w-8 grid place-items-center border border-[#E5E5E0] rounded-sm bg-white hover:bg-rose-50 hover:border-rose-200 hover:text-rose-700 text-[#52524E]"
            title="Soft-delete (30-day grace)"
          >
            <Trash size={12}/>
          </button>
        )}
      </div>
    </li>
  );
}

// Re-export the small helpers if a parent wants them.
export { WarningCircle };
