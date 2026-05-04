import os
import pytest
import requests
import subprocess
import json

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://form3cd-pro.preview.emergentagent.com").rstrip("/")

# File-number prefixes that ALL live test fixtures use to mark their seed
# clients so end-of-session cleanup can wipe them without touching real
# data.  Anything matching `^(ITER\d|TEST_|R3[0-9]_|FORK_|QA_|FIXTURE_)`
# is considered test data and dropped on session teardown.
# Real production file numbers follow the auditor's office convention
# (e.g. `A-504`, `V-904`) and never use these prefixes.
TEST_FILE_NUMBER_REGEX = r"^(ITER\d|TEST_|R3[0-9]_|FORK_|QA_|FIXTURE_)"


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


# ─────────────────────────────────────────────────────────────────────────
# Session-end cleanup: drop any test clients (and their downstream module
# artefacts) so the live database doesn't drift across iterations.  This
# runs once after the entire pytest session completes — regardless of
# which test files were executed.  Real clients (file_number like
# `A-504`, `V-904`) are never touched because the regex requires one of
# the dedicated test prefixes (see TEST_FILE_NUMBER_REGEX above).
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_on_session_end():
    yield  # let the whole session run first
    script = f"""
use('test_database');
var rx = /{TEST_FILE_NUMBER_REGEX}/;
var ids = db.clients.find({{file_number: rx}}, {{client_id: 1, _id: 0}}).toArray().map(c => c.client_id);
if (ids.length === 0) {{
  print(JSON.stringify({{deleted_clients: 0, deleted_runs: 0}}));
}} else {{
  // Wipe clients + every collection that references them.  Unknown
  // collections (e.g. on early iterations) silently no-op.
  var totalRuns = 0;
  ['runs',
   'balance_confirmation_runs',
   'fixed_assets_runs',
   'fin_statement_runs',
   'msme_runs',
   'msme43bh_runs',
   'gst_recon_runs',
   'invoice_ocr_runs'
  ].forEach(function (coll) {{
    try {{
      var r = db[coll].deleteMany({{client_id: {{$in: ids}}}});
      totalRuns += (r && r.deletedCount) || 0;
    }} catch (e) {{}}
  }});
  var c = db.clients.deleteMany({{client_id: {{$in: ids}}}});
  print(JSON.stringify({{deleted_clients: c.deletedCount, deleted_runs: totalRuns}}));
}}
// Wipe pytest-bootstrapped users + sessions (they're seeded by
// _bootstrap_session with predictable id prefixes).
db.user_sessions.deleteMany({{session_token: /^test_session_/}});
db.users.deleteMany({{user_id: /^test-user-/}});
"""
    try:
        out = subprocess.check_output(
            ["mongosh", "--quiet", "--eval", script],
            text=True, timeout=30,
        )
        # Surface counts in the pytest summary so reviewers see cleanup ran.
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{") and "deleted_clients" in line:
                d = json.loads(line)
                print(f"\n[conftest cleanup] dropped {d['deleted_clients']} test client(s) + {d['deleted_runs']} run(s)")
                break
    except Exception as e:  # pragma: no cover — cleanup is best-effort
        print(f"\n[conftest cleanup] skipped due to error: {e}")
