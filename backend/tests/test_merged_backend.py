"""Backend tests for merged MSS x Assure Audit Utilities.

Covers: root, auth, clients CRUD, clause44 /runs, msme43bh full flow
(upload yearend -> profiles -> payments -> compute -> results -> export ->
force_fifo FIFO label fix -> cleanup).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
SESSION = "qa_test_session_token_20260427_stable"
COOKIES = {"session_token": SESSION}
FIX = "/app/tests/fixtures"


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.cookies.update(COOKIES)
    return s


@pytest.fixture(scope="module")
def state():
    return {}


# ------------------- Root + Auth -------------------
def test_root(http):
    r = http.get(f"{BASE_URL}/api/")
    assert r.status_code == 200
    assert r.json() == {"app": "mss-assure-utilities", "ok": True}


def test_auth_me_ok(http):
    r = http.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data["user_id"] == "user_qa_bot_fixed_01"
    assert data["email"] == "qa-bot@transformautomations.com"
    assert data["role"] == "admin"


def test_auth_me_no_cookie():
    r = requests.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 401


def test_msme_sessions_requires_auth():
    r = requests.get(f"{BASE_URL}/api/msme/sessions")
    assert r.status_code == 401


# ------------------- Clients CRUD -------------------
def test_client_create(http, state):
    import uuid
    fn = f"TEST-{uuid.uuid4().hex[:8]}"
    r = http.post(f"{BASE_URL}/api/clients", json={
        "file_number": fn, "name": "TEST_QA_Client", "type": "single", "divisions": []
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["file_number"] == fn
    assert d["name"] == "TEST_QA_Client"
    assert "client_id" in d
    state["client_id"] = d["client_id"]
    state["file_number"] = fn


def test_client_list(http, state):
    r = http.get(f"{BASE_URL}/api/clients")
    assert r.status_code == 200
    ids = [c["client_id"] for c in r.json()["clients"]]
    assert state["client_id"] in ids


def test_client_get(http, state):
    r = http.get(f"{BASE_URL}/api/clients/{state['client_id']}")
    assert r.status_code == 200
    assert r.json()["client_id"] == state["client_id"]


def test_client_update(http, state):
    # Router exposes PATCH, not PUT
    r = http.patch(f"{BASE_URL}/api/clients/{state['client_id']}",
                   json={"name": "TEST_QA_Client_Updated"})
    assert r.status_code == 200
    assert r.json()["name"] == "TEST_QA_Client_Updated"


# ------------------- Clause 44 /runs -------------------
def test_clause44_runs(http, state):
    r = http.get(f"{BASE_URL}/api/runs", params={"client_id": state["client_id"]})
    assert r.status_code == 200


# ------------------- MSME Flow -------------------
def test_msme_session_requires_client(http):
    r = http.post(f"{BASE_URL}/api/msme/sessions", json={"name": "no client"})
    assert r.status_code in (400, 422)


def test_msme_create_session(http, state):
    r = http.post(f"{BASE_URL}/api/msme/sessions", json={
        "client_id": state["client_id"], "name": "TEST QA Session", "fy": "2024-25"
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["client_id"] == state["client_id"]
    state["sid"] = d["id"]


def test_msme_list_sessions_filter(http, state):
    r = http.get(f"{BASE_URL}/api/msme/sessions",
                 params={"client_id": state["client_id"]})
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert state["sid"] in ids


def test_msme_upload_yearend(http, state):
    with open(f"{FIX}/yearend.xlsx", "rb") as f:
        r = http.post(f"{BASE_URL}/api/msme/sessions/{state['sid']}/yearend",
                      files={"file": ("yearend.xlsx", f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bill_count"] == 4
    assert d["unique_ledgers"] == 3
    assert d["profile_count"] == 3


def test_msme_upload_profiles(http, state):
    with open(f"{FIX}/profiles.xlsx", "rb") as f:
        r = http.post(f"{BASE_URL}/api/msme/sessions/{state['sid']}/profiles/upload",
                      files={"file": ("profiles.xlsx", f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["profile_count"] == 3


def test_msme_upload_payments(http, state):
    with open(f"{FIX}/payments.json", "rb") as f:
        r = http.post(f"{BASE_URL}/api/msme/sessions/{state['sid']}/payments",
                      files={"file": ("payments.json", f, "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["payment_count"] == 3


def test_msme_compute(http, state):
    r = http.post(f"{BASE_URL}/api/msme/sessions/{state['sid']}/compute")
    assert r.status_code == 200, r.text
    res = r.json()
    s = res["summary"]
    assert s["bill_count"] == 4
    assert s["exempt_count"] >= 2
    assert s["disallowed_count"] >= 1
    # Acme INV/002 must be disallowed (late payment)
    acme_bills = [a for a in res["audit_rows"]
                  if "acme" in a["ledger_name"].lower() and a["voucher_no"] == "INV/002"]
    assert acme_bills, "INV/002 not found"
    assert acme_bills[0]["status"] == "Disallowed"


def test_msme_compute_force_fifo_label(http, state):
    r = http.post(f"{BASE_URL}/api/msme/sessions/{state['sid']}/compute",
                  params={"force_fifo": "true"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["summary"]["force_fifo"] is True
    assert res["summary"]["fifo_forced_count"] >= 1
    # Bug fix verification: due_date_basis text must NOT be "FIFO Forced" anywhere
    bad = [a for a in res["audit_rows"] if a["due_date_basis"] == "FIFO Forced"]
    assert not bad, f"Found rows with bad 'FIFO Forced' label: {bad}"
    # All rows when force_fifo=True should use Voucher Date + 45 days basis
    forced_rows = [a for a in res["audit_rows"] if a.get("fifo_forced")]
    for row in forced_rows:
        assert row["due_date_basis"] == "Voucher Date + 45 days", row


def test_msme_results(http, state):
    r = http.get(f"{BASE_URL}/api/msme/sessions/{state['sid']}/results")
    assert r.status_code == 200
    assert "summary" in r.json()


def test_msme_export(http, state):
    r = http.get(f"{BASE_URL}/api/msme/sessions/{state['sid']}/export")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "openxmlformats" in ct or "spreadsheetml" in ct, ct
    assert len(r.content) > 1000


def test_msme_template(http, state):
    r = http.get(f"{BASE_URL}/api/msme/sessions/{state['sid']}/template")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "openxmlformats" in ct or "spreadsheetml" in ct, ct
    assert len(r.content) > 500


# ------------------- Cleanup -------------------
def test_zz_cleanup_session(http, state):
    r = http.delete(f"{BASE_URL}/api/msme/sessions/{state['sid']}")
    assert r.status_code == 200
    # verify gone
    r2 = http.get(f"{BASE_URL}/api/msme/sessions/{state['sid']}")
    assert r2.status_code == 404


def test_zz_cleanup_client(http, state):
    # DELETE endpoint may not exist (router only has PATCH for archive).
    # Try DELETE first, then archive fallback.
    r = http.delete(f"{BASE_URL}/api/clients/{state['client_id']}")
    if r.status_code == 405 or r.status_code == 404:
        r = http.patch(f"{BASE_URL}/api/clients/{state['client_id']}",
                       json={"archived": True})
    assert r.status_code in (200, 204), r.text
