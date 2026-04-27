"""Auth dependency + auth router (Emergent Google OAuth).

Sign-in is gated: only existing members or holders of a valid invitation can
exchange a Google session_id for an app session. Everyone else gets HTTP 403.
"""
from fastapi import APIRouter, HTTPException, Request, Response, Cookie, Header
from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid
import requests

from core.db import db, SUPER_ADMIN_EMAIL

router = APIRouter()
EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


async def get_current_user(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = sess["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/auth/session")
async def create_session(response: Response, x_session_id: Optional[str] = Header(default=None)):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header")
    try:
        r = requests.get(EMERGENT_AUTH_URL, headers={"X-Session-ID": x_session_id}, timeout=15)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Auth service error: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()

    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email missing in OAuth response")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    invitation = await db.invitations.find_one({"email": email}, {"_id": 0})

    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "name": data.get("name") or existing.get("name", ""),
                "picture": data.get("picture") or existing.get("picture", ""),
            }},
        )
        role = existing.get("role") or "user"
    elif invitation:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = invitation.get("role") or "user"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.invitations.delete_one({"email": email})
    elif email == SUPER_ADMIN_EMAIL:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = "super_admin"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        raise HTTPException(
            status_code=403,
            detail="Access not granted. Please ask your admin to invite you.",
        )

    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "user_id": user_id,
            "session_token": session_token,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 60 * 60,
    )
    return {
        "user_id": user_id,
        "email": email,
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "role": role,
    }


@router.get("/auth/me")
async def me(request: Request,
             session_token: Optional[str] = Cookie(default=None),
             authorization: Optional[str] = Header(default=None)):
    user = await get_current_user(request, session_token, authorization)
    return {k: user.get(k, "") for k in ("user_id", "email", "name", "picture", "role")}


@router.post("/auth/logout")
async def logout(response: Response,
                 session_token: Optional[str] = Cookie(default=None),
                 authorization: Optional[str] = Header(default=None)):
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/", samesite="none", secure=True)
    return {"ok": True}
