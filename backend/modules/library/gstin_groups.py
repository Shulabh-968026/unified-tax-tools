"""GSTIN Groups — Phase A · Multi-division support.

A GSTIN Group is a labelled set of divisions that share a single GST
registration (GSTIN).  Example: client GMS Processors has 4 divisions
in Tamilnadu sharing one GSTIN, and 1 in Mumbai with a separate GSTIN
— each becomes one GSTIN Group with the divisions as members.

The GST Recon module operates at GSTIN-Group grain.  Other modules
(Clause 44, BC, MSME 43B(h)) can also reference groups for the
"GSTIN-group consolidation" scope option exposed in Phase B.

Schema (collection: ``gstin_groups``):
    group_id        str  (gst_xxxxxxxxxxxxxx)
    client_id       str
    label           str  human-readable, e.g. "TN GSTIN"
    gstin           str  (optional, 15-char alphanumeric)
    division_ids    list[str]
    created_at      ISO-8601 string
    updated_at      ISO-8601 string
    created_by      str  email
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.db import db
from modules.auth.controller import get_current_user

router = APIRouter(prefix="/library", tags=["library"])

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


class GstinGroupIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    gstin: Optional[str] = ""
    division_ids: List[str] = Field(default_factory=list)


class GstinGroupOut(BaseModel):
    group_id:     str
    client_id:    str
    label:        str
    gstin:        str = ""
    division_ids: List[str] = Field(default_factory=list)
    created_at:   str
    updated_at:   str
    created_by:   str = ""
    # Phase C.3 — hidden auto-synthesised "Default" group per client.
    # The frontend GstinGroupsManager filters these out by default; they
    # exist only so every gst_recon_run can be canonicalised by a real
    # gstin_group_id (incl. on single-GSTIN clients).
    is_default:   bool = False


async def ensure_default_group(client_id: str) -> dict:
    """Phase C.3 · idempotently create a hidden ``Default`` GSTIN group
    for the given client and return its full doc.

    Used by GST Recon's POST /runs (and the backfill migration) so every
    working doc — including those on single-GSTIN clients that haven't
    explicitly set up groups — can be canonicalised by a real
    ``gstin_group_id``.

    Behaviour:
      * If the client already has a group flagged ``is_default=True`` →
        return it as-is.
      * Else create a fresh ``Default`` group seeded with the client's
        primary GSTIN (when present on the client doc) and every
        division_id known on the client.
    """
    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(404, f"Client not found: {client_id}")

    existing = await db.gstin_groups.find_one(
        {"client_id": client_id, "is_default": True},
        {"_id": 0},
    )
    if existing:
        return existing

    division_ids = sorted({
        (d.get("division_id") or "").strip()
        for d in (cli.get("divisions") or [])
        if (d.get("division_id") or "").strip()
    })
    primary_gstin = (cli.get("gstin") or "").strip().upper()

    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "group_id":     f"gst_{uuid.uuid4().hex[:14]}",
        "client_id":    client_id,
        "label":        "Default",
        "gstin":        primary_gstin if GSTIN_RE.match(primary_gstin) else "",
        "division_ids": division_ids,
        "created_at":   now_iso,
        "updated_at":   now_iso,
        "created_by":   "system",
        "is_default":   True,
    }
    await db.gstin_groups.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _normalise(payload: GstinGroupIn) -> dict:
    """Strip + uppercase GSTIN; dedupe + sort division_ids; trim label."""
    label = (payload.label or "").strip()
    gstin = (payload.gstin or "").strip().upper()
    if gstin and not GSTIN_RE.match(gstin):
        raise HTTPException(400, "Invalid GSTIN format (expected 15-character pattern e.g. 27ABCDE1234F1Z5)")
    division_ids = sorted(set((d or "").strip() for d in (payload.division_ids or []) if (d or "").strip()))
    if not division_ids:
        raise HTTPException(400, "A GSTIN group must include at least one division")
    return {"label": label, "gstin": gstin, "division_ids": division_ids}


async def _client_or_404(client_id: str) -> dict:
    cli = await db.clients.find_one({"client_id": client_id}, {"_id": 0})
    if not cli:
        raise HTTPException(404, "Client not found")
    return cli


def _validate_membership(cli: dict, division_ids: List[str]) -> None:
    """Every division_id in the payload must exist on the client doc."""
    valid_ids = {d.get("division_id") for d in (cli.get("divisions") or [])}
    bad = [d for d in division_ids if d not in valid_ids]
    if bad:
        raise HTTPException(
            400, f"Division id(s) not found on client: {', '.join(bad)}"
        )


@router.get("/clients/{client_id}/gstin-groups")
async def list_groups(
    client_id: str,
    request: Request,
    include_default: bool = False,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Return GSTIN groups defined for the client (newest first).

    Hidden auto-synthesised ``Default`` groups (``is_default=True``) are
    excluded by default — the GstinGroupsManager UI never shows them.
    Internal callers (e.g. the GST Recon backend) pass
    ``include_default=true`` to see every group.
    """
    await get_current_user(request, session_token, authorization)
    await _client_or_404(client_id)
    query = {"client_id": client_id}
    if not include_default:
        query["is_default"] = {"$ne": True}
    rows = await db.gstin_groups.find(
        query, {"_id": 0},
    ).sort("created_at", -1).to_list(length=200)
    return {"groups": rows}


