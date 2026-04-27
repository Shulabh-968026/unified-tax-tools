"""Runs router — workspace-shared. Records created_by + generated_by attribution."""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Cookie, Header, Query
from pydantic import BaseModel, Field

from core.db import db
from modules.auth.controller import get_current_user
from modules.clause44.service import (
    parse_ledger_xlsx, build_group_chain, compute_suggestions,
    determine_expenditure_ledgers, classify_vouchers,
    compute_recon_and_filter, merge_runs_for_consolidation,
    is_valid_period,
)
from modules.clause44.exports import build_export_response

router = APIRouter()


class GenerateRequest(BaseModel):
    itc_ledgers: List[str] = Field(default_factory=list)
    excluded_ledgers: List[str] = Field(default_factory=list)


async def _fetch_run(run_id: str) -> Dict[str, Any]:
    run = await db.runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs")
async def upload_run(
    request: Request,
    accounting_json: UploadFile = File(...),
    ledger_xlsx: UploadFile = File(...),
    client_id: str = Form(...),
    period: str = Form(...),
    division_id: Optional[str] = Form(default=None),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)

    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(status_code=404, detail="Client not found")
    division_name = None
    if cli.get("type") == "multi":
        if not division_id:
            raise HTTPException(status_code=400, detail="division_id required for multi-division client")
        match = next((d for d in (cli.get("divisions") or []) if d.get("division_id") == division_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Division not found in client")
        division_name = match["name"]
    else:
        division_id = None

    period = (period or "").strip()
    if not is_valid_period(period):
        raise HTTPException(
            status_code=400,
            detail="Invalid period format. Use formats like '2023-24', 'FY 2023-24', 'Q1 2023-24', 'H1 2024-25'.",
        )

    try:
        accounting = json.loads((await accounting_json.read()).decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    try:
        ledgers_xlsx = parse_ledger_xlsx(await ledger_xlsx.read())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse Excel: {e}")

    suggestions = compute_suggestions(ledgers_xlsx, accounting.get("ledgers", []))
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    company_name = (accounting.get("company") or {}).get("name", accounting_json.filename)

    doc = {
        "run_id": run_id,
        "user_id": user["user_id"],                  # legacy
        "created_by_user_id": user["user_id"],
        "created_by_name": user.get("name") or user.get("email"),
        "created_by_email": user.get("email"),
        "client_id": client_id,
        "client_name": cli.get("name"),
        "client_file_number": cli.get("file_number"),
        "client_type": cli.get("type"),
        "period": period,
        "division_id": division_id,
        "division_name": division_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archived": False,
        "json_filename": accounting_json.filename,
        "xlsx_filename": ledger_xlsx.filename,
        "company_name": company_name,
        "accounting": accounting,
        "ledgers_xlsx": ledgers_xlsx,
        "itc_candidates": suggestions["itc_candidates"],
        "pl_ledgers": suggestions["pl_ledgers"],
        "generated": False,
    }
    await db.runs.insert_one(doc)

    return {
        "run_id": run_id,
        "client_id": client_id,
        "period": period,
        "division_id": division_id,
        "division_name": division_name,
        "company_name": company_name,
        "vouchers_count": len(accounting.get("vouchers", [])),
        "ledgers_count": len(accounting.get("ledgers", [])),
        "itc_candidates": suggestions["itc_candidates"],
        "pl_ledgers": suggestions["pl_ledgers"],
    }


@router.get("/runs")
async def list_runs(
    request: Request,
    archived: bool = Query(False),
    client_id: Optional[str] = Query(default=None),
    period: Optional[str] = Query(default=None),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    q: Dict[str, Any] = {"archived": archived}
    if client_id:
        q["client_id"] = client_id
    if period:
        q["period"] = period
    cursor = db.runs.find(
        q,
        {"_id": 0, "accounting": 0, "ledgers_xlsx": 0, "transactions": 0, "by_ledger": 0},
    ).sort("created_at", -1)
    runs = await cursor.to_list(500)
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)
    return {
        "run_id": run["run_id"],
        "created_at": run["created_at"],
        "created_by_name": run.get("created_by_name"),
        "created_by_email": run.get("created_by_email"),
        "archived": run.get("archived", False),
        "client_id": run.get("client_id"),
        "client_name": run.get("client_name"),
        "client_file_number": run.get("client_file_number"),
        "client_type": run.get("client_type"),
        "period": run.get("period"),
        "division_id": run.get("division_id"),
        "division_name": run.get("division_name"),
        "company_name": run.get("company_name"),
        "json_filename": run.get("json_filename"),
        "xlsx_filename": run.get("xlsx_filename"),
        "vouchers_count": len(run.get("accounting", {}).get("vouchers", [])),
        "ledgers_count": len(run.get("accounting", {}).get("ledgers", [])),
        "itc_candidates": run.get("itc_candidates", []),
        "pl_ledgers": run.get("pl_ledgers", []),
        "generated": run.get("generated", False),
        "generated_at": run.get("generated_at"),
        "generated_by_name": run.get("generated_by_name"),
        "generated_by_email": run.get("generated_by_email"),
        "summary": run.get("summary"),
        "by_ledger": run.get("by_ledger"),
        "recon": run.get("recon"),
        "itc_selection": run.get("itc_selection", []),
        "exclusion_selection": run.get("exclusion_selection", []),
    }


@router.post("/runs/{run_id}/generate")
async def generate_run(
    run_id: str,
    body: GenerateRequest,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)

    accounting = run.get("accounting", {}) or {}
    ledgers_xlsx = run.get("ledgers_xlsx", {}) or {}
    ledgers_json = accounting.get("ledgers", []) or []
    vouchers = accounting.get("vouchers", []) or []
    groups = accounting.get("groups", []) or []

    excluded = set(body.excluded_ledgers or [])
    itc_set = set(body.itc_ledgers or [])

    group_chains = build_group_chain(groups)
    full_exp_ledgers = determine_expenditure_ledgers(ledgers_xlsx, ledgers_json, group_chains, set())
    party_lookup = {l.get("name", ""): l for l in ledgers_json}

    full_result = classify_vouchers(vouchers, full_exp_ledgers, itc_set, party_lookup)
    final = compute_recon_and_filter(full_result, excluded)

    await db.runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "generated": True,
            "itc_selection": list(itc_set),
            "exclusion_selection": list(excluded),
            "summary": final["summary"],
            "by_ledger": final["by_ledger"],
            "transactions": final["transactions"],
            "recon": final["recon"],
            "expenditure_ledgers": list(full_exp_ledgers.keys()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by_user_id": user["user_id"],
            "generated_by_name": user.get("name") or user.get("email"),
            "generated_by_email": user.get("email"),
        }},
    )
    return {
        "run_id": run_id,
        "summary": final["summary"],
        "by_ledger": final["by_ledger"],
        "recon": final["recon"],
        "transactions_count": len(final["transactions"]),
    }


@router.get("/runs/{run_id}/transactions")
async def get_transactions(
    run_id: str,
    request: Request,
    bucket: Optional[str] = Query(default=None, pattern="^(col2|col3|col4|col5|col6|col7|all)$"),
    ledger: Optional[str] = Query(default=None),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)
    txns = run.get("transactions", []) or []
    if bucket and bucket not in ("all", "col2", "col6"):
        txns = [t for t in txns if t["bucket"] == bucket]
    elif bucket == "col6":
        txns = [t for t in txns if t["bucket"] in ("col3", "col4", "col5")]
    if ledger:
        txns = [t for t in txns if t["ledger_name"] == ledger]
    return {"run_id": run_id, "bucket": bucket or "all", "ledger": ledger, "transactions": txns}


@router.post("/runs/{run_id}/archive")
async def archive_run(
    run_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)
    new_state = not run.get("archived", False)
    await db.runs.update_one({"run_id": run_id}, {"$set": {"archived": new_state}})
    return {"run_id": run_id, "archived": new_state}


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)
    if not run.get("generated"):
        raise HTTPException(status_code=400, detail="Run not generated yet")
    company = (run.get("company_name") or "Clause44").replace(" ", "_")[:50]
    return build_export_response(run, f"Clause44_{company}_{run_id}")


