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
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import {
  CheckCircle, Circle, WarningCircle, ArrowClockwise, UploadSimple,
  DownloadSimple, Trash, Folder, Lightning, FileArrowDown, Stack, CaretDown,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import {
  getLibraryStatus, uploadLibraryFile, deleteLibraryFile,
  downloadLibraryFileUrl, downloadLibraryTemplateUrl,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { FY_OPTIONS, DEFAULT_FY } from "@/lib/fy";
import GstinGroupsManager from "@/components/GstinGroupsManager";

const PERIOD_PRESETS = FY_OPTIONS;

export default function ClientLibraryPanel({
  clientId, divisions = [],
  initialPeriod = DEFAULT_FY,
  periodLocked = false,
  onChange,
}) {
  const [period, setPeriod] = useState(initialPeriod);
  // Keep local state in sync when the parent rewires the period
  // (e.g. ClientUtilities FY selector).  Without this effect, the panel
  // would freeze on whatever it picked up at first mount.
  useEffect(() => { setPeriod(initialPeriod); }, [initialPeriod]);
  const [division, setDivision] = useState(divisions[0]?.division_id || "");
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);
  const [showSecondary, setShowSecondary] = useState(true);
  // Per-row attribution overrides (only relevant for multi-div clients).
  // Map { fileType -> string[] | null }.  null = "use default for the
  // catalog entry's `default_attribution`".
  const [attrByKey, setAttrByKey] = useState({});
  const fileInputs = useRef({});
  const isMulti = divisions.length > 1;

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

  // Resolve the effective attribution for a given file row.
  // - Single-div clients: empty array (server defaults to legacy `division`).
  // - Multi-div: per-row override if set, else the catalog's
  //   `default_attribution` rule.
  const resolveAttribution = (file) => {
    if (!isMulti) return [];
    const override = attrByKey[file.key];
    if (Array.isArray(override)) return override;
    const mode = file.default_attribution || "current_division";
    if (mode === "all_divisions") return divisions.map((d) => d.division_id);
    if (mode === "current_division") return division ? [division] : [];
    return [];  // pick_divisions — auditor must pick
  };

  const onUpload = async (file, fileType) => {
    const fileRow = (status?.files || []).find((f) => f.key === fileType);
    const divisionIds = fileRow ? resolveAttribution(fileRow) : [];
    // Multi-div clients with `pick_divisions` files must explicitly pick.
    if (isMulti && (fileRow?.default_attribution === "pick_divisions") && divisionIds.length === 0) {
      toast.error("Please pick at least one division before uploading this file.");
      return;
    }
    setBusyKey(fileType);
    try {
      await uploadLibraryFile({
        file, clientId, period,
        division: division || null,
        divisionIds: isMulti ? divisionIds : null,
        fileType,
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
  const outputs = useMemo(
    () => (status?.files || []).filter((f) => f.kind === "output"),
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

      {/* Period + Division selectors.  The whole row is hidden when the
          period is locked from the page-level Working Period selector AND
          there's no division choice to offer (i.e., single-entity client) —
          showing "For FY 2025-26" twice on the same screen is just noise. */}
      {(!periodLocked || divisions.length > 1) && (
        <div className="px-5 py-3 border-b border-[#E5E5E0] flex items-center gap-3 flex-wrap">
          {!periodLocked && (
            <>
              <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">For</span>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger data-testid="library-period-select" className="h-8 w-[140px] rounded-sm shadow-none border-[#D4D4D0] text-xs font-mono"><SelectValue/></SelectTrigger>
                <SelectContent>
                  {PERIOD_PRESETS.map((p) => (
                    <SelectItem key={p} value={p} data-testid={`library-period-${p}`}>FY {p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          )}
          {divisions.length > 1 && (
            <>
              {!periodLocked && <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">·</span>}
              <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#8A8A83]">Division</span>
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
      )}

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
            clientId={clientId}
            period={period}
            division={division}
            divisions={divisions}
            isMulti={isMulti}
            attrByKey={attrByKey}
            setAttrByKey={setAttrByKey}
            resolveAttribution={resolveAttribution}
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
              clientId={clientId}
              period={period}
              division={division}
              divisions={divisions}
              isMulti={isMulti}
              attrByKey={attrByKey}
              setAttrByKey={setAttrByKey}
              resolveAttribution={resolveAttribution}
            />
          )}
          {outputs.length > 0 && (
            <div className="border-t border-[#E5E5E0]">
              <div className="px-5 py-2 bg-[#FAFAF7] font-mono text-[10.5px] uppercase tracking-[0.16em] text-[#8A8A83]">
                Generated reports · produced by utilities
              </div>
              <FileGrid
                files={outputs}
                busyKey={busyKey}
                fileInputs={fileInputs}
                onPickFile={onPickFile}
                triggerInput={triggerInput}
                onDelete={onDelete}
                clientId={clientId}
                period={period}
                division={division}
                divisions={divisions}
                isMulti={isMulti}
                attrByKey={attrByKey}
                setAttrByKey={setAttrByKey}
                resolveAttribution={resolveAttribution}
              />
            </div>
          )}
        </div>
      )}
      <GstinGroupsManager clientId={clientId} divisions={divisions} />
    </section>
  );
}

function FileGrid({ label, files, busyKey, fileInputs, onPickFile, triggerInput, onDelete, clientId, period, division, divisions, isMulti, attrByKey, setAttrByKey, resolveAttribution }) {
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
            clientId={clientId}
            period={period}
            division={division}
            divisions={divisions}
            isMulti={isMulti}
            attrByKey={attrByKey}
            setAttrByKey={setAttrByKey}
            resolveAttribution={resolveAttribution}
          />
        ))}
      </ul>
    </div>
  );
}

function FileChipRow({ file, busy, inputRef, onPick, onUploadClick, onDelete, clientId, period, division, divisions, isMulti, attrByKey, setAttrByKey, resolveAttribution }) {
  const isUploaded = file.uploaded;
  const isOutput = file.kind === "output";
  const templateUrl = file.has_template
    ? downloadLibraryTemplateUrl(clientId, file.key, period, division || null)
    : null;
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
          {isOutput && (
            <Badge className="bg-violet-50 text-violet-900 border border-violet-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0">
              Generated
            </Badge>
          )}
          {isOutput && !isUploaded && (
            <Badge className="bg-slate-50 text-slate-600 border border-slate-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0">
              Awaiting computation
            </Badge>
          )}
          {file.has_template && (
            <Badge className="bg-sky-50 text-sky-900 border border-sky-200 rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0" title="A pre-populated template can be auto-generated for this file">
              Auto-template
            </Badge>
          )}
        </div>
        <div className="font-mono text-[10.5px] tracking-[0.06em] text-[#8A8A83] mt-0.5 truncate">
          {isUploaded ? (
            <>
              {file.filename_original} · {(file.size_bytes / 1024).toFixed(0)} KB
              · {isOutput ? "generated" : "uploaded"} {formatDateTime(file.uploaded_at)}
              {file.uploaded_by_email && !isOutput ? ` by ${file.uploaded_by_email}` : ""}
            </>
          ) : (
            file.description
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {!isOutput && isMulti && (
          <AttributionControl
            file={file}
            divisions={divisions}
            division={division}
            value={attrByKey[file.key]}
            resolved={resolveAttribution(file)}
            onChange={(next) => setAttrByKey((m) => ({ ...m, [file.key]: next }))}
          />
        )}
        {!isOutput && (
          <input
            ref={inputRef}
            type="file"
            accept={file.ext.join(",")}
            onChange={onPick}
            className="hidden"
            data-testid={`library-file-input-${file.key}`}
          />
        )}
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
        {/* Download Template — only for file_types with a registered
            generator (Party Master today; FA Register / Bank Statements
            etc. follow the same pattern in future). */}
        {templateUrl && !isOutput && (
          <a
            href={templateUrl}
            data-testid={`library-template-${file.key}`}
            className="h-8 inline-flex items-center gap-1 px-2.5 border border-sky-200 rounded-sm bg-sky-50 hover:bg-sky-100 text-sky-900 font-mono text-[10.5px] uppercase tracking-[0.12em]"
            title="Download a pre-populated template — fill the gaps offline and re-upload"
          >
            <FileArrowDown size={11}/> Template
          </a>
        )}
        {!isOutput && (
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
        )}
        {isUploaded && !isOutput && (
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

/**
 * AttributionControl — small popover trigger shown on every Library
 * row for multi-division clients.  Lets the auditor scope the upload
 * to one or more specific divisions, all divisions, or just the
 * currently-selected division.  The default selection follows the
 * file_type's `default_attribution` rule from the catalog.
 */
function AttributionControl({ file, divisions, division, value, resolved, onChange }) {
  const allIds = divisions.map((d) => d.division_id);
  const sel = Array.isArray(value) ? value : resolved;
  const isAll = sel.length === allIds.length && allIds.length > 0;

  // Persisted attribution from server (existing uploads).  Show as a
  // muted hint so auditor knows what's currently saved.
  const persisted = file.division_ids || [];

  const label = (() => {
    if (sel.length === 0) return "Pick divisions…";
    if (isAll) return "All divisions";
    if (sel.length === 1) {
      const d = divisions.find((x) => x.division_id === sel[0]);
      return d?.name || "1 division";
    }
    return `${sel.length} divisions`;
  })();

  const toggle = (id) => {
    const cur = new Set(sel);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    onChange(Array.from(cur).sort());
  };

  const tone =
    sel.length === 0
      ? "bg-rose-50 text-rose-900 border-rose-200"
      : isAll
      ? "bg-emerald-50 text-emerald-900 border-emerald-200"
      : "bg-slate-50 text-slate-800 border-slate-200";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          data-testid={`library-attribution-${file.key}`}
          className={`h-8 inline-flex items-center gap-1 px-2 border rounded-sm font-mono text-[10.5px] uppercase tracking-[0.12em] hover:opacity-90 ${tone}`}
          title={`Attribution for ${file.label}`}
          type="button"
        >
          <Stack size={11}/>
          <span className="max-w-[110px] truncate">{label}</span>
          <CaretDown size={9}/>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-0">
        <div className="px-3 py-2 border-b border-[#E5E5E0] bg-[#FAFAF7]">
          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#8A8A83]">
            Attribute to divisions
          </div>
          <div className="text-[11.5px] text-[#52524E] mt-0.5 leading-snug">
            Default for this file: <span className="font-mono">{(file.default_attribution || "current_division").replace("_", " ")}</span>
          </div>
        </div>
        <div className="max-h-64 overflow-auto">
          <button
            type="button"
            data-testid={`library-attribution-${file.key}-all`}
            onClick={() => onChange(isAll ? [] : allIds)}
            className="w-full text-left px-3 py-2 text-[12.5px] hover:bg-[#F3F4F1] flex items-center gap-2 border-b border-[#E5E5E0]"
          >
            <span className={`w-3 h-3 border ${isAll ? "bg-[#0F172A] border-[#0F172A]" : "border-[#D4D4D0]"}`}/>
            <span className="font-medium">All divisions</span>
          </button>
          {divisions.map((d) => {
            const checked = sel.includes(d.division_id);
            return (
              <button
                type="button"
                key={d.division_id}
                data-testid={`library-attribution-${file.key}-div-${d.division_id}`}
                onClick={() => toggle(d.division_id)}
                className="w-full text-left px-3 py-2 text-[12.5px] hover:bg-[#F3F4F1] flex items-center gap-2"
              >
                <span className={`w-3 h-3 border ${checked ? "bg-[#0F172A] border-[#0F172A]" : "border-[#D4D4D0]"}`}/>
                <span className="flex-1 truncate">{d.name}</span>
                {division === d.division_id && (
                  <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-[#8A8A83]">current</span>
                )}
              </button>
            );
          })}
        </div>
        {persisted.length > 0 && (
          <div className="px-3 py-2 border-t border-[#E5E5E0] bg-[#FAFAF7] font-mono text-[10px] tracking-[0.06em] text-[#8A8A83]">
            Saved: {persisted.length === allIds.length ? "All divisions" : `${persisted.length} division${persisted.length === 1 ? "" : "s"}`}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
