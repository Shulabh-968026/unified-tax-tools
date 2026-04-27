"""Iteration 6 — workspace-shared clients & runs, attribution, Resend invite gating."""
import os
import sys
import time
import json as jsonlib
import importlib
import subprocess
import warnings

import pytest
import requests

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://form3cd-pro.preview.emergentagent.com").rstrip("/")
SUPER_ADMIN_TOKEN = "gqV7GaQG5t-2Tp9s-Oc7VJWjOSX-4We5W-O_GvNd1U8"


def _bootstrap_user(suffix: str):
    script = f"""
use('test_database');
var userId = 'iter6-user-{suffix}';
var sessionToken = 'iter6_session_{suffix}';
var email = 'iter6.user.{suffix}@example.com';
db.users.insertOne({{
  user_id: userId, email: email, name: 'Iter6 User {suffix}',
  picture: '', role: 'user', created_at: new Date()
}});
db.user_sessions.insertOne({{
  user_id: userId, session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
}});
print(JSON.stringify({{token: sessionToken, user_id: userId, email: email}}));
"""
    out = subprocess.check_output(["mongosh", "--quiet", "--eval", script], text=True)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and "token" in line:
            return jsonlib.loads(line)
    raise RuntimeError(out)


@pytest.fixture(scope="module")
def two_users():
    a = _bootstrap_user(f"a{int(time.time()*1000)}")
    b = _bootstrap_user(f"b{int(time.time()*1000)+1}")
    yield a, b
    # cleanup
    subprocess.run(["mongosh", "--quiet", "--eval", f"""
use('test_database');
db.users.deleteMany({{user_id: {{$in: ['{a['user_id']}','{b['user_id']}']}}}});
db.user_sessions.deleteMany({{user_id: {{$in: ['{a['user_id']}','{b['user_id']}']}}}});
db.clients.deleteMany({{file_number: /^ITER6_/}});
db.runs.deleteMany({{client_file_number: /^ITER6_/}});
"""], check=False)


def _hdr(t): return {"Authorization": f"Bearer {t}"}


# ---------- Imports ----------
class TestImports:
    def test_email_module_imports(self):
        from email_module import send_invite_email
        assert callable(send_invite_email)

    def test_resend_imports(self):
        import resend
        assert resend is not None


# ---------- Workspace-shared clients ----------
class TestWorkspaceSharedClients:
    def test_user_b_sees_client_created_by_user_a(self, two_users):
        a, b = two_users
        suffix = str(int(time.time() * 1000))
        fn = f"ITER6_SHARE_{suffix}"
        r = requests.post(f"{BASE_URL}/api/clients", headers=_hdr(a["token"]),
                          json={"file_number": fn, "name": "Shared", "type": "single", "divisions": []})
        assert r.status_code == 200, r.text
        cid = r.json()["client_id"]

        # B lists -> sees it
        r2 = requests.get(f"{BASE_URL}/api/clients", headers=_hdr(b["token"]))
        assert r2.status_code == 200
        assert any(c["client_id"] == cid for c in r2.json()["clients"])

        # B GET by id
        r3 = requests.get(f"{BASE_URL}/api/clients/{cid}", headers=_hdr(b["token"]))
        assert r3.status_code == 200
        assert r3.json()["client_id"] == cid

        # B PATCHes a client created by A
        r4 = requests.patch(f"{BASE_URL}/api/clients/{cid}", headers=_hdr(b["token"]),
                            json={"name": "Renamed by B"})
        assert r4.status_code == 200, r4.text
        assert r4.json()["name"] == "Renamed by B"

    def test_abc_textile_mills_visible_to_both(self, two_users):
        a, b = two_users
        for u in (a, b):
            r = requests.get(f"{BASE_URL}/api/clients", headers=_hdr(u["token"]))
            assert r.status_code == 200
            files = [c.get("file_number") for c in r.json()["clients"]]
            assert "A-504" in files, f"A-504 not visible for {u['email']}: {files}"

    def test_global_unique_file_number(self, two_users):
        a, b = two_users
        suffix = str(int(time.time() * 1000))
        fn = f"ITER6_DUPGLOBAL_{suffix}"
        r1 = requests.post(f"{BASE_URL}/api/clients", headers=_hdr(a["token"]),
                           json={"file_number": fn, "name": "X", "type": "single", "divisions": []})
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/clients", headers=_hdr(b["token"]),
                           json={"file_number": fn, "name": "Y", "type": "single", "divisions": []})
        assert r2.status_code == 409


