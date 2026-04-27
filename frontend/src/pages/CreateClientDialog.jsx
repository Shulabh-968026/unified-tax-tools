import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { createClient } from "@/lib/api";
import { Plus, X } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function CreateClientDialog({ open, onOpenChange, onCreated }) {
  const [fileNumber, setFileNumber] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("single");
  const [divisions, setDivisions] = useState([""]);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setFileNumber(""); setName(""); setType("single"); setDivisions([""]); setBusy(false);
  };

  const submit = async () => {
    if (!fileNumber.trim() || !name.trim()) {
      toast.error("File Number and Name are required");
      return;
    }
    const divs = type === "multi" ? divisions.map((d) => d.trim()).filter(Boolean) : [];
    if (type === "multi" && divs.length === 0) {
      toast.error("Add at least one division");
      return;
    }
    setBusy(true);
    try {
      const c = await createClient({ file_number: fileNumber.trim(), name: name.trim(), type, divisions: divs });
      toast.success("Client created");
      onCreated?.(c);
      reset();
      onOpenChange(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create client");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent className="bg-white border border-[#E5E5E0] rounded-sm shadow-xl max-w-lg" data-testid="create-client-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading text-xl tracking-tight">New Client</DialogTitle>
          <DialogDescription className="text-[12px] text-[#52524E]">
            Add the client's file number, name and structure. Single-division clients get one default scope; multi-division clients let you submit a run per division and a consolidated report.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div>
            <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">File Number</Label>
            <Input data-testid="client-file-number" value={fileNumber} onChange={(e) => setFileNumber(e.target.value)} placeholder="A-504" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"/>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Client Name</Label>
            <Input data-testid="client-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="ABC Textile Mills" className="mt-1 rounded-sm shadow-none border-[#D4D4D0]"/>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Client Structure</Label>
            <RadioGroup value={type} onValueChange={setType} className="mt-2 grid grid-cols-2 gap-2">
              <label className={`border ${type === "single" ? "border-[#0F172A] bg-[#F9F9F8]" : "border-[#E5E5E0] bg-white"} rounded-sm px-3 py-3 cursor-pointer flex items-start gap-3`} data-testid="client-type-single">
                <RadioGroupItem value="single" className="mt-0.5"/>
                <div>
                  <div className="text-sm font-medium">Single Division</div>
                  <div className="text-[11px] text-[#52524E] mt-0.5">One scope per period.</div>
                </div>
              </label>
              <label className={`border ${type === "multi" ? "border-[#0F172A] bg-[#F9F9F8]" : "border-[#E5E5E0] bg-white"} rounded-sm px-3 py-3 cursor-pointer flex items-start gap-3`} data-testid="client-type-multi">
                <RadioGroupItem value="multi" className="mt-0.5"/>
                <div>
                  <div className="text-sm font-medium">Multi Division</div>
                  <div className="text-[11px] text-[#52524E] mt-0.5">Per-division + consolidated report.</div>
                </div>
              </label>
            </RadioGroup>
          </div>

          {type === "multi" && (
            <div data-testid="divisions-block">
              <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Divisions</Label>
              <div className="mt-1 space-y-2">
                {divisions.map((d, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      data-testid={`division-input-${i}`}
                      value={d}
                      onChange={(e) => setDivisions(divisions.map((x, j) => j === i ? e.target.value : x))}
                      placeholder={`Division ${i + 1}`}
                      className="rounded-sm shadow-none border-[#D4D4D0]"
                    />
                    {divisions.length > 1 && (
                      <button onClick={() => setDivisions(divisions.filter((_, j) => j !== i))} className="text-[#52524E] hover:text-[#991B1B]" data-testid={`remove-division-${i}`}>
                        <X size={14}/>
                      </button>
                    )}
                  </div>
                ))}
                <button
                  data-testid="add-division-btn"
                  onClick={() => setDivisions([...divisions, ""])}
                  className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#0F172A] hover:underline flex items-center gap-1"
                >
                  <Plus size={12} weight="bold"/> Add Division
                </button>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} className="font-mono text-xs uppercase tracking-[0.1em]">Cancel</Button>
          <Button data-testid="submit-create-client" onClick={submit} disabled={busy} className="bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none">
            {busy ? "Creating…" : "Create Client"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
