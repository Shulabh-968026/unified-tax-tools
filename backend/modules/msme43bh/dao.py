"""DAO layer for the 43B(h) MSME Disallowance utility. All Mongo access lives here."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from core.db import db

SESSIONS = db.msme_sessions


async def insert_session(doc: Dict[str, Any]) -> None:
    await SESSIONS.insert_one(doc)


async def find_session(sid: str) -> Optional[Dict[str, Any]]:
    doc = await SESSIONS.find_one({"id": sid}, {"_id": 0})
    if not doc:
        return None
    # Release 4.5 — silent redirect for collapsed/archived sessions.
    if doc.get("archived") and doc.get("collapsed_into"):
        winner = await SESSIONS.find_one({"id": doc["collapsed_into"]}, {"_id": 0})
        if winner:
            return winner
        # Orphaned pointer — treat as not found.
        return None
    return doc


async def delete_session(sid: str) -> int:
    res = await SESSIONS.delete_one({"id": sid})
    return res.deleted_count


async def list_sessions(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    # Release 4.5 — only show non-archived (canonical) sessions.
    query: Dict[str, Any] = {"archived": {"$ne": True}}
    if client_id:
        query["client_id"] = client_id
    return await SESSIONS.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)


async def set_session_fields(sid: str, fields: Dict[str, Any]) -> None:
    await SESSIONS.update_one({"id": sid}, {"$set": fields})
