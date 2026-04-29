"""Resend send engine + telemetry for Balance Confirmation.

Responsibilities
================
1. **render_email_html()** — substitute `{{placeholder}}` tokens in the chosen
   template with the per-confirmation context, append a tracking pixel <img>
   and rewrite the response button to go through our click-tracking redirect.
2. **send_one()** — call Resend's API in a thread (non-blocking FastAPI),
   attach Ledger Extract + Authorization PDF, set reply_to + cc passthrough,
   capture the resend message id, return success/failure.
3. **bulk_send()** — orchestrates an entire batch: pre-loads books JSON once,
   loops over selected ledgers, accumulates a send-log per ledger.
4. **render_email_text()** — auto-derive a plain-text fallback from HTML so
   the email passes spam filters that demand multi-part bodies.

Resend SDK is synchronous — we wrap with `asyncio.to_thread` per the
playbook recommendation. Failures are caught per-recipient, never block
the whole batch.
"""
from __future__ import annotations
import asyncio
import base64
import gzip
import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import resend

from modules.balance_confirmation.letter_pdf import build_ledger_extract_pdf

log = logging.getLogger("bc.sender")


# ============================ Template rendering ==============================
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _to_inr_string(n: float) -> str:
    if n is None:
        return "–"
    n = float(n)
    if n == 0:
        return "Nil"
    sign = "-" if n < 0 else ""
    return f"{sign}₹ {abs(n):,.2f}"


def render_template(text: str, ctx: Dict[str, Any]) -> str:
    """Replace `{{placeholder}}` tokens with values from `ctx` (HTML-escaped).
    Unknown placeholders are left as-is so the auditor can spot a typo."""
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in ctx:
            return m.group(0)
        v = ctx[key]
        return html.escape(str(v if v is not None else ""), quote=False)
    return _PLACEHOLDER_RE.sub(_sub, text or "")


def build_email_context(*,
                        run: Dict[str, Any],
                        client: Dict[str, Any],
                        ledger: Dict[str, Any],
                        auditor: Dict[str, Any],
                        public_base_url: str) -> Dict[str, Any]:
    """Assemble the placeholder dict shared between the email body and the
    in-app preview."""
    closing = float(ledger.get("closing_balance") or 0.0)
    dr_cr = "Dr" if closing < 0 else "Cr" if closing > 0 else ""
    response_link = f"{public_base_url.rstrip('/')}/confirm/{ledger['response_token']}"
    return {
        "client_name":           client.get("name") or "",
        "client_gstin":          client.get("gstin") or "",
        "as_at_date":            run.get("as_at_date") or "",
        "party_name":            ledger.get("name") or "",
        "contact_name_or_party": ledger.get("contact_name") or ledger.get("name") or "",
        "closing_balance_inr":   _to_inr_string(abs(closing)),
        "dr_cr":                 dr_cr,
        "response_link":         response_link,
        "auditor_name":          auditor.get("name") or "",
        "auditor_firm":          auditor.get("firm") or "",
        "address":               ledger.get("address") or "",
    }


def _strip_html(s: str) -> str:
    """Cheap HTML→text fallback for multi-part email."""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return html.unescape(s).strip()


def inject_tracking(html_body: str, *,
                    pixel_url: str,
                    response_link: str,
                    click_url: str) -> str:
    """1) rewrite `response_link` → `click_url` (302 redirect we own); 2)
    append a 1×1 transparent pixel <img> at the bottom for open tracking."""
    if response_link:
        # Both bare URL and href-quoted URL must be replaced.
        html_body = html_body.replace(f'href="{response_link}"', f'href="{click_url}"')
        html_body = html_body.replace(response_link, click_url)
    pixel = (
        f'<img src="{pixel_url}" width="1" height="1" alt="" '
        f'style="display:none;border:0;" />'
    )
    return html_body + pixel


# ============================ Resend send ====================================
def _resend_configured() -> bool:
    return bool((os.environ.get("RESEND_API_KEY") or "").strip())


def _from_addr() -> str:
    addr = (os.environ.get("RESEND_SENDER_EMAIL") or "").strip()
    name = (os.environ.get("RESEND_SENDER_NAME") or "").strip()
    if not addr:
        addr = "onboarding@resend.dev"
    return f"{name} <{addr}>" if name else addr


