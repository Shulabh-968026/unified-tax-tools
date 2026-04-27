import { useRef, useState } from "react";
import { UploadCloud, FileSpreadsheet, CheckCircle2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/msme-api";

export default function YearEndUpload({ session, onUploaded }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  const upload = async (file) => {
    if (!file) return;
    if (!session?.id) {
      toast.error("No active session");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/sessions/${session.id}/yearend`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Imported ${data.bill_count} bills · ${data.unique_ledgers} unique creditors`);
      onUploaded && onUploaded();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    upload(f);
  };

  return (
    <div className="space-y-4" data-testid="yearend-upload-section">
      <div>
        <h2 className="font-display text-xl md:text-2xl font-semibold text-gray-900">
          Step 1 · Year-End Snapshot
        </h2>
        <p className="text-sm text-gray-600 mt-1">
          Upload the AssureAI 43B(h) Excel containing the year-end MSME ageing report
          (Outstanding Balance / FIFO bills).
        </p>
      </div>

      <div
        className={`upload-drop p-8 text-center cursor-pointer ${drag ? "bg-gray-50 border-gray-900" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        data-testid="yearend-dropzone"
      >
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls"
          onChange={(e) => upload(e.target.files?.[0])}
          className="hidden"
          data-testid="yearend-file-input"
        />
        {busy ? (
          <div className="flex flex-col items-center gap-2 text-gray-700">
            <Loader2 className="animate-spin" />
            <span className="text-sm">Parsing Excel…</span>
          </div>
        ) : session?.has_yearend ? (
          <div className="flex flex-col items-center gap-2">
            <CheckCircle2 className="text-emerald-600" />
            <div className="font-mono text-sm">{session.yearend_count} bills imported</div>
            <div className="text-xs text-gray-500">Click to replace</div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <UploadCloud className="text-gray-700" size={28} />
            <div>
              <div className="font-medium text-gray-900">Drop file or click to browse</div>
              <div className="text-xs text-gray-500 mt-1">Supports .xlsx, .xls</div>
            </div>
          </div>
        )}
      </div>

      <div className="border border-gray-200 bg-gray-50 rounded-sm p-4">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="text-gray-700 mt-0.5" size={18} />
          <div className="text-xs text-gray-700 leading-relaxed">
            <div className="font-semibold text-gray-900 mb-1">Expected columns</div>
            Ledger Name · Analysis Type (Outstanding Balance Report / FIFO) · Voucher No
            · Voucher Date · Bill Amount · Due Date · &gt; 45 Days · Overdue at Year End
          </div>
        </div>
      </div>
    </div>
  );
}
