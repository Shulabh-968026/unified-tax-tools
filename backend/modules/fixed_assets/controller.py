"""FastAPI routes — Fixed Assets / IT Depreciation module.

Prefix: /fixed-assets

Phase 1A — Run CRUD + legal master + Tally Books ingest + ledger workbench.
Subsequent phases land additions/deletions UI, 3CD opening import, and the
final computation engine + Excel export.
"""
from __future__ import annotations
import base64
import gzip
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from core.db import db
from modules.auth.controller import get_current_user
from modules.fixed_assets.additions_xlsx import (
    block_drift,
    build_additions_workbook,
    diff_additions,
    parse_additions_workbook,
)
from modules.fixed_assets.compute import compute_run
from modules.fixed_assets.export import build_workbook
from modules.fixed_assets.legal_master import (
    LEGAL_MASTER_COLLECTION,
    get_block_labels_active,
    list_legal_master,
    seed_legal_master,
)
from modules.fixed_assets.schemas import (
    FaAdditionLink,
    FaAdditionPatch,
    FaCreditClassifyRequest,
    FaLedgerClassifyRequest,
    FaRunCreate,
    FaRunOut,
)
from modules.fixed_assets.service import (
    auto_classify_block,
    fa_ledgers,
    fa_voucher_lines,
    fy_dates,
    parse_books_json,
    parse_prior_3cd,
    stage_addition_rows,
    stage_credit_rows,
)

router = APIRouter(prefix="/fixed-assets")
log = logging.getLogger("fixed_assets")

RUNS = db.fa_runs
LEDGERS = db.fa_ledgers
ADDITIONS = db.fa_additions
CREDITS = db.fa_credits
BLOCK_OPEN = db.fa_block_opening
BOOKS_RAW = db.fa_books_raw
INVOICE_ATTACH = db.fa_invoice_attachments
PENDING_UPLOADS_COL = db.fa_pending_invoice_uploads
PENDING_CHUNK_PDFS  = db.fa_pending_chunk_pdfs


async def _auth(request: Request, tok: Optional[str], hdr: Optional[str]):
    return await get_current_user(request, tok, hdr)


