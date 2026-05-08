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
  DownloadSimple, Trash, Folder, Lightning, FileArrowDown, Stack,
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

/**
 * Map a file's catalog ``default_attribution`` to the page-level scope
 * that's allowed to upload it.  Phase D refinement (2026-05-07) — the
 * page-level Scope is the SOLE control; per-row dropdowns are gone and
 * rows are masked when the auditor's current scope can't upload them.
 */
const ATTR_TO_SCOPE = {
  current_division: "division",
  all_divisions:    "consolidation",
  pick_divisions:   "gstin_group",
};

const SCOPE_LABEL = {
  division:      "Division",
  consolidation: "Consolidation",
  gstin_group:   "GSTIN group",
};

export default function ClientLibraryPanel({
  clientId, divisions = [],
  initialPeriod = DEFAULT_FY,
  periodLocked = false,
  scope = null,           // { scopeKind, divisionIds, gstinGroupId, scopeLabel } from ClientUtilities
  onChange,
}) {
  const [period, setPeriod] = useState(initialPeriod);
  // Keep local state in sync when the parent rewires the period
  // (e.g. ClientUtilities FY selector).  Without this effect, the panel
  // would freeze on whatever it picked up at first mount.
  useEffect(() => { setPeriod(initialPeriod); }, [initialPeriod]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);
  const [showSecondary, setShowSecondary] = useState(true);
  const fileInputs = useRef({});
  const isMulti = divisions.length > 1;

  // Phase D — all uploads are scoped from the page-level Scope selector.
  // Single-div clients: no scope passed → behave as today (consolidation).
  // The shape of `scope` follows ``decodeScope()`` from ``@/lib/scope``:
  //   { kind: "consolidation" | "division" | "gstin_group", id, label,
  //     divisions: [string] }
  const pageScopeKind = scope?.kind || "consolidation";
  const pageDivisionIds = Array.isArray(scope?.divisions) ? scope.divisions : [];
  // The single division id used for back-compat ``division`` query (used
  // by the GET /status call to pin the legacy per-division view).
  const division = pageScopeKind === "division" ? (pageDivisionIds[0] || "") : "";

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

  /**
   * Phase D — derive division_ids for an upload purely from the
   * page-level scope.  Per-row picking is gone.
   *
   * - scope=division     → [<division_id>]
   * - scope=consolidation → every division on the client (same as
   *                          legacy "all_divisions" attribution)
   * - scope=gstin_group  → divisions belonging to the chosen GSTIN
   *                          group (looked up via the group on the
   *                          client doc).  If unavailable, falls back
   *                          to all divisions so the upload still works.
   */
  const resolveAttribution = () => {
    if (!isMulti) return [];
    if (pageScopeKind === "division") return pageDivisionIds.slice();
    if (pageScopeKind === "consolidation") return divisions.map((d) => d.division_id);
    if (pageScopeKind === "gstin_group") {
      // Best-effort: the GSTIN group's division membership lives on the
      // group doc itself (Phase A schema).  We don't have it on the page
      // here, so default to "all divisions" for the upload — the server
      // already accepts this and the Phase C.3 ingest validator will
      // catch any GSTIN mismatch on actual GST returns.
      return divisions.map((d) => d.division_id);
    }
    return [];
  };

  /**
   * Is this row uploadable under the current page-level scope?
   * A row is masked (disabled) when its catalog ``default_attribution``
   * doesn't match the page-level ``scope_kind``.  Outputs (generated
   * files) are never masked — they're read-only either way.
   */
  const rowGate = (file) => {
    if (!isMulti) return { allowed: true, hint: "" };
    if (file.kind === "output") return { allowed: true, hint: "" };
    const required = ATTR_TO_SCOPE[file.default_attribution || "current_division"];
    if (required === pageScopeKind) return { allowed: true, hint: "" };
    return {
      allowed: false,
      hint: `Switch to ${SCOPE_LABEL[required] || required} to upload`,
    };
  };

  const onUpload = async (file, fileType) => {
    const fileRow = (status?.files || []).find((f) => f.key === fileType);
    if (fileRow) {
      const gate = rowGate(fileRow);
      if (!gate.allowed) { toast.error(gate.hint); return; }
    }
    const divisionIds = resolveAttribution();
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

      {/* Period selector — only shown when not locked from the page-level
          Working Period bar (single-page-design rule).  The Division /
          Scope is owned by the page-level Scope selector — there's no
          duplicate here.  Phase D refinement (2026-05-07). */}
      {!periodLocked && (
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
            rowGate={rowGate}
            pageScopeKind={pageScopeKind}
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
              rowGate={rowGate}
              pageScopeKind={pageScopeKind}
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
                rowGate={rowGate}
                pageScopeKind={pageScopeKind}
              />
            </div>
          )}
        </div>
      )}
      <GstinGroupsManager clientId={clientId} divisions={divisions} />
    </section>
  );
}

