import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell, { PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/components/ui/alert-dialog";
import { useAuth } from "@/lib/auth";
import { adminListMembers, adminInvite, adminChangeRole, adminRevoke, adminCancelInvite } from "@/lib/api";
import { ROLE_ACCENT } from "@/lib/colors";
import { UserPlus, Trash, Crown, ShieldCheck, User, ArrowLeft, Clock } from "@phosphor-icons/react";
import { toast } from "sonner";
import { formatDate } from "@/lib/format";

export default function AdminUsers() {
  const navigate = useNavigate();
  const { user } = useAuth() || {};
  const isSuperAdmin = user?.role === "super_admin";

  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("user");
  const [busy, setBusy] = useState(false);

  const [confirmRevoke, setConfirmRevoke] = useState(null); // { user_id, email }

  const refresh = async () => {
    setLoading(true);
    try {
      const d = await adminListMembers();
      setMembers(d.members || []);
      setInvitations(d.invitations || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load users");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (user && user.role !== "admin" && user.role !== "super_admin") {
      navigate("/dashboard", { replace: true });
      return;
    }
    if (user) refresh();
  }, [user, navigate]);

  const onInvite = async (e) => {
    e.preventDefault();
    if (!email.trim()) { toast.error("Email is required"); return; }
    setBusy(true);
    try {
      const out = await adminInvite(email.trim().toLowerCase(), role);
      if (out?.email_sent === false) {
        toast.success(`Invited ${email.trim().toLowerCase()} as ${role}`, { description: "Invitation saved. Email delivery is pending — set RESEND_API_KEY to send automatically." });
      } else {
        toast.success(`Invited ${email.trim().toLowerCase()} as ${role}`, { description: "Invitation email sent." });
      }
      setEmail("");
      setRole("user");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not invite");
    } finally { setBusy(false); }
  };

  const onChangeRole = async (uid, newRole) => {
    try {
      await adminChangeRole(uid, newRole);
      toast.success("Role updated");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Update failed");
    }
  };

  const onRevoke = async () => {
    if (!confirmRevoke) return;
    try {
      await adminRevoke(confirmRevoke.user_id);
      toast.success("Access revoked");
      setConfirmRevoke(null);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Revoke failed");
    }
  };

  const onCancelInvite = async (em) => {
    try {
      await adminCancelInvite(em);
      toast.success("Invitation cancelled");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Cancel failed");
    }
  };

  return (
    <AppShell>
      <PageHeader
        eyebrow={<button onClick={() => navigate("/dashboard")} className="hover:text-[#0F172A] inline-flex items-center gap-1"><ArrowLeft size={11}/>All clients</button>}
        title={<span className="inline-flex items-center gap-3"><span className="font-mono text-[11px] uppercase tracking-[0.18em] bg-violet-600 text-white px-2 py-0.5 rounded-sm">Admin</span>Users & Access</span>}
        subtitle="Invite teammates by email. Members sign in with Google; their role determines whether they can manage other users."
      />

      <div className="px-6 md:px-10 py-8 pb-40 max-w-5xl">
        {/* QA Test Pack download */}
        <div className="border border-sky-200 bg-sky-50/60 rounded-sm p-4 mb-6 flex items-center justify-between gap-4">
          <div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-sky-800">QA Test Pack</div>
            <div className="text-[13px] text-slate-700 mt-0.5">
              Designer A4 PDF with a tick-box checklist for every live module — ready to circulate to your QA team.
            </div>
          </div>
          <a
            href={`${process.env.REACT_APP_BACKEND_URL || ""}/api/admin/qa-pack.pdf`}
            target="_blank"
            rel="noreferrer"
            data-testid="qa-pack-download"
            className="shrink-0 inline-flex items-center gap-2 px-3.5 py-2 bg-sky-800 hover:bg-sky-900 text-white text-[12.5px] rounded-sm"
          >
            Download PDF
          </a>
        </div>

        {/* Invite form */}
        <form onSubmit={onInvite} className="border border-violet-200 bg-violet-50/40 rounded-sm p-5 mb-8" data-testid="invite-form">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-violet-700">Invite Teammate</div>
          <div className="mt-3 grid md:grid-cols-[1fr_180px_auto] gap-3 items-end">
            <div>
              <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Email</Label>
              <Input
                data-testid="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@example.com"
                className="mt-1 rounded-sm shadow-none border-[#D4D4D0] bg-white"
              />
            </div>
            <div>
              <Label className="text-[11px] uppercase tracking-[0.12em] font-mono text-[#52524E]">Role</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger data-testid="invite-role" className="mt-1 rounded-sm shadow-none border-[#D4D4D0] bg-white"><SelectValue/></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user" data-testid="role-user">User</SelectItem>
                  <SelectItem value="admin" data-testid="role-admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button data-testid="invite-submit" type="submit" disabled={busy} className="h-10 px-4 bg-violet-600 hover:bg-violet-700 text-white rounded-sm shadow-none gap-2">
              <UserPlus size={14} weight="bold"/>{busy ? "Inviting…" : "Send Invite"}
            </Button>
          </div>
          <p className="mt-3 text-[12px] text-[#52524E]">
            Members sign in with Google. <strong>Admin</strong> can invite, change roles and revoke access; <strong>User</strong> can only operate utilities.
          </p>
        </form>

        {/* Members */}
        <section className="border border-[#E5E5E0] bg-white rounded-sm" data-testid="members-block">
          <div className="px-4 py-3 border-b border-[#E5E5E0] flex items-center gap-2">
            <h3 className="font-heading text-base">Members</h3>
            <Badge className="bg-slate-100 text-slate-800 border border-slate-200 rounded-sm shadow-none font-mono text-[10px]">{members.length}</Badge>
          </div>
          {loading ? (
            <div className="p-6 font-mono text-sm text-[#8A8A83]">Loading…</div>
          ) : members.length === 0 ? (
            <div className="p-6 text-sm text-[#8A8A83]">No members yet.</div>
          ) : (
            <ul>
              {members.map((m) => {
                const accent = ROLE_ACCENT[m.role] || ROLE_ACCENT.user;
                const isSuper = m.role === "super_admin";
                const RoleIcon = isSuper ? Crown : (m.role === "admin" ? ShieldCheck : User);
                const isMe = user?.user_id === m.user_id;
                return (
                  <li key={m.user_id} className="px-4 py-3 border-b border-[#E5E5E0] last:border-b-0 flex items-center gap-4 flex-wrap" data-testid={`member-${m.user_id}`}>
                    {m.picture ? (
                      <img src={m.picture} alt="" className="w-8 h-8 rounded-full border border-[#E5E5E0]"/>
                    ) : (
                      <div className={`w-8 h-8 rounded-full ${accent.chip} ${accent.text} grid place-items-center text-[12px] font-mono`}>{(m.name || m.email || "?").slice(0, 1).toUpperCase()}</div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-[14px] font-medium truncate">{m.name || m.email}{isMe && <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]">you</span>}</div>
                      <div className="text-[12px] text-[#52524E] truncate">{m.email}</div>
                    </div>
                    <Badge className={`${accent.bg} ${accent.text} ${accent.border} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em] inline-flex items-center gap-1`}>
                      <RoleIcon size={11} weight={isSuper ? "fill" : "duotone"}/> {accent.label}
                    </Badge>
                    {!isSuper && isSuperAdmin && !isMe && (
                      <Select value={m.role} onValueChange={(v) => onChangeRole(m.user_id, v)}>
                        <SelectTrigger className="h-8 w-[120px] rounded-sm shadow-none border-[#D4D4D0]" data-testid={`role-select-${m.user_id}`}><SelectValue/></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="user">User</SelectItem>
                          <SelectItem value="admin">Admin</SelectItem>
                        </SelectContent>
                      </Select>
                    )}
                    {!isSuper && isSuperAdmin && !isMe && (
                      <button
                        onClick={() => setConfirmRevoke({ user_id: m.user_id, email: m.email })}
                        className="text-rose-700 hover:text-rose-900 p-1.5 border border-rose-200 hover:border-rose-300 rounded-sm bg-rose-50/40"
                        title="Revoke access"
                        data-testid={`revoke-${m.user_id}`}
                      ><Trash size={14}/></button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Pending invitations */}
        {invitations.length > 0 && (
          <section className="mt-8 border border-amber-200 bg-amber-50/40 rounded-sm" data-testid="invitations-block">
            <div className="px-4 py-3 border-b border-amber-200 flex items-center gap-2">
              <Clock size={14} weight="duotone" className="text-amber-700"/>
              <h3 className="font-heading text-base">Pending Invitations</h3>
              <Badge className="bg-amber-100 text-amber-900 border border-amber-200 rounded-sm shadow-none font-mono text-[10px]">{invitations.length}</Badge>
            </div>
            <ul>
              {invitations.map((i) => {
                const accent = ROLE_ACCENT[i.role] || ROLE_ACCENT.user;
                return (
                  <li key={i.email} className="px-4 py-3 border-b border-amber-200 last:border-b-0 flex items-center gap-4 flex-wrap" data-testid={`invitation-${i.email}`}>
                    <div className="flex-1 min-w-0">
                      <div className="text-[14px] font-medium truncate">{i.email}</div>
                      <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#8A8A83]">Invited {formatDate(i.created_at)} · by {i.invited_by_email}</div>
                    </div>
                    <Badge className={`${accent.bg} ${accent.text} ${accent.border} border rounded-sm shadow-none font-mono text-[10px] uppercase tracking-[0.1em]`}>
                      {accent.label}
                    </Badge>
                    <button
                      onClick={() => onCancelInvite(i.email)}
                      className="text-[#52524E] hover:text-rose-700 p-1.5 border border-[#E5E5E0] hover:border-rose-200 rounded-sm bg-white"
                      title="Cancel invitation"
                      data-testid={`cancel-invite-${i.email}`}
                    ><Trash size={14}/></button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>

      <AlertDialog open={!!confirmRevoke} onOpenChange={(o) => !o && setConfirmRevoke(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke access?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmRevoke?.email} will lose access immediately. They can be re-invited later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onRevoke} className="bg-rose-700 hover:bg-rose-800" data-testid="confirm-revoke">Revoke</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}
