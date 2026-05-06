/**
 * Release 4.6 — Universal Recipients popover for Balance Confirmation.
 *
 * Replaces the 2 inline text boxes with a compact pill that opens a
 * popover containing two chip-inputs (CC + BCC).  Persists to the
 * backend via PATCH /runs/{rid}/universal-recipients on every add /
 * remove (debounced).  Hydrates from the server on mount.
 */
import { useEffect, useRef, useState } from "react";
import { http } from "@/lib/api";
import { Mail, X, Plus } from "lucide-react";
import { toast } from "sonner";

const isValidEmail = (s) => {
  const e = (s || "").trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
};

function ChipInput({ label, items, onAdd, onRemove, testid }) {
  const [draft, setDraft] = useState("");
  const ref = useRef(null);

  const commit = () => {
    const raw = draft.trim();
    if (!raw) return;
    // Allow batch paste: comma / semicolon / space / newline separated.
    const parts = raw.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean);
    const valid = parts.filter(isValidEmail);
    const invalid = parts.filter((p) => !isValidEmail(p));
    if (invalid.length) toast.error(`Skipped ${invalid.length} invalid email${invalid.length > 1 ? "s" : ""}`);
    if (valid.length) onAdd(valid);
    setDraft("");
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" || e.key === "," || e.key === ";") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && items.length) {
      // Remove last on Backspace when empty.
      onRemove(items[items.length - 1]);
    }
  };

  return (
    <div data-testid={testid}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-gray-500 mb-1">
        {label}
      </div>
      <div
        className="flex flex-wrap gap-1.5 px-2 py-1.5 border border-gray-300 rounded-sm bg-white min-h-[36px] focus-within:border-emerald-600"
        onClick={() => ref.current?.focus()}
      >
        {items.map((e) => (
          <span
            key={e}
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-50 border border-emerald-200 rounded-sm text-[11.5px] font-mono text-emerald-800"
            data-testid={`${testid}-chip-${e}`}
          >
            {e}
            <button
              type="button"
              onClick={(ev) => { ev.stopPropagation(); onRemove(e); }}
              className="hover:text-rose-700"
              data-testid={`${testid}-remove-${e}`}
            >
              <X size={10} />
            </button>
          </span>
        ))}
        <input
          ref={ref}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={items.length ? "Add another…" : "type email + Enter"}
          className="flex-1 min-w-[140px] text-[12px] outline-none bg-transparent"
          data-testid={`${testid}-input`}
        />
      </div>
    </div>
  );
}

export default function UniversalRecipientsPopover({ rid, anchorRef, open, onClose, onChange }) {
  const [cc, setCc] = useState([]);
  const [bcc, setBcc] = useState([]);
  const [loaded, setLoaded] = useState(false);

  // Hydrate
  useEffect(() => {
    if (!rid) return;
    let cancel = false;
    http.get(`/balance-confirmation/runs/${rid}/universal-recipients`)
      .then(({ data }) => {
        if (cancel) return;
        setCc(data?.universal_cc || []);
        setBcc(data?.universal_bcc || []);
        setLoaded(true);
        onChange?.({ cc: data?.universal_cc || [], bcc: data?.universal_bcc || [] });
      })
      .catch(() => setLoaded(true));
    return () => { cancel = true; };
  }, [rid]);   // eslint-disable-line react-hooks/exhaustive-deps

  const persist = async (nextCc, nextBcc) => {
    try {
      const { data } = await http.patch(
        `/balance-confirmation/runs/${rid}/universal-recipients`,
        { universal_cc: nextCc, universal_bcc: nextBcc },
      );
      const c = data?.universal_cc || [];
      const b = data?.universal_bcc || [];
      setCc(c); setBcc(b);
      onChange?.({ cc: c, bcc: b });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const addCc = (vals) => persist(Array.from(new Set([...cc, ...vals])), bcc);
  const rmCc = (e) => persist(cc.filter((x) => x !== e), bcc);
  const addBcc = (vals) => persist(cc, Array.from(new Set([...bcc, ...vals])));
  const rmBcc = (e) => persist(cc, bcc.filter((x) => x !== e));

  if (!open) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-30"
        onClick={onClose}
        data-testid="bc-universal-recipients-backdrop"
      />
      <div
        className="absolute right-0 top-full mt-1.5 w-[420px] bg-white border border-gray-200 rounded-sm shadow-lg z-40 p-4"
        data-testid="bc-universal-recipients-popover"
      >
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-gray-500">
              Apply to every send
            </div>
            <h3 className="text-sm font-semibold mt-0.5 inline-flex items-center gap-1.5">
              <Mail size={14}/> Universal Recipients
            </h3>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X size={14}/>
          </button>
        </div>
        <div className="space-y-3">
          <ChipInput
            label="Universal CC" items={cc}
            onAdd={addCc} onRemove={rmCc}
            testid="bc-universal-cc"
          />
          <ChipInput
            label="Universal BCC" items={bcc}
            onAdd={addBcc} onRemove={rmBcc}
            testid="bc-universal-bcc"
          />
        </div>
        <div className="mt-3 text-[10.5px] text-gray-500 font-mono leading-relaxed">
          Each address is applied to every confirmation email + reminder sent
          from this run. Press Enter, comma, semicolon or paste a comma-/space-
          separated batch to add multiple at once.
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- */
/* Trigger pill — shows the live count + opens the popover.         */
/* ---------------------------------------------------------------- */
export function UniversalRecipientsTrigger({ rid, ccCount = 0, bccCount = 0 }) {
  const [open, setOpen] = useState(false);
  const [counts, setCounts] = useState({ cc: ccCount, bcc: bccCount });
  const ref = useRef(null);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(true)}
        className="text-xs h-8 px-3 rounded-sm border border-gray-300 inline-flex items-center gap-1.5 hover:bg-gray-50"
        data-testid="bc-universal-recipients-btn"
        title="Configure universal CC / BCC for this run"
      >
        <Mail size={12}/>
        Universal CC/BCC
        {(counts.cc + counts.bcc) > 0 && (
          <span className="ml-1 inline-block px-1.5 py-0.5 text-[10px] rounded-sm bg-emerald-100 text-emerald-800 font-mono"
            data-testid="bc-universal-recipients-count">
            {counts.cc + counts.bcc}
          </span>
        )}
      </button>
      <UniversalRecipientsPopover
        rid={rid}
        anchorRef={ref}
        open={open}
        onClose={() => setOpen(false)}
        onChange={({ cc, bcc }) => setCounts({ cc: cc.length, bcc: bcc.length })}
      />
    </div>
  );
}
