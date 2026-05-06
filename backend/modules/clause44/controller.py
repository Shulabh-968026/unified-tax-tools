"""Runs router — workspace-shared. Records created_by + generated_by attribution."""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Cookie, Header, Query
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from core.db import db
from modules.auth.controller import get_current_user
from modules.clause44.service import (
    parse_ledger_xlsx, build_group_chain, compute_suggestions, compute_pools,
    determine_expenditure_ledgers, classify_vouchers,
    compute_recon_and_filter, merge_runs_for_consolidation,
    is_valid_period,
)
from modules.clause44.exports import build_export_response

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────
_COMMON_SUFFIXES = re.compile(
    r"\b(p\.?|pvt\.?|private|ltd\.?|limited|llp|co\.?|company|inc\.?|corp\.?|corporation|and|&)\b",
    re.IGNORECASE,
)


def _extract_company_name(accounting: Dict[str, Any]) -> str:
    """Pull a company name out of the uploaded books JSON — tolerating both the
    Tally/legacy `company.name` and the newer `company.companyName` key."""
    comp = accounting.get("company") or {}
    if not isinstance(comp, dict):
        return ""
    for key in ("name", "companyName", "company_name"):
        v = comp.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _normalise_name(s: str) -> str:
    """Lower-case + strip corporate suffixes + collapse whitespace for a
    tolerant fuzzy-match baseline (so 'Velav Garments India P Ltd' ≈
    'Velav Garments India Private Limited')."""
    s = (s or "").lower()
    s = _COMMON_SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return " ".join(s.split())


def _company_names_match(client_name: str, books_name: str) -> bool:
    """Return True if the books company clearly belongs to this client file.

    Strategy: normalise both names (drop common corporate suffixes) and
    require ≥ 80 on token-sort-ratio. Empty `books_name` is allowed (we can't
    verify what isn't there) — the hard block only fires on a confident
    mismatch. Empty `client_name` is also allowed (shouldn't happen but
    don't block).
    """
    if not books_name or not client_name:
        return True
    a = _normalise_name(client_name)
    b = _normalise_name(books_name)
    if not a or not b:
        return True
    # Token-set handles word-order + extra words; token-sort guards against
    # one name being a proper subset of the other. Pick the best.
    score = max(fuzz.token_set_ratio(a, b), fuzz.token_sort_ratio(a, b))
    return score >= 80


class GenerateRequest(BaseModel):
    itc_ledgers: List[str] = Field(default_factory=list)
    excluded_ledgers: List[str] = Field(default_factory=list)
    exempt_ledgers: List[str] = Field(default_factory=list)
    use_itc_inference: bool = True
    exclusion_categories: Dict[str, str] = Field(default_factory=dict)
    disclaimer_text: Optional[str] = None


async def _fetch_run(run_id: str) -> Dict[str, Any]:
    run = await db.runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # Release 4.5 — silent redirect for collapsed/archived run_ids.  When
    # an old link points to a doc that was archived during the
    # canonical-collapse migration, transparently re-route to its winner.
    if run.get("archived") and run.get("collapsed_into"):
        winner = await db.runs.find_one({"run_id": run["collapsed_into"]}, {"_id": 0})
        if winner:
            return winner
    return run


# ─────────────────────────────────────────────────────────────────────────
# Default boilerplate disclaimer — shipped on every fresh run, editable by
# the auditor per choice 8B.  Stored on the run document once the auditor
# first opens the report step.
# ─────────────────────────────────────────────────────────────────────────
DEFAULT_DISCLAIMER = (
    "The classification of expenditure under Clause 44 is based solely on "
    "the books of account maintained by the entity.  Where the records do "
    "not capture nature of supply, supplier registration status, or "
    "bill-of-supply indicators, the classification relies on (a) purchase "
    "ledgers internally designated by the entity as exempt-supply ledgers, "
    "and (b) where applicable, the absence of an ITC-input ledger on a "
    "registered-vendor voucher as a presumptive marker of exempt supply — "
    "both as adopted and affirmed by management.  RCM vouchers and "
    "purchases from foreign suppliers are reported under Column 7.  The "
    "entity confirms that the data made available is a true and complete "
    "extract of its books for the relevant financial year, and any "
    "limitations arising from incomplete or absent GST-specific attributes "
    "in the underlying records are acknowledged by management.  "
    "(Ref: ICAI Guidance Note on Tax Audit, Para 79.20 / 79.21.)"
)


