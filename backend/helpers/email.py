"""Transactional email via Resend (optional — gracefully no-ops if RESEND_API_KEY is unset)."""
import os
import logging

log = logging.getLogger("email")


def _render_invite_html(to_email: str, role: str, invited_by_name: str, app_url: str) -> str:
    role_label = "Admin" if role == "admin" else "User"
    role_pill_bg = "#EDE9FE" if role == "admin" else "#F1F5F9"
    role_pill_text = "#5B21B6" if role == "admin" else "#1E293B"
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F9F9F8;">
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#111110;padding:40px 16px;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #E5E5E0;border-radius:4px;overflow:hidden;">
    <div style="background:#0F172A;color:#ffffff;padding:20px 32px;display:flex;align-items:center;gap:10px;">
      <div style="width:28px;height:28px;border:1px solid rgba(255,255,255,0.4);display:inline-flex;align-items:center;justify-content:center;font-family:monospace;font-size:12px;">M</div>
      <div style="font-family:monospace;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;">MSS&nbsp;×&nbsp;ASSURE&nbsp;·&nbsp;AUDIT&nbsp;UTILITIES</div>
    </div>
    <div style="padding:36px 32px 28px;">
      <div style="display:inline-block;font-family:monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#8A8A83;">Invitation</div>
      <h1 style="font-size:28px;line-height:1.2;margin:10px 0 14px;color:#111110;font-weight:700;">You're invited.</h1>
      <p style="font-size:15px;line-height:1.7;color:#52524E;margin:0 0 14px;">
        <strong style="color:#111110;">{invited_by_name}</strong> has invited you to MSS&nbsp;×&nbsp;Assure as
        <span style="display:inline-block;background:{role_pill_bg};color:{role_pill_text};padding:2px 8px;border-radius:3px;font-family:monospace;font-size:11px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;margin-left:4px;">{role_label}</span>.
      </p>
      <p style="font-size:15px;line-height:1.7;color:#52524E;margin:0 0 28px;">
        You can sign in using your Google account associated with <strong style="color:#111110;">{to_email}</strong> — no password needed.
      </p>
      <a href="{app_url}/login" style="display:inline-block;background:#0F172A;color:#ffffff;text-decoration:none;padding:14px 26px;font-weight:600;font-size:14px;letter-spacing:0.01em;border-radius:3px;">Sign in with Google&nbsp;&rarr;</a>
      <div style="margin-top:36px;padding-top:24px;border-top:1px solid #E5E5E0;font-size:12.5px;color:#8A8A83;line-height:1.7;">
        If you didn't expect this invite you can safely ignore this email. Your access can be revoked at any time by your admin.
      </div>
    </div>
  </div>
  <div style="text-align:center;font-family:monospace;font-size:11px;color:#8A8A83;margin-top:24px;letter-spacing:0.04em;">
    MSS&nbsp;&amp;&nbsp;Co.&nbsp;·&nbsp;AssureAI&nbsp;·&nbsp;Audit&nbsp;Utilities
  </div>
</div>
</body></html>"""


def send_invite_email(to_email: str, role: str, invited_by_name: str, app_url: str) -> bool:
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not api_key:
        log.info(f"[email skipped] RESEND_API_KEY not set; would have invited {to_email}")
        return False
    try:
        import resend
        resend.api_key = api_key
        from_addr = os.environ.get("EMAIL_FROM", "MSS x Assure <onboarding@resend.dev>")
        html = _render_invite_html(to_email, role, invited_by_name, app_url.rstrip("/"))
        resend.Emails.send({
            "from": from_addr,
            "to": [to_email],
            "subject": "You've been invited to MSS × Assure · Audit Utilities",
            "html": html,
        })
        log.info(f"[email sent] invitation to {to_email} as {role}")
        return True
    except Exception as e:
        log.warning(f"[email failed] {to_email}: {e}")
        return False
