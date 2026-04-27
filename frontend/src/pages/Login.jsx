import { Button } from "@/components/ui/button";
import { ArrowRight, ShieldCheck, FileText, Warning } from "@phosphor-icons/react";
import { useLocation } from "react-router-dom";

export default function Login() {
  const location = useLocation();
  const authError = location.state?.authError;

  const handleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirect = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
  };

  return (
    <div className="min-h-screen w-full grid grid-cols-1 lg:grid-cols-[1.05fr_1fr] bg-[#F9F9F8]" data-testid="login-page">
      {/* Left visual */}
      <div className="relative hidden lg:block bg-[#0F172A]">
        <div
          className="absolute inset-0 mix-blend-luminosity opacity-60"
          style={{
            backgroundImage:
              "url(https://images.pexels.com/photos/8297076/pexels-photo-8297076.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200)",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-[#0F172A]/85 via-[#0F172A]/65 to-[#0F172A]/85" />
        <div className="relative z-10 flex flex-col justify-between h-full p-10 text-white">
          <div className="flex items-center gap-2 font-mono text-sm tracking-tight">
            <div className="w-6 h-6 border border-white/40 grid place-items-center font-mono text-[10px]">M</div>
            <span>MSS&nbsp;×&nbsp;Assure&nbsp;·&nbsp;Audit Utilities</span>
          </div>
          <div className="max-w-md">
            <p className="font-heading text-4xl xl:text-5xl leading-[1.05] tracking-tight">
              Audit utilities,<br/>refined for the everyday.
            </p>
            <p className="mt-6 text-white/70 text-sm leading-relaxed">
              The miscellaneous workbench from MSS &amp; Co. and AssureAI — small, well-built tools for the everyday audit chores AssureAI doesn't yet cover. Clause 44, TDS reconciliations, MSME 43B(h), 26AS / AIS / TIS — under one roof.
            </p>
            <ul className="mt-8 space-y-3 text-sm text-white/85">
              <li className="flex gap-3 items-start"><FileText size={18} weight="duotone" className="mt-0.5 shrink-0"/>Drop in books and mappings; we run the math.</li>
              <li className="flex gap-3 items-start"><ShieldCheck size={18} weight="duotone" className="mt-0.5 shrink-0"/>Every classification reasoned and auditable.</li>
            </ul>
          </div>
          <div className="font-mono text-xs text-white/45">v1.2&nbsp;·&nbsp;MSS &amp; Co. × AssureAI</div>
        </div>
      </div>

      {/* Right login */}
      <div className="flex items-center justify-center p-8 lg:p-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-2 font-mono text-sm tracking-tight mb-10">
            <div className="w-6 h-6 border border-[#0F172A] grid place-items-center text-[#0F172A] font-mono text-[10px]">M</div>
            <span className="text-[#0F172A]">MSS&nbsp;×&nbsp;Assure&nbsp;·&nbsp;Audit Utilities</span>
          </div>
          <div className="border border-[#E5E5E0] bg-white p-8 rounded-sm">
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#8A8A83]">Sign in</div>
            <h1 className="mt-2 font-heading text-3xl tracking-tight">Welcome back, partner.</h1>
            <p className="mt-3 text-sm text-[#52524E] leading-relaxed">
              Continue with your Google account. We use Emergent-managed authentication — your credentials never touch our servers.
            </p>
            {authError && (
              <div data-testid="auth-error-banner" className="mt-5 border border-rose-200 bg-rose-50 text-rose-900 rounded-sm p-3 flex gap-3 items-start">
                <Warning size={16} weight="duotone" className="text-rose-700 mt-0.5 shrink-0"/>
                <div className="text-[13px] leading-relaxed">{authError}</div>
              </div>
            )}

            <Button
              data-testid="google-login-btn"
              onClick={handleLogin}
              className="mt-8 w-full h-12 bg-[#0F172A] hover:bg-[#1E293B] text-white rounded-sm shadow-none flex items-center justify-center gap-3 font-medium"
            >
              <span className="bg-white rounded-full w-5 h-5 grid place-items-center">
                <svg viewBox="0 0 48 48" width="14" height="14"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
              </span>
              Continue with Google
              <ArrowRight size={16} weight="bold" />
            </Button>

            <div className="mt-8 grid grid-cols-3 gap-3 font-mono text-[10px] uppercase tracking-[0.12em] text-[#8A8A83]">
              <div className="border-t border-[#E5E5E0] pt-3">9&nbsp;Utilities</div>
              <div className="border-t border-[#E5E5E0] pt-3">Clause&nbsp;44&nbsp;Live</div>
              <div className="border-t border-[#E5E5E0] pt-3">More&nbsp;Soon</div>
            </div>
          </div>
          <p className="mt-6 text-xs text-[#8A8A83] leading-relaxed">
            By continuing you agree to operate this tool as part of your statutory audit workflow. Files remain bound to your account until manually archived.
          </p>
        </div>
      </div>
    </div>
  );
}
