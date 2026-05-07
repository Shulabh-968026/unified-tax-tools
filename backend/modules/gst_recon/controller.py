"""GST Recon routes — Phase A scaffold (prefix: /gst-recon)."""
from __future__ import annotations
import base64
import gzip
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from core.db import db
from helpers.mapping import parse_ledger_mapping
from modules.auth.controller import get_current_user
from modules.library import service as lib_svc
from modules.library.controller import DEFAULT_FIRM_ID
from modules.library.generations import append_generation, list_generations
from modules.library.scope import resolve_scope_for_request
from modules.gst_recon.schemas import RunCreate, RunOut
from modules.gst_recon.aggregators import (
    aggregate_books,
    aggregate_gstr1,
    aggregate_gstr2b,
    extract_books_invoices,
    extract_gstr1_invoices,
    extract_gstr2b_invoices,
)
from modules.gst_recon.excel_export import build_workbook
from modules.gst_recon.pdf_export import build_pdf
from modules.gst_recon.service import build_month_grid, build_summary, categorize_file, match_invoices
from modules.gst_recon.validation import inspect_file, validate_run

router = APIRouter(prefix="/gst-recon")
COLL = db.gst_recon_runs
INV = db.gst_recon_invoices  # Phase D — voucher-level invoice records
BOOKS_RAW = db.gst_recon_books_raw  # Raw Books JSON stored for re-processing when Mapping arrives


async def _auth(request, tok, auth):
    return await get_current_user(request, tok, auth)


def _load_rules_from_doc(doc: Dict[str, Any]) -> Optional[Dict[str, set]]:
    """Convert stored mapping_rules (lists) back to sets for aggregator consumption."""
    stored = doc.get("mapping_rules") or {}
    if not stored:
        return None
    return {k: set(v or []) for k, v in stored.items()}


async def _load_books_content(rid: str) -> Optional[bytes]:
    raw = await BOOKS_RAW.find_one({"run_id": rid}, {"_id": 0, "content_b64": 1})
    if not raw or not raw.get("content_b64"):
        return None
    try:
        return gzip.decompress(base64.b64decode(raw["content_b64"]))
    except Exception:
        return None


async def _reprocess_books(rid: str, content: bytes, rules: Dict[str, set], all_files: List[Dict[str, Any]]):
    """Re-aggregate books with current mapping rules; rewrite invoices collection."""
    # Re-aggregate the books file entry
    books_per_month = aggregate_books(content, rules)
    for entry in all_files:
        if entry.get("bucket") == "books":
            entry["books_per_month"] = books_per_month
    # Rewrite voucher-level invoice records
    await INV.delete_many({"run_id": rid, "source": "books"})
    inv_records = extract_books_invoices(content, rules)
    if inv_records:
        await INV.insert_many([{"run_id": rid, "source": "books", **r} for r in inv_records])


