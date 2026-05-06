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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel
from svix.webhooks import Webhook, WebhookVerificationError

from core.db import db
from modules.auth.controller import get_current_user
from modules.library import service as lib_svc
from modules.library.controller import DEFAULT_FIRM_ID
from modules.library.generations import append_generation, list_generations
from modules.balance_confirmation.exports import build_authorization_template_docx
from modules.balance_confirmation.recon import auto_match, parse_recipient_statement
from modules.balance_confirmation.schemas import (
    AuthorizationOut,
    LedgerPatch,
    PublicConfirmRequest,
    RunCreate,
    RunOut,
    TemplateUpsert,
)
from modules.balance_confirmation.summary_export import (
    build_summary_pdf, build_summary_xlsx,
)
from modules.balance_confirmation.analytics import build_analytics
from modules.balance_confirmation.sender import (
    build_authorization_attachment,
    build_email_context,
    build_extract_attachment,
    build_notice_body,
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

    # Release 4.5 — upsert canonical working doc per (client_id, fy)
    existing = await RUNS.find_one(
        {"client_id": payload.client_id, "fy": payload.fy, "archived": False},
        {"_id": 0, "id": 1},
    )
    if existing:
        # Reuse the canonical id; refresh metadata + as_at, but preserve
        # status / pinned files / ledgers (auditor's prior progress).
        rid = existing["id"]
        await RUNS.update_one(
            {"id": rid},
            {"$set": {
                "name": (payload.name or f"Balance Confirmation {payload.fy}").strip(),
                "as_at_date": as_at,
            }},
        )
        doc = await RUNS.find_one({"id": rid}, {"_id": 0})
        return doc

    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "client_id": payload.client_id,
        "fy": payload.fy,
        "module": "balance_confirmation",
        "archived": False,
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
    q: Dict[str, Any] = {"archived": False}
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
    user = await _auth(request, session_token, authorization)
    doc = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")
    # Release 4.5 — silent redirect for collapsed/archived run_ids.
    if doc.get("archived") and doc.get("collapsed_into"):
        winner = await RUNS.find_one({"id": doc["collapsed_into"]}, {"_id": 0})
        if winner:
            doc = winner
            rid = winner["id"]
        else:
            raise HTTPException(404, "Run not found")
    # Attach library outdated/missing status — drives the morphing
    # "Rerun on Latest Data" button on the BC run shell.
    try:
        firm_id = doc.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID
        doc["library_status"] = await lib_svc.compute_module_status(
            firm_id=firm_id, client_id=doc["client_id"],
            period=doc.get("fy", ""), division=None,
            module_key="balance_confirmation",
            pinned_files=doc.get("pinned_files") or {},
        )
    except Exception:
        log.exception("library_status attach failed (non-fatal)")
        doc["library_status"] = None
    return doc


@router.delete("/runs/{rid}")
async def delete_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await RUNS.find_one({"id": rid}, {"_id": 0, "pinned_files": 1})
    res = await RUNS.delete_one({"id": rid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Run not found")
    # Unpin Library files so old versions can be auto-pruned.
    for fid in (doc or {}).get("pinned_files", {}).values():
        try:
            await lib_svc.unpin_file_from_run(fid, rid)
        except Exception:
            pass
    # Cascade
    await LEDGERS.delete_many({"run_id": rid})
    await BOOKS_RAW.delete_many({"run_id": rid})
    await SENDLOG.delete_many({"run_id": rid})
    await db.bc_responses.delete_many({"run_id": rid})
    await db.bc_recon_comments.delete_many({"run_id": rid})
    return {"deleted": True}


@router.post("/runs/{rid}/rerun")
async def rerun_on_latest(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Re-pin to the current Library `books_json` version and re-parse.
    Auditor's manual ledger edits (email, category, response_token, etc.)
    are preserved through the existing `build_ledger_records` carry-forward
    logic in `upload_books`."""
    user = await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    firm_id = run.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID
    cur = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=run["client_id"], period=run.get("fy", ""),
        division=None, file_type="books_json",
    )
    if not cur:
        raise HTTPException(409, "No Books JSON in Library — upload one first.")
    # Read the current bytes and feed them through the same upload path.
    content = await lib_svc.read_file_bytes(cur["file_id"])
    try:
        company, groups, ledgers = parse_books_json(content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    old_pinned = run.get("pinned_files") or {}
    # Unpin previous files we're about to replace.
    for ft, old_fid in old_pinned.items():
        if ft == "books_json" and old_fid != cur["file_id"]:
            try:
                await lib_svc.unpin_file_from_run(old_fid, rid)
            except Exception:
                pass
    await lib_svc.pin_file_to_run(cur["file_id"], rid)

    existing = {
        L["name"]: L for L in await LEDGERS.find(
            {"run_id": rid}, {"_id": 0}
        ).to_list(20000)
    }
    new_records = build_ledger_records(rid, groups, ledgers)
    for rec in new_records:
        prev = existing.get(rec["name"])
        if prev:
            for k in ("email", "cc_emails", "bcc_emails", "contact_name", "phone",
                      "address", "gstin", "pan", "category"):
                if prev.get(k):
                    rec[k] = prev[k]
            rec["response_token"] = prev.get("response_token") or rec["response_token"]
            rec["confirmation_status"] = prev.get("confirmation_status") or rec["confirmation_status"]
    await LEDGERS.delete_many({"run_id": rid})
    if new_records:
        await LEDGERS.insert_many(new_records)
    summary = summarise_ledgers(new_records)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {
            "module": "balance_confirmation",
            "source_filename": cur["filename_original"],
            "company": company,
            "summary": summary,
            "status": "ingested",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "pinned_files": {**old_pinned, "books_json": cur["file_id"]},
            "firm_id": firm_id,
        }},
    )
    return {
        "ok": True, "ledger_count": len(new_records), "company": company,
        "pinned_books_file_id": cur["file_id"],
    }


# ============================ Books JSON ingest ===============================
@router.post("/runs/{rid}/upload-books")
async def upload_books(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
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

    # Library integration — also save bytes to the Client Library and pin
    # this run to the resulting version.  Downstream "outdated" detection
    # works off this pin.
    pinned_files = run.get("pinned_files") or {}
    try:
        firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
        lib_books = await lib_svc.save_and_pin(
            firm_id=firm_id, client_id=run["client_id"], period=run.get("fy", ""),
            division=None, file_type="books_json",
            filename_original=file.filename or "books.json",
            content=content, uploaded_by_email=user.get("email") or "",
            run_id=rid, parse_status="success",
            parse_summary={"company_name": company, "n_ledgers": len(ledgers or [])},
        )
        pinned_files = {**pinned_files, "books_json": lib_books["file_id"]}
    except Exception:
        log.exception("Library save failed (non-fatal)")

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
            for k in ("email", "cc_emails", "bcc_emails", "contact_name", "phone",
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
            "module": "balance_confirmation",
            "source_filename": file.filename or "",
            "company": company,
            "summary": summary,
            "status": "ingested",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "pinned_files": pinned_files,
            "firm_id": user.get("firm_id") or DEFAULT_FIRM_ID,
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
# Subject prefixes from older default seeds — auto-upgraded to the new
# "Confirmation of Balance — M/s {{client_name}} as on {{as_at_date}}" format
# on first /templates call, but only if user hasn't customized the subject.
_LEGACY_DEFAULT_SUBJECT_PREFIXES = (
    "Balance Confirmation Request",
    "Statement of Account & Balance Confirmation",
    "Independent Bank Confirmation",
)


async def _ensure_default_templates() -> None:
    """Idempotent: insert one row per default kind if no global default exists.
    Also upgrades a legacy default-subject in place to the new branded format."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for d in all_defaults():
        existing = await TEMPLATES.find_one({"kind": d["kind"], "is_default": True})
        if existing:
            cur_subj = (existing.get("subject") or "").strip()
            if cur_subj.startswith(_LEGACY_DEFAULT_SUBJECT_PREFIXES) and cur_subj != d["subject"]:
                await TEMPLATES.update_one(
                    {"template_id": existing["template_id"]},
                    {"$set": {"subject": d["subject"], "updated_at": now_iso}},
                )
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
    bcc: List[str] = []                # universal bcc applied to every send
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

    # Ensure default-template subjects are on the latest branded format (cheap,
    # idempotent — only writes when a legacy prefix is detected).
    await _ensure_default_templates()

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
    auditor_firm = (payload.auditor_firm or "").strip() or "AssureAI Audit Utilities"

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
        bcc_list = list(set([*(payload.bcc or []), *(ledger.get("bcc_emails") or [])]))

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
            cc=None,         # Legal safeguard: cc/bcc receive a separate
            bcc=None,        # informational notice with the CTA disabled.
            attachments=attachments or None,
            from_name=(f"Confirmation of Balance — M/s {client.get('name')}".strip()
                       if client.get("name") else None),
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

            # ---- Notice copy (cc/bcc) — CTA disabled ----------------------
            # Only fired when the primary actually went out. The CTA in this
            # body is rendered as an inert grey badge so cc/bcc parties (often
            # the audit team or the client themselves) cannot self-confirm
            # the balance — closes the legal lacuna where a CC'd client could
            # confirm their own books.
            if cc_list or bcc_list:
                notice_body = build_notice_body(
                    rendered_html=body,
                    click_url=click_url,
                    response_link=ctx["response_link"],
                    primary_email=ledger["email"],
                )
                notice_subject = f"[Informational copy] {subject}"
                notice_text = _strip_html(notice_body)
                # to: primary CC list (so they see each other in the To line);
                # if no CC, fall back to auditor's own email so each BCC
                # recipient still gets a privately-addressed copy.
                notice_to = (cc_list[0] if cc_list else auditor_email)
                notice_other_cc = cc_list[1:] if len(cc_list) > 1 else []
                notice_res = await send_one(
                    to_email=notice_to,
                    subject=notice_subject,
                    html_body=notice_body,
                    text_body=notice_text,
                    reply_to=auditor_email or None,
                    cc=notice_other_cc or None,
                    bcc=bcc_list or None,
                    attachments=attachments or None,
                    from_name=(f"Confirmation of Balance — M/s {client.get('name')}".strip()
                               if client.get("name") else None),
                    tags=[
                        {"name": "run_id", "value": rid[:40]},
                        {"name": "kind", "value": "notice"},
                    ],
                )
                notice_recipients_disp = ", ".join(
                    [notice_to] + notice_other_cc + [f"(bcc) {b}" for b in bcc_list]
                )
                await SENDLOG.insert_one(_send_log_doc(
                    run_id=rid, ledger_id=ledger_id, kind="notice",
                    status="sent" if notice_res.get("ok") else "failed",
                    resend_id=notice_res.get("id") or "",
                    error=None if notice_res.get("ok") else notice_res.get("error"),
                    to_email=notice_recipients_disp,
                    subject=notice_subject, actor_email=auditor_email,
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
    # Release 4.5 — append-only generations log
    try:
        await append_generation(
            run_id=rid, module="balance_confirmation",
            client_id=run.get("client_id"),
            period=run.get("fy"),
            generated_by_email=user.get("email"),
            pinned_files_snapshot=run.get("pinned_files") or {},
            summary_snapshot={
                "sent": sent_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "kind": "reminder" if payload.is_reminder else "send",
            },
        )
    except Exception:
        pass
    return {
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "results": results,
    }


@router.get("/runs/{rid}/generations")
async def bc_generations(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Append-only history of bulk-send actions on this working doc."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1, "collapsed_into": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    canonical_id = run.get("collapsed_into") or run.get("id") or rid
    rows = await list_generations(canonical_id)
    return {"run_id": canonical_id, "generations": rows}


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
    kind: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Run not found")
    q: Dict[str, Any] = {"run_id": rid}
    if ledger_id:
        q["ledger_id"] = ledger_id
    if kind:
        # Allow ?kind=notice OR comma-separated like ?kind=initial,reminder
        kinds = [k.strip() for k in kind.split(",") if k.strip()]
        q["kind"] = kinds[0] if len(kinds) == 1 else {"$in": kinds}
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
        "auditor_firm":        run.get("auditor_firm") or "AssureAI Audit Utilities",
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



# ============================ Phase 5 — Summary exports =====================
async def _build_summary_payload(rid: str) -> Tuple[Dict, Dict, list, list, list]:
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    client = await db.clients.find_one(
        {"client_id": run.get("client_id")}, {"_id": 0}
    ) or {}
    ledgers = await LEDGERS.find({"run_id": rid}, {"_id": 0}).to_list(20000)
    responses = await RESPONSES.find(
        {"run_id": rid}, {"_id": 0, "uploaded_content_b64": 0}
    ).to_list(2000)
    send_log = await SENDLOG.find({"run_id": rid}, {"_id": 0}).to_list(20000)
    return run, client, ledgers, responses, send_log


@router.get("/runs/{rid}/analytics")
async def get_analytics(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Single JSON payload powering the Summary Dashboard. Same payload is
    embedded into the Summary PDF so on-screen and print are pixel-true."""
    await _auth(request, session_token, authorization)
    run, client, ledgers, responses, _ = await _build_summary_payload(rid)
    comments = await db.bc_recon_comments.find(
        {"run_id": rid}, {"_id": 0},
    ).to_list(5000)
    return build_analytics(
        run=run, client=client, ledgers=ledgers,
        responses=responses, comments=comments,
    )


@router.get("/runs/{rid}/summary.xlsx")
async def export_summary_xlsx(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    run, client, ledgers, responses, send_log = await _build_summary_payload(rid)
    xlsx = build_summary_xlsx(
        run=run, client=client,
        ledgers=ledgers, responses=responses, send_log=send_log,
    )
    fy = (run.get("fy") or "").replace("-", "_")
    fname = (
        f"BalanceConfirmation_Summary_FY{fy}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    return StreamingResponse(
        iter([xlsx]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/runs/{rid}/summary.pdf")
async def export_summary_pdf(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    run, client, ledgers, responses, _ = await _build_summary_payload(rid)
    comments = await db.bc_recon_comments.find(
        {"run_id": rid}, {"_id": 0},
    ).to_list(5000)
    analytics = build_analytics(
        run=run, client=client, ledgers=ledgers,
        responses=responses, comments=comments,
    )
    pdf = build_summary_pdf(
        run=run, client=client, ledgers=ledgers, responses=responses,
        analytics=analytics,
    )
    fy = (run.get("fy") or "").replace("-", "_")
    fname = (
        f"BalanceConfirmation_Summary_FY{fy}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ============================ Phase 6 — Side-by-side recon ==================
@router.get("/runs/{rid}/responses/{response_id}/recon")
async def reconcile_response(
    rid: str,
    response_id: str,
    request: Request,
    tolerance: float = 1.0,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Parse the recipient's uploaded statement (XLSX/CSV) and return a
    side-by-side reconciliation pairing with our books."""
    await _auth(request, session_token, authorization)

    resp = await RESPONSES.find_one(
        {"run_id": rid, "response_id": response_id}, {"_id": 0},
    )
    if not resp:
        raise HTTPException(404, "Response not found")

    ledger = await LEDGERS.find_one(
        {"ledger_id": resp.get("ledger_id")}, {"_id": 0},
    )
    if not ledger:
        raise HTTPException(404, "Ledger not found")

    # Our side — pull from the cached books JSON we keep on ingest
    from modules.balance_confirmation.letter_pdf import find_ledger_vouchers
    from modules.balance_confirmation.sender import load_books_from_run

    books_raw = await BOOKS_RAW.find_one({"run_id": rid}, {"_id": 0})
    books = load_books_from_run(books_raw)
    ours = find_ledger_vouchers(books, ledger.get("name", "")) if books else []

    # Their side — parse the uploaded attachment
    parsed: Dict[str, Any] = {"records": [], "supported": False, "format": "none"}
    if resp.get("uploaded_content_b64"):
        try:
            content = base64.b64decode(resp["uploaded_content_b64"])
            parsed = parse_recipient_statement(
                resp.get("uploaded_filename", ""), content,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"Recon parse failed: {e}")
            parsed = {"records": [], "supported": False,
                      "format": "error", "message": str(e)}

    pairs = auto_match(ours, parsed.get("records", []), tolerance=tolerance)

    # Convert "amount" → "debit/credit" on our side for symmetric display
    def _our_view(r: Dict[str, Any]) -> Dict[str, Any]:
        a = float(r.get("amount", 0) or 0)
        return {
            "date": r.get("date", ""),
            "vtype": r.get("vtype", ""),
            "vno": r.get("vno", ""),
            "narration": r.get("narration", ""),
            "debit": round(-a, 2) if a < 0 else 0.0,
            "credit": round(a, 2) if a > 0 else 0.0,
        }

    out_pairs = []
    for p in pairs:
        out_pairs.append({
            "status": p["status"],
            "diff": p.get("diff"),
            "our": _our_view(p["our"]) if p["our"] else None,
            "theirs": p["theirs"],
        })

    matched = sum(1 for p in pairs if p["status"] == "match")
    return {
        "ledger_id": ledger.get("ledger_id"),
        "ledger_name": ledger.get("name"),
        "our_balance": round(abs(float(ledger.get("closing_balance") or 0.0)), 2),
        "our_dr_cr": ledger.get("dr_cr") or "",
        "their_balance": resp.get("their_balance"),
        "their_dr_cr": resp.get("their_dr_cr") or "",
        "format": parsed.get("format"),
        "supported": parsed.get("supported", False),
        "message": parsed.get("message"),
        "pairs": out_pairs,
        "counts": {
            "matched": matched,
            "ours_only": sum(1 for p in pairs if p["status"] == "ours_only"),
            "theirs_only": sum(1 for p in pairs if p["status"] == "theirs_only"),
            "total_ours": len([p for p in pairs if p["our"] is not None]),
            "total_theirs": len([p for p in pairs if p["theirs"] is not None]),
        },
    }


class ReconCommentIn(BaseModel):
    text: str
    pair_key: Optional[str] = None  # e.g. "match:0:5" or "ours_only:3"


@router.post("/runs/{rid}/responses/{response_id}/recon/comments")
async def add_recon_comment(
    rid: str,
    response_id: str,
    payload: ReconCommentIn,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    if not (payload.text or "").strip():
        raise HTTPException(400, "Comment text is required")
    doc = {
        "comment_id": str(uuid.uuid4()),
        "run_id": rid,
        "response_id": response_id,
        "pair_key": (payload.pair_key or "").strip(),
        "text": payload.text.strip(),
        "author_email": user.get("email") or "",
        "author_name": user.get("name") or "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.bc_recon_comments.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/runs/{rid}/responses/{response_id}/recon/comments")
async def list_recon_comments(
    rid: str,
    response_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    rows = await db.bc_recon_comments.find(
        {"run_id": rid, "response_id": response_id}, {"_id": 0},
    ).sort("ts", 1).to_list(2000)
    return {"rows": rows, "count": len(rows)}


@router.delete("/runs/{rid}/responses/{response_id}/recon/comments/{cid}")
async def delete_recon_comment(
    rid: str,
    response_id: str,
    cid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    res = await db.bc_recon_comments.delete_one(
        {"run_id": rid, "response_id": response_id, "comment_id": cid},
    )
    if not res.deleted_count:
        raise HTTPException(404, "Comment not found")
    return {"deleted": True}

