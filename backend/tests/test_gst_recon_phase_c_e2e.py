"""End-to-end backend tests for GST Recon Phase C.2 (parsers/aggregators wired
into upload pipeline) and C.3 (12-month build_summary endpoint).

Hits the public REACT_APP_BACKEND_URL with the seeded QA session cookie. All
endpoints are prefixed with /api. Creates a run, uploads synthetic GSTR-1 / 2B /
3B / Books files, validates Mongo persistence via subsequent GETs, then calls
POST /summary and verifies math + variance columns.

Run:
  cd /app/backend && python -m pytest tests/test_gst_recon_phase_c_e2e.py -v
"""
from __future__ import annotations
import io
import json
import os

import pytest
import requests

# Direct Mongo read (bypasses RunOut Pydantic stripping) — Phase C.2 persisted
# fields like r1_outward/r2b_itc/books_per_month/table_3_1 are NOT exposed by
# GET /runs/{rid} because RunOut.FileBucketItem schema doesn't whitelist them.
# We verify persistence via the DB directly + via the summary math endpoint.
from pymongo import MongoClient

_BACKEND_ENV = "/app/backend/.env"
_mongo_url = None
_db_name = None
if os.path.exists(_BACKEND_ENV):
    with open(_BACKEND_ENV) as fh:
        for line in fh:
            if line.startswith("MONGO_URL="):
                _mongo_url = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("DB_NAME="):
                _db_name = line.split("=", 1)[1].strip().strip('"')
_mongo = MongoClient(_mongo_url)[_db_name] if _mongo_url and _db_name else None


def _load_base_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    # fallback: read from /app/frontend/.env
    env_path = "/app/frontend/.env"
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_base_url()
COOKIE = {"session_token": "qa_test_session_token_20260427_stable"}
CLIENT_ID = "cli_bdf1e22faa7c"
GSTIN = "33AAEFA5684J1ZC"
FY = "2024-25"


# --- fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.cookies.update(COOKIE)
    return sess