# ---------- Workspace-shared runs + attribution ----------
class TestWorkspaceSharedRuns:
    @pytest.fixture(scope="class")
    def shared_run(self, two_users, sample_files):
        a, _b = two_users
        # create or reuse a client for this period
        suffix = str(int(time.time() * 1000))
        rc = requests.post(f"{BASE_URL}/api/clients", headers=_hdr(a["token"]),
                           json={"file_number": f"ITER6_RUN_{suffix}", "name": "RunShare",
                                 "type": "single", "divisions": []})
        assert rc.status_code == 200
        cid = rc.json()["client_id"]

        with open(sample_files["json"], "rb") as fj, open(sample_files["xlsx"], "rb") as fx:
            files = {
                "accounting_json": ("sample.json", fj, "application/json"),
                "ledger_xlsx": ("sample.xlsx", fx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            }
            r = requests.post(f"{BASE_URL}/api/runs", headers=_hdr(a["token"]),
                              data={"client_id": cid, "period": "2023-24"}, files=files)
        assert r.status_code == 200, r.text
        return {"run_id": r.json()["run_id"], "client_id": cid, "creator": a}

    def test_user_b_sees_and_reads_run(self, two_users, shared_run):
        _a, b = two_users
        rl = requests.get(f"{BASE_URL}/api/runs", headers=_hdr(b["token"]))
        assert rl.status_code == 200
        assert any(rn["run_id"] == shared_run["run_id"] for rn in rl.json()["runs"])

        rg = requests.get(f"{BASE_URL}/api/runs/{shared_run['run_id']}", headers=_hdr(b["token"]))
        assert rg.status_code == 200
        body = rg.json()
        assert body["created_by_email"] == shared_run["creator"]["email"]
        assert body.get("created_by_name")

    def test_user_b_can_generate_run_created_by_a(self, two_users, shared_run):
        _a, b = two_users
        rgen = requests.post(f"{BASE_URL}/api/runs/{shared_run['run_id']}/generate",
                             headers=_hdr(b["token"]),
                             json={"itc_ledgers": [], "excluded_ledgers": []})
        assert rgen.status_code == 200, rgen.text

        rg = requests.get(f"{BASE_URL}/api/runs/{shared_run['run_id']}", headers=_hdr(b["token"]))
        body = rg.json()
        assert body["generated"] is True
        assert body["generated_by_email"] == b["email"]
        assert body.get("generated_by_name")
        assert body.get("generated_at")
        # created_by remains the original creator
        assert body["created_by_email"] == shared_run["creator"]["email"]

    def test_user_b_can_archive_run(self, two_users, shared_run):
        _a, b = two_users
        ra = requests.post(f"{BASE_URL}/api/runs/{shared_run['run_id']}/archive", headers=_hdr(b["token"]))
        assert ra.status_code == 200
        # restore so other tests can see it
        requests.post(f"{BASE_URL}/api/runs/{shared_run['run_id']}/archive", headers=_hdr(b["token"]))

    def test_user_b_can_export_generated_run(self, two_users, shared_run):
        _a, b = two_users
        rx = requests.get(f"{BASE_URL}/api/runs/{shared_run['run_id']}/export", headers=_hdr(b["token"]))
        assert rx.status_code == 200
        assert "spreadsheet" in rx.headers.get("content-type", "") or rx.headers.get("content-type", "").startswith("application/vnd")

    def test_transactions_endpoint_no_deprecation_warning(self, two_users, shared_run):
        _a, b = two_users
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rt = requests.get(f"{BASE_URL}/api/runs/{shared_run['run_id']}/transactions",
                              headers=_hdr(b["token"]), params={"bucket": "all"})
        assert rt.status_code == 200
        # Local-side warnings list shouldn't contain regex deprecation; mainly we verify status.
        # Backend-side: verified by inspecting source uses pattern=
        from runs_module import get_transactions  # noqa
        import inspect
        src = inspect.getsource(get_transactions)
        assert "pattern=" in src and "regex=" not in src


# ---------- Admin invite email_sent gating ----------
class TestAdminInviteEmailGating:
    def test_invite_returns_email_sent_false_when_no_resend_key(self):
        # Use seeded super_admin
        suffix = str(int(time.time() * 1000))
        email = f"iter6_invite_{suffix}@example.com"
        r = requests.post(f"{BASE_URL}/api/admin/users",
                          headers=_hdr(SUPER_ADMIN_TOKEN),
                          json={"email": email, "role": "user"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "email_sent" in body, f"missing email_sent in response: {body}"
        # RESEND_API_KEY is empty in /app/backend/.env -> must be False
        assert body["email_sent"] is False
        assert body["email"] == email
        # invitation row created
        rl = requests.get(f"{BASE_URL}/api/admin/users", headers=_hdr(SUPER_ADMIN_TOKEN))
        assert any(i["email"] == email for i in rl.json()["invitations"])
        # cleanup
        requests.delete(f"{BASE_URL}/api/admin/invitations",
                        headers=_hdr(SUPER_ADMIN_TOKEN), params={"email": email})

    def test_send_invite_email_returns_false_when_unset(self, monkeypatch):
        from email_module import send_invite_email
        monkeypatch.setenv("RESEND_API_KEY", "")
        assert send_invite_email("nobody@example.com", "user", "Tester", "https://example.com") is False
