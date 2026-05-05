"""Client Library HTTP API — `/api/library/...`

Endpoints
---------

  POST   /upload                           multipart upload, creates new version
  GET    /clients/{client_id}/status       file-type chips + per-module status
  GET    /clients/{client_id}/files        all versions (active + soft-deleted)
  GET    /files/{file_id}                  metadata
  GET    /files/{file_id}/download         raw bytes
  DELETE /files/{file_id}                  soft-delete (rejects pinned versions)
  POST   /files/{file_id}/restore          undo soft-delete (within 30-day grace)
  POST   /admin/prune-expired              hard-delete soft-deleted past grace
  GET    /catalog                          file-type catalog (UI lookup)

All routes are session-gated.  `firm_id` is currently a hard-coded
single-tenant value (`firm_mss_001`) — when Transform's multi-tenant
work lands, it'll be derived from `user["firm_id"]` and the rest of
this module won't change.
"""
from __future__ import annotations

import io
from typing import Optional

from fastapi import (
    APIRouter, Cookie, File, Form, Header, HTTPException, Request, UploadFile,
)
from fastapi.responses import StreamingResponse

from core.db import db
from modules.auth.controller import get_current_user
from modules.library import service as svc
from modules.library.catalog import (
    FILE_TYPE_BY_KEY, FILE_TYPE_CATALOG, FILE_TYPE_KEYS,
)

# Until multi-tenant work lands, every user's firm is the same.
DEFAULT_FIRM_ID = "firm_mss_001"

router = APIRouter(prefix="/library", tags=["library"])


def _firm_id_for(user: dict) -> str:
    return user.get("firm_id") or DEFAULT_FIRM_ID


def _validate_extension(file_type: str, filename: str):
    ft = FILE_TYPE_BY_KEY.get(file_type)
    if not ft:
        raise HTTPException(400, f"Unknown file_type '{file_type}'")
    name = filename.lower()
    if not any(name.endswith(ext) for ext in ft["ext"]):
        raise HTTPException(
            400,
            f"{ft['label']} expects extension {ft['ext']}, got '{filename}'.",
        )


# ---------------------------------------------------------------------------
@router.get("/catalog")
async def get_catalog(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Return the file-type catalog so the UI can render upload tiles."""
    await get_current_user(request, session_token, authorization)
    from modules.library.catalog import FILE_TYPES_WITH_TEMPLATES
    enriched = [{**ft, "has_template": ft["key"] in FILE_TYPES_WITH_TEMPLATES} for ft in FILE_TYPE_CATALOG]
    return {"file_types": enriched}


# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    period: str = Form(...),
    division: Optional[str] = Form(default=None),
    file_type: str = Form(...),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Create a new version of `file_type` for `(client, period, division)`.

    Returns the persisted file row.  If the upload's checksum matches the
    current version, returns the existing row (idempotent).
    """
    user = await get_current_user(request, session_token, authorization)
    firm_id = _firm_id_for(user)

    # Sanity: the client must exist.
    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(404, "Client not found")

    # Multi-division clients require an explicit division (matches the
    # Clause 44 upload path's contract).
    if cli.get("type") == "multi" and not division:
        # Allow division = null when the file is engagement-wide
        # (e.g. consolidated 26AS).  We don't enforce here — UI
        # decides per file-type.
        pass

    if file_type not in FILE_TYPE_KEYS:
        raise HTTPException(400, f"Unknown file_type '{file_type}'")
    _validate_extension(file_type, file.filename or "")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    row = await svc.create_file_version(
        firm_id=firm_id,
        client_id=client_id,
        period=period,
        division=division,
        file_type=file_type,
        filename_original=file.filename or "unnamed",
        content=content,
        uploaded_by_email=user.get("email") or "",
    )
    return {"file": row}


# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/status")
async def get_status(
    client_id: str,
    request: Request,
    period: str,
    division: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """File-type chips + per-module status for ONE engagement window.

    Powers BOTH the ClientHome Library panel and the 9-tile module
    catalog badges in a single round-trip.
    """
    user = await get_current_user(request, session_token, authorization)
    firm_id = _firm_id_for(user)

    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(404, "Client not found")

    return await svc.compute_client_status(
        firm_id=firm_id, client_id=client_id, period=period, division=division,
    )


# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/template/{file_type}")
async def download_template(
    client_id: str,
    file_type: str,
    request: Request,
    period: str,
    division: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Generate and stream a pre-populated template for `file_type`.

    The auditor downloads, fills in the gaps offline, and re-uploads via
    the standard upload endpoint.  Only file_types in
    `FILE_TYPES_WITH_TEMPLATES` are supported — others 404.
    """
    user = await get_current_user(request, session_token, authorization)
    firm_id = _firm_id_for(user)

    if file_type not in FILE_TYPE_KEYS:
        raise HTTPException(400, f"Unknown file_type '{file_type}'")

    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(404, "Client not found")

    from modules.library.templates import generate_template, has_template as _has_t
    if not _has_t(file_type):
        raise HTTPException(404, f"No template available for '{file_type}' yet.")

    try:
        blob, filename = await generate_template(
            file_type=file_type, firm_id=firm_id, client_id=client_id,
            period=period, division=division,
        )
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))

    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/files")
async def list_client_files(
    client_id: str,
    request: Request,
    period: Optional[str] = None,
    include_deleted: bool = False,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """All versions for a client (optionally filtered to one period)."""
    user = await get_current_user(request, session_token, authorization)
    firm_id = _firm_id_for(user)
    rows = await svc.list_files_for_client(
        firm_id=firm_id, client_id=client_id, period=period,
        include_soft_deleted=include_deleted,
    )
    return {"files": rows}


# ---------------------------------------------------------------------------
@router.get("/files/{file_id}")
async def get_file_metadata(
    file_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    f = await svc.get_file(file_id)
    if not f:
        raise HTTPException(404, "File not found")
    return {"file": f}


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    f = await svc.get_file(file_id)
    if not f:
        raise HTTPException(404, "File not found")
    try:
        data = await svc.read_file_bytes(file_id)
    except FileNotFoundError:
        raise HTTPException(410, "Blob no longer on disk (post-grace prune)")
    media = "application/json" if f["filename_original"].lower().endswith(".json") else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if f["filename_original"].lower().endswith(".xlsx") else "application/octet-stream"
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{f["filename_original"]}"'},
    )


# ---------------------------------------------------------------------------
@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Soft-delete (30-day grace).  Pinned versions cannot be deleted."""
    await get_current_user(request, session_token, authorization)
    try:
        row = await svc.soft_delete(file_id)
        return {"file": row, "soft_deleted": True}
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))


@router.post("/files/{file_id}/restore")
async def restore_file(
    file_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    try:
        row = await svc.restore(file_id)
        return {"file": row, "restored": True}
    except FileNotFoundError as e:
        raise HTTPException(410, f"Cannot restore: {e}")


# ---------------------------------------------------------------------------
@router.post("/admin/prune-expired")
async def prune_expired(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Hard-prune soft-deleted files past the 30-day grace.  Admin-gated
    in production; for now any logged-in user can trigger it (cleanup
    is idempotent and safe)."""
    await get_current_user(request, session_token, authorization)
    n = await svc.hard_prune_expired()
    return {"pruned": n}