# ============================ Legal Master =================================
@router.get("/legal-master")
async def legal_master(
    request: Request,
    active: Optional[bool] = True,
    block_label: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    await seed_legal_master()  # cheap, idempotent
    rows = await list_legal_master(active_only=bool(active), block_label=block_label)
    return {"rows": rows, "count": len(rows)}


@router.get("/blocks")
async def blocks(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Distinct active block_labels with rate + entry count — populates the
    workbench's block-classification dropdown."""
    await _auth(request, session_token, authorization)
    await seed_legal_master()
    return {"rows": await get_block_labels_active()}


@router.post("/legal-master/reseed")
async def legal_master_reseed(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Admin-only: wipe and re-import the shipped XLSX. Used when the law
    changes (rare). Read-only for normal auditors."""
    user = await _auth(request, session_token, authorization)
    if not user.get("is_admin") and not user.get("is_super_admin"):
        raise HTTPException(403, "Admin access required to reseed legal master")
    count = await seed_legal_master(force=True)
    return {"ok": True, "rows": count}


# ============================ Runs =========================================
@router.post("/runs", response_model=FaRunOut)
async def create_run(
    payload: FaRunCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    client = await db.clients.find_one({"client_id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")

    fy_start, fy_end = fy_dates(payload.fy)
    run_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # Multi-FY continuity — if a prior run exists for this client, link it
    prior = await RUNS.find_one(
        {"client_id": payload.client_id},
        {"_id": 0, "id": 1, "fy_end": 1},
        sort=[("fy_end", -1)],
    )
    rolled_from = prior["id"] if prior and (prior.get("fy_end") or "") < (payload.fy_end or fy_end) else ""

    doc = {
        "id":                run_id,
        "client_id":         payload.client_id,
        "fy":                payload.fy,
        "fy_start":          payload.fy_start or fy_start,
        "fy_end":            payload.fy_end or fy_end,
        "name":              (payload.name or "").strip(),
        "status":            "draft",
        "source_filename":   "",
        "summary":           {"total_ledgers": 0, "pending": 0, "confirmed": 0,
                              "additions": 0, "credits": 0},
        "created_at":        now_iso,
        "created_by_email":  user.get("email") or "",
        "created_by_name":   user.get("name") or "",
        "rolled_from_run_id": rolled_from,
    }
    await RUNS.insert_one(doc)
    doc.pop("_id", None)
    return {**doc}


@router.get("/runs")
async def list_runs(
    request: Request,
    client_id: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    q = {"client_id": client_id} if client_id else {}
    rows = await RUNS.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"rows": rows}


@router.get("/runs/{rid}")
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
    run = await RUNS.find_one({"id": rid})
    if not run:
        raise HTTPException(404, "Run not found")
    await RUNS.delete_one({"id": rid})
    await LEDGERS.delete_many({"run_id": rid})
    await ADDITIONS.delete_many({"run_id": rid})
    await CREDITS.delete_many({"run_id": rid})
    await BLOCK_OPEN.delete_many({"run_id": rid})
    await BOOKS_RAW.delete_many({"run_id": rid})
    await INVOICE_ATTACH.delete_many({"run_id": rid})
    # Cascade — also drop pending invoice uploads + their chunk PDFs
    pending = await PENDING_UPLOADS_COL.find({"run_id": rid}, {"_id": 0, "upload_id": 1}).to_list(2000)
    if pending:
        upids = [p["upload_id"] for p in pending]
        await PENDING_CHUNK_PDFS.delete_many({"upload_id": {"$in": upids}})
        await PENDING_UPLOADS_COL.delete_many({"run_id": rid})
    return {"ok": True}


# ============================ Books Ingest =================================
async def _refresh_run_summary(rid: str) -> Dict[str, Any]:
    led_total   = await LEDGERS.count_documents({"run_id": rid})
    # New simpler semantics: any non-empty block_label = classified;
    # otherwise the row needs auditor attention.
    led_pending = await LEDGERS.count_documents({"run_id": rid, "$or": [
        {"block_label": ""}, {"block_label": {"$exists": False}}, {"block_label": None},
    ]})
    led_confirm = led_total - led_pending
    additions   = await ADDITIONS.count_documents({"run_id": rid})
    credits     = await CREDITS.count_documents({"run_id": rid})
    summary = {
        "total_ledgers": led_total,
        "pending":       led_pending,
        "confirmed":     led_confirm,
        "additions":     additions,
        "credits":       credits,
    }
    await RUNS.update_one({"id": rid}, {"$set": {"summary": summary}})
    return summary


@router.post("/runs/{rid}/ingest-books")
async def ingest_books(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Re-runnable: wipes prior FA ledger / addition / credit rows for this run
    and rebuilds them from the uploaded Books JSON."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")

    raw = await file.read()
    try:
        books = parse_books_json(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid Books JSON: {e}")

    # --- Stash a gzipped copy for re-classification later -------------------
    try:
        compressed = base64.b64encode(gzip.compress(raw)).decode("ascii")
        await BOOKS_RAW.delete_many({"run_id": rid})
        await BOOKS_RAW.insert_one({
            "run_id":      rid,
            "filename":    file.filename or "books.json",
            "content_b64": compressed,
            "stored_at":   datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:  # noqa: BLE001
        log.warning(f"BOOKS_RAW stash failed for run {rid}: {e}")

    # --- Build FA ledgers (depreciation ledgers excluded by service) -------
    detected = fa_ledgers(books)
    if not detected:
        raise HTTPException(
            400,
            "No Fixed Asset ledgers found under 'Fixed Assets' / 'Property, "
            "Plant and Equipment' groups in the uploaded Books JSON.",
        )

    # Wipe prior staged data
    await LEDGERS.delete_many({"run_id": rid})
    await ADDITIONS.delete_many({"run_id": rid})
    await CREDITS.delete_many({"run_id": rid})

    now_iso = datetime.now(timezone.utc).isoformat()
    ledger_id_by_name: Dict[str, str] = {}
    led_docs: List[Dict[str, Any]] = []

    # Pre-fetch a {block_label → smallest active row_id} map so each
    # auto-classified ledger gets a sensible default legal-master entry.
    default_legal_row: Dict[str, int] = {}
    async for r in LEGAL_MASTER_COLLECTION.find(
        {"is_active": True}, {"_id": 0, "block_label": 1, "row_id": 1},
    ).sort([("block_label", 1), ("sort_order", 1), ("row_id", 1)]):
        bl = r.get("block_label") or ""
        if bl and bl not in default_legal_row:
            default_legal_row[bl] = int(r.get("row_id") or 0)

    for L in detected:
        lid = str(uuid.uuid4())
        ledger_id_by_name[L["name"]] = lid
        suggested = auto_classify_block(L["name"], L["parent_group"])
        led_docs.append({
            "fa_ledger_id":           lid,
            "run_id":                 rid,
            "name":                   L["name"],
            "parent_group":           L["parent_group"],
            "opening_balance":        L["opening_balance"],
            "closing_balance":        L["closing_balance"],
            "addition_count":         0,
            "deletion_count":         0,
            "block_label":            suggested,
            "legal_master_row_id":   default_legal_row.get(suggested) if suggested else None,
            "classification_status":  "auto_suggested" if suggested else "pending",
            "classification_note":    "",
            "last_modified":          now_iso,
        })
    if led_docs:
        await LEDGERS.insert_many(led_docs)

    # --- Stage additions + credit lines ------------------------------------
    fy_end = run.get("fy_end") or ""
    lines = fa_voucher_lines(books, set(ledger_id_by_name.keys()))
    add_rows = stage_addition_rows(lines, ledger_id_by_name, rid, fy_end)
    cr_rows = stage_credit_rows(lines, ledger_id_by_name, rid)

    # Cascade the auto-suggested block_label down onto each addition
    block_by_lid = {d["fa_ledger_id"]: d["block_label"] for d in led_docs}
    for d in add_rows:
        d["block_label"] = block_by_lid.get(d["fa_ledger_id"], "")
        d["addition_id"] = str(uuid.uuid4())
    for d in cr_rows:
        d["credit_id"] = str(uuid.uuid4())

    if add_rows:
        await ADDITIONS.insert_many(add_rows)
    if cr_rows:
        await CREDITS.insert_many(cr_rows)

    # --- Update per-ledger counts -----------------------------------------
    for name, lid in ledger_id_by_name.items():
        adds = sum(1 for r in add_rows if r["fa_ledger_id"] == lid)
        dels = sum(1 for r in cr_rows if r["fa_ledger_id"] == lid)
        await LEDGERS.update_one(
            {"fa_ledger_id": lid},
            {"$set": {"addition_count": adds, "deletion_count": dels}},
        )

    await RUNS.update_one(
        {"id": rid},
        {"$set": {"source_filename": file.filename or "",
                  "status": "draft"}},
    )
    summary = await _refresh_run_summary(rid)
    return {"ok": True, "summary": summary,
            "ledgers": len(led_docs),
            "additions": len(add_rows),
            "credits": len(cr_rows)}


# ============================ Ledger Workbench =============================
@router.get("/runs/{rid}/ledgers")
async def list_ledgers(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    rows = await LEDGERS.find({"run_id": rid}, {"_id": 0}) \
        .sort([("classification_status", 1), ("parent_group", 1), ("name", 1)]) \
        .to_list(2000)
    return {"rows": rows}


@router.post("/runs/{rid}/ledgers/{lid}/classify")
async def classify_ledger(
    rid: str,
    lid: str,
    payload: FaLedgerClassifyRequest,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    led = await LEDGERS.find_one({"fa_ledger_id": lid, "run_id": rid}, {"_id": 0})
    if not led:
        raise HTTPException(404, "Ledger not found")
    # Verify the legal master row exists & matches the block_label
    lm = await LEGAL_MASTER_COLLECTION.find_one(
        {"row_id": payload.legal_master_row_id, "is_active": True}, {"_id": 0},
    )
    if not lm:
        raise HTTPException(400, "Invalid or inactive legal master row")
    if lm["block_label"] != payload.block_label:
        raise HTTPException(400, "block_label does not match legal master row")

    now_iso = datetime.now(timezone.utc).isoformat()
    await LEDGERS.update_one(
        {"fa_ledger_id": lid, "run_id": rid},
        {"$set": {
            "block_label":            payload.block_label,
            "legal_master_row_id":   payload.legal_master_row_id,
            "classification_status":  "confirmed" if payload.confirm else "auto_suggested",
            "classification_note":    payload.note or "",
            "last_modified":          now_iso,
        }},
    )
    # Cascade block_label to staged additions for this ledger
    await ADDITIONS.update_many(
        {"run_id": rid, "fa_ledger_id": lid},
        {"$set": {"block_label": payload.block_label}},
    )
    await _refresh_run_summary(rid)
    return {"ok": True}


# Lightweight inline endpoint used by the workbench dropdown — needs only the
# block_label; legal_master_row_id is auto-resolved server-side.
class FaLedgerSetBlock(BaseModel):
    block_label: str  # empty string ⇒ unset / pending


@router.patch("/runs/{rid}/ledgers/{lid}/block")
async def set_ledger_block(
    rid: str,
    lid: str,
    payload: FaLedgerSetBlock,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    led = await LEDGERS.find_one({"fa_ledger_id": lid, "run_id": rid}, {"_id": 0})
    if not led:
        raise HTTPException(404, "Ledger not found")

    block = (payload.block_label or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not block:
        # Clear classification
        await LEDGERS.update_one(
            {"fa_ledger_id": lid, "run_id": rid},
            {"$set": {
                "block_label": "",
                "legal_master_row_id": None,
                "classification_status": "pending",
                "last_modified": now_iso,
            }},
        )
        await ADDITIONS.update_many(
            {"run_id": rid, "fa_ledger_id": lid},
            {"$set": {"block_label": ""}},
        )
        await _refresh_run_summary(rid)
        return {"ok": True, "block_label": "", "status": "pending"}

    # Pick the smallest active row_id for this block_label as the default
    # legal_master entry — the auditor can drill deeper later if needed.
    default = await LEGAL_MASTER_COLLECTION.find_one(
        {"is_active": True, "block_label": block},
        {"_id": 0, "row_id": 1},
        sort=[("sort_order", 1), ("row_id", 1)],
    )
    if not default:
        raise HTTPException(400, f"Unknown or inactive block_label: {block}")

    await LEDGERS.update_one(
        {"fa_ledger_id": lid, "run_id": rid},
        {"$set": {
            "block_label": block,
            "legal_master_row_id": int(default["row_id"]),
            "classification_status": "confirmed",
            "last_modified": now_iso,
        }},
    )
    await ADDITIONS.update_many(
        {"run_id": rid, "fa_ledger_id": lid},
        {"$set": {"block_label": block}},
    )
    await _refresh_run_summary(rid)
    return {"ok": True, "block_label": block, "status": "confirmed"}


@router.post("/runs/{rid}/auto-classify-pending")
async def auto_classify_pending(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Run heuristic auto-classification across every ledger in this run that
    has an empty block_label. Idempotent — already-classified ledgers (whether
    auto_suggested or confirmed) are left untouched, so any auditor overrides
    are preserved. Used as a one-shot backfill for runs ingested before the
    auto-classifier existed, and as a manual 'apply heuristic' trigger."""
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")

    # Pre-fetch {block_label → smallest active row_id}
    default_legal_row: Dict[str, int] = {}
    async for r in LEGAL_MASTER_COLLECTION.find(
        {"is_active": True}, {"_id": 0, "block_label": 1, "row_id": 1},
    ).sort([("block_label", 1), ("sort_order", 1), ("row_id", 1)]):
        bl = r.get("block_label") or ""
        if bl and bl not in default_legal_row:
            default_legal_row[bl] = int(r.get("row_id") or 0)

    pending = await LEDGERS.find(
        {"run_id": rid, "$or": [
            {"block_label": ""}, {"block_label": {"$exists": False}}, {"block_label": None},
        ]}, {"_id": 0},
    ).to_list(5000)

    now_iso = datetime.now(timezone.utc).isoformat()
    classified = 0
    for L in pending:
        suggested = auto_classify_block(L.get("name", ""), L.get("parent_group", ""))
        if not suggested:
            continue
        await LEDGERS.update_one(
            {"fa_ledger_id": L["fa_ledger_id"], "run_id": rid},
            {"$set": {
                "block_label":            suggested,
                "legal_master_row_id":   default_legal_row.get(suggested),
                "classification_status":  "auto_suggested",
                "last_modified":          now_iso,
            }},
        )
        await ADDITIONS.update_many(
            {"run_id": rid, "fa_ledger_id": L["fa_ledger_id"]},
            {"$set": {"block_label": suggested}},
        )
        classified += 1

    summary = await _refresh_run_summary(rid)
    return {"ok": True, "classified": classified,
            "still_pending": len(pending) - classified, "summary": summary}


# ============================ Additions ====================================
def _recompute_180(addition: Dict[str, Any], fy_end: str) -> Dict[str, Any]:
    from modules.fixed_assets.service import is_more_than_180
    ptu = addition.get("put_to_use_date") or ""
    full = is_more_than_180(ptu, fy_end)
    addition["is_more_than_180"] = full
    addition["half_rate"] = not full
    return addition


@router.get("/runs/{rid}/additions")
async def list_additions(
    rid: str,
    request: Request,
    block: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Returns regular additions PLUS any credit entries the auditor has
    classified as 'discount' — surfaced as locked, negative-cost addition
    rows so they appear inline in the Additions register. Discount rows are
    not editable from this endpoint (managed via `/credits/.../classify`)."""
    await _auth(request, session_token, authorization)
    q: Dict[str, Any] = {"run_id": rid}
    if block:
        q["block_label"] = block
    rows = await ADDITIONS.find(q, {"_id": 0}) \
        .sort([("block_label", 1), ("invoice_date", 1)]).to_list(5000)

    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1, "block_label": 1}):
        led_map[L["fa_ledger_id"]] = L
    for r in rows:
        Ldoc = led_map.get(r.get("fa_ledger_id", ""), {})
        r["ledger_name"] = Ldoc.get("name", "")
        # Defensive defaults for documents written before reviewed/source/desc
        # fields were introduced — keeps the UI clean for legacy runs.
        r.setdefault("reviewed", False)
        r.setdefault("source", "addition")
        r.setdefault("description", r.get("particulars", ""))
        r.setdefault("invoice_no", "")
        r.setdefault("parent_addition_id", "")
        r.setdefault("linked_as", "")

    # --- Merge in discount-classified credits as negative rows --------------
    cred_q: Dict[str, Any] = {"run_id": rid, "classification": "discount"}
    discount_rows = []
    async for c in CREDITS.find(cred_q, {"_id": 0}):
        Ldoc = led_map.get(c.get("fa_ledger_id", ""), {})
        bl = Ldoc.get("block_label", "")
        if block and bl != block:
            continue
        discount_rows.append({
            "addition_id":         f"discount-{c['credit_id']}",
            "run_id":              rid,
            "fa_ledger_id":        c.get("fa_ledger_id", ""),
            "block_label":         bl,
            "voucher_id":          c.get("voucher_id", ""),
            "voucher_no":          c.get("voucher_no", ""),
            "voucher_type":        c.get("voucher_type", ""),
            "accounting_date":     c.get("accounting_date", ""),
            "invoice_date":        c.get("accounting_date", ""),
            "invoice_no":          "",
            "put_to_use_date":     "",
            "party_name":          c.get("party_name", ""),
            "particulars":         c.get("particulars", ""),
            "description":         f"[Discount] {c.get('particulars') or ''}",
            "ledger_name":         Ldoc.get("name", ""),
            "invoice_cost":        -float(c.get("amount") or 0),
            "discount_credits":    0.0,
            "other_expenses":      0.0,
            "itc_reversed":        0.0,
            "interest_capitalized": 0.0,
            "forex_fluctuations":  0.0,
            "is_more_than_180":    True,
            "half_rate":           False,
            "reviewed":            True,
            "source":              "discount_credit",
            "credit_id":           c["credit_id"],
        })
    rows.extend(discount_rows)
    rows.sort(key=lambda r: ((r.get("block_label") or "~"),
                             (r.get("invoice_date") or r.get("accounting_date") or "")))
    return {"rows": rows}


@router.get("/runs/{rid}/additions/progress")
async def additions_progress(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Per-block progress of the Additions tab — used to render the
    "2 done · 2 not started · 1 in progress" strip the auditor sees at the
    top of the tab. A row counts as 'reviewed' once the auditor has touched
    any field on it (server sets reviewed=True on every PATCH)."""
    await _auth(request, session_token, authorization)
    pipeline = [
        {"$match": {"run_id": rid, "block_label": {"$ne": ""}}},
        {"$group": {
            "_id":      "$block_label",
            "total":    {"$sum": 1},
            "reviewed": {"$sum": {"$cond": [{"$eq": ["$reviewed", True]}, 1, 0]}},
        }},
    ]
    raw: Dict[str, Dict[str, int]] = {}
    async for r in ADDITIONS.aggregate(pipeline):
        raw[r["_id"]] = {"total": r["total"], "reviewed": r["reviewed"]}

    blocks = await get_block_labels_active()
    out = []
    for b in blocks:
        bl = b["block_label"]
        agg = raw.get(bl)
        if not agg:
            continue
        total = agg["total"]
        rev = agg["reviewed"]
        status = "done" if rev == total else ("in_progress" if rev > 0 else "not_started")
        out.append({"block_label": bl, "rate": b["rate"],
                    "total": total, "reviewed": rev, "status": status})

    summary = {
        "blocks":       len(out),
        "done":         sum(1 for r in out if r["status"] == "done"),
        "in_progress":  sum(1 for r in out if r["status"] == "in_progress"),
        "not_started":  sum(1 for r in out if r["status"] == "not_started"),
    }
    return {"rows": out, "summary": summary}


@router.patch("/runs/{rid}/additions/{aid}")
async def patch_addition(
    rid: str,
    aid: str,
    payload: FaAdditionPatch,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if aid.startswith("discount-"):
        raise HTTPException(400, "Discount rows are managed via Credits tab")
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "fy_end": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    add = await ADDITIONS.find_one({"addition_id": aid, "run_id": rid}, {"_id": 0})
    if not add:
        raise HTTPException(404, "Addition not found")
    fields = payload.model_dump(exclude_none=True)
    for k, v in fields.items():
        add[k] = v
    if "put_to_use_date" in fields:
        _recompute_180(add, run.get("fy_end") or "")
    # Any auditor edit marks the row as reviewed (drives the per-block
    # progress strip — Done / In Progress / Not Started).
    add["reviewed"] = True
    add.pop("_id", None)
    await ADDITIONS.replace_one({"addition_id": aid, "run_id": rid}, add)
    return {"ok": True, "row": add}


# ============================ Link / Unlink (Option A) =====================
ADJ_FIELDS_VALID = ("other_expenses", "itc_reversed", "interest_capitalized",
                    "forex_fluctuations", "discount_credits")


async def _unlink_addition(rid: str, aid: str) -> None:
    """Internal helper — undoes any existing parent linkage on `aid`.
    Decrements the parent's <linked_as> column by `aid.invoice_cost` and
    clears the child's parent_addition_id / linked_as fields."""
    add = await ADDITIONS.find_one({"addition_id": aid, "run_id": rid}, {"_id": 0})
    if not add:
        return
    parent_id = add.get("parent_addition_id") or ""
    if not parent_id:
        return
    parent = await ADDITIONS.find_one({"addition_id": parent_id, "run_id": rid}, {"_id": 0})
    if parent:
        col = add.get("linked_as") or "other_expenses"
        if col in ADJ_FIELDS_VALID:
            new_val = max(0.0, float(parent.get(col, 0)) - float(add.get("invoice_cost", 0)))
            await ADDITIONS.update_one(
                {"addition_id": parent_id, "run_id": rid},
                {"$set": {col: round(new_val, 2)}},
            )
    await ADDITIONS.update_one(
        {"addition_id": aid, "run_id": rid},
        {"$set": {"parent_addition_id": "", "linked_as": ""}},
    )


@router.post("/runs/{rid}/additions/{aid}/link")
async def link_addition(
    rid: str,
    aid: str,
    payload: FaAdditionLink,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Merge `aid` into another addition. The full `aid.invoice_cost` flows
    into the parent's `<linked_as>` column; the child stays in the table but
    is treated as 'merged' (skipped by compute, rendered compactly in UI)."""
    await _auth(request, session_token, authorization)
    if aid.startswith("discount-"):
        raise HTTPException(400, "Discount rows are managed via Credits tab")
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    if payload.linked_as not in ADJ_FIELDS_VALID:
        raise HTTPException(400, f"linked_as must be one of {ADJ_FIELDS_VALID}")
    if payload.parent_addition_id == aid:
        raise HTTPException(400, "Cannot link a row to itself")

    add = await ADDITIONS.find_one({"addition_id": aid, "run_id": rid}, {"_id": 0})
    if not add:
        raise HTTPException(404, "Addition not found")
    parent = await ADDITIONS.find_one(
        {"addition_id": payload.parent_addition_id, "run_id": rid}, {"_id": 0},
    )
    if not parent:
        raise HTTPException(404, "Parent addition not found")
    if parent.get("parent_addition_id"):
        raise HTTPException(400, "Cannot link to a row that is itself merged")
    # Block-coherence: keep linked rows inside the same block as the parent
    if (add.get("block_label") or "") and (parent.get("block_label") or "") and \
            add["block_label"] != parent["block_label"]:
        raise HTTPException(400, "Parent and child must belong to the same IT Block")

    # Idempotently undo any prior link first
    await _unlink_addition(rid, aid)

    amt = float(add.get("invoice_cost", 0))
    new_val = round(float(parent.get(payload.linked_as, 0)) + amt, 2)
    now_iso = datetime.now(timezone.utc).isoformat()
    await ADDITIONS.update_one(
        {"addition_id": payload.parent_addition_id, "run_id": rid},
        {"$set": {payload.linked_as: new_val, "reviewed": True}},
    )
    await ADDITIONS.update_one(
        {"addition_id": aid, "run_id": rid},
        {"$set": {
            "parent_addition_id": payload.parent_addition_id,
            "linked_as":          payload.linked_as,
            "reviewed":           True,
            "last_modified":      now_iso,
        }},
    )
    return {"ok": True}


@router.post("/runs/{rid}/additions/{aid}/unlink")
async def unlink_addition(
    rid: str,
    aid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    await _unlink_addition(rid, aid)
    return {"ok": True}


# ============================ Credits =======================================
@router.get("/runs/{rid}/credits")
async def list_credits(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    rows = await CREDITS.find({"run_id": rid}, {"_id": 0}) \
        .sort([("classification", 1), ("accounting_date", 1)]).to_list(5000)
    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1, "block_label": 1}):
        led_map[L["fa_ledger_id"]] = L
    for r in rows:
        L = led_map.get(r.get("fa_ledger_id", ""), {})
        r["ledger_name"] = L.get("name", "")
        r["block_label"] = L.get("block_label", "")
    return {"rows": rows}


@router.post("/runs/{rid}/credits/{cid}/classify")
async def classify_credit(
    rid: str,
    cid: str,
    payload: FaCreditClassifyRequest,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    cr = await CREDITS.find_one({"credit_id": cid, "run_id": rid}, {"_id": 0})
    if not cr:
        raise HTTPException(404, "Credit not found")
    classification = (payload.classification or "").strip().lower()
    if classification not in ("sale", "discount", "pending"):
        raise HTTPException(400, "classification must be 'sale', 'discount', or 'pending'")
    if classification == "sale":
        cr["classification"] = "sale"
        cr["sale_value"] = float(payload.sale_value) if payload.sale_value is not None else cr.get("amount", 0.0)
        cr["sale_date"] = (payload.sale_date or cr.get("sale_date") or "").strip()
        cr["buyer_name"] = (payload.buyer_name or cr.get("buyer_name") or "").strip()
    elif classification == "discount":
        cr["classification"] = "discount"
    else:
        cr["classification"] = "pending"
    cr.pop("_id", None)
    await CREDITS.replace_one({"credit_id": cid, "run_id": rid}, cr)
    return {"ok": True, "row": cr}


# ============================ Invoice OCR (Phase 1.5) =====================
class InvoiceApplySelection(BaseModel):
    """Auditor confirms which chunks to attach + per-chunk addition_id +
    whether to overwrite the addition's `description` field with the OCR-
    extracted asset description."""
    upload_id:    str
    selections: List[Dict[str, Any]]   # [{chunk_index, addition_id, apply_description: bool}]


async def _store_chunk_pdfs(upload_id: str, chunks: List[Dict[str, Any]]) -> None:
    """Persist each chunk's gzipped+base64 PDF in a sidecar collection
    (one doc per chunk) so the parent pending-upload doc stays well under
    Mongo's 16 MB doc size cap even for 25 MB combined PDFs with many chunks."""
    if not chunks:
        return
    docs = [
        {
            "upload_id":   upload_id,
            "chunk_index": c["chunk_index"],
            "content_b64": c["pdf_b64"],
            "stored_at":   datetime.now(timezone.utc).isoformat(),
        }
        for c in chunks
    ]
    await PENDING_CHUNK_PDFS.insert_many(docs)


async def _fetch_chunk_pdf(upload_id: str, chunk_index: int) -> Optional[str]:
    """Return the gzipped+base64 chunk PDF or None."""
    doc = await PENDING_CHUNK_PDFS.find_one(
        {"upload_id": upload_id, "chunk_index": int(chunk_index)},
        {"_id": 0, "content_b64": 1},
    )
    return (doc or {}).get("content_b64")


def _strip_chunk_for_payload(c: Dict[str, Any]) -> Dict[str, Any]:
    """Drop heavy fields from a stored chunk before shipping to the browser."""
    return {
        "chunk_index":         c.get("chunk_index"),
        "page_range":          c.get("page_range"),
        "pdf_size":            c.get("pdf_size"),
        "extraction":          c.get("extraction"),
        "match":               c.get("match"),
        "applied":             bool(c.get("applied")),
        "applied_addition_id": c.get("applied_addition_id"),
        "applied_at":          c.get("applied_at"),
    }


async def _build_match_previews(
    rid: str, chunks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Decorate each chunk's match with the addition's display info so the
    UI can render '<inv-no> · <party> · ₹<cost>' without a second fetch."""
    aids: List[str] = []
    for c in chunks:
        m = c.get("match") or {}
        if m.get("addition_id"):
            aids.append(m["addition_id"])
        if c.get("applied_addition_id"):
            aids.append(c["applied_addition_id"])
    if not aids:
        return chunks
    add_by_id: Dict[str, Dict[str, Any]] = {}
    async for a in ADDITIONS.find(
        {"run_id": rid, "addition_id": {"$in": aids}},
        {"_id": 0, "addition_id": 1, "description": 1, "particulars": 1,
         "ledger_name": 1, "block_label": 1, "invoice_cost": 1,
         "invoice_no": 1, "voucher_no": 1, "party_name": 1, "fa_ledger_id": 1},
    ):
        add_by_id[a["addition_id"]] = a
    led_map: Dict[str, str] = {}
    async for L in LEDGERS.find({"run_id": rid}, {"_id": 0, "fa_ledger_id": 1, "name": 1}):
        led_map[L["fa_ledger_id"]] = L.get("name", "")
    for a in add_by_id.values():
        if not a.get("ledger_name"):
            a["ledger_name"] = led_map.get(a.get("fa_ledger_id", ""), "")
    out = []
    for c in chunks:
        c = dict(c)
        m = dict(c.get("match") or {}) if c.get("match") else None
        if m and m.get("addition_id") in add_by_id:
            a = add_by_id[m["addition_id"]]
            m["preview"] = {
                "description":  a.get("description") or a.get("particulars") or "",
                "ledger_name":  a.get("ledger_name") or "",
                "block_label":  a.get("block_label") or "",
                "invoice_cost": float(a.get("invoice_cost") or 0),
                "invoice_no":   a.get("invoice_no") or "",
                "voucher_no":   a.get("voucher_no") or "",
            }
            c["match"] = m
        if c.get("applied_addition_id") in add_by_id:
            a = add_by_id[c["applied_addition_id"]]
            c["applied_preview"] = {
                "description":  a.get("description") or a.get("particulars") or "",
                "ledger_name":  a.get("ledger_name") or "",
                "invoice_no":   a.get("invoice_no") or "",
                "party_name":   a.get("party_name") or "",
            }
        out.append(c)
    return out


@router.post("/runs/{rid}/upload-invoices")
async def upload_invoices(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Accept ONE invoice PDF, kick off OCR in the background, and return a
    fresh upload_id immediately. Multi-file upload is handled client-side by
    firing N parallel POSTs. Pending uploads are persisted to MongoDB so the
    auditor can return to them later via the inbox."""
    import asyncio
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "client_id": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported.")

    raw = await file.read()
    if not raw[:4] == b"%PDF":
        raise HTTPException(400, "File doesn't look like a valid PDF.")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "PDF exceeds 25 MB limit. Split before uploading.")

    # Snapshot the run's additions + ledgers for matching. We freeze them at
    # upload time so the background task doesn't race with the auditor
    # editing rows on the live page.
    additions = await ADDITIONS.find(
        {"run_id": rid},
        {"_id": 0, "addition_id": 1, "invoice_no": 1, "invoice_cost": 1,
         "party_name": 1, "party_gstin": 1, "parent_addition_id": 1,
         "source": 1, "description": 1, "particulars": 1,
         "block_label": 1, "voucher_no": 1, "fa_ledger_id": 1},
    ).to_list(20000)
    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1, "block_label": 1}):
        led_map[L["fa_ledger_id"]] = L
    for a in additions:
        a["ledger_name"] = led_map.get(a.get("fa_ledger_id", ""), {}).get("name", "")
    run_ledgers = list(led_map.values())

    upload_id    = str(uuid.uuid4())
    started_iso  = datetime.now(timezone.utc).isoformat()

    # Insert the parent pending-upload doc immediately with status='processing'
    # so the inbox can surface it even before OCR finishes.
    await PENDING_UPLOADS_COL.insert_one({
        "upload_id":   upload_id,
        "run_id":      rid,
        "client_id":   run.get("client_id"),
        "filename":    file.filename or "invoice.pdf",
        "pdf_size":    len(raw),
        "status":      "processing",
        "created_at":  started_iso,
        "started_at":  started_iso,
    })

    async def _run_ocr_bg(uid: str, pdf_bytes: bytes,
                          adds: List[Dict[str, Any]], ledgers: List[Dict[str, Any]]):
        from modules.fixed_assets.invoice_ocr import split_extract_and_match
        try:
            # LiteLLM's HTTP client is sync under the hood — wrap in a worker
            # thread so the event loop isn't blocked while Gemini works.
            result = await asyncio.to_thread(
                lambda: asyncio.run(
                    split_extract_and_match(
                        pdf_bytes=pdf_bytes, additions=adds, run_ledgers=ledgers,
                    ),
                ),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("background OCR failed for upload %s: %s", uid, e)
            await PENDING_UPLOADS_COL.update_one(
                {"upload_id": uid},
                {"$set": {
                    "status":      "failed",
                    "error":       str(e)[:500],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return
        # Tag every chunk as not-yet-applied
        chunks_meta = []
        for c in result["chunks"]:
            chunks_meta.append({
                "chunk_index":         c["chunk_index"],
                "page_range":          c["page_range"],
                "pdf_size":            c["pdf_size"],
                "extraction":          c["extraction"],
                "match":               c["match"],
                "applied":             False,
                "applied_addition_id": None,
                "applied_at":          None,
            })
        await PENDING_UPLOADS_COL.update_one(
            {"upload_id": uid},
            {"$set": {
                "status":               "done",
                "page_classifications": result["page_classifications"],
                "ledger_pages":         result["ledger_pages"],
                "detected_ledger_name": result.get("detected_ledger_name", ""),
                "detected_fa_ledger_id": result.get("detected_fa_ledger_id") or "",
                "single_invoice":       result["single_invoice"],
                "summary":              result["summary"],
                "chunks":               chunks_meta,
                "finished_at":          datetime.now(timezone.utc).isoformat(),
            }},
        )
        await _store_chunk_pdfs(uid, result["chunks"])

    asyncio.create_task(_run_ocr_bg(upload_id, raw, additions, run_ledgers))
    return {
        "ok":         True,
        "upload_id":  upload_id,
        "filename":   file.filename or "",
        "status":     "processing",
        "pdf_size":   len(raw),
    }


@router.get("/runs/{rid}/upload-status/{upload_id}")
async def upload_status(
    rid: str,
    upload_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Poll the background OCR job. Returns the same shape as the original
    sync upload-invoices response once status='done'."""
    await _auth(request, session_token, authorization)
    doc = await PENDING_UPLOADS_COL.find_one(
        {"upload_id": upload_id, "run_id": rid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Upload not found.")

    started = doc.get("started_at") or doc.get("created_at") or datetime.now(timezone.utc).isoformat()
    try:
        started_dt = datetime.fromisoformat(started)
    except Exception:  # noqa: BLE001
        started_dt = datetime.now(timezone.utc)
    elapsed_s = int((datetime.now(timezone.utc) - started_dt).total_seconds())

    if doc["status"] == "processing":
        return {"ok": True, "status": "processing", "elapsed_s": elapsed_s,
                "filename": doc.get("filename", "")}
    if doc["status"] == "failed":
        return {"ok": False, "status": "failed",
                "error": doc.get("error", "Unknown OCR failure"),
                "elapsed_s": elapsed_s, "filename": doc.get("filename", "")}

    chunks = await _build_match_previews(rid, doc.get("chunks") or [])
    return {
        "ok":                   True,
        "status":               "done",
        "upload_id":            upload_id,
        "filename":             doc.get("filename", ""),
        "page_classifications": doc.get("page_classifications") or [],
        "ledger_pages":         doc.get("ledger_pages") or [],
        "detected_ledger_name": doc.get("detected_ledger_name") or "",
        "detected_fa_ledger_id": doc.get("detected_fa_ledger_id") or "",
        "single_invoice":       doc.get("single_invoice", False),
        "summary":              doc.get("summary") or {},
        "chunks":               [_strip_chunk_for_payload(c) for c in chunks],
        "elapsed_s":            elapsed_s,
    }


@router.post("/runs/{rid}/apply-invoice-uploads")
async def apply_invoice_uploads(
    rid: str,
    payload: InvoiceApplySelection,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Persist the auditor-confirmed chunks: store each chunk PDF in
    fa_invoice_attachments, mark the chunk as applied on the parent pending
    upload doc (so the inbox shows '4 of 9 attached'), and (optionally)
    overwrite the addition's `description` with the OCR-extracted line."""
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")

    pending = await PENDING_UPLOADS_COL.find_one(
        {"upload_id": payload.upload_id, "run_id": rid}, {"_id": 0},
    )
    if not pending:
        raise HTTPException(404, "Upload not found.")
    if pending.get("status") != "done":
        raise HTTPException(409, f"Upload is in '{pending.get('status')}' state — cannot apply.")

    chunks_by_idx = {c["chunk_index"]: c for c in (pending.get("chunks") or [])}
    now_iso = datetime.now(timezone.utc).isoformat()
    saved = 0
    descriptions_updated = 0

    for sel in payload.selections:
        ci = sel.get("chunk_index")
        aid = (sel.get("addition_id") or "").strip()
        apply_desc = bool(sel.get("apply_description", False))
        if ci is None or not aid:
            continue
        chunk = chunks_by_idx.get(int(ci))
        if not chunk:
            continue
        add = await ADDITIONS.find_one(
            {"run_id": rid, "addition_id": aid},
            {"_id": 0, "addition_id": 1, "description": 1, "particulars": 1},
        )
        if not add:
            continue

        chunk_pdf_b64 = await _fetch_chunk_pdf(payload.upload_id, int(ci))
        if not chunk_pdf_b64:
            log.warning("chunk PDF missing for upload %s ci %s", payload.upload_id, ci)
            continue

        ext = chunk.get("extraction") or {}
        await INVOICE_ATTACH.replace_one(
            {"run_id": rid, "addition_id": aid},
            {
                "run_id":         rid,
                "addition_id":    aid,
                "filename":       pending.get("filename", "invoice.pdf"),
                "page_range":     chunk.get("page_range"),
                "pdf_size":       chunk.get("pdf_size"),
                "content_b64":    chunk_pdf_b64,
                "ocr_extraction": ext,
                "uploaded_at":    now_iso,
                "from_upload_id": payload.upload_id,
            },
            upsert=True,
        )
        saved += 1

        # Mark this chunk as applied on the pending upload doc
        await PENDING_UPLOADS_COL.update_one(
            {"upload_id": payload.upload_id, "chunks.chunk_index": int(ci)},
            {"$set": {
                "chunks.$.applied":             True,
                "chunks.$.applied_addition_id": aid,
                "chunks.$.applied_at":          now_iso,
            }},
        )

        if apply_desc and ext.get("description"):
            await ADDITIONS.update_one(
                {"run_id": rid, "addition_id": aid},
                {"$set": {
                    "description":     ext["description"][:500],
                    "reviewed":        True,
                    "last_modified":   now_iso,
                }},
            )
            descriptions_updated += 1

    await _refresh_run_summary(rid)
    return {"ok": True, "attached": saved, "descriptions_updated": descriptions_updated}


@router.get("/runs/{rid}/invoice-inbox")
async def invoice_inbox(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """List every pending invoice upload for this run — used by the
    Additions tab to render the persistent inbox panel."""
    await _auth(request, session_token, authorization)
    rows = await PENDING_UPLOADS_COL.find(
        {"run_id": rid},
        {"_id": 0, "upload_id": 1, "filename": 1, "pdf_size": 1, "status": 1,
         "error": 1, "created_at": 1, "finished_at": 1, "summary": 1,
         "detected_ledger_name": 1, "detected_fa_ledger_id": 1,
         "chunks": 1},
    ).sort([("created_at", -1)]).to_list(500)

    out = []
    for r in rows:
        chunks = r.get("chunks") or []
        applied = sum(1 for c in chunks if c.get("applied"))
        out.append({
            "upload_id":    r["upload_id"],
            "filename":     r.get("filename", ""),
            "pdf_size":     r.get("pdf_size", 0),
            "status":       r.get("status", "processing"),
            "error":        r.get("error", ""),
            "created_at":   r.get("created_at", ""),
            "finished_at":  r.get("finished_at", ""),
            "detected_ledger_name":  r.get("detected_ledger_name", ""),
            "detected_fa_ledger_id": r.get("detected_fa_ledger_id", ""),
            "summary":      r.get("summary", {}),
            "total_chunks": len(chunks),
            "applied":      applied,
            "pending":      len(chunks) - applied,
        })
    return {"rows": out}


@router.delete("/runs/{rid}/invoice-inbox/{upload_id}")
async def discard_pending_upload(
    rid: str,
    upload_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Delete a pending upload entry + its sidecar chunk PDFs. Already-applied
    chunks (which live in fa_invoice_attachments) are NOT touched — the
    auditor's per-row attachments survive."""
    await _auth(request, session_token, authorization)
    res = await PENDING_UPLOADS_COL.delete_one({"upload_id": upload_id, "run_id": rid})
    await PENDING_CHUNK_PDFS.delete_many({"upload_id": upload_id})
    return {"ok": True, "deleted": res.deleted_count}


@router.get("/runs/{rid}/additions/{aid}/invoice")
async def download_invoice_attachment(
    rid: str,
    aid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Stream back the per-chunk PDF stored against this addition row."""
    import base64
    import gzip
    await _auth(request, session_token, authorization)
    doc = await INVOICE_ATTACH.find_one(
        {"run_id": rid, "addition_id": aid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "No invoice attached to this addition")
    try:
        blob = gzip.decompress(base64.b64decode(doc["content_b64"]))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Stored attachment is corrupt: {e}")

    fname = (doc.get("filename") or "invoice.pdf")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}"'},
    )


@router.delete("/runs/{rid}/additions/{aid}/invoice")
async def delete_invoice_attachment(
    rid: str,
    aid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Detach the stored invoice from this addition (does NOT touch the row's
    `description` field — that stays as is so any auditor edits aren't lost)."""
    await _auth(request, session_token, authorization)
    res = await INVOICE_ATTACH.delete_one({"run_id": rid, "addition_id": aid})
    return {"ok": True, "deleted": res.deleted_count}


@router.get("/runs/{rid}/invoice-attachments")
async def list_invoice_attachments(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Return a thin list (no pdf bytes) of every addition that has an
    invoice attached — used to render paperclip icons on the Additions tab."""
    await _auth(request, session_token, authorization)
    rows = await INVOICE_ATTACH.find(
        {"run_id": rid},
        {"_id": 0, "addition_id": 1, "filename": 1, "pdf_size": 1,
         "page_range": 1, "uploaded_at": 1, "ocr_extraction": 1},
    ).to_list(20000)
    return {"rows": rows}


# ============================ Bulk Patch (Phase A) =========================
class FaAdditionsBulkPatch(BaseModel):
    addition_ids: List[str]
    patch:        Dict[str, Any]


@router.post("/runs/{rid}/additions/bulk-patch")
async def bulk_patch_additions(
    rid: str,
    payload: FaAdditionsBulkPatch,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Apply the same patch to many addition rows. Used by the bulk-action
    bar (Set Block, Mark Reviewed, Copy PTU = Acc Date). Skips merged-child
    rows and discount-credit rows for safety."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "fy_end": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    ids = [x for x in (payload.addition_ids or []) if isinstance(x, str)]
    if not ids:
        return {"ok": True, "updated": 0}
    fy_end = run.get("fy_end") or ""
    updated = 0
    copy_ptu_from_acc = bool(payload.patch.get("__copy_ptu_from_acc"))
    base_patch = {k: v for k, v in payload.patch.items() if not k.startswith("__")}

    async for a in ADDITIONS.find({"run_id": rid, "addition_id": {"$in": ids}}, {"_id": 0}):
        if (a.get("source") or "") == "discount_credit":
            continue
        if a.get("parent_addition_id"):
            continue
        merged = {**a, **base_patch}
        if copy_ptu_from_acc and a.get("accounting_date"):
            merged["put_to_use_date"] = a["accounting_date"]
        if "put_to_use_date" in merged or copy_ptu_from_acc:
            from modules.fixed_assets.service import is_more_than_180
            full = is_more_than_180(merged.get("put_to_use_date") or "", fy_end)
            merged["is_more_than_180"] = full
            merged["half_rate"] = not full
        merged["reviewed"] = True
        await ADDITIONS.update_one(
            {"addition_id": a["addition_id"], "run_id": rid},
            {"$set": {k: v for k, v in merged.items() if k != "_id"}},
        )
        updated += 1
    return {"ok": True, "updated": updated}


# ============================ Excel Round-Trip (Phase B) ===================
async def _gather_additions_for_xlsx(rid: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return additions grouped by block_label. Includes ledger_name and
    rolls in discount-credits as locked rows so the auditor sees the full
    block picture in one sheet."""
    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1, "block_label": 1}):
        led_map[L["fa_ledger_id"]] = L

    rows = await ADDITIONS.find({"run_id": rid}, {"_id": 0}) \
        .sort([("block_label", 1), ("invoice_date", 1)]).to_list(20000)
    for r in rows:
        Ldoc = led_map.get(r.get("fa_ledger_id", ""), {})
        r["ledger_name"] = Ldoc.get("name", "")
        r.setdefault("source", "addition")

    # Surface discount-classified credits as negative locked addition rows
    async for c in CREDITS.find({"run_id": rid, "classification": "discount"}, {"_id": 0}):
        Ldoc = led_map.get(c.get("fa_ledger_id", ""), {})
        rows.append({
            "addition_id":         f"discount-{c['credit_id']}",
            "parent_addition_id":  "",
            "fa_ledger_id":        c.get("fa_ledger_id", ""),
            "ledger_name":         Ldoc.get("name", ""),
            "block_label":         Ldoc.get("block_label", ""),
            "accounting_date":     c.get("accounting_date", ""),
            "invoice_date":        c.get("accounting_date", ""),
            "put_to_use_date":     "",
            "description":         f"[Discount] {c.get('particulars') or ''}",
            "party_name":          c.get("party_name", ""),
            "voucher_no":          c.get("voucher_no", ""),
            "invoice_no":          "",
            "invoice_cost":        -float(c.get("amount") or 0),
            "other_expenses":      0.0, "itc_reversed": 0.0,
            "interest_capitalized": 0.0, "forex_fluctuations": 0.0,
            "discount_credits":    0.0,
            "source":              "discount_credit",
        })

    by_block: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_block.setdefault(r.get("block_label") or "(unblocked)", []).append(r)
    return by_block


@router.get("/runs/{rid}/additions/export.xlsx")
async def additions_export_xlsx(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    by_block = await _gather_additions_for_xlsx(rid)
    client = await db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0, "name": 1})
    blob = build_additions_workbook(
        client_name=(client or {}).get("name") or run.get("name") or "",
        fy=run.get("fy") or "",
        rows_by_block=by_block,
    )
    safe = (((client or {}).get("name") or "client").replace(" ", "_"))[:40]
    fy = run.get("fy") or ""
    filename = f"Additions_{safe}_FY{fy}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{rid}/additions/import.xlsx")
async def additions_import_xlsx(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = True,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Two-phase: dry_run=true returns a diff + drift report; dry_run=false
    applies the changes and (when totals drift) persists a warning flag on
    the run. The Compute tab refuses to hide that warning until the auditor
    explicitly clears it via /clear-excel-drift."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "fy_end": 1})
    if not run:
        raise HTTPException(404, "Run not found")

    raw = await file.read()
    try:
        parsed = parse_additions_workbook(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid Additions Excel: {e}")

    # Build the live DB view (regular rows only — discount-credits skip)
    db_rows = await ADDITIONS.find({"run_id": rid}, {"_id": 0}).to_list(20000)
    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1}):
        led_map[L["fa_ledger_id"]] = L
    for r in db_rows:
        r["ledger_name"] = led_map.get(r.get("fa_ledger_id", ""), {}).get("name", "")

    diff = diff_additions(db_rows=db_rows, xl_rows=parsed["rows"])
    drift = block_drift(db_rows=db_rows, xl_changes=diff["changes"])

    if dry_run:
        return {
            "ok":            True,
            "dry_run":       True,
            "filename":      file.filename or "",
            "sheets":        parsed["sheets"],
            "errors":        parsed["errors"],
            "rows_changed":  len(diff["changes"]),
            "unknown_ids":   diff["unknown_ids"],
            "changes":       diff["changes"][:500],   # cap payload
            "drift":         drift,
        }

    # ---- APPLY ---------------------------------------------------------
    fy_end = run.get("fy_end") or ""
    applied = 0
    from modules.fixed_assets.service import is_more_than_180
    for ch in diff["changes"]:
        aid = ch["addition_id"]
        patch: Dict[str, Any] = {f: v["new"] for f, v in ch["changes"].items()}
        if "put_to_use_date" in patch:
            full = is_more_than_180(patch["put_to_use_date"] or "", fy_end)
            patch["is_more_than_180"] = full
            patch["half_rate"] = not full
        patch["reviewed"] = True
        await ADDITIONS.update_one({"addition_id": aid, "run_id": rid}, {"$set": patch})
        applied += 1

    drift_set: Dict[str, Any] = {}
    if drift["drifted"]:
        drift_set = {
            "applied_at":    datetime.now(timezone.utc).isoformat(),
            "applied_by":    file.filename or "",
            "blocks":        [b for b in drift["blocks"] if abs(b["diff"]) > 1.0],
            "rows_changed":  applied,
        }
        await RUNS.update_one({"id": rid}, {"$set": {"excel_drift_warning": drift_set}})
    else:
        # Successful clean import — clear any prior drift warning.
        await RUNS.update_one({"id": rid}, {"$unset": {"excel_drift_warning": ""}})

    return {
        "ok":           True,
        "dry_run":      False,
        "applied":      applied,
        "unknown_ids":  diff["unknown_ids"],
        "drift":        drift,
        "drift_warning": drift_set,
    }


@router.post("/runs/{rid}/clear-excel-drift")
async def clear_excel_drift(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Auditor-driven acknowledgement that the totals drift introduced by
    a re-imported Excel has been investigated and reconciled."""
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    await RUNS.update_one({"id": rid}, {"$unset": {"excel_drift_warning": ""}})
    return {"ok": True}


# ============================ Block Opening WDV ============================
class BlockOpeningUpsert(BaseModel):
    block_label: str
    opening_wdv: float
    description: Optional[str] = ""


@router.get("/runs/{rid}/block-opening")
async def list_block_opening(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Return one row per active block_label; 0 when auditor has not yet
    entered an opening WDV. Includes the canonical rate."""
    await _auth(request, session_token, authorization)
    blocks = await get_block_labels_active()
    saved: Dict[str, Dict[str, Any]] = {}
    async for b in BLOCK_OPEN.find({"run_id": rid}, {"_id": 0}):
        saved[b["block_label"]] = b
    rows = []
    for b in blocks:
        s = saved.get(b["block_label"], {})
        rows.append({
            "block_label": b["block_label"],
            "rate":        b["rate"],
            "opening_wdv": float(s.get("opening_wdv") or 0),
            "source":      s.get("source", "manual"),
            "description": s.get("description", ""),
        })
    return {"rows": rows}


@router.post("/runs/{rid}/block-opening")
async def upsert_block_opening(
    rid: str,
    payload: BlockOpeningUpsert,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")
    if not await LEGAL_MASTER_COLLECTION.find_one(
        {"is_active": True, "block_label": payload.block_label}, {"_id": 0, "row_id": 1},
    ):
        raise HTTPException(400, f"Unknown block_label: {payload.block_label}")
    await BLOCK_OPEN.update_one(
        {"run_id": rid, "block_label": payload.block_label},
        {"$set": {
            "run_id":      rid,
            "block_label": payload.block_label,
            "opening_wdv": float(payload.opening_wdv or 0),
            "source":      "manual",
            "description": (payload.description or "").strip(),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True}


# ============================ Prior 3CD Import (Phase 1D) ==================
@router.post("/runs/{rid}/ingest-prior-3cd")
async def ingest_prior_3cd(
    rid: str,
    request: Request,
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Parse the uploaded prior-year Form 3CD JSON, auto-map each rate row to
    the active block_label(s) sharing that rate, and return a staged preview.
    Nothing is written to fa_block_opening at this step — auditor confirms
    via POST /apply-prior-3cd."""
    await _auth(request, session_token, authorization)
    if not await RUNS.find_one({"id": rid}, {"_id": 0}):
        raise HTTPException(404, "Run not found")

    raw = await file.read()
    try:
        rate_rows = parse_prior_3cd(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid 3CD JSON: {e}")
    if not rate_rows:
        raise HTTPException(400, "No depreciation entries found in 3CD JSON "
                                 "(expected FORM3CA.F3CA.Form3cdDeprAllw).")

    blocks = await get_block_labels_active()
    by_rate: Dict[float, List[Dict[str, Any]]] = {}
    for b in blocks:
        by_rate.setdefault(b["rate"], []).append(b)

    staged = []
    for r in rate_rows:
        cands = by_rate.get(r["rate"], [])
        suggested = cands[0]["block_label"] if len(cands) == 1 else ""
        staged.append({
            **r,
            "suggested_block_label":  suggested,
            "candidate_block_labels": [c["block_label"] for c in cands],
            "needs_review":           len(cands) != 1,
        })

    await RUNS.update_one({"id": rid}, {"$set": {
        "prior_3cd_staged":      staged,
        "prior_3cd_filename":    file.filename or "",
        "prior_3cd_ingested_at": datetime.now(timezone.utc).isoformat(),
    }})
    return {"ok": True, "rows": staged}


class Prior3CDApplyItem(BaseModel):
    rate: float
    block_label: str
    opening_wdv: float


class Prior3CDApply(BaseModel):
    items: List[Prior3CDApplyItem]


@router.post("/runs/{rid}/apply-prior-3cd")
async def apply_prior_3cd(
    rid: str,
    payload: Prior3CDApply,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Write the auditor-confirmed 3CD opening WDV into fa_block_opening."""
    await _auth(request, session_token, authorization)
    run = await RUNS.find_one({"id": rid}, {"_id": 0, "prior_3cd_filename": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    valid_blocks = {b["block_label"] for b in await get_block_labels_active()}

    applied = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    fname = run.get("prior_3cd_filename") or "prior_3cd.json"
    for item in payload.items:
        bl = (item.block_label or "").strip()
        if not bl or bl not in valid_blocks:
            continue
        await BLOCK_OPEN.update_one(
            {"run_id": rid, "block_label": bl},
            {"$set": {
                "run_id":      rid,
                "block_label": bl,
                "opening_wdv": float(item.opening_wdv or 0),
                "source":      "prior_3cd",
                "source_ref":  fname,
                "description": f"Auto-imported from prior 3CD ({fname})",
                "updated_at":  now_iso,
            }},
            upsert=True,
        )
        applied += 1
    return {"ok": True, "applied": applied}


# ============================ Multi-FY Roll Forward (Phase 1H) =============
async def _roll_forward_preview(rid: str) -> Dict[str, Any]:
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    src_id = run.get("rolled_from_run_id") or ""
    if not src_id:
        src = await RUNS.find_one(
            {"client_id": run["client_id"], "id": {"$ne": rid},
             "fy_end":  {"$lt": run.get("fy_end") or ""}},
            {"_id": 0, "id": 1, "fy": 1, "fy_end": 1},
            sort=[("fy_end", -1)],
        )
        if not src:
            return {"ok": False, "reason": "No prior FY run found for this client."}
        src_id = src["id"]

    src_run = await RUNS.find_one({"id": src_id}, {"_id": 0})
    if not src_run:
        return {"ok": False, "reason": "Linked prior run not found."}

    src_inputs = await _gather_compute_inputs(src_id)
    from modules.fixed_assets.compute import compute_run as _cr
    rows, _totals = _cr(
        openings=src_inputs["openings"],
        blocks_meta=src_inputs["blocks_meta"],
        additions=src_inputs["additions"],
        deletions=src_inputs["credits"],
    )
    items = [
        {"block_label": r["block_label"], "closing_wdv": float(r["closing_wdv"])}
        for r in rows if r["closing_wdv"] > 0
    ]
    return {
        "ok":         True,
        "src_run_id": src_id,
        "src_fy":     src_run.get("fy") or "",
        "src_name":   src_run.get("name") or "",
        "items":      items,
    }


@router.get("/runs/{rid}/roll-forward-source")
async def roll_forward_source_endpoint(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    return await _roll_forward_preview(rid)


@router.post("/runs/{rid}/roll-forward")
async def roll_forward_endpoint(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    preview = await _roll_forward_preview(rid)
    if not preview.get("ok"):
        raise HTTPException(400, preview.get("reason") or "Roll-forward source unavailable")

    src_fy = preview["src_fy"]
    src_run_id = preview["src_run_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    applied = 0
    for it in preview["items"]:
        bl = it["block_label"]
        await BLOCK_OPEN.update_one(
            {"run_id": rid, "block_label": bl},
            {"$set": {
                "run_id":      rid,
                "block_label": bl,
                "opening_wdv": float(it["closing_wdv"]),
                "source":      "prior_run",
                "source_ref":  f"run:{src_run_id}",
                "description": f"Auto-rolled forward from FY {src_fy}",
                "updated_at":  now_iso,
            }},
            upsert=True,
        )
        applied += 1
    await RUNS.update_one({"id": rid}, {"$set": {"rolled_from_run_id": src_run_id}})
    return {"ok": True, "applied": applied, "src_fy": src_fy, "src_run_id": src_run_id}


# ============================ Compute & Export =============================
async def _gather_compute_inputs(rid: str) -> Dict[str, Any]:
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    blocks = await get_block_labels_active()
    blocks_meta = {b["block_label"]: b["rate"] for b in blocks}

    openings = await BLOCK_OPEN.find({"run_id": rid}, {"_id": 0}).to_list(50)
    additions_all = await ADDITIONS.find({"run_id": rid}, {"_id": 0}).to_list(10000)
    # Merged child rows already had their invoice_cost rolled into a parent's
    # adjustment column via /link — skip them here to avoid double counting.
    additions = [a for a in additions_all if not (a.get("parent_addition_id") or "")]
    credits = await CREDITS.find({"run_id": rid}, {"_id": 0}).to_list(5000)

    led_map: Dict[str, Dict[str, Any]] = {}
    async for L in LEDGERS.find({"run_id": rid},
                                {"_id": 0, "fa_ledger_id": 1, "name": 1, "block_label": 1}):
        led_map[L["fa_ledger_id"]] = L
    for c in credits:
        Ldoc = led_map.get(c.get("fa_ledger_id", ""), {})
        c["block_label"] = Ldoc.get("block_label", "")
        c["ledger_name"] = Ldoc.get("name", "")
    for a in additions:
        Ldoc = led_map.get(a.get("fa_ledger_id", ""), {})
        a["ledger_name"] = Ldoc.get("name", "")

    # Discount-classified credits become negative pseudo-additions so they
    # reduce the block's capitalised cost in the depreciation working.
    for c in credits:
        if (c.get("classification") or "").lower() != "discount":
            continue
        if not c.get("block_label"):
            continue
        additions.append({
            "block_label":         c["block_label"],
            "fa_ledger_id":        c.get("fa_ledger_id", ""),
            "ledger_name":         c.get("ledger_name", ""),
            "voucher_no":          c.get("voucher_no", ""),
            "voucher_type":        c.get("voucher_type", ""),
            "accounting_date":     c.get("accounting_date", ""),
            "invoice_date":        c.get("accounting_date", ""),
            "put_to_use_date":     "",
            "particulars":         f"[Discount] {c.get('particulars') or ''}",
            "description":         f"[Discount] {c.get('particulars') or ''}",
            "party_name":          c.get("party_name", ""),
            "invoice_cost":        -float(c.get("amount") or 0),
            "discount_credits":    0.0,
            "other_expenses":      0.0,
            "itc_reversed":        0.0,
            "interest_capitalized": 0.0,
            "forex_fluctuations":  0.0,
            "is_more_than_180":    True,
            "half_rate":           False,
            "source":              "discount_credit",
        })

    return {
        "run":         run,
        "blocks_meta": blocks_meta,
        "openings":    openings,
        "additions":   additions,
        "credits":     credits,
    }


@router.post("/runs/{rid}/compute")
async def compute_run_endpoint(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    inputs = await _gather_compute_inputs(rid)
    rows, totals = compute_run(
        openings=inputs["openings"],
        blocks_meta=inputs["blocks_meta"],
        additions=inputs["additions"],
        deletions=inputs["credits"],
    )
    await RUNS.update_one({"id": rid}, {"$set": {
        "status":           "computed",
        "last_computed_at": datetime.now(timezone.utc).isoformat(),
    }})
    return {"ok": True, "rows": rows, "totals": totals}


@router.get("/runs/{rid}/export.xlsx")
async def export_xlsx(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    inputs = await _gather_compute_inputs(rid)
    rows, totals = compute_run(
        openings=inputs["openings"],
        blocks_meta=inputs["blocks_meta"],
        additions=inputs["additions"],
        deletions=inputs["credits"],
    )
    client = await db.clients.find_one(
        {"client_id": inputs["run"]["client_id"]}, {"_id": 0, "name": 1},
    )
    client_name = (client or {}).get("name") or inputs["run"].get("name") or ""
    blob = build_workbook(
        client_name=client_name,
        fy_start=inputs["run"].get("fy_start") or "",
        fy_end=inputs["run"].get("fy_end") or "",
        rows=rows,
        totals=totals,
        additions=inputs["additions"],
        deletions=inputs["credits"],
    )
    fy = inputs["run"].get("fy") or ""
    safe = (client_name or "client").replace(" ", "_")[:40]
    filename = f"IT_Depreciation_{safe}_FY{fy}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================ Health probe (Phase 1A) =====================
class HealthOut(BaseModel):
    ok: bool
    legal_master_rows: int
    runs: int


@router.get("/health", response_model=HealthOut)
async def health(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    await seed_legal_master()
    return {
        "ok": True,
        "legal_master_rows": await LEGAL_MASTER_COLLECTION.count_documents({}),
        "runs": await RUNS.count_documents({}),
    }
