"""Routes for the 43B(h) MSME Disallowance utility (prefix: /msme)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile

from modules.auth.controller import get_current_user
from modules.msme43bh import dao
from modules.msme43bh.exports import build_audit_export, build_profile_template
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
    sid = str(uuid.uuid4())
    doc = {
        "id": sid,
        "client_id": payload.client_id,
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
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    content = await file.read()
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

    await dao.set_session_fields(sid, {
        "yearend_bills": bills,
        "profiles": profiles,
        "results": None,
        "source_filename": file.filename or "",
    })
    return {
        "bill_count": len(bills),
        "unique_ledgers": len({b["ledger_name"] for b in bills}),
        "profile_count": len(profiles),
    }


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
    await _auth(request, session_token, authorization)
    doc = await dao.find_session(sid)
    if not doc:
        raise HTTPException(404, "Session not found")
    bills = doc.get("yearend_bills", [])
    if not bills:
        raise HTTPException(400, "Year-end bills not uploaded")
    result = compute_disallowance(
        bills, doc.get("profiles", []), doc.get("payments", []), force_fifo=force_fifo
    )
    await dao.set_session_fields(sid, {"results": result})
    return result


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
