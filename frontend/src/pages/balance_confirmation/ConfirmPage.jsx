/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Public recipient confirmation page — NO AUTH.
 * Reached from the email's "Confirm or dispute" button after going through
 * /api/balance-confirmation/track/click/{token} (which 302s here and logs the
 * click). AssureAI green branding.
 */
export default function ConfirmPage() {
  const { token } = useParams();
  const [ctx, setCtx] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState("choose"); // choose | confirm | dispute | done
  const [submitting, setSubmitting] = useState(false);

  // form state
  const [responderName, setResponderName] = useState("");
  const [responderEmail, setResponderEmail] = useState("");
  const [note, setNote] = useState("");
  const [theirBalance, setTheirBalance] = useState("");
  const [theirDrCr, setTheirDrCr] = useState("");
  const [reason, setReason] = useState("");
  const [file, setFile] = useState(null);
  const [submitted, setSubmitted] = useState(null);

  useEffect(() => {
    axios.get(`${API}/balance-confirmation/public/confirmation/${token}`)
      .then(({ data }) => {
        setCtx(data);
        if (data.submitted_response) {
          setSubmitted(data.submitted_response);
          setView("done");
        }
      })
      .catch(e => setError(e?.response?.data?.detail || "Could not load this confirmation request."));
  }, [token]);

  const submitConfirm = async () => {
    setSubmitting(true);
    try {
      const { data } = await axios.post(
        `${API}/balance-confirmation/public/confirmation/${token}/confirm`,
        { responder_name: responderName, responder_email: responderEmail, note },
      );
      setSubmitted(data); setView("done");
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not submit your confirmation.");
    } finally { setSubmitting(false); }
  };

  const submitDispute = async () => {
    if (!reason.trim()) { setError("Please enter a reason explaining the difference."); return; }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("responder_name", responderName);
      fd.append("responder_email", responderEmail);
      if (theirBalance) fd.append("their_balance", String(theirBalance));
      if (theirDrCr) fd.append("their_dr_cr", theirDrCr);
      fd.append("reason", reason);
      if (file) fd.append("file", file);
      const { data } = await axios.post(
        `${API}/balance-confirmation/public/confirmation/${token}/dispute`,
        fd, { headers: { "Content-Type": "multipart/form-data" } },
      );
      setSubmitted(data); setView("done");
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not submit your reply.");
    } finally { setSubmitting(false); }
  };

  if (error) return <ErrorShell msg={error}/>;
  if (!ctx) return <LoadingShell/>;

  return (
    <Shell>
      <Header ctx={ctx}/>

      {view === "done" ? (
        <ThankYou submitted={submitted} ctx={ctx}/>
      ) : (
        <>
          <BalanceCard ctx={ctx}/>
          {view === "choose" && (
            <Choices
              onConfirm={() => setView("confirm")}
              onDispute={() => setView("dispute")}
            />
          )}
          {view === "confirm" && (
            <ConfirmForm
              responderName={responderName} setResponderName={setResponderName}
              responderEmail={responderEmail} setResponderEmail={setResponderEmail}
              note={note} setNote={setNote}
              submitting={submitting} onBack={() => setView("choose")}
              onSubmit={submitConfirm}
            />
          )}
          {view === "dispute" && (
            <DisputeForm
              ctx={ctx}
              responderName={responderName} setResponderName={setResponderName}
              responderEmail={responderEmail} setResponderEmail={setResponderEmail}
              theirBalance={theirBalance} setTheirBalance={setTheirBalance}
              theirDrCr={theirDrCr} setTheirDrCr={setTheirDrCr}
              reason={reason} setReason={setReason}
              file={file} setFile={setFile}
              submitting={submitting} onBack={() => setView("choose")}
              onSubmit={submitDispute}
            />
          )}
        </>
      )}

      <Footer ctx={ctx}/>
    </Shell>
  );
}

/* ============================================================ */
const G = "#047857";
const G_SOFT = "#ECFDF5";

function Shell({ children }) {
  return (
    <div style={{ minHeight: "100vh", background: "#F4F5F4", padding: "32px 16px",
                  fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                  color: "#111827" }}>
      <div style={{ maxWidth: 720, margin: "0 auto", background: "#FFF",
                    borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
                    border: "1px solid #E5E7EB", overflow: "hidden" }}>
        {children}
      </div>
      <div style={{ maxWidth: 720, margin: "12px auto 0", textAlign: "center",
                    fontSize: 11, color: "#9CA3AF", fontFamily: "monospace" }}>
        Powered by MSS × Assure Audit Utilities
      </div>
    </div>
  );
}

function LoadingShell() {
  return <Shell><div style={{ padding: 64, textAlign: "center", fontSize: 14, color: "#6B7280" }}>Loading your confirmation request…</div></Shell>;
}
function ErrorShell({ msg }) {
  return (
    <Shell>
      <div style={{ padding: 48, textAlign: "center" }}>
        <div style={{ fontSize: 36, marginBottom: 16 }}>⚠️</div>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>Link Invalid or Expired</h1>
        <p style={{ fontSize: 14, color: "#52525B" }}>{msg}</p>
        <p style={{ fontSize: 12, color: "#9CA3AF", marginTop: 16 }}>If you believe this is an error, please reply to the original email.</p>
      </div>
    </Shell>
  );
}

