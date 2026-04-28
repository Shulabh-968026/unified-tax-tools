"""GST Recon routes — Phase A scaffold (prefix: /gst-recon)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile

from core.db import db
from modules.auth.controller import get_current_user
from modules.gst_recon.schemas import RunCreate, RunOut
from modules.gst_recon.service import build_month_grid, categorize_file
from modules.gst_recon.validation import inspect_file, validate_run

router = APIRouter(prefix="/gst-recon")
COLL = db.gst_recon_runs


async def _auth(request, tok, auth):
    return await get_current_user(request, tok, auth)


@router.post("/runs", response_model=RunOut)
async def create_run(
    payload: RunCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "client_id": payload.client_id,
        "fy": payload.fy,
        "name": payload.name or f"GST Recon {payload.fy}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["user_id"],
        "status": "draft",
        "files": [],
        "months": build_month_grid(payload.fy, []),
        "has_books": False,
        "has_mapping": False,
        "validation": None,
    }
    await COLL.insert_one(doc)
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
    q = {"client_id": client_id} if client_id else {}
    return await COLL.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.get("/runs/{rid}", response_model=RunOut)
async def get_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
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
    res = await COLL.delete_one({"id": rid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Run not found")
    return {"deleted": True}


@router.post("/runs/{rid}/files")
async def upload_batch(
    rid: str,
    request: Request,
    files: List[UploadFile] = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Categorize a batch of filenames into buckets. Phase A returns the bucket summary + updated 12-month grid.
    Phase B will persist file contents and run pre-flight validation."""
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")

    new_entries = []
    for f in files:
        content = await f.read()
        entry = categorize_file(f.filename or "", size=len(content))
        meta = inspect_file(entry["filename"], entry["bucket"], content)
        # Prefer content-level period/gstin where available; else keep filename-inferred
        if meta.get("period"):
            entry["period"] = meta["period"]
        if meta.get("gstin"):
            entry["gstin"] = meta["gstin"]
        entry["integrity_ok"] = meta.get("integrity_ok", False)
        entry["parse_error"] = meta.get("parse_error")
        if entry["bucket"] == "books":
            entry["books_from"] = meta.get("books_from")
            entry["books_to"] = meta.get("books_to")
        new_entries.append(entry)

    merged = {(x["filename"]): x for x in doc.get("files", [])}
    for e in new_entries:
        merged[e["filename"]] = e
    all_files = list(merged.values())

    months = build_month_grid(doc.get("fy", ""), all_files)
    has_books = any(x["bucket"] == "books" for x in all_files)
    has_mapping = any(x["bucket"] == "mapping" for x in all_files)

    await COLL.update_one(
        {"id": rid},
        {"$set": {
            "files": all_files,
            "months": months,
            "has_books": has_books,
            "has_mapping": has_mapping,
        }},
    )

    return {
        "accepted": len(new_entries),
        "total_files": len(all_files),
        "buckets": {
            b: sum(1 for x in all_files if x["bucket"] == b)
            for b in ("gstr1", "gstr2b", "gstr3b", "books", "mapping", "unknown")
        },
        "months": months,
        "has_books": has_books,
        "has_mapping": has_mapping,
    }


@router.post("/runs/{rid}/validate")
async def validate(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase B: run the 4 pre-flight gates and persist the verdict on the run."""
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")
    client = await db.clients.find_one({"client_id": doc["client_id"]}, {"_id": 0})
    doc["client_gstin"] = (client or {}).get("gstin", "") or ""
    verdict = validate_run(doc)
    await COLL.update_one({"id": rid}, {"$set": {"validation": verdict}})
    return verdict
