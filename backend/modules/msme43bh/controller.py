"""Routes for the 43B(h) MSME Disallowance utility (prefix: /msme)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile

from modules.auth.controller import get_current_user
from modules.msme43bh import dao
from modules.msme43bh.exports import build_audit_export, build_audit_export_bytes, build_profile_template
from modules.msme43bh.schemas import (
    ProfilesUpdate,
    SessionCreate,
    SessionOut,
)
from modules.msme43bh.service import (
    compute_disallowance,
    parse_payments_json,
    parse_profiles_excel,
    parse_yearend_excel,
    session_summary,
)
from modules.library import service as lib_svc
from modules.library.controller import DEFAULT_FIRM_ID
from modules.library.generations import append_generation, list_generations
from modules.library.scope import resolve_scope_for_request
from core.db import db

router = APIRouter(prefix="/msme")
logger = logging.getLogger("msme43bh")


async def _auth(request: Request, session_token: Optional[str], authorization: Optional[str]):
    return await get_current_user(request, session_token, authorization)


@router.post("/sessions", response_model=SessionOut)
async def create_session(
    payload: SessionCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    if not payload.client_id:
        raise HTTPException(400, "client_id is required")
    # Phase C.1 — resolve scope (defaults to consolidation when absent).
    scope = await resolve_scope_for_request(
        db, client_id=payload.client_id,
        scope_kind=payload.scope_kind,
        division_ids=payload.division_ids,
        gstin_group_id=payload.gstin_group_id,
    )
    # Release 4.5 — upsert canonical working session per (client_id, fy, scope_key)
    existing = await dao.SESSIONS.find_one(
        {"client_id": payload.client_id, "fy": payload.fy or "",
         "scope_key": scope["scope_key"], "archived": False},
        {"_id": 0},
    )
    if existing:
        return session_summary(existing)
    sid = str(uuid.uuid4())
    doc = {
        "id": sid,
        "client_id": payload.client_id,
        "module": "msme43bh",
        "archived": False,
        "name": payload.name or "Untitled Computation",
        "fy": payload.fy or "",
        "scope": "Single scope",
        "source_filename": "",
        "payments_filename": "",
        "generated_by": user.get("name") or user.get("email") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_user_id": user["user_id"],
        "yearend_bills": [],
        "profiles": [],
        "payments": [],
        "results": None,
        # Phase C.1 — scope fields.
        "scope_kind":     scope["scope_kind"],
        "division_ids":   scope["division_ids"],
        "scope_label":    scope["scope_label"],
        "scope_key":      scope["scope_key"],
        "gstin_group_id": scope["gstin_group_id"],
    }
    await dao.insert_session(doc)
    return session_summary(doc)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    client_id: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    docs = await dao.list_sessions(client_id)
    return [session_summary(d) for d in docs]


@router.get("/sessions/{sid}")
async def get_session(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    doc["has_yearend"] = bool(doc.get("yearend_bills"))
    doc["has_profiles"] = bool(doc.get("profiles"))
    doc["has_payments"] = bool(doc.get("payments"))
    doc["has_results"] = bool(doc.get("results"))
    doc["yearend_count"] = len(doc.get("yearend_bills") or [])
    doc["profile_count"] = len(doc.get("profiles") or [])
    doc["payment_count"] = len(doc.get("payments") or [])
    return doc


@router.delete("/sessions/{sid}")
async def delete_session(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if await dao.delete_session(sid) == 0:
        raise HTTPException(404, "Session not found")
    return {"deleted": True}


@router.post("/sessions/{sid}/yearend")
async def upload_yearend(
    sid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    content = await file.read()
    return await _persist_msme_yearend(
        sid=sid, doc=doc, content=content,
        filename=file.filename or "yearend.xlsx", user=user,
    )


async def _persist_msme_yearend(*, sid: str, doc: dict, content: bytes, filename: str, user: dict, save_to_library: bool = True) -> dict:
    """Shared yearend-Excel ingest logic — used by both ``POST /yearend``
    (multipart re-upload) and ``POST /yearend-from-library`` (Phase D)."""
    try:
        bills = parse_yearend_excel(content)
    except Exception as e:
        logger.exception("yearend parse failed")
        raise HTTPException(400, f"Failed to parse Excel: {e}")

    if not doc.get("profiles"):
        unique_ledgers = sorted({b["ledger_name"] for b in bills})
        profiles = [{"ledger_name": lg, "msme_number": "", "sector": "", "msme_type": "", "capital_goods": ""} for lg in unique_ledgers]
    else:
        profiles = doc["profiles"]

    pinned_files = doc.get("pinned_files") or {}
    if save_to_library and doc.get("client_id") and doc.get("fy"):
        try:
            firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
            lib_file = await lib_svc.save_and_pin(
                firm_id=firm_id, client_id=doc["client_id"], period=doc["fy"],
                division=None, file_type="msme43bh_creditor_report_xlsx",
                filename_original=filename, content=content,
                uploaded_by_email=user.get("email") or "", run_id=sid,
                parse_status="success",
                parse_summary={"bill_count": len(bills)},
            )
            pinned_files = {**pinned_files, "msme43bh_creditor_report_xlsx": lib_file["file_id"]}
        except Exception:
            logger.exception("Library save failed (non-fatal)")

    await dao.set_session_fields(sid, {
        "yearend_bills": bills,
        "profiles": profiles,
        "results": None,
        "source_filename": filename,
        "pinned_files": pinned_files,
        "firm_id": user.get("firm_id") or DEFAULT_FIRM_ID,
    })
    return {
        "bill_count": len(bills),
        "unique_ledgers": len({b["ledger_name"] for b in bills}),
        "profile_count": len(profiles),
    }


@router.post("/sessions/{sid}/yearend-from-library")
async def yearend_from_library(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase D — pull the pinned MSME 43B(h) creditor report from the
    Library and ingest without re-uploading."""
    user = await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    if not doc.get("client_id") or not doc.get("fy"):
        raise HTTPException(400, "Session is not bound to a client/FY")
    firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
    division = (doc.get("division_ids") or [None])[0] if doc.get("scope_kind") == "division" else None
    cur = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=doc["client_id"], period=doc["fy"],
        division=division, file_type="msme43bh_creditor_report_xlsx",
    )
    if not cur:
        raise HTTPException(
            400,
            "MSME 43B(h) Creditor Report is not pinned in the Library for this scope. "
            "Upload it via the Data Library tab first, or use the legacy upload.",
        )
    content = await lib_svc.read_file_bytes(cur["file_id"])
    return await _persist_msme_yearend(
        sid=sid, doc=doc, content=content,
        filename=cur.get("filename_original") or "yearend.xlsx",
        user=user, save_to_library=False,
    )