@router.post("/clients/{client_id}/gstin-groups/ensure-default", response_model=GstinGroupOut)
async def ensure_default_group_endpoint(
    client_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Phase C.3 — idempotently fetch (or create) the hidden ``Default``
    GSTIN group for this client.  Used by the frontend before opening a
    GST Recon working doc so a single-GSTIN client doesn't see a
    confusing "pick a group" prompt.
    """
    await get_current_user(request, session_token, authorization)
    return await ensure_default_group(client_id)


@router.post("/clients/{client_id}/gstin-groups", response_model=GstinGroupOut)
async def create_group(
    client_id: str,
    payload: GstinGroupIn,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Define a new GSTIN group for the client.  The label must be unique
    per client; division_ids must reference real divisions on the client."""
    user = await get_current_user(request, session_token, authorization)
    cli = await _client_or_404(client_id)
    norm = _normalise(payload)
    _validate_membership(cli, norm["division_ids"])

    # Label uniqueness within client.
    existing = await db.gstin_groups.find_one(
        {"client_id": client_id, "label": norm["label"]},
        {"_id": 0, "group_id": 1},
    )
    if existing:
        raise HTTPException(409, f"A GSTIN group named '{norm['label']}' already exists for this client")

    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "group_id":     f"gst_{uuid.uuid4().hex[:14]}",
        "client_id":    client_id,
        "label":        norm["label"],
        "gstin":        norm["gstin"],
        "division_ids": norm["division_ids"],
        "created_at":   now_iso,
        "updated_at":   now_iso,
        "created_by":   user.get("email") or "",
    }
    await db.gstin_groups.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.patch("/clients/{client_id}/gstin-groups/{group_id}", response_model=GstinGroupOut)
async def update_group(
    client_id: str,
    group_id: str,
    payload: GstinGroupIn,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Update the label, GSTIN, or membership of an existing group."""
    await get_current_user(request, session_token, authorization)
    cli = await _client_or_404(client_id)
    norm = _normalise(payload)
    _validate_membership(cli, norm["division_ids"])

    # Label uniqueness, excluding self.
    clash = await db.gstin_groups.find_one(
        {
            "client_id": client_id,
            "label":     norm["label"],
            "group_id":  {"$ne": group_id},
        },
        {"_id": 0, "group_id": 1},
    )
    if clash:
        raise HTTPException(409, f"A GSTIN group named '{norm['label']}' already exists for this client")

    res = await db.gstin_groups.update_one(
        {"client_id": client_id, "group_id": group_id},
        {"$set": {
            "label":        norm["label"],
            "gstin":        norm["gstin"],
            "division_ids": norm["division_ids"],
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "GSTIN group not found")
    doc = await db.gstin_groups.find_one(
        {"client_id": client_id, "group_id": group_id}, {"_id": 0},
    )
    return doc


@router.delete("/clients/{client_id}/gstin-groups/{group_id}")
async def delete_group(
    client_id: str,
    group_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Delete a GSTIN group.  Does not cascade to runs / files — Phase
    B/C will introduce reference checking when modules consume groups."""
    await get_current_user(request, session_token, authorization)
    await _client_or_404(client_id)
    res = await db.gstin_groups.delete_one(
        {"client_id": client_id, "group_id": group_id},
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "GSTIN group not found")
    return {"deleted": True}
