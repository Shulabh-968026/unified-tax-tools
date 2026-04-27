"""Admin user-management router.

Auth flow with whitelist:
- super_admin email is hard-coded (set on every startup, cannot be demoted).
- Other users may sign in via Google ONLY if their email is already a member
  OR has a pending invitation. Otherwise create_session returns 403.
- Admin / super_admin can invite, list, change-role, revoke.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Cookie, Header
from pydantic import BaseModel, EmailStr, Field

from core.db import db
from modules.auth.controller import get_current_user
from helpers.email import send_invite_email

router = APIRouter()
SUPER_ADMIN_EMAIL = "mssandco@gmail.com"
ROLES = ("super_admin", "admin", "user")


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|user)$")


class RoleIn(BaseModel):
    role: str = Field(pattern="^(admin|user)$")


async def require_admin(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    user = await get_current_user(request, session_token, authorization)
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _user_public(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": u.get("user_id"),
        "email": u.get("email"),
        "name": u.get("name", ""),
        "picture": u.get("picture", ""),
        "role": u.get("role", "user"),
        "created_at": u.get("created_at"),
        "status": "active",
    }


def _inv_public(i: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "email": i.get("email"),
        "role": i.get("role"),
        "invited_by": i.get("invited_by"),
        "invited_by_email": i.get("invited_by_email"),
        "created_at": i.get("created_at"),
        "status": "pending",
    }


@router.post("/admin/users")
async def invite_user(
    body: InviteIn,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    admin = await require_admin(request, session_token, authorization)
    email = body.email.lower().strip()

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        if existing.get("role") == "super_admin":
            raise HTTPException(status_code=400, detail="Cannot modify super admin via invite")
        await db.users.update_one({"email": email}, {"$set": {"role": body.role}})
        existing["role"] = body.role
        return {"updated": True, **_user_public(existing)}

    pending = await db.invitations.find_one({"email": email}, {"_id": 0})
    if pending:
        await db.invitations.update_one(
            {"email": email},
            {"$set": {
                "role": body.role,
                "invited_by": admin["user_id"],
                "invited_by_email": admin["email"],
            }},
        )
        return {"updated": True, "email": email, "role": body.role, "status": "pending"}

    doc = {
        "invitation_id": f"inv_{uuid.uuid4().hex[:12]}",
        "email": email,
        "role": body.role,
        "invited_by": admin["user_id"],
        "invited_by_email": admin["email"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.invitations.insert_one(doc)

    # Best-effort transactional email (no-op if RESEND_API_KEY isn't set)
    app_url = os.environ.get("APP_URL") or str(request.base_url).rstrip("/").replace("/api", "")
    invited_by_name = admin.get("name") or admin.get("email") or "Your admin"
    email_sent = send_invite_email(email, body.role, invited_by_name, app_url)
    out = _inv_public(doc)
    out["email_sent"] = email_sent
    return out


@router.get("/admin/users")
async def list_members(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await require_admin(request, session_token, authorization)
    users = await db.users.find({}, {"_id": 0}).sort("created_at", 1).to_list(500)
    invs = await db.invitations.find({}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {
        "members": [_user_public(u) for u in users],
        "invitations": [_inv_public(i) for i in invs],
    }


@router.patch("/admin/users/{user_id}")
async def change_role(
    user_id: str,
    body: RoleIn,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    admin = await require_admin(request, session_token, authorization)
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "super_admin" or target.get("email") == SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Super admin role cannot be changed")
    await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    target["role"] = body.role
    return _user_public(target)


@router.delete("/admin/users/{user_id}")
async def revoke_user(
    user_id: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    admin = await require_admin(request, session_token, authorization)
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "super_admin" or target.get("email") == SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Super admin cannot be removed")
    await db.users.delete_one({"user_id": user_id})
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"removed": True, "user_id": user_id}


@router.delete("/admin/invitations")
async def cancel_invitation(
    request: Request,
    email: str,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await require_admin(request, session_token, authorization)
    email = email.lower().strip()
    res = await db.invitations.delete_one({"email": email})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return {"cancelled": True, "email": email}
