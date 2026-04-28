"""GST Recon routes — Phase A scaffold (prefix: /gst-recon)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile

from core.db import db
from modules.auth.controller import get_current_user
from modules.gst_recon.schemas import RunCreate, RunOut
from modules.gst_recon.aggregators import (
    aggregate_books,
    aggregate_gstr1,
    aggregate_gstr2b,
    extract_books_invoices,
    extract_gstr1_invoices,
    extract_gstr2b_invoices,
)
from modules.gst_recon.service import build_month_grid, build_summary, categorize_file, match_invoices
from modules.gst_recon.validation import inspect_file, validate_run

router = APIRouter(prefix="/gst-recon")
COLL = db.gst_recon_runs
INV = db.gst_recon_invoices  # Phase D — voucher-level invoice records


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
    # Cascade — Phase D invoices are tied to the run
    await INV.delete_many({"run_id": rid})
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
            if meta.get("integrity_ok"):
                entry["books_per_month"] = aggregate_books(content)
                # Phase D — drop & re-insert per-voucher records (idempotent on re-upload)
                await INV.delete_many({"run_id": rid, "source": "books"})
                inv_records = extract_books_invoices(content)
                if inv_records:
                    await INV.insert_many([{"run_id": rid, "source": "books", **r} for r in inv_records])
        if entry["bucket"] == "gstr3b":
            entry["table_3_1"] = meta.get("table_3_1") or {}
            entry["table_4"] = meta.get("table_4") or {}
        if entry["bucket"] == "gstr1" and meta.get("integrity_ok"):
            entry["r1_outward"] = aggregate_gstr1(content)
            await INV.delete_many({"run_id": rid, "source": "gstr1", "period": entry.get("period") or ""})
            inv_records = extract_gstr1_invoices(content, entry.get("period") or "")
            if inv_records:
                await INV.insert_many([{"run_id": rid, "source": "gstr1", **r} for r in inv_records])
        if entry["bucket"] == "gstr2b" and meta.get("integrity_ok"):
            entry["r2b_itc"] = aggregate_gstr2b(content)
            await INV.delete_many({"run_id": rid, "source": "gstr2b", "period": entry.get("period") or ""})
            inv_records = extract_gstr2b_invoices(content, entry.get("period") or "")
            if inv_records:
                await INV.insert_many([{"run_id": rid, "source": "gstr2b", **r} for r in inv_records])
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


@router.post("/runs/{rid}/summary")
async def compute_summary(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase C.3: build the 12-month Turnover & ITC reconciliation summary
    from the per-file aggregates already stored on the run."""
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")
    summary = build_summary(doc)
    await COLL.update_one(
        {"id": rid},
        {"$set": {"summary": summary, "status": "summarized"}},
    )
    return summary


@router.post("/runs/{rid}/match")
async def compute_match(
    rid: str,
    request: Request,
    period: str,
    direction: str = "outward",
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase D: voucher-level matching for one (period, direction) pair.

    direction='outward' → Books-Sales ↔ GSTR-1
    direction='inward'  → Books-Purchase ↔ GSTR-2B

    Returns: { matched, value_mismatch, date_mismatch, missing_in_books,
               missing_in_portal, counts }
    """
    await _auth(request, session_token, authorization)
    if direction not in ("outward", "inward"):
        raise HTTPException(400, "direction must be 'outward' or 'inward'")
    if not period or len(period) != 6:
        raise HTTPException(400, "period must be MMYYYY (6 digits)")
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")

    portal_src = "gstr1" if direction == "outward" else "gstr2b"
    books = await INV.find(
        {"run_id": rid, "source": "books", "period": period, "direction": direction},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(20000)
    portal = await INV.find(
        {"run_id": rid, "source": portal_src, "period": period},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(20000)
    return match_invoices(books, portal)
