import os
import pytest
import requests
import subprocess
import json

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://form3cd-pro.preview.emergentagent.com").rstrip("/")


def _bootstrap_session():
    """Create a fresh user + session in MongoDB and return (token, user_id)."""
    script = """
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Pytest User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print(JSON.stringify({token: sessionToken, user_id: userId}));
"""
    out = subprocess.check_output(["mongosh", "--quiet", "--eval", script], text=True)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and "token" in line:
            return json.loads(line)["token"], json.loads(line)["user_id"]
    raise RuntimeError(f"Could not bootstrap session: {out}")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def session_info():
    token, user_id = _bootstrap_session()
    return {"token": token, "user_id": user_id}


@pytest.fixture(scope="session")
def auth_headers(session_info):
    return {"Authorization": f"Bearer {session_info['token']}"}


@pytest.fixture(scope="session")
def api_client(auth_headers):
    s = requests.Session()
    s.headers.update(auth_headers)
    return s


@pytest.fixture(scope="session")
def sample_files():
    json_path = "/tmp/sample.json"
    xlsx_path = "/tmp/sample.xlsx"
    if not os.path.exists(json_path):
        subprocess.check_call(["curl", "-s", "-o", json_path,
            "https://customer-assets.emergentagent.com/job_d9f5082f-4b1e-443e-9b80-79f0f0b17c88/artifacts/tg0b69rx_ABC_Textile_Mills_01042023-31032024-1741152147.json"])
    if not os.path.exists(xlsx_path):
        subprocess.check_call(["curl", "-s", "-o", xlsx_path,
            "https://customer-assets.emergentagent.com/job_d9f5082f-4b1e-443e-9b80-79f0f0b17c88/artifacts/96v2xon6_A_504_2023_2024_v1_ledger_mapping.xlsx"])
    return {"json": json_path, "xlsx": xlsx_path}