function Header({ ctx }) {
  return (
    <div style={{ background: G, color: "#FFF", padding: "18px 28px" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase",
                    opacity: 0.8, fontFamily: "monospace" }}>Balance Confirmation</div>
      <h1 style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{ctx.client_name || "Audit Confirmation"}</h1>
      <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>
        {ctx.client_gstin ? `GSTIN ${ctx.client_gstin} · ` : ""}As at <strong>{ctx.as_at_date || "—"}</strong>
        {ctx.fy ? ` · FY ${ctx.fy}` : ""}
      </div>
    </div>
  );
}

function BalanceCard({ ctx }) {
  const dr = ctx.dr_cr === "Dr";
  return (
    <div style={{ padding: "28px 28px 20px" }}>
      <p style={{ fontSize: 14, color: "#374151", marginBottom: 12 }}>
        Dear {ctx.contact_name || ctx.party_name},
      </p>
      <p style={{ fontSize: 14, color: "#374151", marginBottom: 12 }}>
        As part of the statutory audit of <strong>{ctx.client_name}</strong> for the financial year ended <strong>{ctx.as_at_date || "—"}</strong>,
        we are reconciling balances. As per our books, the balance with respect to your account is:
      </p>
      <div style={{ background: G_SOFT, borderLeft: `4px solid ${G}`,
                    padding: "16px 20px", marginTop: 8 }}>
        <div style={{ fontSize: 12, color: "#065F46", letterSpacing: "0.1em",
                      textTransform: "uppercase", fontFamily: "monospace" }}>
          {ctx.party_name}
        </div>
        <div style={{ fontSize: 30, fontWeight: 700, color: G, marginTop: 4 }}>
          ₹ {Number(ctx.closing_balance).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          <span style={{ fontSize: 14, marginLeft: 8, fontWeight: 600 }}>{ctx.dr_cr}</span>
        </div>
        <div style={{ fontSize: 11, color: "#065F46", marginTop: 6 }}>
          ({dr ? "Debit balance — receivable from / advance to your firm" : "Credit balance — payable to / standing in your favour"})
        </div>
      </div>
    </div>
  );
}

function Choices({ onConfirm, onDispute }) {
  return (
    <div style={{ padding: "12px 28px 32px", display: "flex", gap: 12, flexWrap: "wrap" }}>
      <button onClick={onConfirm} data-testid="confirm-yes-btn"
        style={{ flex: 1, minWidth: 220, padding: "14px 18px", background: G, color: "#FFF",
                 border: 0, borderRadius: 4, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
        ✓ Yes, the balance is correct
      </button>
      <button onClick={onDispute} data-testid="confirm-no-btn"
        style={{ flex: 1, minWidth: 220, padding: "14px 18px", background: "#FFF", color: "#92400E",
                 border: "1px solid #F59E0B", borderRadius: 4, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
        ✗ No, our records show a different amount
      </button>
    </div>
  );
}

function ConfirmForm({ responderName, setResponderName, responderEmail, setResponderEmail, note, setNote, submitting, onBack, onSubmit }) {
  return (
    <div style={{ padding: "8px 28px 32px" }} data-testid="confirm-form">
      <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Confirm balance</h2>
      <Field label="Your name" value={responderName} onChange={setResponderName} placeholder="Mr. ABC" testid="confirm-name"/>
      <Field label="Your email (optional)" type="email" value={responderEmail} onChange={setResponderEmail} placeholder="you@example.com" testid="confirm-email"/>
      <Field label="Note (optional)" value={note} onChange={setNote} placeholder="Any clarification you'd like to add" textarea testid="confirm-note"/>
      <Actions onBack={onBack} onSubmit={onSubmit} submitting={submitting}
               submitLabel={submitting ? "Submitting…" : "✓ Submit Confirmation"}
               submitTestid="confirm-submit"/>
    </div>
  );
}

function DisputeForm({ ctx, responderName, setResponderName, responderEmail, setResponderEmail,
                       theirBalance, setTheirBalance, theirDrCr, setTheirDrCr,
                       reason, setReason, file, setFile, submitting, onBack, onSubmit }) {
  return (
    <div style={{ padding: "8px 28px 32px" }} data-testid="dispute-form">
      <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Reconciliation needed</h2>
      <Field label="Your name" value={responderName} onChange={setResponderName} placeholder="Mr. ABC" testid="dispute-name"/>
      <Field label="Your email" type="email" value={responderEmail} onChange={setResponderEmail} placeholder="you@example.com" testid="dispute-email"/>
      <div style={{ display: "flex", gap: 8 }}>
        <div style={{ flex: 2 }}>
          <Field label="Your balance (₹)" type="number" value={theirBalance} onChange={setTheirBalance} placeholder={String(ctx.closing_balance)} testid="dispute-balance"/>
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>Type</label>
          <select value={theirDrCr} onChange={e => setTheirDrCr(e.target.value)}
                  style={{ ...inputStyle, height: 40 }} data-testid="dispute-drcr">
            <option value="">—</option>
            <option value="Dr">Debit (Dr)</option>
            <option value="Cr">Credit (Cr)</option>
          </select>
        </div>
      </div>
      <Field label="Reason / explanation *" value={reason} onChange={setReason} textarea
        placeholder="e.g. Cheque #4521 dated 28-Mar-2025 for ₹ 50,000 not cleared yet; debit note #DN-12 for ₹ 5,000 not posted in your books." testid="dispute-reason"/>
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>Attach your statement of account (optional)</label>
        <input type="file" accept=".pdf,.csv,.xlsx,.xls,.png,.jpg,.jpeg"
          onChange={e => setFile(e.target.files?.[0] || null)}
          data-testid="dispute-file"
          style={{ fontSize: 13, padding: "6px 0" }}/>
        {file && <div style={{ fontSize: 12, color: "#52525B", marginTop: 4 }}>
          {file.name} · {(file.size / 1024).toFixed(1)} KB
        </div>}
      </div>
      <Actions onBack={onBack} onSubmit={onSubmit} submitting={submitting}
               submitLabel={submitting ? "Submitting…" : "Submit Reconciliation"}
               submitTestid="dispute-submit"
               submitColor="#92400E" submitBorder="#F59E0B" submitBg="#FFF"/>
    </div>
  );
}

function ThankYou({ submitted, ctx }) {
  const confirmed = submitted?.decision === "confirmed";
  return (
    <div style={{ padding: "40px 28px", textAlign: "center" }} data-testid="thankyou-screen">
      <div style={{ fontSize: 48, marginBottom: 12 }}>
        {confirmed ? "✓" : "📨"}
      </div>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
        {confirmed ? "Thank you — balance confirmed" : "Thank you — we'll reconcile from here"}
      </h2>
      <p style={{ fontSize: 14, color: "#374151", maxWidth: 520, margin: "0 auto 16px" }}>
        {confirmed
          ? `Your confirmation for ${ctx.client_name} as on ${ctx.as_at_date} has been recorded against our audit working paper.`
          : `We've received your input and the auditors will review the difference. They may reach back to you for clarification.`}
      </p>
      <div style={{ background: G_SOFT, padding: "12px 18px", borderRadius: 4,
                    display: "inline-block", border: "1px solid #A7F3D0",
                    fontFamily: "monospace", fontSize: 11, color: "#065F46" }}>
        Reference: {submitted?.response_id?.slice(0, 13)}…<br/>
        Submitted: {(submitted?.submitted_at || "").slice(0, 19).replace("T", " ")} UTC
      </div>
    </div>
  );
}

function Footer({ ctx }) {
  return (
    <div style={{ borderTop: "1px solid #E5E7EB", padding: "14px 28px",
                  background: "#FAFAFA", fontSize: 11, color: "#6B7280", lineHeight: 1.6 }}>
      <strong>Auditor:</strong> {ctx.auditor_name || "—"} · {ctx.auditor_firm || "—"}<br/>
      This confirmation is sought purely for audit verification under section 44AB of
      the Income-tax Act, 1961. Your response does not modify any balance shown in
      your books or ours. The unique link in this page is valid only for this single
      confirmation and expires after the audit is signed off.
    </div>
  );
}

const labelStyle = { display: "block", fontSize: 11, fontWeight: 600,
                     color: "#374151", marginBottom: 4, textTransform: "uppercase",
                     letterSpacing: "0.06em" };
const inputStyle = { width: "100%", border: "1px solid #D4D4D8",
                     borderRadius: 4, padding: "8px 10px", fontSize: 13,
                     background: "#FFF", outline: "none", boxSizing: "border-box" };

function Field({ label, value, onChange, placeholder, type = "text", textarea = false, testid }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={labelStyle}>{label}</label>
      {textarea ? (
        <textarea value={value} onChange={e => onChange(e.target.value)}
                  placeholder={placeholder} rows={3} data-testid={testid}
                  style={{ ...inputStyle, resize: "vertical" }}/>
      ) : (
        <input type={type} value={value} onChange={e => onChange(e.target.value)}
               placeholder={placeholder} data-testid={testid}
               style={inputStyle}/>
      )}
    </div>
  );
}

function Actions({ onBack, onSubmit, submitting, submitLabel, submitTestid,
                   submitColor = "#FFF", submitBorder = G, submitBg = G }) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
      <button onClick={onBack} disabled={submitting} data-testid="form-back"
        style={{ padding: "10px 16px", background: "#FFF", color: "#374151",
                 border: "1px solid #D4D4D8", borderRadius: 4, cursor: "pointer",
                 fontSize: 13 }}>← Back</button>
      <button onClick={onSubmit} disabled={submitting} data-testid={submitTestid}
        style={{ flex: 1, padding: "10px 16px", background: submitBg, color: submitColor,
                 border: `1px solid ${submitBorder}`, borderRadius: 4, cursor: "pointer",
                 fontSize: 13, fontWeight: 600,
                 opacity: submitting ? 0.6 : 1 }}>{submitLabel}</button>
    </div>
  );
}