def _run_classification(run: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run the Clause 44 engine against a run's persisted selections
    (used for both initial generate and silent re-classification on GET).
    """
    accounting = run.get("accounting", {}) or {}
    ledgers_xlsx = run.get("ledgers_xlsx", {}) or {}
    ledgers_json = accounting.get("ledgers", []) or []
    vouchers = accounting.get("vouchers", []) or []
    groups = accounting.get("groups", []) or []

    excluded = set(run.get("exclusion_selection") or [])
    itc_set = set(run.get("itc_selection") or [])
    exempt_set = set(run.get("exempt_selection") or [])
    use_itc_inf = run.get("use_itc_inference", True)
    exclusion_categories = run.get("exclusion_categories") or {}

    group_chains = build_group_chain(groups)
    full_exp_ledgers = determine_expenditure_ledgers(ledgers_xlsx, ledgers_json, group_chains, set())
    party_lookup = {l.get("name", ""): l for l in ledgers_json}

    full_result = classify_vouchers(
        vouchers, full_exp_ledgers, itc_set, party_lookup,
        exempt_ledgers=exempt_set,
        excluded_ledgers=excluded,
        use_itc_inference=use_itc_inf,
    )
    return compute_recon_and_filter(
        full_result, excluded,
        ledgers_xlsx=ledgers_xlsx,
        group_chains=group_chains,
        exclusion_categories=exclusion_categories,
    )


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

    # Guard against the classic "wrong books uploaded into wrong file"
    # mistake — if the JSON declares a company name and it clearly doesn't
    # belong to this client, abort early so a run for "ABC Textile Mills"
    # can't slip inside the "Velav Garments" file.
    books_company = _extract_company_name(accounting)
    if books_company and not _company_names_match(cli.get("name", ""), books_company):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The uploaded books belong to “{books_company}”, but this "
                f"file is for “{cli.get('name')}”. Please open the correct "
                f"client file or upload the matching books."
            ),
        )

    try:
        ledgers_xlsx = parse_ledger_xlsx(await ledger_xlsx.read())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse Excel: {e}")

    suggestions = compute_suggestions(
        ledgers_xlsx,
        accounting.get("ledgers", []),
        accounting.get("vouchers", []),
    )
    # ── Single-working-doc upsert (Release 4.5) ─────────────────────────
    # Look up an existing canonical doc; reuse its run_id so deep-links
    # stay stable.  Unpin its prior Library pins so old file versions
    # become eligible for the prune job.
    existing = await db.runs.find_one(
        {
            "module": "clause44",
            "client_id": client_id,
            "period": period,
            "division_id": division_id,
            "archived": False,
        },
        {"_id": 0, "run_id": 1, "pinned_files": 1},
    )
    if existing:
        run_id = existing["run_id"]
        for fid in (existing.get("pinned_files") or {}).values():
            if fid:
                try:
                    await lib_svc.unpin_file_from_run(fid, run_id)
                except Exception:
                    pass
    else:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
    company_name = books_company or accounting_json.filename

    # Library integration (Release 4.0) — save the two source files into
    # the Client Library and pin this run to the resulting versions.  The
    # raw bytes are no longer kept on the run document; we keep the
    # parsed `accounting` + `ledgers_xlsx` since downstream code consumes
    # those structures directly.
    from modules.library import service as lib_svc
    from modules.library.controller import DEFAULT_FIRM_ID

    firm_id = user.get("firm_id") or DEFAULT_FIRM_ID
    await accounting_json.seek(0)
    accounting_json_bytes = await accounting_json.read()
    await ledger_xlsx.seek(0)
    ledger_xlsx_bytes = await ledger_xlsx.read()

    lib_books = await lib_svc.create_file_version(
        firm_id=firm_id, client_id=client_id, period=period,
        division=division_id, file_type="books_json",
        filename_original=accounting_json.filename or "books.json",
        content=accounting_json_bytes,
        uploaded_by_email=user.get("email") or "",
        parse_status="success",
        parse_summary={
            "n_vouchers": len(accounting.get("vouchers", [])),
            "n_ledgers": len(accounting.get("ledgers", [])),
            "company_name": company_name,
        },
    )
    lib_xlsx = await lib_svc.create_file_version(
        firm_id=firm_id, client_id=client_id, period=period,
        division=division_id, file_type="ledger_mapping_xlsx",
        filename_original=ledger_xlsx.filename or "ledger_mapping.xlsx",
        content=ledger_xlsx_bytes,
        uploaded_by_email=user.get("email") or "",
        parse_status="success",
        parse_summary={"n_rows": len(ledgers_xlsx)},
    )
    pinned_files = {
        "books_json": lib_books["file_id"],
        "ledger_mapping_xlsx": lib_xlsx["file_id"],
    }
    await lib_svc.pin_file_to_run(lib_books["file_id"], run_id)
    await lib_svc.pin_file_to_run(lib_xlsx["file_id"], run_id)

    doc = {
        "run_id": run_id,
        "module": "clause44",                          # NEW · enables per-module library status lookup
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
        "pinned_files": pinned_files,                  # NEW · {file_type → file_id}
        "firm_id": firm_id,                            # NEW · forward-looking tenant key
    }
    # Upsert: replace any existing canonical working doc; preserve audit
    # fields if we're updating an existing one.  Selections / generated
    # flag are intentionally reset because the books were re-uploaded.
    await db.runs.replace_one(
        {"run_id": run_id}, doc, upsert=True,
    )

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
    # Recompute ITC / P&L suggestions on every GET so runs uploaded before a
    # classifier-policy change pick up the new behaviour without re-upload.
    ledgers_xlsx = run.get("ledgers_xlsx", {}) or {}
    accounting = run.get("accounting", {}) or {}
    suggestions = (compute_suggestions(ledgers_xlsx,
                                        accounting.get("ledgers", []),
                                        accounting.get("vouchers", []))
                   if ledgers_xlsx else
                   {"itc_candidates": run.get("itc_candidates", []),
                    "pl_ledgers":     run.get("pl_ledgers", [])})
    pools = (compute_pools(ledgers_xlsx,
                           accounting.get("ledgers", []),
                           accounting.get("vouchers", []))
             if ledgers_xlsx else
             {"exempt_ledgers": [], "itc_ledgers": [],
              "itc_ledgers_all_bs": [], "exclusion_ledgers": []})

    # Silent re-classification for generated runs (choice 7A) — opening an
    # old run reflects the *current* engine logic without forcing the
    # auditor to click Generate again.  We don't persist the re-classified
    # values; they're computed on demand and overwritten on the next
    # explicit Generate call.
    summary = run.get("summary")
    by_ledger = run.get("by_ledger")
    by_party = run.get("by_party")
    recon = run.get("recon")
    if run.get("generated"):
        try:
            fresh = _run_classification(run)
            summary = fresh["summary"]
            by_ledger = fresh["by_ledger"]
            by_party = fresh["by_party"]
            recon = fresh["recon"]
        except Exception:  # pragma: no cover — fall back to stored snapshot
            pass

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
        "itc_candidates": suggestions["itc_candidates"],
        "pl_ledgers":     suggestions["pl_ledgers"],
        # Release 4.4 — three-pool model used by the new ledger tables.
        "exempt_ledgers":     pools["exempt_ledgers"],
        "itc_ledgers":        pools["itc_ledgers"],
        "itc_ledgers_all_bs": pools["itc_ledgers_all_bs"],
        "exclusion_ledgers":  pools["exclusion_ledgers"],
        "generated": run.get("generated", False),
        "generated_at": run.get("generated_at"),
        "generated_by_name": run.get("generated_by_name"),
        "generated_by_email": run.get("generated_by_email"),
        "summary": summary,
        "by_ledger": by_ledger,
        "by_party": by_party,
        "recon": recon,
        "itc_selection": run.get("itc_selection", []),
        "exempt_selection": run.get("exempt_selection", []),
        "exclusion_selection": run.get("exclusion_selection", []),
        "exclusion_categories": run.get("exclusion_categories", {}),
        "use_itc_inference": run.get("use_itc_inference", True),
        "disclaimer_text": run.get("disclaimer_text", DEFAULT_DISCLAIMER),
        # Library integration — pinned versions + outdated check.
        "pinned_files": run.get("pinned_files") or {},
        "library_status": await _compute_library_status(run),
    }


async def _compute_library_status(run: dict) -> dict:
    """Wrap `library.service.compute_module_status` for a Clause 44 run."""
    try:
        from modules.library import service as lib_svc
        from modules.library.controller import DEFAULT_FIRM_ID
    except Exception:
        return {"outdated": False, "missing": False, "dependencies": []}
    return await lib_svc.compute_module_status(
        firm_id=run.get("firm_id") or DEFAULT_FIRM_ID,
        client_id=run["client_id"],
        period=run["period"],
        division=run.get("division_id"),
        module_key="clause44",
        pinned_files=run.get("pinned_files") or {},
    )


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

    itc_set = set(body.itc_ledgers or [])
    excluded = set(body.excluded_ledgers or [])
    exempt_set = set(body.exempt_ledgers or [])

    # Persist the selections onto the run doc first so `_run_classification`
    # reads them via the canonical path (keeps the GET-path and the
    # generate-path using identical inputs).
    run["itc_selection"] = list(itc_set)
    run["exempt_selection"] = list(exempt_set)
    run["exclusion_selection"] = list(excluded)
    run["use_itc_inference"] = bool(body.use_itc_inference)
    run["exclusion_categories"] = dict(body.exclusion_categories or {})

    final = _run_classification(run)

    update_doc = {
        "generated": True,
        "itc_selection": list(itc_set),
        "exempt_selection": list(exempt_set),
        "exclusion_selection": list(excluded),
        "use_itc_inference": bool(body.use_itc_inference),
        "exclusion_categories": dict(body.exclusion_categories or {}),
        "summary": final["summary"],
        "by_ledger": final["by_ledger"],
        "by_party": final["by_party"],
        "transactions": final["transactions"],
        "recon": final["recon"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by_user_id": user["user_id"],
        "generated_by_name": user.get("name") or user.get("email"),
        "generated_by_email": user.get("email"),
    }
    if body.disclaimer_text is not None:
        update_doc["disclaimer_text"] = body.disclaimer_text

    # Backfill Library tracking for legacy runs created before 4.0 — when
    # the auditor regenerates such a run, snapshot the current Library
    # versions of its dependencies into pinned_files so the catalog tile
    # flips to "Report Ready" and future re-uploads correctly trigger
    # the "Outdated" badge.
    if not run.get("pinned_files"):
        from modules.library import service as lib_svc
        from modules.library.controller import DEFAULT_FIRM_ID
        firm_id = run.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID
        snap: dict = {}
        for ft in ("books_json", "ledger_mapping_xlsx"):
            cur = await lib_svc.get_current_file(
                firm_id=firm_id, client_id=run["client_id"],
                period=run.get("period", ""),
                division=run.get("division_id"), file_type=ft,
            )
            if cur:
                snap[ft] = cur["file_id"]
                await lib_svc.pin_file_to_run(cur["file_id"], run_id)
        if snap:
            update_doc["pinned_files"] = snap
        update_doc["module"] = "clause44"
        update_doc["firm_id"] = firm_id

    await db.runs.update_one({"run_id": run_id}, {"$set": update_doc})

    # Release 4.5 — append-only generations log.  Records every Generate
    # action with totals + pinned-file snapshot for the History drawer.
    try:
        gen_id = f"gen_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{run_id[:8]}"
        await db.run_generations.insert_one({
            "gen_id": gen_id,
            "run_id": run_id,
            "module": "clause44",
            "client_id": run.get("client_id"),
            "period": run.get("period"),
            "division_id": run.get("division_id"),
            "generated_by_email": user.get("email"),
            "generated_at": update_doc["generated_at"],
            "pinned_files_snapshot": run.get("pinned_files") or update_doc.get("pinned_files") or {},
            "summary_snapshot": {
                "col_2_total": final["summary"].get("col_2_total"),
                "col_3_total": final["summary"].get("col_3_total"),
                "col_4_total": final["summary"].get("col_4_total"),
                "col_5_total": final["summary"].get("col_5_total"),
                "col_7_total": final["summary"].get("col_7_total"),
                "col_8_total": final["summary"].get("col_8_total"),
            },
        })
    except Exception:
        pass

    return {
        "run_id": run_id,
        "summary": final["summary"],
        "by_ledger": final["by_ledger"],
        "by_party": final["by_party"],
        "recon": final["recon"],
        "transactions_count": len(final["transactions"]),
    }


@router.post("/runs/{run_id}/rerun")
async def rerun(
    run_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Re-pin to the LATEST Library versions of this run's dependencies,
    re-parse them, then return the updated run (without re-running
    classification — the auditor still has to click Generate).

    Preserves: itc_selection, exempt_selection, exclusion_selection,
    use_itc_inference, exclusion_categories, disclaimer_text.
    Re-computes: accounting + ledgers_xlsx (re-parsed from latest blobs),
    itc_candidates, pl_ledgers.
    """
    user = await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)

    from modules.library import service as lib_svc
    from modules.library.controller import DEFAULT_FIRM_ID

    firm_id = run.get("firm_id") or user.get("firm_id") or DEFAULT_FIRM_ID

    # Resolve latest versions for every dep.
    latest_books = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=run["client_id"], period=run["period"],
        division=run.get("division_id"), file_type="books_json",
    )
    latest_xlsx = await lib_svc.get_current_file(
        firm_id=firm_id, client_id=run["client_id"], period=run["period"],
        division=run.get("division_id"), file_type="ledger_mapping_xlsx",
    )
    if not latest_books or not latest_xlsx:
        raise HTTPException(409, "Cannot rerun — Library is missing required files.")

    # Pull the bytes, re-parse.
    books_bytes = await lib_svc.read_file_bytes(latest_books["file_id"])
    xlsx_bytes = await lib_svc.read_file_bytes(latest_xlsx["file_id"])

    try:
        accounting = json.loads(books_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"Latest Books JSON failed to parse: {e}")
    try:
        ledgers_xlsx = parse_ledger_xlsx(xlsx_bytes)
    except Exception as e:
        raise HTTPException(400, f"Latest Ledger Mapping XLSX failed to parse: {e}")

    suggestions = compute_suggestions(
        ledgers_xlsx,
        accounting.get("ledgers", []),
        accounting.get("vouchers", []),
    )

    # Unpin OLD versions, pin the NEW ones.
    old_pinned = run.get("pinned_files") or {}
    for old_id in old_pinned.values():
        if old_id and old_id not in (latest_books["file_id"], latest_xlsx["file_id"]):
            await lib_svc.unpin_file_from_run(old_id, run_id)
    await lib_svc.pin_file_to_run(latest_books["file_id"], run_id)
    await lib_svc.pin_file_to_run(latest_xlsx["file_id"], run_id)

    update_doc = {
        "accounting": accounting,
        "ledgers_xlsx": ledgers_xlsx,
        "itc_candidates": suggestions["itc_candidates"],
        "pl_ledgers": suggestions["pl_ledgers"],
        "json_filename": latest_books["filename_original"],
        "xlsx_filename": latest_xlsx["filename_original"],
        "pinned_files": {
            "books_json": latest_books["file_id"],
            "ledger_mapping_xlsx": latest_xlsx["file_id"],
        },
        "firm_id": firm_id,
        # Reset the "generated" flag so the UI prompts the auditor to
        # click Generate (the morphing button) explicitly — we never
        # silently update numbers.
        "generated": False,
        "rerun_at": datetime.now(timezone.utc).isoformat(),
        "rerun_by_email": user.get("email"),
    }
    await db.runs.update_one({"run_id": run_id}, {"$set": update_doc})
    return {
        "run_id": run_id,
        "rerun": True,
        "vouchers_count": len(accounting.get("vouchers", [])),
        "ledgers_count": len(accounting.get("ledgers", [])),
        "pinned_files": update_doc["pinned_files"],
    }


