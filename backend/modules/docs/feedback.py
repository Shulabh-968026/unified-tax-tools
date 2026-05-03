"""Documentation feedback — captures `Was this helpful?` clicks per (user × module × section).

Storage strategy
-----------------
One row per (user_id, module_key, section_id) — upsert on each click so users
can change their mind without polluting the dataset.  We keep the most recent
helpful flag + reason; aggregation queries become trivial group-bys.

Endpoints
---------
POST /api/docs/feedback                — any logged-in user
GET  /api/docs/feedback/aggregate      — admin only; per-module/per-section heatmap
GET  /api/docs/feedback/raw            — admin only; recent rows for triage

DB shape
--------
{
    feedback_id:  uuid,
    module_key:   "clause-44",
    section_id:   "walkthrough"  | "_overall",
    helpful:      true | false,
    reason:       "" | "...",
    user_id:      "...",
    user_email:   "...",
    ts:           ISO,
    updated_at:   ISO,
}
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.db import db
from modules.auth.controller import get_current_user

# Local sub-router; the parent module mounts everything under /api/docs.
feedback_router = APIRouter()
COL = db.docs_feedback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") in ("admin", "super_admin")


# ----------------------------- payload models -----------------------------
class FeedbackPayload(BaseModel):
    module_key: str = Field(..., min_length=1, max_length=64)
    section_id: str = Field(..., min_length=1, max_length=64)
    helpful: bool
    reason: str = Field("", max_length=2000)


# ----------------------------- POST /feedback -----------------------------
@feedback_router.post("/feedback", include_in_schema=False)
async def submit_feedback(
    payload: FeedbackPayload,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)

    key = {
        "user_id":    user["user_id"],
        "module_key": payload.module_key.strip(),
        "section_id": payload.section_id.strip(),
    }
    existing = await COL.find_one(key, {"_id": 0})
    now = _now()
    doc = {
        **key,
        "helpful":    payload.helpful,
        "reason":     payload.reason.strip()[:2000],
        "user_email": user.get("email", ""),
        "user_name":  user.get("name", ""),
        "ts":         existing["ts"] if existing else now,
        "updated_at": now,
    }
    if existing:
        await COL.update_one(key, {"$set": doc})
    else:
        doc["feedback_id"] = str(uuid.uuid4())
        await COL.insert_one(doc)
    return {"ok": True, "first_time": not existing}


# ----------------------------- GET /aggregate -----------------------------
@feedback_router.get("/feedback/aggregate", include_in_schema=False)
async def aggregate_feedback(
    request: Request,
    module_key: Optional[str] = None,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Heatmap-ready aggregation: by (module_key, section_id) →
    {up: n, down: n, score: up/(up+down), recent_reasons: [...]}"""
    user = await get_current_user(request, session_token, authorization)
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")

    match: Dict[str, Any] = {}
    if module_key:
        match["module_key"] = module_key

    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$group": {
            "_id":   {"module_key": "$module_key", "section_id": "$section_id"},
            "up":    {"$sum": {"$cond": ["$helpful", 1, 0]}},
            "down":  {"$sum": {"$cond": ["$helpful", 0, 1]}},
            "reasons": {
                "$push": {
                    "$cond": [
                        {"$and": [
                            {"$eq": ["$helpful", False]},
                            {"$ne": ["$reason", ""]},
                        ]},
                        {"reason": "$reason", "user": "$user_email", "ts": "$updated_at"},
                        None,
                    ]
                }
            },
        }},
        {"$sort": {"_id.module_key": 1, "_id.section_id": 1}},
    ]
    cursor = COL.aggregate(pipeline)
    rows = []
    async for r in cursor:
        n = r["up"] + r["down"]
        reasons = [x for x in (r.get("reasons") or []) if x]
        # most recent first, cap at 5 for the heatmap UI
        reasons.sort(key=lambda x: x.get("ts", ""), reverse=True)
        rows.append({
            "module_key": r["_id"]["module_key"],
            "section_id": r["_id"]["section_id"],
            "up":     r["up"],
            "down":   r["down"],
            "total":  n,
            "score":  round(r["up"] / n, 3) if n else None,
            "recent_reasons": reasons[:5],
        })
    return {"rows": rows, "count": len(rows)}


# ----------------------------- GET /raw ----------------------------------
@feedback_router.get("/feedback/raw", include_in_schema=False)
async def raw_feedback(
    request: Request,
    module_key: Optional[str] = None,
    limit: int = 200,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    q: Dict[str, Any] = {}
    if module_key:
        q["module_key"] = module_key
    rows = await COL.find(q, {"_id": 0}).sort("updated_at", -1).limit(min(limit, 500)).to_list(500)
    return {"rows": rows, "count": len(rows)}
