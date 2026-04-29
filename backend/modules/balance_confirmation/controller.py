"""Routes for the Balance Confirmation utility (prefix: /balance-confirmation).

Phase 1 — Data ingestion + ledger workbench
Phase 2 — Template configuration
Phase 3 — Sending engine (Resend) + bulk send + reminders + telemetry

Phases 4-6 (recipient response loop UI, full reconciliation) will land in
subsequent iterations. Database schema is already token-ready: every ledger
receives a UUID `response_token` at ingest time.
"""
from __future__ import annotations
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel
from svix.webhooks import Webhook, WebhookVerificationError

from core.db import db
from modules.auth.controller import get_current_user
from modules.balance_confirmation.exports import build_authorization_template_docx
from modules.balance_confirmation.schemas import (
    AuthorizationOut,
    LedgerPatch,
    PublicConfirmRequest,
    RunCreate,
    RunOut,
    TemplateUpsert,
)
from modules.balance_confirmation.sender import (
    build_authorization_attachment,
    build_email_context,
    build_extract_attachment,
    can_transition,
    inject_tracking,
    load_books_from_run,
    render_template,
    send_one,
    _strip_html,
)
from modules.balance_confirmation.service import (
    EMAIL_CSV_COLUMNS,
    build_ledger_records,
    export_email_csv,
    fy_end_date,
    import_email_csv,
    parse_books_json,
    summarise_ledgers,
)
from modules.balance_confirmation.templates import all_defaults

router = APIRouter(prefix="/balance-confirmation")
log = logging.getLogger("balance_confirmation")

RUNS = db.bc_runs
LEDGERS = db.bc_ledgers
TEMPLATES = db.bc_templates
AUTH = db.bc_authorizations
BOOKS_RAW = db.bc_books_raw  # gzipped JSON (kept for re-classification later)
SENDLOG = db.bc_send_log     # one row per send attempt (Phase 3)


# Transparent 1×1 GIF — 43 bytes, no external request needed.
_PIXEL_GIF = base64.b64decode(
    b"R0lGODlhAQABAIAAAP///wAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
)


async def _auth(request: Request, tok: Optional[str], hdr: Optional[str]):
    return await get_current_user(request, tok, hdr)


# ============================ Runs ============================================
@router.post("/runs", response_model=RunOut)
async def create_run(
    payload: RunCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    if not payload.client_id:
        raise HTTPException(400, "client_id is required")
    if not payload.fy:
        raise HTTPException(400, "fy is required (e.g. '2024-25')")

    # Best-effort default for as_at_date
    as_at = (payload.as_at_date or "").strip() or fy_end_date(payload.fy)

    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "client_id": payload.client_id,
        "fy": payload.fy,
        "name": (payload.name or f"Balance Confirmation {payload.fy}").strip(),
        "as_at_date": as_at,
        "source_filename": "",
        "status": "draft",
        "summary": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_user_id": user["user_id"],
        "created_by_name": user.get("name") or "",
        "created_by_email": user.get("email") or "",
    }
    await RUNS.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/runs", response_model=List[RunOut])
