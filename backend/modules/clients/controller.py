"""Clients router — workspace-shared (no user_id filtering); file_number is globally unique."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Cookie, Header, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core.db import db
from modules.auth.controller import get_current_user

router = APIRouter()


GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$"


class ClientCreate(BaseModel):
    file_number: str
    name: str
    type: str = Field(pattern="^(single|multi)$")
    gstin: Optional[str] = Field(default=None, pattern=GSTIN_PATTERN)
    divisions: List[str] = Field(default_factory=list)


class ClientUpdate(BaseModel):
    file_number: Optional[str] = None
    name: Optional[str] = None
    gstin: Optional[str] = Field(default=None, pattern=GSTIN_PATTERN)
    add_divisions: List[str] = Field(default_factory=list)
    archived: Optional[bool] = None


def _public(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "client_id": c["client_id"],
        "file_number": c.get("file_number", ""),
        "name": c.get("name", ""),
        "type": c.get("type", "single"),
        "gstin": c.get("gstin") or "",
        "divisions": c.get("divisions", []),
        "archived": c.get("archived", False),
        "created_at": c.get("created_at"),
        "created_by_name": c.get("created_by_name") or c.get("created_by_email") or "—",
        "created_by_email": c.get("created_by_email"),
    }


@router.post("/clients")
async def create_client(
    body: ClientCreate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    file_number = body.file_number.strip()
    name = body.name.strip()
    if not file_number or not name:
        raise HTTPException(status_code=400, detail="file_number and name are required")

    divisions: List[Dict[str, Any]] = []
    if body.type == "multi":
        names = [n.strip() for n in (body.divisions or []) if n and n.strip()]
        if not names:
            raise HTTPException(status_code=400, detail="Multi-division client requires at least one division")
        seen = set()
        for nm in names:
            key = nm.lower()
            if key in seen:
                continue
            seen.add(key)
            divisions.append({"division_id": f"div_{uuid.uuid4().hex[:10]}", "name": nm})

    doc = {
        "client_id": f"cli_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],            # legacy / created_by attribution
        "created_by_user_id": user["user_id"],
        "created_by_name": user.get("name") or user.get("email"),
        "created_by_email": user.get("email"),
        "file_number": file_number,
        "name": name,
        "type": body.type,
        "gstin": (body.gstin or "").upper().strip() or None,
        "divisions": divisions,
        "archived": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.clients.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"A client with file number '{file_number}' already exists")
    return _public(doc)


@router.get("/clients")
async def list_clients(
    request: Request,
    archived: bool = Query(False),
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    cursor = db.clients.find({"archived": archived}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(500)
    return {"clients": [_public(c) for c in items]}


@router.get("/clients/{client_id}")
async def get_client(
    client_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    c = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return _public(c)


@router.patch("/clients/{client_id}")
async def update_client(
    client_id: str,
    body: ClientUpdate,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    c = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    update: Dict[str, Any] = {}
    if body.file_number is not None:
        update["file_number"] = body.file_number.strip()
    if body.name is not None:
        update["name"] = body.name.strip()
    if body.gstin is not None:
        update["gstin"] = body.gstin.upper().strip() or None
    if body.archived is not None:
        update["archived"] = body.archived
    if body.add_divisions:
        if c.get("type") != "multi":
            raise HTTPException(status_code=400, detail="Cannot add divisions to a single-division client")
        existing = c.get("divisions", []) or []
        existing_names = {(d.get("name") or "").strip().lower() for d in existing}
        for nm in body.add_divisions:
            nm = nm.strip()
            if not nm or nm.lower() in existing_names:
                continue
            existing_names.add(nm.lower())
            existing.append({"division_id": f"div_{uuid.uuid4().hex[:10]}", "name": nm})
        update["divisions"] = existing
    if update:
        try:
            await db.clients.update_one({"client_id": client_id}, {"$set": update})
        except DuplicateKeyError:
            raise HTTPException(status_code=409, detail="Another client with the same file number already exists")
    c.update(update)
    return _public(c)
