import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { uploadRun } from "@/lib/api";
import { CloudArrowUp, FileText, FileXls, X, CheckCircle } from "@phosphor-icons/react";
import { toast } from "sonner";

function Dropzone({ accept, label, sublabel, file, onFile, testid, icon: Icon }) {
  const ref = useRef();
  const [over, setOver] = useState(false);
  return (
    <div
      data-testid={testid}
      className={`dropzone ${over ? "is-active" : ""} px-8 py-8 text-center rounded-sm relative`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
      }}
    >
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        data-testid={`${testid}-input`}
      />
      {file ? (
        <div className="flex items-center justify-between bg-white border border-[#E5E5E0] rounded-sm px-4 py-3 text-left">
          <div className="flex items-center gap-3 min-w-0">
            <Icon size={22} weight="duotone" className="text-[#0F172A] shrink-0"/>
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{file.name}</div>
              <div className="font-mono text-[11px] text-[#8A8A83]">{(file.size / 1024).toFixed(1)} KB</div>
            </div>
          </div>
          <button onClick={() => onFile(null)} className="text-[#52524E] hover:text-[#991B1B]" data-testid={`${testid}-remove`}>
            <X size={16}/>
          </button>
        </div>
      ) : (
        <div onClick={() => ref.current?.click()} className="cursor-pointer">
          <Icon size={26} weight="duotone" className="mx-auto text-[#52524E]"/>
          <div className="mt-2 text-sm font-medium text-[#111110]">{label}</div>
          <div className="mt-1 text-xs text-[#52524E]">{sublabel}</div>
          <div className="mt-3 inline-flex items-center gap-2 text-xs font-mono uppercase tracking-[0.12em] text-[#0F172A]">
            <CloudArrowUp size={14}/> Click or drop file
          </div>
        </div>
      )}
    </div>
  );
}

export default function StepUpload({ clientId, period, divisionId, scopeKind, onUploaded }) {
  const [json, setJson] = useState(null);
  const [xlsx, setXlsx] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pct, setPct] = useState(0);

  const submit = async () => {
    if (!json || !xlsx) {
      toast.error("Please attach both files.");
      return;
    }
    if (!clientId || !period) {
      toast.error("Client and period are required.");
      return;
    }
    setBusy(true);
    setPct(0);
    try {
      const res = await uploadRun({
        jsonFile: json,
        xlsxFile: xlsx,
        clientId,
        period,
        divisionId,
        scopeKind,
        onProgress: (e) => { if (e.total) setPct(Math.round((e.loaded * 100) / e.total)); },
      });
      toast.success("Files parsed", { description: `${res.vouchers_count} vouchers, ${res.ledgers_count} ledgers` });
      onUploaded?.(res.run_id);
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-6 py-6 pb-40">
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#8A8A83]">A · Books of Accounts</span>
            {json && <CheckCircle size={14} weight="fill" className="text-emerald-700"/>}
          </div>
          <Dropzone
            accept="application/json,.json"
            label="accounting_data.json"
            sublabel="Books exported from Assure Software (Tally JSON format)"
            file={json}
            onFile={setJson}
            testid="upload-json"
            icon={FileText}
          />
        </div>
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#8A8A83]">B · Ledger Mapping</span>
            {xlsx && <CheckCircle size={14} weight="fill" className="text-emerald-700"/>}
          </div>
          <Dropzone
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            label="ledger_mapping.xlsx"
            sublabel="Voucher/Ledger mapping from AssureAI"
            file={xlsx}
            onFile={setXlsx}
            testid="upload-xlsx"
            icon={FileXls}
          />
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-[#E5E5E0] pt-4">
        <div className="text-xs text-[#8A8A83] font-mono uppercase tracking-[0.12em]">
          {busy ? `Uploading… ${pct}%` : "Files stay private to your account"}
        </div>
        <Button
          data-testid="upload-submit-btn"
          disabled={!json || !xlsx || busy}
          onClick={submit}
          className="h-10 px-5 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none disabled:opacity-50"
        >
          {busy ? "Parsing…" : "Continue to Mapping"}
        </Button>
      </div>
    </div>
  );
}