async def list_runs(
    request: Request,
    client_id: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    q: Dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    docs = await RUNS.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@router.get("/runs/{rid}")
async def get_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")
    return doc


@router.delete("/runs/{rid}")
async def delete_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    res = await RUNS.delete_one({"id": rid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Run not found")
    # Cascade
    await LEDGERS.delete_many({"run_id": rid})
    await BOOKS_RAW.delete_many({"run_id": rid})
    await SENDLOG.delete_many({"run_id": rid})
    await db.bc_responses.delete_many({"run_id": rid})
    return {"deleted": True}


# ============================ Books JSON ingest ===============================
@router.post("/runs/{rid}/upload-books")
async def upload_books(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")

    content = await file.read()
    try:
        company, groups, ledgers = parse_books_json(content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Persist gzipped raw for any later re-classification + audit trail
    import gzip
    await BOOKS_RAW.delete_many({"run_id": rid})
    await BOOKS_RAW.insert_one({
        "run_id": rid,
        "filename": file.filename or "",
        "content_b64": base64.b64encode(gzip.compress(content)).decode("ascii"),
        "size": len(content),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })

    # Build ledger records — replace any prior ledgers from earlier upload, but
    # preserve manual email mappings if the same name reappears.
    existing = {
        L["name"]: L for L in await LEDGERS.find(
            {"run_id": rid}, {"_id": 0}
        ).to_list(20000)
    }
    new_records = build_ledger_records(rid, groups, ledgers)
    for rec in new_records:
        prev = existing.get(rec["name"])
        if prev:
            # carry forward user-edited fields
            for k in ("email", "cc_emails", "contact_name", "phone",
                      "address", "gstin", "pan", "category"):
                if prev.get(k):
                    rec[k] = prev[k]
            # keep the prior token + status so any sent/awaiting links don't break
            rec["response_token"] = prev.get("response_token") or rec["response_token"]
            rec["confirmation_status"] = prev.get("confirmation_status") or rec["confirmation_status"]

    await LEDGERS.delete_many({"run_id": rid})
    if new_records:
        await LEDGERS.insert_many(new_records)

    summary = summarise_ledgers(new_records)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {
            "source_filename": file.filename or "",
            "company": company,
            "summary": summary,
            "status": "ingested",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {
        "ledger_count": len(new_records),
        "summary": summary,
        "company": company,
    }


# ============================ Ledgers (workbench) =============================
@router.get("/runs/{rid}/ledgers")
async def list_ledgers(
    rid: str,
    request: Request,
    category: Optional[str] = None,
    missing_email: Optional[bool] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    q: Dict[str, Any] = {"run_id": rid}
    if category:
        q["category"] = category
    if missing_email:
        q["email"] = ""
    rows = await LEDGERS.find(q, {"_id": 0}).sort("name", 1).to_list(20000)
    return {"rows": rows, "count": len(rows)}


@router.patch("/runs/{rid}/ledgers/{ledger_id}")
async def patch_ledger(
    rid: str,
    ledger_id: str,
    payload: LedgerPatch,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await LEDGERS.find_one({"run_id": rid, "ledger_id": ledger_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Ledger not found")
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "category" in update and update["category"] not in ("trade_receivable", "trade_payable", "bank", "other"):
        raise HTTPException(400, "Invalid category")
    if update:
        update["last_modified"] = datetime.now(timezone.utc).isoformat()
        await LEDGERS.update_one({"run_id": rid, "ledger_id": ledger_id}, {"$set": update})
        # Recompute run summary so the dashboard counts stay fresh
        rows = await LEDGERS.find({"run_id": rid}, {"_id": 0}).to_list(20000)
        await RUNS.update_one({"id": rid}, {"$set": {"summary": summarise_ledgers(rows)}})
    return await LEDGERS.find_one({"run_id": rid, "ledger_id": ledger_id}, {"_id": 0})


@router.get("/runs/{rid}/ledgers/export.csv")
async def export_ledgers_csv(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    rows = await LEDGERS.find({"run_id": rid}, {"_id": 0}).sort("name", 1).to_list(20000)
    csv_bytes = export_email_csv(rows)
    fname = f"BalanceConfirmation_EmailMaster_{rid[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/runs/{rid}/ledgers/import.csv")
async def import_ledgers_csv(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    content = await file.read()
    try:
        updates = import_email_csv(content)
    except Exception as e:
        log.exception("CSV import failed")
        raise HTTPException(400, f"CSV parse failed: {e}")

    matched = 0
    not_found: List[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for u in updates:
        q: Dict[str, Any] = {"run_id": rid}
        if u.get("ledger_id"):
            q["ledger_id"] = u["ledger_id"]
        elif u.get("name"):
            q["name"] = u["name"]
        else:
            continue
        update = {
            k: v for k, v in u.items()
            if k not in ("ledger_id", "name") and v is not None
        }
        if not update:
            continue
        update["last_modified"] = now_iso
        res = await LEDGERS.update_one(q, {"$set": update})
        if res.matched_count:
            matched += 1
        else:
            not_found.append(u.get("name") or u.get("ledger_id") or "?")

    rows = await LEDGERS.find({"run_id": rid}, {"_id": 0}).to_list(20000)
    summary = summarise_ledgers(rows)
    await RUNS.update_one({"id": rid}, {"$set": {"summary": summary}})
    return {
        "rows_in_csv": len(updates),
        "matched": matched,
        "not_found": not_found[:50],
        "summary": summary,
    }


# ============================ Authorization Letter ===========================
@router.post("/clients/{cid}/authorization", response_model=AuthorizationOut)
async def upload_authorization(
    cid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    if not await db.clients.find_one({"client_id": cid}, {"_id": 0, "client_id": 1}):
        raise HTTPException(404, "Client not found")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if not (file.content_type or "").lower().startswith(("application/pdf",)) and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Authorization letter must be a PDF")
    doc = {
        "client_id": cid,
        "filename": file.filename or "authorization.pdf",
        "content_b64": base64.b64encode(content).decode("ascii"),
        "size": len(content),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by_name": user.get("name") or "",
    }
    await AUTH.replace_one({"client_id": cid}, doc, upsert=True)
    return {
        "client_id": cid,
        "filename": doc["filename"],
        "size": doc["size"],
        "uploaded_at": doc["uploaded_at"],
        "uploaded_by_name": doc["uploaded_by_name"],
    }


@router.get("/clients/{cid}/authorization", response_model=Optional[AuthorizationOut])
async def get_authorization_meta(
    cid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await AUTH.find_one({"client_id": cid}, {"_id": 0, "content_b64": 0})
    return doc


@router.get("/clients/{cid}/authorization/file")
async def download_authorization(
    cid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await AUTH.find_one({"client_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "No authorization letter on file")
    pdf_bytes = base64.b64decode(doc["content_b64"])
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
    )


@router.delete("/clients/{cid}/authorization")
async def delete_authorization(
    cid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    res = await AUTH.delete_one({"client_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "No authorization letter on file")
    return {"deleted": True}


@router.get("/clients/{cid}/authorization/template.docx")
async def download_authorization_template(
    cid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Editable Word letter the client can sign and re-upload as the auth PDF."""
    await _auth(request, session_token, authorization)
    client = await db.clients.find_one({"client_id": cid}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    docx_bytes = build_authorization_template_docx(client)
    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": (
            f'attachment; filename="Authorization_Template_{(client.get("name") or "Client").replace(" ", "_")}.docx"'
        )},
    )


# ============================ Templates =======================================
async def _ensure_default_templates() -> None:
    """Idempotent: insert one row per default kind if no global default exists."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for d in all_defaults():
        existing = await TEMPLATES.find_one({"kind": d["kind"], "is_default": True})
        if existing:
            continue
        await TEMPLATES.insert_one({
            "template_id": str(uuid.uuid4()),
            "kind": d["kind"],
            "name": d["name"],
            "subject": d["subject"],
            "html_body": d["html_body"],
            "is_default": True,
            "scope": "global",
            "created_at": now_iso,
            "updated_at": now_iso,
        })


@router.get("/templates")
async def list_templates(
    request: Request,
    kind: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    await _ensure_default_templates()  # cheap; runs only on first call
    q: Dict[str, Any] = {}
    if kind:
        q["kind"] = kind
    rows = await TEMPLATES.find(q, {"_id": 0}).sort("created_at", 1).to_list(200)
    return {"rows": rows}


@router.post("/templates")
async def create_template(
    payload: TemplateUpsert,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    if payload.kind not in ("customer", "vendor", "bank"):
        raise HTTPException(400, "kind must be customer | vendor | bank")
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "template_id": str(uuid.uuid4()),
        "kind": payload.kind,
        "name": payload.name.strip() or f"Custom {payload.kind} template",
        "subject": payload.subject.strip(),
        "html_body": payload.html_body,
        "is_default": False,
        "scope": "global",
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_by_email": user.get("email") or "",
    }
    await TEMPLATES.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/templates/{tid}")
async def update_template(
    tid: str,
    payload: TemplateUpsert,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if payload.kind not in ("customer", "vendor", "bank"):
        raise HTTPException(400, "kind must be customer | vendor | bank")
    res = await TEMPLATES.update_one(
        {"template_id": tid},
        {"$set": {
            "kind": payload.kind,
            "name": payload.name.strip(),
            "subject": payload.subject.strip(),
            "html_body": payload.html_body,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Template not found")
    return await TEMPLATES.find_one({"template_id": tid}, {"_id": 0})


@router.delete("/templates/{tid}")
async def delete_template(
    tid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await TEMPLATES.find_one({"template_id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Template not found")
    if doc.get("is_default"):
        raise HTTPException(400, "Default templates cannot be deleted; edit instead")
    await TEMPLATES.delete_one({"template_id": tid})
    return {"deleted": True}


# ============================ Phase 3 — Sending engine =======================
class BulkSendRequest(BaseModel):
    ledger_ids: List[str]
    template_id: Optional[str] = None  # if missing, use default per category
    cc: List[str] = []                 # universal cc applied to every send
    extra_subject_suffix: Optional[str] = None
    is_reminder: bool = False
    auditor_firm: Optional[str] = None


def _public_base_url(request: Request) -> str:
    """Return the base URL the recipient will hit. Falls back to host header.
    For prod we can pin via PUBLIC_BASE_URL env if needed."""
    pinned = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    if pinned:
        return pinned.rstrip("/")
    # Build from request
    scheme = request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _send_log_doc(*, run_id: str, ledger_id: str, kind: str, status: str,
                  resend_id: Optional[str] = None, error: Optional[str] = None,
                  to_email: str = "", subject: str = "", actor_email: str = "") -> Dict[str, Any]:
    return {
        "log_id": str(uuid.uuid4()),
        "run_id": run_id,
        "ledger_id": ledger_id,
        "kind": kind,                  # "send" | "reminder" | "webhook" | "telemetry"
        "status": status,              # "queued" | "sent" | "failed" | "delivered" | "bounced" | ...
        "resend_id": resend_id or "",
        "error": error or "",
        "to_email": to_email,
        "subject": subject,
        "actor_email": actor_email,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def _resolve_template(template_id: Optional[str], category: str) -> Optional[Dict[str, Any]]:
    if template_id:
        t = await TEMPLATES.find_one({"template_id": template_id}, {"_id": 0})
        if t:
            return t
    kind = "customer" if category == "trade_receivable" else \
           "vendor" if category == "trade_payable" else \
           "bank"     if category == "bank" else "customer"
    return await TEMPLATES.find_one({"kind": kind, "is_default": True}, {"_id": 0})


@router.post("/runs/{rid}/send")
async def bulk_send(
    rid: str,
    payload: BulkSendRequest,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Bulk-send confirmation emails. Each recipient receives a Resend message
    with: rendered HTML body (template + tracking pixel) + Ledger Extract PDF +
    (optional) signed Authorization PDF. reply_to = current user's email; cc =
    universal cc + per-ledger cc_emails. Failures are isolated per recipient.
    """
    user = await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    if not payload.ledger_ids:
        raise HTTPException(400, "ledger_ids is required")

    client = await db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found for this run")

    # Pre-load — books + auth letter ONCE per batch
    books_raw = await BOOKS_RAW.find_one({"run_id": rid}, {"_id": 0})
    books = load_books_from_run(books_raw)
    auth_doc = await AUTH.find_one({"client_id": run["client_id"]}, {"_id": 0})
    auth_attachment = build_authorization_attachment(auth_doc)

    base_url = _public_base_url(request)
    auditor_email = (user.get("email") or "").strip()
    auditor_firm = (payload.auditor_firm or "").strip() or "MSS & Co."

    results: List[Dict[str, Any]] = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for ledger_id in payload.ledger_ids:
        ledger = await LEDGERS.find_one({"run_id": rid, "ledger_id": ledger_id}, {"_id": 0})
        if not ledger:
            results.append({"ledger_id": ledger_id, "ok": False, "error": "Ledger not found"})
            failed_count += 1
            continue
        if not ledger.get("email"):
            results.append({"ledger_id": ledger_id, "name": ledger.get("name"),
                            "ok": False, "error": "No email on file"})
            skipped_count += 1
            continue

        template = await _resolve_template(payload.template_id, ledger.get("category", "other"))
        if not template:
            results.append({"ledger_id": ledger_id, "name": ledger.get("name"),
                            "ok": False, "error": "No template available"})
            skipped_count += 1
            continue

        ctx = build_email_context(
            run=run, client=client, ledger=ledger,
            auditor={"name": user.get("name") or auditor_email, "firm": auditor_firm},
            public_base_url=base_url,
        )
        subject = render_template(template["subject"], ctx)
        if payload.is_reminder:
            subject = f"[Reminder] {subject}"
        if payload.extra_subject_suffix:
            subject = f"{subject} {payload.extra_subject_suffix}"
        body = render_template(template["html_body"], ctx)

        token = ledger["response_token"]
        pixel_url = f"{base_url}/api/balance-confirmation/track/pixel/{token}.gif"
        click_url = f"{base_url}/api/balance-confirmation/track/click/{token}"
        body = inject_tracking(
            body, pixel_url=pixel_url,
            response_link=ctx["response_link"], click_url=click_url,
        )
        text_body = _strip_html(body)

        # Per-ledger cc = universal + ledger.cc_emails
        cc_list = list(set([*(payload.cc or []), *(ledger.get("cc_emails") or [])]))

        # Attachments
        attachments: List[Dict[str, Any]] = []
        ext = build_extract_attachment(books, ledger, client,
                                       run.get("as_at_date") or "", auditor_firm)
        if ext:
            attachments.append(ext)
        if auth_attachment:
            attachments.append(auth_attachment)

        # Mark queued, send, settle
        kind = "reminder" if payload.is_reminder else "send"
        await LEDGERS.update_one(
            {"run_id": rid, "ledger_id": ledger_id},
            {"$set": {
                "confirmation_status": "queued",
                "queued_at": now_iso,
                "last_modified": now_iso,
            }},
        )

        send_res = await send_one(
            to_email=ledger["email"],
            subject=subject,
            html_body=body,
            text_body=text_body,
            reply_to=auditor_email or None,
            cc=cc_list or None,
            attachments=attachments or None,
            tags=[
                {"name": "run_id", "value": rid[:40]},
                {"name": "kind", "value": kind},
            ],
        )

        if send_res.get("ok"):
            sent_count += 1
            new_status = "sent"
            await LEDGERS.update_one(
                {"run_id": rid, "ledger_id": ledger_id},
                {"$set": {
                    "confirmation_status": new_status,
                    "sent_at": now_iso,
                    "resend_id": send_res.get("id") or "",
                    "last_error": "",
                    "last_subject": subject,
                    "last_modified": now_iso,
                }, "$inc": {"send_attempts": 1}},
            )
            if payload.is_reminder:
                await LEDGERS.update_one(
                    {"run_id": rid, "ledger_id": ledger_id},
                    {"$set": {"last_reminded_at": now_iso}},
                )
            await SENDLOG.insert_one(_send_log_doc(
                run_id=rid, ledger_id=ledger_id, kind=kind,
                status=new_status, resend_id=send_res.get("id") or "",
                to_email=ledger["email"], subject=subject,
                actor_email=auditor_email,
            ))
            results.append({"ledger_id": ledger_id, "name": ledger.get("name"),
                            "ok": True, "id": send_res.get("id")})
        else:
            failed_count += 1
            await LEDGERS.update_one(
                {"run_id": rid, "ledger_id": ledger_id},
                {"$set": {
                    "confirmation_status": "failed",
                    "last_error": send_res.get("error") or "Send failed",
                    "last_error_at": now_iso,
                    "last_modified": now_iso,
                }, "$inc": {"send_attempts": 1}},
            )
            await SENDLOG.insert_one(_send_log_doc(
                run_id=rid, ledger_id=ledger_id, kind=kind,
                status="failed", error=send_res.get("error"),
                to_email=ledger["email"], subject=subject,
                actor_email=auditor_email,
            ))
            results.append({"ledger_id": ledger_id, "name": ledger.get("name"),
                            "ok": False, "error": send_res.get("error")})

    # Refresh run summary
    rows = await LEDGERS.find({"run_id": rid}, {"_id": 0}).to_list(20000)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {"summary": summarise_ledgers(rows), "status": "sending"}},
    )
    return {
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "results": results,
    }


@router.get("/runs/{rid}/reminders")
async def list_reminder_eligible(
    rid: str,
    request: Request,
    cadence_days: int = 3,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """List ledgers eligible for a reminder (read-only, idempotent).
    Default cadence 3 → next sweeps at 7 → 14 days. The sending step itself
    happens via POST /runs/{rid}/send with `is_reminder=true` and the chosen
    `ledger_ids[]` from this list."""
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cadence_days)).isoformat()
    rows = await LEDGERS.find(
        {
            "run_id": rid,
            "confirmation_status": {"$in": ["sent", "delivered", "opened", "clicked"]},
            "$or": [
                {"last_reminded_at": {"$exists": False}},
                {"last_reminded_at": {"$lt": cutoff}},
            ],
            "sent_at": {"$lt": cutoff},
            "email": {"$ne": ""},
        },
        {"_id": 0, "ledger_id": 1, "name": 1},
    ).to_list(2000)
    return {"eligible": rows, "count": len(rows), "cadence_days": cadence_days}


# ============================ Send log ======================================
@router.get("/runs/{rid}/send-log")
async def get_send_log(
    rid: str,
    request: Request,
    ledger_id: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    q: Dict[str, Any] = {"run_id": rid}
    if ledger_id:
        q["ledger_id"] = ledger_id
    rows = await SENDLOG.find(q, {"_id": 0}).sort("ts", -1).to_list(2000)
    return {"rows": rows, "count": len(rows)}


# ============================ Public telemetry ===============================
async def _record_telemetry(token: str, event: str) -> Optional[Dict[str, Any]]:
    """Update the ledger's status + timestamp + write a telemetry log row.
    `event` ∈ {opened, clicked}. Returns the ledger doc or None."""
    ledger = await LEDGERS.find_one({"response_token": token}, {"_id": 0})
    if not ledger:
        return None
    now_iso = datetime.now(timezone.utc).isoformat()
    set_ops: Dict[str, Any] = {"last_modified": now_iso}
    if event == "opened":
        set_ops["opened_at"] = ledger.get("opened_at") or now_iso
        if can_transition(ledger.get("confirmation_status", "not_sent"), "opened"):
            set_ops["confirmation_status"] = "opened"
    elif event == "clicked":
        set_ops["clicked_at"] = ledger.get("clicked_at") or now_iso
        if can_transition(ledger.get("confirmation_status", "not_sent"), "clicked"):
            set_ops["confirmation_status"] = "clicked"
    await LEDGERS.update_one({"response_token": token}, {"$set": set_ops})
    await SENDLOG.insert_one(_send_log_doc(
        run_id=ledger["run_id"], ledger_id=ledger["ledger_id"],
        kind="telemetry", status=event,
        to_email=ledger.get("email", ""),
    ))
    return ledger


@router.get("/track/pixel/{token}.gif")
async def track_open_pixel(token: str):
    """Public endpoint — no auth. Hit by recipient mail clients on open. Always
    returns the 1×1 gif (even if token is unknown — never leak which tokens
    are valid)."""
    await _record_telemetry(token, "opened")
    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/track/click/{token}")
async def track_click(token: str, request: Request):
    """Public — log + 302 redirect to the recipient confirmation page."""
    await _record_telemetry(token, "clicked")
    base = _public_base_url(request)
    return RedirectResponse(url=f"{base}/confirm/{token}", status_code=302)


# ============================ Resend webhook =================================
_RESEND_EVENT_TO_STATUS = {
    "email.sent":       "sent",
    "email.delivered":  "delivered",
    "email.opened":     "opened",
    "email.clicked":    "clicked",
    "email.bounced":    "bounced",
    "email.complained": "bounced",  # treat complaint same severity as bounce
    "email.delivery_delayed": None,  # no status flip; just log
}


@router.post("/webhook/resend")
async def resend_webhook(request: Request):
    """Verify Svix-signed webhook and update ledger status from Resend events.

    Public endpoint — auth via signature only. Returns 200 even on unknown
    event to prevent retries.
    """
    secret = (os.environ.get("RESEND_WEBHOOK_SECRET") or "").strip()
    body_bytes = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not secret:
        # Fail-closed: if no secret is configured we can't trust the payload,
        # so reject. (Set RESEND_WEBHOOK_SECRET in env to enable.)
        raise HTTPException(503, "Webhook handler not configured")

    try:
        wh = Webhook(secret)
        wh.verify(body_bytes, {
            "svix-id":         headers.get("svix-id", ""),
            "svix-timestamp":  headers.get("svix-timestamp", ""),
            "svix-signature":  headers.get("svix-signature", ""),
        })
    except WebhookVerificationError as e:
        raise HTTPException(401, f"Invalid webhook signature: {e}")

    try:
        evt = json.loads(body_bytes.decode("utf-8", errors="replace"))
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event_type = evt.get("type", "")
    data = evt.get("data") or {}
    resend_id = data.get("email_id") or data.get("id") or ""
    if not resend_id:
        return {"ok": True, "skipped": "no email_id"}

    target_status = _RESEND_EVENT_TO_STATUS.get(event_type)
    ledger = await LEDGERS.find_one({"resend_id": resend_id}, {"_id": 0})
    if not ledger:
        return {"ok": True, "matched": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    set_ops: Dict[str, Any] = {"last_modified": now_iso}
    field_for = {
        "delivered": "delivered_at",
        "opened":    "opened_at",
        "clicked":   "clicked_at",
        "bounced":   "bounced_at",
    }
    if target_status:
        if target_status in field_for and not ledger.get(field_for[target_status]):
            set_ops[field_for[target_status]] = now_iso
        if can_transition(ledger.get("confirmation_status", "not_sent"), target_status):
            set_ops["confirmation_status"] = target_status
    await LEDGERS.update_one({"resend_id": resend_id}, {"$set": set_ops})
    await SENDLOG.insert_one(_send_log_doc(
        run_id=ledger["run_id"], ledger_id=ledger["ledger_id"],
        kind="webhook", status=target_status or event_type,
        resend_id=resend_id, to_email=ledger.get("email", ""),
    ))
    return {"ok": True, "matched": True, "event": event_type, "status": target_status}


# ============================ Cascade enhancement ============================
# Re-export delete_run cascade — extend to drop send-log on run delete
@router.delete("/runs/{rid}/send-log")
async def clear_send_log(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    res = await SENDLOG.delete_many({"run_id": rid})
    return {"deleted": res.deleted_count}



# ============================ Phase 4 — Recipient response loop ==============
RESPONSES = db.bc_responses  # one doc per (token, latest submission)


def _public_ctx_for_ledger(ledger: Dict[str, Any], run: Dict[str, Any],
                           client: Dict[str, Any]) -> Dict[str, Any]:
    closing = float(ledger.get("closing_balance") or 0.0)
    dr_cr = "Dr" if closing < 0 else "Cr" if closing > 0 else ""
    return {
        "party_name":          ledger.get("name") or "",
        "contact_name":        ledger.get("contact_name") or "",
        "closing_balance":     round(abs(closing), 2),
        "dr_cr":               dr_cr,
        "as_at_date":          run.get("as_at_date") or "",
        "fy":                  run.get("fy") or "",
        "client_name":         client.get("name") or "",
        "client_gstin":        client.get("gstin") or "",
        "auditor_firm":        run.get("auditor_firm") or "MSS & Co.",
        "auditor_name":        run.get("created_by_name") or "",
        "confirmation_status": ledger.get("confirmation_status") or "not_sent",
    }


@router.get("/public/confirmation/{token}")
async def public_get_confirmation(token: str):
    """Public endpoint — no auth. Returns the context the recipient page renders."""
    ledger = await LEDGERS.find_one({"response_token": token}, {"_id": 0})
    if not ledger:
        raise HTTPException(404, "This confirmation link is invalid or has expired.")
    run = await RUNS.find_one({"id": ledger["run_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Confirmation request not found.")
    client = await db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0}) or {}
    ctx = _public_ctx_for_ledger(ledger, run, client)

    # If a response already exists, surface it (read-only acknowledgement)
    submitted = await RESPONSES.find_one(
        {"response_token": token},
        {"_id": 0, "uploaded_content_b64": 0},  # never echo file bytes
    )
    ctx["submitted_response"] = submitted
    return ctx


async def _record_response(*, ledger: Dict[str, Any], run: Dict[str, Any],
                           decision: str, payload: Dict[str, Any],
                           request: Request,
                           uploaded: Optional[UploadFile] = None) -> Dict[str, Any]:
    """Common writer for confirm + dispute — also flips ledger to terminal status."""
    now_iso = datetime.now(timezone.utc).isoformat()
    doc: Dict[str, Any] = {
        "response_id": str(uuid.uuid4()),
        "run_id": run["id"],
        "ledger_id": ledger["ledger_id"],
        "response_token": ledger["response_token"],
        "decision": decision,                   # "confirmed" | "disputed"
        "responder_name":  (payload.get("responder_name") or "").strip(),
        "responder_email": (payload.get("responder_email") or "").strip(),
        "their_balance":   payload.get("their_balance"),
        "their_dr_cr":     (payload.get("their_dr_cr") or "").strip(),
        "reason":          (payload.get("reason") or "").strip(),
        "note":            (payload.get("note") or "").strip(),
        "responder_ip":    (request.client.host if request.client else "") or
                           request.headers.get("x-forwarded-for", ""),
        "user_agent":      request.headers.get("user-agent", "")[:300],
        "submitted_at":    now_iso,
    }

    # Optional uploaded ledger statement (disputed only)
    if uploaded is not None:
        content = await uploaded.read()
        # Cap at 8MB to keep our Mongo doc sane (Resend attachment cap is 40MB
        # but we're storing in BSON which is hard-limited at 16MB).
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(413, "Attachment too large (max 8MB)")
        if content:
            doc["uploaded_filename"] = uploaded.filename or "attachment"
            doc["uploaded_size"] = len(content)
            doc["uploaded_content_b64"] = base64.b64encode(content).decode("ascii")

    await RESPONSES.replace_one(
        {"response_token": ledger["response_token"]}, doc, upsert=True,
    )

    # Flip ledger status — confirmed/disputed are TERMINAL (can_transition guard)
    set_ops: Dict[str, Any] = {
        "confirmation_status": decision,
        "responded_at":        now_iso,
        "last_modified":       now_iso,
    }
    await LEDGERS.update_one(
        {"ledger_id": ledger["ledger_id"]}, {"$set": set_ops},
    )

    # Audit trail
    await SENDLOG.insert_one(_send_log_doc(
        run_id=run["id"], ledger_id=ledger["ledger_id"],
        kind="response", status=decision,
        to_email=ledger.get("email", ""),
        subject=f"Recipient {decision} via /confirm",
    ))
    # Don't echo file bytes back
    out = {k: v for k, v in doc.items() if k != "uploaded_content_b64"}
    return out


@router.post("/public/confirmation/{token}/confirm")
async def public_confirm(token: str, payload: PublicConfirmRequest, request: Request):
    """Public — recipient confirms the balance shown."""
    ledger = await LEDGERS.find_one({"response_token": token}, {"_id": 0})
    if not ledger:
        raise HTTPException(404, "Invalid confirmation link.")
    run = await RUNS.find_one({"id": ledger["run_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Confirmation request not found.")
    return await _record_response(
        ledger=ledger, run=run,
        decision="confirmed", payload=payload.model_dump(),
        request=request,
    )


@router.post("/public/confirmation/{token}/dispute")
async def public_dispute(
    token: str,
    request: Request,
    responder_name: str = Form(""),
    responder_email: str = Form(""),
    their_balance: Optional[float] = Form(default=None),
    their_dr_cr: str = Form(""),
    reason: str = Form(""),
    file: Optional[UploadFile] = File(default=None),
):
    """Public — recipient disagrees and (optionally) attaches their statement.
    Multipart endpoint so the file uploads land natively from the browser."""
    # Early DoS guard — reject oversize requests BEFORE we buffer the body.
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > 9 * 1024 * 1024:  # 9MB request cap
        raise HTTPException(413, "Attachment too large (max 8MB)")
    if not (reason or "").strip():
        raise HTTPException(400, "Please provide a reason explaining the difference.")
    ledger = await LEDGERS.find_one({"response_token": token}, {"_id": 0})
    if not ledger:
        raise HTTPException(404, "Invalid confirmation link.")
    run = await RUNS.find_one({"id": ledger["run_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Confirmation request not found.")
    return await _record_response(
        ledger=ledger, run=run,
        decision="disputed",
        payload={
            "responder_name": responder_name,
            "responder_email": responder_email,
            "their_balance": their_balance,
            "their_dr_cr": their_dr_cr,
            "reason": reason,
        },
        request=request,
        uploaded=file,
    )


# ============================ Auditor-side responses view ===================
@router.get("/runs/{rid}/responses")
async def list_responses(
    rid: str,
    request: Request,
    decision: Optional[str] = None,  # confirmed | disputed
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    q: Dict[str, Any] = {"run_id": rid}
    if decision:
        q["decision"] = decision
    rows = await RESPONSES.find(
        q, {"_id": 0, "uploaded_content_b64": 0}
    ).sort("submitted_at", -1).to_list(2000)
    # Enrich each response with the ledger name + balance for easy display
    if rows:
        ledger_ids = [r["ledger_id"] for r in rows]
        ledgers = {
            L["ledger_id"]: L for L in await LEDGERS.find(
                {"ledger_id": {"$in": ledger_ids}},
                {"_id": 0, "ledger_id": 1, "name": 1, "closing_balance": 1, "dr_cr": 1, "email": 1},
            ).to_list(5000)
        }
        for r in rows:
            L = ledgers.get(r["ledger_id"]) or {}
            r["ledger_name"] = L.get("name", "")
            r["our_balance"] = L.get("closing_balance", 0.0)
            r["our_dr_cr"] = L.get("dr_cr", "")
    return {"rows": rows, "count": len(rows)}


@router.get("/runs/{rid}/responses/{response_id}/attachment")
async def download_response_attachment(
    rid: str, response_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Download the recipient's uploaded statement (auth-gated)."""
    await _auth(request, session_token, authorization)
    doc = await RESPONSES.find_one(
        {"run_id": rid, "response_id": response_id}, {"_id": 0},
    )
    if not doc or not doc.get("uploaded_content_b64"):
        raise HTTPException(404, "No attachment on this response")
    content = base64.b64decode(doc["uploaded_content_b64"])
    fname = doc.get("uploaded_filename") or "recipient_statement"
    # Sanitise filename for the Content-Disposition header — strip path
    # separators and quotes that could break the header / enable attacks.
    import re as _re
    safe_fname = _re.sub(r"[\r\n\"\\]+", "_", fname).split("/")[-1].split("\\")[-1]
    # Pick a content-type by extension (best-effort)
    ext = safe_fname.lower().rsplit(".", 1)[-1] if "." in safe_fname else ""
    media = {
        "pdf":  "application/pdf",
        "csv":  "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":  "application/vnd.ms-excel",
        "png":  "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe_fname}"'},
    )