@pytest.fixture(scope="module")
def run_id(s):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs",
               json={"client_id": CLIENT_ID, "fy": FY, "name": "TEST_phase_c_e2e"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    yield rid
    # teardown
    s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# --- synthetic payloads -------------------------------------------------------
GSTR1_OBJ = {
    "gstin": GSTIN, "fp": "042024",
    "b2b": [{"ctin": "33XXXXX1234X1Z5", "inv": [
        {"inum": "I1", "idt": "15-04-2024", "val": 1180,
         "itms": [{"itm_det": {"txval": 1000, "iamt": 0, "camt": 90, "samt": 90, "csamt": 0, "rt": 18}}]},
    ]}],
}
GSTR2B_OBJ = {"data": {"gstin": GSTIN, "rtnprd": "042024",
              "itcsumm": {"itcavl": {
                  "nonrevsup": {"b2b": {"iamt": 0, "camt": 90, "samt": 90, "csamt": 0}},
              }},
              "docdata": {"b2b": []}}}
BOOKS_OBJ = {
    "company": {"booksFromDate": "2024-04-01", "booksToDate": "2025-03-31", "gstin": GSTIN},
    "vouchers": [{
        "date": "2024-04-15", "voucherTypeName": "Sales",
        "ledgerEntries": [
            {"ledgerName": "ABC Customer Ltd", "amount": -1180},
            {"ledgerName": "Sales Account", "amount": 1000},
            {"ledgerName": "Output CGST @ 9%", "amount": 90},
            {"ledgerName": "Output SGST @ 9%", "amount": 90},
        ],
    }],
}
# Minimal valid PDF blob (won't yield any Table 3.1/4 data — that's expected;
# we only assert the upload pipeline persists the keys without crashing).
PDF_STUB = (b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")


def _run_doc_from_mongo(rid):
    if _mongo is None:
        pytest.skip("Mongo not configured")
    return _mongo.gst_recon_runs.find_one({"id": rid}, {"_id": 0})


def _upload(s, rid, name, content, mime):
    files = [("files", (name, io.BytesIO(content), mime))]
    return s.post(f"{BASE_URL}/api/gst-recon/runs/{rid}/files", files=files)


# --- auth gate ---------------------------------------------------------------
def test_auth_required():
    r = requests.get(f"{BASE_URL}/api/gst-recon/runs")
    assert r.status_code == 401


def test_auth_me_works(s):
    r = s.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "qa-bot@transformautomations.com"


# --- create run + regression CRUD -------------------------------------------
def test_create_run_persisted(s, run_id):
    r = s.get(f"{BASE_URL}/api/gst-recon/runs/{run_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["client_id"] == CLIENT_ID
    assert d["fy"] == FY
    assert d["status"] == "draft"
    assert isinstance(d["months"], list) and len(d["months"]) == 12
    assert d["months"][0]["month_label"] == "Apr 2024"


def test_list_runs_filtered_by_client(s, run_id):
    r = s.get(f"{BASE_URL}/api/gst-recon/runs", params={"client_id": CLIENT_ID})
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert run_id in ids


# --- C.2: GSTR-1 aggregator wired into upload --------------------------------
def test_upload_gstr1_persists_r1_outward(s, run_id):
    r = _upload(s, run_id, f"{GSTIN}_GSTR1_April_2024-2025_0.json",
                json.dumps(GSTR1_OBJ).encode("utf-8"), "application/json")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buckets"]["gstr1"] == 1
    # Verify run doc has aggregated r1_outward (read directly from Mongo —
    # RunOut response model strips unknown fields, so GET /runs/{rid} hides them.
    # See action_items in test report.)
    d = _run_doc_from_mongo(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr1"), None)
    assert f is not None
    assert f["period"] == "042024"
    r1 = f.get("r1_outward")
    assert r1 == {"taxable": 1000.0, "igst": 0.0, "cgst": 90.0, "sgst": 90.0, "cess": 0.0}


# --- C.2: GSTR-2B aggregator -------------------------------------------------
def test_upload_gstr2b_persists_r2b_itc(s, run_id):
    r = _upload(s, run_id, f"returns_R2B_{GSTIN}_042024.json",
                json.dumps(GSTR2B_OBJ).encode("utf-8"), "application/json")
    assert r.status_code == 200, r.text
    d = _run_doc_from_mongo(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr2b"), None)
    assert f is not None and f["period"] == "042024"
    r2b = f.get("r2b_itc")
    assert r2b is not None
    assert {"taxable", "igst", "cgst", "sgst", "cess"} <= set(r2b.keys())
    assert r2b["cgst"] == 90.0 and r2b["sgst"] == 90.0


# --- C.2: GSTR-3B PDF parsing wired (keys must exist even on stub) -----------
def test_upload_gstr3b_pdf_persists_table_keys(s, run_id):
    r = _upload(s, run_id, f"GSTR3B_{GSTIN}_042024.pdf", PDF_STUB, "application/pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buckets"]["gstr3b"] == 1
    d = _run_doc_from_mongo(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr3b"), None)
    assert f is not None
    # keys must exist (may be empty dicts on unparseable PDF stub)
    assert "table_3_1" in f and isinstance(f["table_3_1"], dict)
    assert "table_4" in f and isinstance(f["table_4"], dict)


# --- C.2: Books aggregator ---------------------------------------------------
def test_upload_books_persists_books_per_month(s, run_id):
    r = _upload(s, run_id, "Allman_Knit_Wear_IT_24-25_01042024-31032025-165633.json",
                json.dumps(BOOKS_OBJ).encode("utf-8"), "application/json")
    assert r.status_code == 200, r.text
    d = _run_doc_from_mongo(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "books"), None)
    assert f is not None
    bpm = f.get("books_per_month") or {}
    assert "042024" in bpm
    apr = bpm["042024"]
    assert apr["out_taxable"] == 1000.0
    assert apr["out_cgst"] == 90.0
    assert apr["out_sgst"] == 90.0


# --- Regression: validate endpoint -------------------------------------------
def test_validate_endpoint(s, run_id):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs/{run_id}/validate")
    assert r.status_code == 200
    v = r.json()
    # verdict is the persisted validation object — just confirm it returns
    assert isinstance(v, dict)
    d = s.get(f"{BASE_URL}/api/gst-recon/runs/{run_id}").json()
    assert d["validation"] is not None


# --- C.3: summary endpoint shape + math --------------------------------------
def test_summary_shape_and_math(s, run_id):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs/{run_id}/summary")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["fy"] == FY
    rows = summary["rows"]
    assert len(rows) == 12
    assert rows[0]["month_label"] == "Apr 2024"
    assert rows[-1]["month_label"] == "Mar 2025"

    expected_keys = {
        "period", "month_label",
        "books_outward_taxable", "books_outward_tax", "books_itc_total",
        "r1_outward_taxable", "r1_outward_tax",
        "r2b_itc_total",
        "r3b_outward_taxable", "r3b_outward_tax", "r3b_itc_total",
        "var_r1_vs_r3b_outward", "var_r2b_vs_r3b_itc",
        "var_books_vs_r1_outward", "var_books_vs_r2b_itc",
    }
    for r0 in rows:
        assert expected_keys <= set(r0.keys()), f"missing keys: {expected_keys - set(r0.keys())}"

    apr = rows[0]
    assert apr["period"] == "042024"
    assert apr["books_outward_taxable"] == 1000.0
    assert apr["r1_outward_taxable"] == 1000.0
    assert apr["r2b_itc_total"] == 180.0   # 90 + 90
    # r3b empty (PDF stub) — both 3B columns stay at 0
    assert apr["r3b_outward_taxable"] == 0.0
    assert apr["r3b_itc_total"] == 0.0
    # variances (left - right)
    assert apr["var_r1_vs_r3b_outward"] == 1000.0  # 1000 - 0
    assert apr["var_r2b_vs_r3b_itc"] == 180.0      # 180 - 0
    assert apr["var_books_vs_r1_outward"] == 0.0   # 1000 - 1000

    # other 11 months are zero-filled
    may = rows[1]
    for k in ("books_outward_taxable", "r1_outward_taxable", "r2b_itc_total",
              "var_r1_vs_r3b_outward"):
        assert may[k] == 0.0

    # totals
    t = summary["totals"]
    assert t["r1_outward_taxable"] == 1000.0
    assert t["var_r1_vs_r3b_outward"] == 1000.0


def test_summary_persisted_status_summarized(s, run_id):
    d = _run_doc_from_mongo(run_id)
    assert d["status"] == "summarized"
    assert "summary" in d and isinstance(d["summary"], dict)


# --- C.3: empty run produces 12 zero rows ------------------------------------
def test_empty_run_summary_zero_rows(s):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs",
               json={"client_id": CLIENT_ID, "fy": "2024-25", "name": "TEST_empty_summary"})
    rid = r.json()["id"]
    try:
        sm = s.post(f"{BASE_URL}/api/gst-recon/runs/{rid}/summary")
        assert sm.status_code == 200
        body = sm.json()
        assert len(body["rows"]) == 12
        for row in body["rows"]:
            for k in ("books_outward_taxable", "r1_outward_taxable", "r2b_itc_total",
                      "r3b_outward_taxable", "var_r1_vs_r3b_outward", "var_books_vs_r2b_itc"):
                assert row[k] == 0.0
        for k, v in body["totals"].items():
            assert v == 0.0
    finally:
        s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# --- Regression sanity: clause44 + clients still work ------------------------
def test_clients_endpoint_has_seeded_gstin_client(s):
    r = s.get(f"{BASE_URL}/api/clients")
    assert r.status_code == 200
    body = r.json()
    items = body["clients"] if isinstance(body, dict) else body
    found = next((c for c in items if c.get("client_id") == CLIENT_ID), None)
    assert found is not None
    assert found.get("gstin") == GSTIN


def test_clause44_runs_endpoint_reachable(s):
    r = s.get(f"{BASE_URL}/api/runs")
    assert r.status_code == 200
    body = r.json()
    items = body["runs"] if isinstance(body, dict) else body
    assert isinstance(items, list)