function FileGrid({ label, files, busyKey, fileInputs, onPickFile, triggerInput, onDelete, clientId, period, division, divisions, isMulti, rowGate, pageScopeKind }) {
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
            gate={rowGate(f)}
            pageScopeKind={pageScopeKind}
          />
        ))}
      </ul>
    </div>
  );
}

function FileChipRow({ file, busy, inputRef, onPick, onUploadClick, onDelete, clientId, period, division, divisions, isMulti, gate, pageScopeKind }) {
  const isUploaded = file.uploaded;
  const isOutput = file.kind === "output";
  const templateUrl = file.has_template
    ? downloadLibraryTemplateUrl(clientId, file.key, period, division || null)
    : null;
  // Phase D — gate.allowed=false → row stays visible but greyed/disabled.
  const masked = !gate.allowed;
  // Static badge label for the row (no dropdown; purely informational).
  const scopeBadge = (() => {
    if (!isMulti || isOutput) return null;
    const attr = file.default_attribution || "current_division";
    if (attr === "current_division") {
      // Show the actual division name when the auditor IS in division
      // scope; else label generically as "Per-division".
      if (pageScopeKind === "division") {
        const d = divisions.find((x) => x.division_id === (division || ""));
        return { tone: "slate", label: d?.name || "Division" };
      }
      return { tone: "slate", label: "Per-division" };
    }
    if (attr === "all_divisions") return { tone: "emerald", label: "All divisions" };
    if (attr === "pick_divisions") return { tone: "violet", label: "Per GSTIN group" };
    return null;
  })();
  const badgeTone = {
    slate:   "bg-slate-50 text-slate-800 border-slate-200",
    emerald: "bg-emerald-50 text-emerald-900 border-emerald-200",
    violet:  "bg-violet-50 text-violet-900 border-violet-200",
  };
  return (
    <li
      data-testid={`library-file-${file.key}`}
      data-masked={masked || undefined}
      className={`px-5 py-3 flex items-start gap-4 ${masked ? "bg-[#FBFBF8] opacity-55 hover:bg-[#FBFBF8]" : "hover:bg-[#F9F9F8]"}`}
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
          {masked ? (
            <span data-testid={`library-file-${file.key}-mask-hint`}>{gate.hint}</span>
          ) : isUploaded ? (
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
        {/* Phase D — static, read-only scope badge (no dropdown). */}
        {scopeBadge && (
          <span
            data-testid={`library-scope-badge-${file.key}`}
            className={`h-8 inline-flex items-center gap-1 px-2 border rounded-sm font-mono text-[10.5px] uppercase tracking-[0.12em] ${badgeTone[scopeBadge.tone]}`}
            title={`Effective scope · ${scopeBadge.label}`}
          >
            <Stack size={11} />
            <span className="max-w-[110px] truncate">{scopeBadge.label}</span>
          </span>
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
        {templateUrl && !isOutput && !masked && (
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
            disabled={busy || masked}
            onClick={onUploadClick}
            title={masked ? gate.hint : (isUploaded ? "Replace this file" : "Upload this file")}
            className="h-8 px-2.5 rounded-sm shadow-none border-[#D4D4D0] font-mono text-[10.5px] uppercase tracking-[0.12em] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? <><Lightning size={11} className="animate-pulse mr-1"/> Uploading</> : (
              <>
                <UploadSimple size={11} className="mr-1"/> {isUploaded ? "Replace" : "Upload"}
              </>
            )}
          </Button>
        )}
        {/* Delete stays enabled even on masked rows so an auditor can
            clean up files that were uploaded under a different scope. */}
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