async def send_one(*,
                   to_email: str,
                   subject: str,
                   html_body: str,
                   text_body: str,
                   reply_to: Optional[str] = None,
                   cc: Optional[List[str]] = None,
                   attachments: Optional[List[Dict[str, Any]]] = None,
                   tags: Optional[List[Dict[str, str]]] = None,
                   from_name: Optional[str] = None) -> Dict[str, Any]:
    """Send a single transactional email via Resend.

    `from_name` (optional) overrides the static RESEND_SENDER_NAME for this
    one send — used for dynamic display names like
    ``Confirmation of Balance — M/s ABC Pvt Ltd``.

    Returns {ok: bool, id?, error?}. Never raises.
    """
    if not _resend_configured():
        return {"ok": False, "error": "RESEND_API_KEY not set"}
    resend.api_key = (os.environ.get("RESEND_API_KEY") or "").strip()

    if from_name:
        addr = (os.environ.get("RESEND_SENDER_EMAIL") or "onboarding@resend.dev").strip()
        from_field = f"{from_name} <{addr}>"
    else:
        from_field = _from_addr()

    params: Dict[str, Any] = {
        "from": from_field,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    if reply_to:
        params["reply_to"] = [reply_to] if isinstance(reply_to, str) else list(reply_to)
    if cc:
        params["cc"] = [c for c in cc if c]
    if attachments:
        params["attachments"] = [
            {
                "filename": a["filename"],
                "content": a["content_b64"] if isinstance(a.get("content_b64"), str)
                else base64.b64encode(a["content"]).decode("ascii"),
            }
            for a in attachments
        ]
    if tags:
        params["tags"] = tags

    try:
        res = await asyncio.to_thread(resend.Emails.send, params)
        return {"ok": True, "id": (res or {}).get("id"), "raw": res}
    except Exception as e:  # noqa: BLE001
        log.warning(f"Resend send failed for {to_email}: {e}")
        return {"ok": False, "error": str(e)}


# ============================ Books JSON helpers =============================
def load_books_from_run(books_raw_doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Decompress the gzipped books JSON we stored on ingest, return parsed dict."""
    if not books_raw_doc:
        return None
    try:
        content = gzip.decompress(base64.b64decode(books_raw_doc["content_b64"]))
        return json.loads(content.decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        log.warning(f"Books JSON decompress failed: {e}")
        return None


# ============================ Status transition =============================
SEND_STATUS_PROGRESSION = (
    "not_sent", "queued", "sent", "delivered", "opened", "clicked",
    "confirmed", "disputed", "bounced", "failed",
)
TERMINAL_STATUSES = {"confirmed", "disputed"}


def can_transition(current: str, target: str) -> bool:
    """Don't downgrade a confirmation that's already terminal."""
    if current in TERMINAL_STATUSES:
        return False
    if current == target:
        return False
    return target in SEND_STATUS_PROGRESSION


# ============================ Public attachment shape =======================
def attachment_dict(filename: str, content_bytes: bytes) -> Dict[str, Any]:
    return {
        "filename": filename,
        "content_b64": base64.b64encode(content_bytes).decode("ascii"),
    }


def build_extract_attachment(books: Optional[Dict[str, Any]],
                             ledger: Dict[str, Any],
                             client: Dict[str, Any],
                             as_at_date: str,
                             auditor_firm: str = "") -> Optional[Dict[str, Any]]:
    if not books:
        return None
    try:
        pdf = build_ledger_extract_pdf(
            ledger=ledger, books=books, client=client,
            as_at_date=as_at_date, auditor_firm=auditor_firm,
        )
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", ledger.get("name", "Ledger"))[:60]
        return attachment_dict(f"LedgerExtract_{safe}.pdf", pdf)
    except Exception as e:  # noqa: BLE001
        log.warning(f"Extract PDF build failed for {ledger.get('name')}: {e}")
        return None


def build_authorization_attachment(auth_doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not auth_doc:
        return None
    try:
        return {
            "filename": auth_doc.get("filename") or "AuthorizationLetter.pdf",
            "content_b64": auth_doc["content_b64"],
        }
    except KeyError:
        return None