@router.get("/sessions/{sid}/template")
async def download_template(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    profiles = doc.get("profiles") or []
    if not profiles:
        profiles = [{"ledger_name": lg, "msme_number": "", "sector": "", "msme_type": "", "capital_goods": ""}
                    for lg in sorted({b["ledger_name"] for b in doc.get("yearend_bills", [])})]
    return build_profile_template(profiles, sid)


@router.put("/sessions/{sid}/profiles")
async def update_profiles(
    sid: str,
    payload: ProfilesUpdate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    profiles = [p.model_dump() for p in payload.profiles]
    await dao.set_session_fields(sid, {"profiles": profiles, "results": None})
    return {"profile_count": len(profiles)}


@router.post("/sessions/{sid}/profiles/upload")
async def upload_profiles(
    sid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    content = await file.read()
    try:
        profiles = parse_profiles_excel(content)
    except Exception as e:
        logger.exception("profile parse failed")
        raise HTTPException(400, f"Failed to parse Excel: {e}")
    await dao.set_session_fields(sid, {"profiles": profiles, "results": None})
    return {"profile_count": len(profiles)}


@router.post("/sessions/{sid}/payments")
async def upload_payments(
    sid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    content = await file.read()
    try:
        payments = parse_payments_json(content)
    except Exception as e:
        logger.exception("payments parse failed")
        raise HTTPException(400, f"Failed to parse JSON: {e}")
    await dao.set_session_fields(sid, {
        "payments": payments,
        "results": None,
        "payments_filename": file.filename or "",
    })
    return {"payment_count": len(payments)}


@router.post("/sessions/{sid}/compute")
async def compute_session(
    sid: str,
    request: Request,
    force_fifo: bool = False,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    bills = doc.get("yearend_bills", [])
    if not bills:
        raise HTTPException(400, "Year-end bills not uploaded")
    result = compute_disallowance(
        bills, doc.get("profiles", []), doc.get("payments", []), force_fifo=force_fifo
    )

    # Snapshot the current Library file_ids for our declared dependencies
    # so the "outdated" badge works without changing 43BH's existing flows.
    pinned_files: dict = {}
    try:
        firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
        for ft in ("books_json", "party_master_xlsx"):
            cur = await lib_svc.get_current_file(
                firm_id=firm_id, client_id=doc.get("client_id", ""),
                period=doc.get("fy", ""), division=None, file_type=ft,
            )
            if cur:
                pinned_files[ft] = cur["file_id"]
                await lib_svc.pin_file_to_run(cur["file_id"], sid)
    except Exception:
        logger.exception("43BH library pin snapshot failed (non-fatal)")

    await dao.set_session_fields(sid, {
        "results": result,
        "module": "msme43bh",
        "pinned_files": pinned_files,
        "firm_id": user.get("firm_id") or DEFAULT_FIRM_ID,
    })

    # Auto-save the Creditor Report into the Client Library so it shows
    # up under "Generated reports" alongside the source files.
    try:
        client_id = doc.get("client_id")
        period = doc.get("fy") or ""
        if client_id and period:
            blob = build_audit_export_bytes(result)
            await lib_svc.create_file_version(
                firm_id=user.get("firm_id") or DEFAULT_FIRM_ID,
                client_id=client_id,
                period=period,
                division=None,
                file_type="msme43bh_creditor_report_xlsx",
                filename_original=f"AssureAI_43Bh_CreditorReport_{sid[:8]}.xlsx",
                content=blob,
                uploaded_by_email=user.get("email") or "",
                parse_status="generated",
                parse_summary={
                    "session_id": sid,
                    "final_disallowance": result["summary"]["final_disallowance"],
                    "bill_count": result["summary"]["bill_count"],
                    "disallowed_count": result["summary"]["disallowed_count"],
                },
            )
    except Exception:
        logger.exception("Failed to auto-save 43B(h) creditor report to Library (non-fatal)")

    # Release 4.5 — append-only generations log
    try:
        s = (result or {}).get("summary") or {}
        await append_generation(
            run_id=sid, module="msme43bh",
            client_id=doc.get("client_id"),
            period=doc.get("fy"),
            generated_by_email=user.get("email"),
            pinned_files_snapshot=pinned_files,
            summary_snapshot={
                "final_disallowance": s.get("final_disallowance"),
                "bill_count": s.get("bill_count"),
                "disallowed_count": s.get("disallowed_count"),
            },
        )
    except Exception:
        logger.exception("append_generation failed (non-fatal)")

    return result


@router.get("/sessions/{sid}/generations")
async def session_generations(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Append-only history of compute actions on this working session.
    Newest first."""
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    canonical_id = doc.get("id") or sid
    rows = await list_generations(canonical_id)
    return {"run_id": canonical_id, "generations": rows}


@router.get("/sessions/{sid}/results")
async def get_results(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    if not doc.get("results"):
        raise HTTPException(404, "No results yet — run /compute first")
    return doc["results"]


@router.get("/sessions/{sid}/export")
async def export_results(
    sid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    res = doc.get("results")
    if not res:
        raise HTTPException(400, "Run computation first")
    return build_audit_export(res, sid)
