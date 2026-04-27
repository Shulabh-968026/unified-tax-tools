import { useNavigate } from "react-router-dom";
import { authLogout } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { House, SignOut, ShieldStar, Crown, ShieldCheck, User as UserIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ROLE_ACCENT } from "@/lib/colors";

export default function AppShell({ children }) {
  const navigate = useNavigate();
  const { user } = useAuth() || {};

  const onLogout = async () => {
    try { await authLogout(); } catch {}
    navigate("/login", { replace: true });
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] h-screen overflow-hidden bg-[#F9F9F8]">
      <aside className="hidden md:flex flex-col border-r border-[#E5E5E0] bg-[#F3F4F1]" data-testid="sidebar">
        <div className="px-5 pt-6 pb-4 flex items-center gap-2">
          <div className="w-7 h-7 border border-[#0F172A] grid place-items-center text-[#0F172A] font-mono text-xs">M</div>
          <div>
            <div className="font-heading text-[15px] tracking-tight leading-none">MSS × Assure</div>
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#8A8A83] mt-1">Audit Utilities</div>
          </div>
        </div>

        <div className="px-4 pb-3 space-y-2">
          <Button
            data-testid="home-btn"
            onClick={() => navigate("/dashboard")}
            className="w-full h-10 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none gap-2 justify-start pl-3"
          >
            <House size={16} weight="bold"/> All Clients
          </Button>
          {(user?.role === "admin" || user?.role === "super_admin") && (
            <Button
              data-testid="admin-btn"
              onClick={() => navigate("/dashboard/admin")}
              variant="outline"
              className="w-full h-10 bg-violet-50 hover:bg-violet-100 border-violet-200 text-violet-800 rounded-sm shadow-none gap-2 justify-start pl-3"
            >
              <ShieldStar size={16} weight="duotone"/> Users & Access
            </Button>
          )}
        </div>

        <div className="flex-1"/>

        <div className="border-t border-[#E5E5E0] px-4 py-3 flex items-center gap-3" data-testid="sidebar-footer">
          {user?.picture ? (
            <img src={user.picture} alt="" className="w-7 h-7 rounded-full border border-[#E5E5E0]"/>
          ) : (
            <div className="w-7 h-7 rounded-full bg-[#0F172A] text-white grid place-items-center text-[11px] font-mono">
              {(user?.name || "?").slice(0, 1)}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-medium truncate">{user?.name || "—"}</div>
            <div className="text-[10px] text-[#8A8A83] truncate flex items-center gap-1.5">
              {user?.email || ""}
              {user?.role && (() => {
                const a = ROLE_ACCENT[user.role] || ROLE_ACCENT.user;
                const Icon = user.role === "super_admin" ? Crown : (user.role === "admin" ? ShieldCheck : UserIcon);
                return (
                  <Badge className={`${a.bg} ${a.text} ${a.border} border rounded-sm shadow-none font-mono text-[9px] tracking-[0.04em] px-1 py-0 inline-flex items-center gap-0.5 shrink-0`}>
                    <Icon size={9} weight={user.role === "super_admin" ? "fill" : "duotone"}/>{a.label}
                  </Badge>
                );
              })()}
            </div>
          </div>
          <button data-testid="logout-btn" onClick={onLogout} className="text-[#52524E] hover:text-[#991B1B]" title="Logout">
            <SignOut size={16}/>
          </button>
        </div>
      </aside>

      <main className="flex flex-col h-full overflow-y-auto" data-testid="main">
        <div className="page-enter">{children}</div>
      </main>
    </div>
  );
}

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <div className="border-b border-[#E5E5E0] px-6 md:px-10 py-6 bg-white">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          {eyebrow && <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#8A8A83]">{eyebrow}</div>}
          <h1 className="mt-1 font-heading text-2xl md:text-3xl tracking-tight text-[#111110]">{title}</h1>
          {subtitle && <div className="mt-2 text-sm text-[#52524E] max-w-2xl">{subtitle}</div>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}

export function StepRail({ step }) {
  const steps = [
    { n: 1, label: "Upload" },
    { n: 2, label: "Mapping" },
    { n: 3, label: "Report" },
  ];
  return (
    <div className="flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.15em] text-[#52524E]">
      {steps.map((s, i) => (
        <div key={s.n} className="flex items-center gap-3">
          <span className={`step-dot ${step === s.n ? "active" : step > s.n ? "done" : ""}`}>{s.n}</span>
          <span className={step === s.n ? "text-[#0F172A]" : ""}>{s.label}</span>
          {i < steps.length - 1 && <span className="w-8 h-px bg-[#D4D4D0]"/>}
        </div>
      ))}
    </div>
  );
}