async def _build_partywise(rid: str, direction: str) -> Dict[str, Any]:
    """Aggregate gst_recon_invoices by party_gstin to produce annual party-wise
    Books vs Portal totals.

    direction='outward' → Books-Sales ↔ GSTR-1
    direction='inward'  → Books-Purchase ↔ GSTR-2B

    Returns { rows: [{party_gstin, party_name, books_total, portal_total,
                     books_taxable, portal_taxable, books_tax, portal_tax,
                     diff_total}], totals }
    """
    portal_src = "gstr1" if direction == "outward" else "gstr2b"
    books = await INV.find(
        {"run_id": rid, "source": "books", "direction": direction},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(50000)
    portal = await INV.find(
        {"run_id": rid, "source": portal_src},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(50000)

    # Group both by party_gstin
    by_gstin: Dict[str, Dict[str, Any]] = {}
    for b in books:
        g = b.get("party_gstin", "")
        if not g:
            continue
        row = by_gstin.setdefault(g, {
            "party_gstin": g, "party_name": b.get("party_name", ""),
            "books_total": 0.0, "portal_total": 0.0,
            "books_taxable": 0.0, "portal_taxable": 0.0,
            "books_tax": 0.0, "portal_tax": 0.0,
        })
        row["books_total"] += float(b.get("total", 0) or 0)
        row["books_taxable"] += float(b.get("taxable", 0) or 0)
        row["books_tax"] += sum(float(b.get(k, 0) or 0) for k in ("igst", "cgst", "sgst", "cess"))
        # Prefer the longer / non-empty name
        if not row["party_name"] and b.get("party_name"):
            row["party_name"] = b["party_name"]

    for p in portal:
        g = p.get("party_gstin", "")
        if not g:
            continue
        row = by_gstin.setdefault(g, {
            "party_gstin": g, "party_name": p.get("party_name", ""),
            "books_total": 0.0, "portal_total": 0.0,
            "books_taxable": 0.0, "portal_taxable": 0.0,
            "books_tax": 0.0, "portal_tax": 0.0,
        })
        row["portal_total"] += float(p.get("total", 0) or 0)
        row["portal_taxable"] += float(p.get("taxable", 0) or 0)
        row["portal_tax"] += sum(float(p.get(k, 0) or 0) for k in ("igst", "cgst", "sgst", "cess"))
        if not row["party_name"] and p.get("party_name"):
            row["party_name"] = p["party_name"]

    rows = []
    for g, r in by_gstin.items():
        for k in ("books_total", "portal_total", "books_taxable", "portal_taxable", "books_tax", "portal_tax"):
            r[k] = round(r[k], 2)
        r["diff_total"] = round(r["books_total"] - r["portal_total"], 2)
        r["diff_taxable"] = round(r["books_taxable"] - r["portal_taxable"], 2)
        r["diff_tax"] = round(r["books_tax"] - r["portal_tax"], 2)
        rows.append(r)
    rows.sort(key=lambda r: -abs(r["diff_total"]))  # largest variance first

    totals = {k: round(sum(r[k] for r in rows), 2) for k in
              ("books_total", "portal_total", "books_taxable", "portal_taxable",
               "books_tax", "portal_tax", "diff_total", "diff_taxable", "diff_tax")}
    return {"direction": direction, "rows": rows, "totals": totals}


@router.post("/runs", response_model=RunOut)
async def create_run(
    payload: RunCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    # Phase C.1 — resolve scope (defaults to consolidation when absent).
    scope = await resolve_scope_for_request(
        db, client_id=payload.client_id,
        scope_kind=payload.scope_kind,
        division_ids=payload.division_ids,
        gstin_group_id=payload.gstin_group_id,
    )
    # Release 4.5 — upsert canonical working doc per (client_id, fy, scope_key)
    existing = await COLL.find_one(
        {"client_id": payload.client_id, "fy": payload.fy,
         "scope_key": scope["scope_key"], "archived": False},
        {"_id": 0},
    )
    if existing:
        return existing
    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "client_id": payload.client_id,
        "fy": payload.fy,
        "module": "gst_recon",
        "archived": False,
        "name": payload.name or f"GST Recon {payload.fy}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["user_id"],
        "status": "draft",
        "files": [],
        "months": build_month_grid(payload.fy, []),
        "has_books": False,
        "has_mapping": False,
        "validation": None,
        # Phase C.1 — scope fields.
        "scope_kind":     scope["scope_kind"],
        "division_ids":   scope["division_ids"],
        "scope_label":    scope["scope_label"],
        "scope_key":      scope["scope_key"],
        "gstin_group_id": scope["gstin_group_id"],
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
    q = {"client_id": client_id, "archived": False} if client_id else {"archived": False}
    return await COLL.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.get("/runs/{rid}", response_model=RunOut)
async def get_run(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")
    # Release 4.5 — silent redirect for collapsed/archived run_ids.
    seen = {doc["id"]}
    while doc.get("archived") and doc.get("collapsed_into") and doc["collapsed_into"] not in seen:
        nxt = await COLL.find_one({"id": doc["collapsed_into"]}, {"_id": 0})
        if not nxt:
            raise HTTPException(404, "Run not found")
        seen.add(nxt["id"])
        doc = nxt
        rid = nxt["id"]
    if doc.get("archived"):
        raise HTTPException(404, "Run not found")
    try:
        firm_id = doc.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID
        doc["library_status"] = await lib_svc.compute_module_status(
            firm_id=firm_id, client_id=doc["client_id"],
            period=doc.get("fy", ""), division=None,
            module_key="gst_recon",
            pinned_files=doc.get("pinned_files") or {},
        )
    except Exception:
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
    res = await COLL.delete_one({"id": rid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Run not found")
    # Cascade — Phase D invoices are tied to the run
    await INV.delete_many({"run_id": rid})
    await BOOKS_RAW.delete_many({"run_id": rid})
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
    user = await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")

    # Load any pre-existing mapping rules to re-process Books on upload
    existing_rules = _load_rules_from_doc(doc)

    new_entries = []
    pending_books_content: Optional[bytes] = None
    new_mapping_rules: Optional[Dict[str, Any]] = None
    mapping_meta: Dict[str, Any] = {}
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
                # Store raw content so a later Mapping upload can re-process
                await BOOKS_RAW.delete_many({"run_id": rid})
                await BOOKS_RAW.insert_one({
                    "run_id": rid,
                    "filename": entry["filename"],
                    "content_b64": base64.b64encode(gzip.compress(content)).decode("ascii"),
                    "size": len(content),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                })
                pending_books_content = content
                # Library integration — also save as books_json + pin to run.
                try:
                    firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
                    lib_books = await lib_svc.save_and_pin(
                        firm_id=firm_id, client_id=doc["client_id"],
                        period=doc.get("fy", ""), division=None,
                        file_type="books_json",
                        filename_original=entry["filename"], content=content,
                        uploaded_by_email=user.get("email") or "", run_id=rid,
                        parse_status="success",
                    )
                    pinned = doc.get("pinned_files") or {}
                    pinned["books_json"] = lib_books["file_id"]
                    await COLL.update_one(
                        {"id": rid},
                        {"$set": {"module": "gst_recon", "pinned_files": pinned,
                                  "firm_id": firm_id}},
                    )
                    doc["pinned_files"] = pinned
                except Exception:
                    pass
        if entry["bucket"] == "mapping" and meta.get("integrity_ok"):
            parsed = parse_ledger_mapping(content)
            if parsed.get("error"):
                entry["parse_error"] = parsed["error"]
                entry["integrity_ok"] = False
            else:
                # Serialise sets → sorted lists for Mongo
                new_mapping_rules = {k: sorted(v) for k, v in parsed["rules"].items()}
                mapping_meta = {
                    "mapping_unmapped_ledgers": parsed["unmapped_candidates"],
                    "mapping_row_count": parsed["row_count"],
                    "mapping_filename": entry["filename"],
                }
                entry["mapping_rules_counts"] = {k: len(v) for k, v in parsed["rules"].items()}
                entry["mapping_unmapped"] = len(parsed["unmapped_candidates"])
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

    # Resolve which mapping rules to use for Books aggregation:
    #   - new mapping this batch? → use the fresh rules
    #   - otherwise → fall back to rules previously stored on the run
    active_rules_sets: Optional[Dict[str, set]] = None
    if new_mapping_rules is not None:
        active_rules_sets = {k: set(v) for k, v in new_mapping_rules.items()}
    elif existing_rules:
        active_rules_sets = existing_rules

    # Re-aggregate Books if we have both rules and content (either newly uploaded or from disk)
    if active_rules_sets:
        books_content = pending_books_content or await _load_books_content(rid)
        if books_content:
            await _reprocess_books(rid, books_content, active_rules_sets, all_files)

    months = build_month_grid(doc.get("fy", ""), all_files)
    has_books = any(x["bucket"] == "books" for x in all_files)
    has_mapping = any(x["bucket"] == "mapping" for x in all_files)

    set_fields: Dict[str, Any] = {
        "files": all_files,
        "months": months,
        "has_books": has_books,
        "has_mapping": has_mapping,
    }
    if new_mapping_rules is not None:
        set_fields["mapping_rules"] = new_mapping_rules
        set_fields.update(mapping_meta)

    await COLL.update_one({"id": rid}, {"$set": set_fields})

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
        "mapping_unmapped_ledgers": mapping_meta.get("mapping_unmapped_ledgers", []),
        "books_reprocessed": bool(active_rules_sets and (pending_books_content is not None or new_mapping_rules is not None)),
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
    # Release 4.5 — append-only generations log
    try:
        await append_generation(
            run_id=rid, module="gst_recon",
            client_id=doc.get("client_id"),
            period=doc.get("fy"),
            generated_by_email=None,
            pinned_files_snapshot=doc.get("pinned_files") or {},
            summary_snapshot={"summary": summary or {}},
        )
    except Exception:
        pass
    return summary


@router.get("/runs/{rid}/generations")
async def gst_generations(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await _auth(request, session_token, authorization)
    run = await COLL.find_one({"id": rid}, {"_id": 0, "id": 1, "collapsed_into": 1})
    if not run:
        raise HTTPException(404, "Run not found")
    canonical_id = run.get("collapsed_into") or run.get("id") or rid
    rows = await list_generations(canonical_id)
    return {"run_id": canonical_id, "generations": rows}


@router.post("/runs/{rid}/match")
async def compute_match(
    rid: str,
    request: Request,
    period: str,
    direction: str = "outward",
    relaxed: bool = False,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase D: voucher-level matching for one (period, direction) pair.

    direction='outward' → Books-Sales ↔ GSTR-1
    direction='inward'  → Books-Purchase ↔ GSTR-2B
    relaxed=true        → Pass 3 (same gstin+period+total) auto-matches
                          residual transactions where bill #s and dates differ.

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
    return match_invoices(books, portal, relaxed=relaxed)


@router.post("/runs/{rid}/match-party")
async def compute_match_party(
    rid: str,
    request: Request,
    party_gstin: str,
    direction: str = "inward",
    relaxed: bool = True,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Whole-year voucher-level matching for ONE party.

    Loads all 12 months of books and portal vouchers for the given party_gstin
    and direction, then runs the same 3-pass matching engine. Useful when a CA
    wants to drill into a single supplier's full annual variance.
    """
    await _auth(request, session_token, authorization)
    if direction not in ("outward", "inward"):
        raise HTTPException(400, "direction must be 'outward' or 'inward'")
    if not party_gstin:
        raise HTTPException(400, "party_gstin is required")
    doc = await COLL.find_one({"id": rid}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(404, "Run not found")
    portal_src = "gstr1" if direction == "outward" else "gstr2b"
    books = await INV.find(
        {"run_id": rid, "source": "books", "direction": direction, "party_gstin": party_gstin},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(20000)
    portal = await INV.find(
        {"run_id": rid, "source": portal_src, "party_gstin": party_gstin},
        {"_id": 0, "run_id": 0, "source": 0},
    ).to_list(20000)
    return match_invoices(books, portal, relaxed=relaxed)


@router.get("/runs/{rid}/partywise")
async def get_partywise(
    rid: str,
    request: Request,
    direction: str = "inward",
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Annual Party-wise Summary — group voucher records by party_gstin
    across all months, return Books vs Portal totals per party with variance.
    direction='outward' (Books vs GSTR-1) | 'inward' (Books vs GSTR-2B)
    """
    await _auth(request, session_token, authorization)
    if direction not in ("outward", "inward"):
        raise HTTPException(400, "direction must be 'outward' or 'inward'")
    doc = await COLL.find_one({"id": rid}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(404, "Run not found")
    return await _build_partywise(rid, direction)



@router.get("/runs/{rid}/export.xlsx")
async def export_workbook(
    rid: str,
    request: Request,
    relaxed: bool = False,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Audit working-paper export — multi-sheet XLSX with Dashboard, 12-month
    summary, voucher-level matches per direction, Pending Classification, and
    run metadata. The sheet matches the on-screen layout 1:1 so the file can
    be saved directly to the audit working-paper folder."""
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")

    # Make sure the latest summary is on the doc; recompute on the fly if missing
    summary = doc.get("summary")
    if not summary:
        summary = build_summary(doc)
        await COLL.update_one({"id": rid}, {"$set": {"summary": summary, "status": "summarized"}})

    # Run match_invoices per (period, direction) — only for periods that have
    # at least one party-GSTIN-bearing voucher on either side
    rows = summary.get("rows", [])
    outward_matches: Dict[str, Dict[str, Any]] = {}
    inward_matches: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        period = row["period"]
        label = row["month_label"]
        # Outward
        b_out = await INV.find(
            {"run_id": rid, "source": "books", "period": period, "direction": "outward"},
            {"_id": 0, "run_id": 0, "source": 0},
        ).to_list(20000)
        p_out = await INV.find(
            {"run_id": rid, "source": "gstr1", "period": period},
            {"_id": 0, "run_id": 0, "source": 0},
        ).to_list(20000)
        if b_out or p_out:
            outward_matches[label] = match_invoices(b_out, p_out, relaxed=relaxed)
        # Inward
        b_in = await INV.find(
            {"run_id": rid, "source": "books", "period": period, "direction": "inward"},
            {"_id": 0, "run_id": 0, "source": 0},
        ).to_list(20000)
        p_in = await INV.find(
            {"run_id": rid, "source": "gstr2b", "period": period},
            {"_id": 0, "run_id": 0, "source": 0},
        ).to_list(20000)
        if b_in or p_in:
            inward_matches[label] = match_invoices(b_in, p_in, relaxed=relaxed)

    # Annual Party-wise summary aggregates (both directions)
    partywise_outward = await _build_partywise(rid, "outward")
    partywise_inward = await _build_partywise(rid, "inward")

    xlsx_bytes = build_workbook(doc, summary, outward_matches, inward_matches,
                                partywise_outward, partywise_inward)
    suffix = "_relaxed" if relaxed else ""
    filename = f"GST_Recon_FY{doc.get('fy', '')}{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



@router.get("/runs/{rid}/working-paper.pdf")
async def export_working_paper_pdf(
    rid: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Signature-ready PDF working-paper for the audit file.

    Renders the Reconciliation Health dashboard, 12-month tables, and Annual
    Party-wise (top-15 by variance) into a single A4 PDF a CA can print or
    attach to the audit working-paper folder.
    """
    await _auth(request, session_token, authorization)
    doc = await COLL.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Run not found")

    summary = doc.get("summary")
    if not summary:
        summary = build_summary(doc)
        await COLL.update_one(
            {"id": rid}, {"$set": {"summary": summary, "status": "summarized"}}
        )

    partywise_outward = await _build_partywise(rid, "outward")
    partywise_inward = await _build_partywise(rid, "inward")

    client = await db.clients.find_one(
        {"client_id": doc.get("client_id")}, {"_id": 0}
    )

    pdf_bytes = build_pdf(doc, summary, partywise_outward, partywise_inward, client)
    fy = (doc.get("fy") or "").replace("-", "_")
    filename = (
        f"GST_Recon_WorkingPaper_FY{fy}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
