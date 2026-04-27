"""Iteration 5 — User Management & whitelist gating tests.

Covers:
- super_admin bootstrap + GET /auth/me role propagation
- /api/admin/users invite/list/patch/delete
- /api/admin/invitations cancel
- whitelist enforcement on /api/auth/session (mocked Emergent OAuth)
- unique indexes on users.email and invitations.email
"""
import os
import json
import time
import uuid
import subprocess
from unittest.mock import patch, MagicMock

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://form3cd-pro.preview.emergentagent.com").rstrip("/")
SUPER_ADMIN_EMAIL = "mssandco@gmail.com"


# ---------- helpers ----------
def _mongo(script: str) -> str:
    return subprocess.check_output(["mongosh", "--quiet", "--eval", script], text=True)


def _bootstrap_user(role: str = "user", email_prefix: str = "TEST_iter5"):
    """Create a fresh user (already a member, with role) + session."""
    suffix = uuid.uuid4().hex[:8]
    email = f"{email_prefix}_{suffix}@example.com".lower()
    user_id = f"test-user-{int(time.time()*1000)}-{suffix}"
    token = f"test_session_iter5_{suffix}"
    script = f"""
use('test_database');
db.users.insertOne({{
  user_id: '{user_id}',
  email: '{email}',
  name: 'Iter5 User',
  picture: '',
  role: '{role}',
  created_at: new Date().toISOString()
}});
db.user_sessions.insertOne({{
  user_id: '{user_id}',
  session_token: '{token}',
  expires_at: new Date(Date.now()+7*24*3600*1000).toISOString(),
  created_at: new Date().toISOString()
}});
print('OK');
"""
    _mongo(script)
    return {"token": token, "user_id": user_id, "email": email}


def _ensure_super_admin_session():
    """Use the seeded super_admin session if present, else mint one."""
    out = _mongo(f"""
use('test_database');
var u = db.users.findOne({{email:'{SUPER_ADMIN_EMAIL}'}});
if(!u){{print(JSON.stringify({{error:'no_super_admin'}}));}} else {{
  var s = db.user_sessions.findOne({{user_id:u.user_id}});
  if(!s){{
    var tok = 'iter5_super_'+Date.now();
    db.user_sessions.insertOne({{user_id:u.user_id, session_token: tok,
      expires_at: new Date(Date.now()+7*24*3600*1000).toISOString(),
      created_at: new Date().toISOString()}});
    print(JSON.stringify({{token: tok, user_id: u.user_id, role: u.role}}));
  }} else {{
    print(JSON.stringify({{token: s.session_token, user_id: u.user_id, role: u.role}}));
  }}
}}
""")
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            return json.loads(ln)
    raise RuntimeError(f"could not find super admin: {out}")


@pytest.fixture(scope="module")
def super_admin():
    info = _ensure_super_admin_session()
    assert info.get("role") == "super_admin", f"super admin role missing: {info}"
    return info


@pytest.fixture(scope="module")
def super_headers(super_admin):
    return {"Authorization": f"Bearer " + super_admin["token"]}


@pytest.fixture(scope="module")
def regular_user():
    return _bootstrap_user(role="user")


@pytest.fixture(scope="module")
def user_headers(regular_user):
    return {"Authorization": f"Bearer " + regular_user["token"]}


