"""FastAPI routes for the Financial Statement Designer.

Prefix: /fin-statement

Phase 1 scope (this drop): Runs CRUD + JSON upload + Schedule III
aggregation preview. Drop 2 will land the PDF templates + full notes.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.db import db
from modules.auth.controller import get_current_user
from modules.fin_statement.aggregator import aggregate_schedule_iii

router = APIRouter(prefix="/fin-statement")
log = logging.getLogger("fin_statement")

RUNS = db.fs_runs
BOOKS_RAW = db.fs_books_raw  # Tally JSON snapshot per run (for re-derivation)
FS_DOC = db.fs_documents     # Aggregated Schedule III document per run


# ---- Schemas -----------------------------------------------------------
class FsRunCreate(BaseModel):
    client_id: str
    fy:        str
    fy_start:  str
    fy_end:    str
    name:      Optional[str] = None


class FsRunOut(BaseModel):
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
    ledger_count: int = 0
    voucher_count: int = 0


async def _auth(request: Request, tok: Optional[str], hdr: Optional[str]):
    return await get_current_user(request, tok, hdr)


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
        "ledger_count":  0,
        "voucher_count": 0,
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
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
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
async def ingest_books(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Upload a Tally books JSON export for this run. Parses, runs the
    Schedule III aggregator, persists the raw JSON (for re-derivation) +
    the aggregated FS document. Returns the document."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if len(raw) > 60 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 60 MB)")
    try:
        books = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Invalid JSON: {e}")
    if not isinstance(books, dict) or "ledgers" not in books:
        raise HTTPException(400, "JSON does not look like a Tally books export "
                                  "(missing `ledgers`).")

    doc = aggregate_schedule_iii(books)
    doc["run_id"] = rid
    doc["source_filename"] = file.filename or ""
    doc["ingested_at"] = datetime.now(timezone.utc).isoformat()

    # Store only a minimal snapshot of the raw JSON so re-aggregation stays
    # cheap. Full vouchers list can balloon past 10 MB — keep it too for
    # later notes work (Drop 2), but in a dedicated collection.
    await BOOKS_RAW.replace_one(
        {"run_id": rid},
        {
            "run_id":           rid,
            "ingested_at":      doc["ingested_at"],
            "source_filename":  doc["source_filename"],
            "version":          books.get("version"),
            "company":          books.get("company", {}),
            "groups":           books.get("groups", []),
            "ledgers":          books.get("ledgers", []),
            "vouchers":         books.get("vouchers", []),
            "outstandingBills": books.get("outstandingBills", []),
            "voucherTypes":     books.get("voucherTypes", []),
        },
        upsert=True,
    )
    await FS_DOC.replace_one({"run_id": rid}, doc, upsert=True)
    await RUNS.update_one(
        {"id": rid},
        {"$set": {
            "status":        "ingested",
            "books_loaded":  True,
            "ledger_count":  doc["ledger_count"],
            "voucher_count": doc["voucher_count"],
            "updated_at":    doc["ingested_at"],
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
    """Return the aggregated Schedule III document for this run."""
    await _auth(request, session_token, authorization)
    doc = await FS_DOC.find_one({"run_id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "No financial-statement document for this run. "
                                  "Upload the Tally books JSON first.")
    return doc
