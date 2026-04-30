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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from core.db import db
from modules.auth.controller import get_current_user
from modules.fixed_assets.compute import compute_run
from modules.fixed_assets.export import build_workbook
from modules.fixed_assets.legal_master import (
    LEGAL_MASTER_COLLECTION,
    get_block_labels_active,
    list_legal_master,
    seed_legal_master,
)
from modules.fixed_assets.schemas import (
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
    await _auth(request, session_token, authorization)
    q: Dict[str, Any] = {"run_id": rid}
    if block:
        q["block_label"] = block
    rows = await ADDITIONS.find(q, {"_id": 0}) \
        .sort([("block_label", 1), ("invoice_date", 1)]).to_list(5000)
    led_map: Dict[str, str] = {}
    async for L in LEDGERS.find({"run_id": rid}, {"_id": 0, "fa_ledger_id": 1, "name": 1}):
        led_map[L["fa_ledger_id"]] = L.get("name", "")
    for r in rows:
        r["ledger_name"] = led_map.get(r.get("fa_ledger_id", ""), "")
    return {"rows": rows}


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
    add.pop("_id", None)
    await ADDITIONS.replace_one({"addition_id": aid, "run_id": rid}, add)
    return {"ok": True, "row": add}


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


# ============================ Compute & Export =============================
async def _gather_compute_inputs(rid: str) -> Dict[str, Any]:
    run = await RUNS.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    blocks = await get_block_labels_active()
    blocks_meta = {b["block_label"]: b["rate"] for b in blocks}

    openings = await BLOCK_OPEN.find({"run_id": rid}, {"_id": 0}).to_list(50)
    additions = await ADDITIONS.find({"run_id": rid}, {"_id": 0}).to_list(10000)
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