# ---------- 1. bootstrap & /auth/me ----------
class TestSuperAdminBootstrap:
    def test_super_admin_user_exists(self):
        out = _mongo(f"use('test_database'); printjson(db.users.findOne({{email:'{SUPER_ADMIN_EMAIL}'}}, {{_id:0,email:1,role:1,user_id:1}}));")
        assert SUPER_ADMIN_EMAIL in out
        assert "super_admin" in out

    def test_auth_me_returns_role_super_admin(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == SUPER_ADMIN_EMAIL
        assert body["role"] == "super_admin"
        assert "user_id" in body

    def test_auth_me_returns_role_for_regular_user(self, user_headers, regular_user):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=user_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == regular_user["email"]
        assert body["role"] == "user"


# ---------- 2. admin RBAC ----------
class TestAdminRBAC:
    def test_non_admin_cannot_invite(self, user_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=user_headers,
                          json={"email": "blocked@example.com", "role": "user"}, timeout=15)
        assert r.status_code == 403
        assert "Admin access required" in r.text

    def test_non_admin_cannot_list(self, user_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=user_headers, timeout=15)
        assert r.status_code == 403

    def test_unauthenticated_cannot_list(self):
        r = requests.get(f"{BASE_URL}/api/admin/users", timeout=15)
        assert r.status_code == 401


# ---------- 3. invitations ----------
class TestInvitations:
    NEW_EMAIL = f"TEST_invitee_{uuid.uuid4().hex[:8]}@example.com"

    def test_invite_new_email_creates_pending(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=super_headers,
                          json={"email": self.NEW_EMAIL, "role": "admin"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == self.NEW_EMAIL.lower()
        assert body["role"] == "admin"
        assert body["status"] == "pending"

    def test_list_shows_invitation(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=super_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "members" in body and "invitations" in body
        emails = [i["email"] for i in body["invitations"]]
        assert self.NEW_EMAIL.lower() in emails
        # role badge field present
        assert all("role" in i and "status" in i for i in body["invitations"])

    def test_invite_again_updates_role(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=super_headers,
                          json={"email": self.NEW_EMAIL, "role": "user"}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("updated") is True
        assert body["role"] == "user"

    def test_cancel_invitation(self, super_headers):
        r = requests.delete(f"{BASE_URL}/api/admin/invitations",
                            params={"email": self.NEW_EMAIL}, headers=super_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("cancelled") is True
        # gone from list
        r2 = requests.get(f"{BASE_URL}/api/admin/users", headers=super_headers, timeout=15)
        emails = [i["email"] for i in r2.json()["invitations"]]
        assert self.NEW_EMAIL.lower() not in emails

    def test_cannot_invite_super_admin_email(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=super_headers,
                          json={"email": SUPER_ADMIN_EMAIL, "role": "user"}, timeout=15)
        assert r.status_code == 400
        assert "super admin" in r.text.lower()

    def test_invite_invalid_role_rejected(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=super_headers,
                          json={"email": "x@example.com", "role": "owner"}, timeout=15)
        assert r.status_code == 422


# ---------- 4. existing-member role updates ----------
class TestRoleManagement:
    def test_invite_existing_member_updates_role(self, super_headers, regular_user):
        # Promote regular_user to admin via /admin/users invite path
        r = requests.post(f"{BASE_URL}/api/admin/users", headers=super_headers,
                          json={"email": regular_user["email"], "role": "admin"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("updated") is True
        assert body["role"] == "admin"
        # GET /me on that user reflects new role
        h = {"Authorization": f"Bearer " + regular_user["token"]}
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15).json()
        assert me["role"] == "admin"

    def test_patch_role_via_user_id(self, super_headers, regular_user):
        # Demote back to user
        r = requests.patch(f"{BASE_URL}/api/admin/users/{regular_user['user_id']}",
                           headers=super_headers, json={"role": "user"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "user"

    def test_patch_super_admin_role_blocked(self, super_headers, super_admin):
        r = requests.patch(f"{BASE_URL}/api/admin/users/{super_admin['user_id']}",
                           headers=super_headers, json={"role": "user"}, timeout=15)
        assert r.status_code == 400
        assert "super admin" in r.text.lower()

    def test_delete_super_admin_blocked(self, super_headers, super_admin):
        r = requests.delete(f"{BASE_URL}/api/admin/users/{super_admin['user_id']}",
                            headers=super_headers, timeout=15)
        assert r.status_code == 400

    def test_delete_user_removes_sessions(self, super_headers):
        # Create a throwaway user
        u = _bootstrap_user(role="user", email_prefix="TEST_delme")
        r = requests.delete(f"{BASE_URL}/api/admin/users/{u['user_id']}",
                            headers=super_headers, timeout=15)
        assert r.status_code == 200
        # session should be gone -> /me returns 401
        h = {"Authorization": f"Bearer " + u["token"]}
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15)
        assert me.status_code == 401


# ---------- 5. whitelist gating on /auth/session (mocked) ----------
class TestWhitelistGating:
    """Directly invoke auth_module.create_session with mocked requests.get."""

    @pytest.mark.asyncio
    async def test_unknown_email_rejected_403(self):
        import sys, importlib, os
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient
        auth_module = importlib.import_module("auth_module")
        from fastapi import HTTPException, Response
        fresh_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        original_db = auth_module.db
        auth_module.db = fresh_client[os.environ["DB_NAME"]]
        try:
            unknown_email = f"test_unknown_{uuid.uuid4().hex[:6]}@nowhere.com"
            fake = MagicMock(); fake.status_code = 200
            fake.json = lambda: {"email": unknown_email, "name": "X", "picture": "", "session_token": "tok-x"}
            with patch.object(auth_module.requests, "get", return_value=fake):
                with pytest.raises(HTTPException) as ei:
                    await auth_module.create_session(Response(), x_session_id="any")
                assert ei.value.status_code == 403
                assert "ask your admin" in ei.value.detail.lower()
        finally:
            auth_module.db = original_db
            fresh_client.close()

    @pytest.mark.asyncio
    async def test_invitation_holder_admitted(self):
        import sys, importlib, os
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient
        auth_module = importlib.import_module("auth_module")
        from fastapi import Response
        # Bind a fresh motor client to the *current* event loop and monkey-patch
        fresh_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        fresh_db = fresh_client[os.environ["DB_NAME"]]
        original_db = auth_module.db
        auth_module.db = fresh_db
        invited_email = f"test_invited_{uuid.uuid4().hex[:6]}@example.com"
        _mongo(f"""use('test_database');
db.invitations.insertOne({{invitation_id:'inv_xyz', email:'{invited_email}', role:'admin',
  invited_by:'x', invited_by_email:'x@x', created_at:'now'}});""")
        try:
            tok = f"tok_{uuid.uuid4().hex[:8]}"
            fake = MagicMock(); fake.status_code = 200
            fake.json = lambda: {"email": invited_email, "name": "Inv", "picture": "", "session_token": tok}
            with patch.object(auth_module.requests, "get", return_value=fake):
                resp = await auth_module.create_session(Response(), x_session_id="any")
            assert resp["email"] == invited_email
            assert resp["role"] == "admin"
            out = _mongo(f"""use('test_database');
print('inv_count='+db.invitations.countDocuments({{email:'{invited_email}'}}));
print('user_count='+db.users.countDocuments({{email:'{invited_email}'}}));
""")
            assert "inv_count=0" in out
            assert "user_count=1" in out
        finally:
            auth_module.db = original_db
            fresh_client.close()
            _mongo(f"""use('test_database');
db.users.deleteMany({{email:'{invited_email}'}});
db.invitations.deleteMany({{email:'{invited_email}'}});
db.user_sessions.deleteMany({{session_token: {{$regex:'^tok_'}}}});
""")


# ---------- 6. unique indexes ----------
class TestUniqueIndexes:
    def test_users_email_unique(self):
        e = f"TEST_dup_{uuid.uuid4().hex[:6]}@example.com"
        out = _mongo(f"""
use('test_database');
try {{
  db.users.insertOne({{user_id:'a', email:'{e}', role:'user'}});
  db.users.insertOne({{user_id:'b', email:'{e}', role:'user'}});
  print('NO_ERROR');
}} catch(err){{ print('DUP:'+(err.code||err.codeName||err.message)); }}
db.users.deleteMany({{email:'{e}'}});
""")
        assert ("DUP:11000" in out) or ("DuplicateKey" in out) or ("E11000" in out), out

    def test_invitations_email_unique(self):
        e = f"TEST_dupinv_{uuid.uuid4().hex[:6]}@example.com"
        out = _mongo(f"""
use('test_database');
try {{
  db.invitations.insertOne({{invitation_id:'a', email:'{e}', role:'user'}});
  db.invitations.insertOne({{invitation_id:'b', email:'{e}', role:'user'}});
  print('NO_ERROR');
}} catch(err){{ print('DUP:'+(err.code||err.codeName||err.message)); }}
db.invitations.deleteMany({{email:'{e}'}});
""")
        assert ("DUP:11000" in out) or ("DuplicateKey" in out) or ("E11000" in out), out


# ---------- cleanup ----------
def teardown_module(module):
    _mongo("""use('test_database');
db.users.deleteMany({email: /^TEST_/});
db.invitations.deleteMany({email: /^TEST_/});
db.user_sessions.deleteMany({session_token: /^test_session_iter5_/});
db.user_sessions.deleteMany({session_token: /^iter5_super_/});
""")
