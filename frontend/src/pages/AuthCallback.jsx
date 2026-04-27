import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { authSession } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth() || {};
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash || "";
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) {
      navigate("/login", { replace: true });
      return;
    }
    const sessionId = decodeURIComponent(m[1]);

    (async () => {
      try {
        const user = await authSession(sessionId);
        setUser?.(user);
        window.history.replaceState({}, "", "/dashboard");
        navigate("/dashboard", { replace: true, state: { user } });
      } catch (e) {
        console.error("Auth exchange failed", e);
        const errMsg = e?.response?.data?.detail || "Sign-in failed. Please try again.";
        navigate("/login", { replace: true, state: { authError: errMsg } });
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen grid place-items-center bg-[#F9F9F8] text-[#52524E] font-mono text-sm">
      Authenticating…
    </div>
  );
}