class SelectionsRequest(BaseModel):
    itc_ledgers: Optional[List[str]] = None
    excluded_ledgers: Optional[List[str]] = None
    exempt_ledgers: Optional[List[str]] = None
    use_itc_inference: Optional[bool] = None
    exclusion_categories: Optional[Dict[str, str]] = None
    disclaimer_text: Optional[str] = None


@router.patch("/runs/{run_id}/selections")
async def save_selections(
    run_id: str,
    body: SelectionsRequest,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Persist any subset of the stepper selections across navigation —
    without running classification.  Each stepper "Proceed" calls this so
    going Back does not lose state.
    """
    await get_current_user(request, session_token, authorization)
    await _fetch_run(run_id)
    update: Dict[str, Any] = {}
    if body.itc_ledgers is not None:
        update["itc_selection"] = list(set(body.itc_ledgers))
    if body.excluded_ledgers is not None:
        update["exclusion_selection"] = list(set(body.excluded_ledgers))
    if body.exempt_ledgers is not None:
        update["exempt_selection"] = list(set(body.exempt_ledgers))
    if body.use_itc_inference is not None:
        update["use_itc_inference"] = bool(body.use_itc_inference)
    if body.exclusion_categories is not None:
        update["exclusion_categories"] = dict(body.exclusion_categories)
    if body.disclaimer_text is not None:
        update["disclaimer_text"] = body.disclaimer_text

    # Live rebucket — when the auditor changes one or more
    # `exclusion_categories` overrides, recompute the recon block from the
    # persisted run state so the UI / Excel export reflect the change
    # without requiring a full Generate.  Cheap: no voucher reclassifying,
    # just re-bucketing already-classified excluded ledgers.
    fresh_recon = None
    if body.exclusion_categories is not None:
        run = await db.runs.find_one(
            {"run_id": run_id},
            {"_id": 0, "by_ledger": 1, "by_party": 1, "summary": 1,
             "transactions": 1, "ledgers_xlsx": 1, "accounting": 1},
        )
        if run and run.get("by_ledger"):
            from modules.clause44.service import (
                build_group_chain, compute_recon_and_filter,
            )
            ledgers_xlsx = run.get("ledgers_xlsx") or {}
            groups = (run.get("accounting") or {}).get("groups", [])
            group_chains = build_group_chain(groups)
            full_result = {
                "by_ledger":    run["by_ledger"],
                "by_party":     run.get("by_party") or {},
                "summary":      run.get("summary") or {},
                "transactions": run.get("transactions") or [],
            }
            recon_payload = compute_recon_and_filter(
                full_result,
                set(update.get("exclusion_selection")
                    or (await db.runs.find_one({"run_id": run_id}, {"_id": 0, "exclusion_selection": 1}) or {}).get("exclusion_selection") or []),
                ledgers_xlsx=ledgers_xlsx,
                group_chains=group_chains,
                exclusion_categories=update["exclusion_categories"],
            )
            fresh_recon = recon_payload["recon"]
            update["recon"] = fresh_recon
    if not update:
        return {"run_id": run_id, "saved": False}
    update["last_selections_saved_at"] = datetime.now(timezone.utc).isoformat()
    await db.runs.update_one({"run_id": run_id}, {"$set": update})
    resp: Dict[str, Any] = {"run_id": run_id, "saved": True}
    # Echo the persisted scalars (lists / dicts) so the client can reuse
    # them without an extra GET — but not the heavy by_ledger blob.
    for k, v in update.items():
        if k in ("itc_selection", "exclusion_selection", "exempt_selection",
                 "use_itc_inference", "exclusion_categories",
                 "disclaimer_text", "last_selections_saved_at", "recon"):
            resp[k] = v
    return resp


@router.get("/runs/{run_id}/transactions")
async def get_transactions(
    run_id: str,
    request: Request,
    bucket: Optional[str] = Query(default=None, pattern="^(col2|col3|col4|col5|col6|col7|col8|all)$"),
    ledger: Optional[str] = Query(default=None),
    party: Optional[str] = Query(default=None),
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
    if party:
        # "— Cash / No Party —" is the synthetic bucket for empty party names.
        if party == "— Cash / No Party —":
            txns = [t for t in txns if not (t.get("party_name") or "")]
        else:
            txns = [t for t in txns if t.get("party_name") == party]
    return {"run_id": run_id, "bucket": bucket or "all", "ledger": ledger, "party": party, "transactions": txns}



@router.get("/runs/{run_id}/generations")
async def list_generations(
    run_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Append-only history of Generate actions on this working doc.
    Used by the History drawer; small payload (no transactions / no
    by_ledger).  Newest first."""
    await get_current_user(request, session_token, authorization)
    run = await _fetch_run(run_id)
    canonical_id = run.get("run_id") or run_id
    rows = await db.run_generations.find(
        {"run_id": canonical_id},
        {"_id": 0},
    ).sort("generated_at", -1).to_list(length=200)
    return {"run_id": canonical_id, "generations": rows}


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
