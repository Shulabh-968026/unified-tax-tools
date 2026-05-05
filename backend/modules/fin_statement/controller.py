"""FastAPI routes for the Financial Statement Designer.

Prefix: /fin-statement

Accepts a pre-aggregated FinalStatement JSON (Schedule III) and
produces a signature-ready PDF in one of two designer templates.
"""
from __future__ import annotations
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from core.db import db
from modules.auth.controller import get_current_user
from modules.library import service as lib_svc
from modules.library.controller import DEFAULT_FIRM_ID
from modules.fin_statement.normalizer import normalize_final_statement
from modules.fin_statement.pdf_renderer import render_pdf

router = APIRouter(prefix="/fin-statement")
log = logging.getLogger("fin_statement")

RUNS = db.fs_runs
BOOKS_RAW = db.fs_books_raw           # Raw JSON snapshot per run
FS_DOC = db.fs_documents              # Normalized FS document per run

TEMPLATES = {"classic", "boardroom"}


# ---- Schemas -----------------------------------------------------------
class FsRunCreate(BaseModel):
    client_id: str
    fy:        str
    fy_start:  str
    fy_end:    str
    name:      Optional[str] = None


class FsRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id:         str
    client_id:  str
    fy:         str
    fy_start:   str
    fy_end:     str
    name:       str
    status:     str  # draft | ingested | rendered
    created_at: str
    updated_at: str
    books_loaded: bool = False
    note_count:   int = 0
    detail_count: int = 0


async def _auth(request: Request, tok: Optional[str], hdr: Optional[str]):
    return await get_current_user(request, tok, hdr)


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "")[:120] or "statement"


# ============================ Runs CRUD ==================================
@router.post("/runs", response_model=FsRunOut)
async def create_run(
    payload: FsRunCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    client = await db.clients.find_one(
        {"client_id": payload.client_id}, {"_id": 0, "name": 1},
    )
    if not client:
        raise HTTPException(404, "Client not found")

    now_iso = datetime.now(timezone.utc).isoformat()
    run = {
        "id":         str(uuid.uuid4()),
        "client_id":  payload.client_id,
        "fy":         payload.fy,
        "fy_start":   payload.fy_start,
        "fy_end":     payload.fy_end,
        "name":       (payload.name or client["name"]).strip(),
        "status":     "draft",
        "created_at": now_iso,
        "updated_at": now_iso,
        "books_loaded":  False,
        "note_count":    0,
        "detail_count":  0,
    }
    await RUNS.insert_one(run)
    run.pop("_id", None)
    return run


@router.get("/runs")
async def list_runs(
    request: Request,
    client_id: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    q = {"client_id": client_id} if client_id else {}
    rows = await RUNS.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"rows": rows}


@router.get("/runs/{rid}", response_model=FsRunOut)
async def get_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    try:
        firm_id = run.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID
        run["library_status"] = await lib_svc.compute_module_status(
            firm_id=firm_id, client_id=run["client_id"],
            period=run.get("fy", ""), division=None,
            module_key="fin_statement",
            pinned_files=run.get("pinned_files") or {},
        )
    except Exception:
        run["library_status"] = None
    return run


@router.delete("/runs/{rid}")
async def delete_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    await RUNS.delete_one({"id": rid})
    await BOOKS_RAW.delete_many({"run_id": rid})
    await FS_DOC.delete_many({"run_id": rid})
    return {"ok": True}


# ============================ Ingestion ==================================
@router.post("/runs/{rid}/ingest")
async def ingest_statement(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Upload a pre-aggregated FinalStatement JSON for this run. Parses,
    normalizes, persists, and returns the normalized preview document."""
    user = await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if len(raw) > 60 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 60 MB)")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    try:
        client_rec = await db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0})
        doc = normalize_final_statement(payload, client_record=client_rec)
    except ValueError as e:
        raise HTTPException(400, str(e))

    now_iso = datetime.now(timezone.utc).isoformat()
    doc["run_id"] = rid
    doc["source_filename"] = file.filename or ""
    doc["ingested_at"] = now_iso

    # Library — save the FinalStatement JSON as books_json + pin to run.
    pinned_files = run.get("pinned_files") or {}
    try:
        firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
        lib_books = await lib_svc.save_and_pin(
            firm_id=firm_id, client_id=run["client_id"], period=run.get("fy", ""),
            division=None, file_type="books_json",
            filename_original=file.filename or "books.json", content=raw,
            uploaded_by_email=user.get("email") or "", run_id=rid,
            parse_status="success",
            parse_summary={"n_notes": doc.get("counts", {}).get("notes", 0)},
        )
        pinned_files = {**pinned_files, "books_json": lib_books["file_id"]}
    except Exception:
        log.exception("Library save failed (non-fatal)")

    await BOOKS_RAW.replace_one(
        {"run_id": rid},
        {
            "run_id":          rid,
            "ingested_at":     now_iso,
            "source_filename": file.filename or "",
            "envelope":        payload,
        },
        upsert=True,
    )
    await FS_DOC.replace_one({"run_id": rid}, doc, upsert=True)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {
            "module":       "fin_statement",
            "status":       "ingested",
            "books_loaded": True,
            "note_count":   doc.get("counts", {}).get("notes", 0),
            "detail_count": doc.get("counts", {}).get("details", 0),
            "updated_at":   now_iso,
            "pinned_files": pinned_files,
            "firm_id":      user.get("firm_id") or DEFAULT_FIRM_ID,
        }},
    )
    doc.pop("_id", None)
    return doc


@router.get("/runs/{rid}/document")
async def get_document(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Return the normalized FS document for this run."""
    await _auth(request, session_token, authorization)
    doc = await FS_DOC.find_one({"run_id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(
            404, "No financial-statement document for this run. "
                 "Upload the FinalStatement JSON first.")
    return doc


# ============================ Export PDF =================================
@router.get("/runs/{rid}/export.pdf")
async def export_pdf(
    rid: str,
    request: Request,
    template: str = "classic",
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if template not in TEMPLATES:
        raise HTTPException(400, f"Unknown template: {template}")
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    doc = await FS_DOC.find_one({"run_id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(
            409, "No financial-statement document yet — upload the JSON first.")

    pdf_bytes = render_pdf(doc, template=template)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {"status": "rendered",
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    co_name = _safe_name(doc.get("company", {}).get("name", "statement"))
    fy = _safe_name(doc.get("period", {}).get("fy_current", ""))
    filename = f"{co_name}_FS_{fy}_{template}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