@router.get("/clients/{client_id}/consolidated")
async def get_consolidated(
    client_id: str,
    request: Request,
    period: str = Query(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(status_code=404, detail="Client not found")
    runs = await db.runs.find(
        {"client_id": client_id, "period": period, "generated": True},
        {"_id": 0, "accounting": 0, "ledgers_xlsx": 0},
    ).to_list(500)
    if not runs:
        raise HTTPException(status_code=404, detail="No generated runs for this client/period")
    merged = merge_runs_for_consolidation(runs)
    return {
        "client_id": client_id,
        "client_name": cli.get("name"),
        "client_file_number": cli.get("file_number"),
        "period": period,
        "client_type": cli.get("type"),
        "divisions": cli.get("divisions", []),
        **merged,
    }


@router.get("/clients/{client_id}/consolidated/export")
async def export_consolidated(
    client_id: str,
    request: Request,
    period: str = Query(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(status_code=404, detail="Client not found")
    runs = await db.runs.find(
        {"client_id": client_id, "period": period, "generated": True},
        {"_id": 0, "accounting": 0, "ledgers_xlsx": 0},
    ).to_list(500)
    if not runs:
        raise HTTPException(status_code=404, detail="No generated runs for this client/period")
    merged = merge_runs_for_consolidation(runs)
    pseudo = {
        "company_name": f"{cli.get('name')} (Consolidated · {period})",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **merged,
        "generated": True,
    }
    safe = (cli.get("name") or "client").replace(" ", "_")[:40]
    return build_export_response(pseudo, f"Clause44_{safe}_Consolidated_{period}")
