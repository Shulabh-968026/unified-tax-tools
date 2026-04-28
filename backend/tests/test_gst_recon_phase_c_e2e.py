"""GST Recon Phase C.2 + C.3 e2e — REGENERATED for mapping-driven Books.

Now uploads a synthetic Ledger Mapping XLSX before Books so that the
mapping-driven aggregator produces non-empty books_per_month. Uses the new
Tally voucher contract: `ledger`/`partyLedgerName` keys + sign convention.

Hits public REACT_APP_BACKEND_URL with seeded QA session cookie. All endpoints
prefixed with /api. Verifies persistence via direct Mongo reads + summary math.
"""
from __future__ import annotations
import io
import json
import os

import pytest
import requests
from pymongo import MongoClient

from tests._gst_recon_helpers import (
    books_payload, sales_voucher, synthetic_mapping_xlsx,
)


# ---- env --------------------------------------------------------------------
_BACKEND_ENV = "/app/backend/.env"
_mongo_url, _db_name = None, None
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
    env_path = "/app/frontend/.env"
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_base_url()
COOKIE = {"session_token": "qa_test_session_token_20260427_stable"}
CLIENT_ID = "cli_7f0b86b1ab0b"  # Allman Knitwear — retained after DB cleanup
GSTIN = "33AAEFA5684J1ZC"
FY = "2024-25"


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.cookies.update(COOKIE)
    return sess


@pytest.fixture(scope="module")
def run_id(s):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs",
               json={"client_id": CLIENT_ID, "fy": FY,
                     "name": "TEST_phase_c_e2e_v2"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    yield rid
    s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# ---- synthetic payloads -----------------------------------------------------
GSTR1_OBJ = {
    "gstin": GSTIN, "fp": "042024",
    "b2b": [{"ctin": "33XXXXX1234X1Z5", "inv": [
        {"inum": "I1", "idt": "15-04-2024", "val": 1180,
         "itms": [{"itm_det": {"txval": 1000, "iamt": 0,
                                "camt": 90, "samt": 90, "csamt": 0, "rt": 18}}]},
    ]}],
}
GSTR2B_OBJ = {"data": {"gstin": GSTIN, "rtnprd": "042024",
              "itcsumm": {"itcavl": {
                  "nonrevsup": {"b2b": {"iamt": 0, "camt": 90, "samt": 90, "csamt": 0}},
              }},
              "docdata": {"b2b": []}}}
PDF_STUB = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _run_doc(rid):
    if _mongo is None:
        pytest.skip("Mongo not configured")
    return _mongo.gst_recon_runs.find_one({"id": rid}, {"_id": 0})


def _upload(s, rid, name, content, mime="application/json"):
    files = [("files", (name, io.BytesIO(content), mime))]
    return s.post(f"{BASE_URL}/api/gst-recon/runs/{rid}/files", files=files)


# ---- auth -------------------------------------------------------------------
def test_auth_required():
    r = requests.get(f"{BASE_URL}/api/gst-recon/runs")
    assert r.status_code == 401


def test_auth_me_works(s):
    r = s.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "qa-bot@transformautomations.com"


# ---- create run + CRUD ------------------------------------------------------
def test_create_run_persisted(s, run_id):
    r = s.get(f"{BASE_URL}/api/gst-recon/runs/{run_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["client_id"] == CLIENT_ID
    assert d["fy"] == FY
    assert d["status"] == "draft"
    assert isinstance(d["months"], list) and len(d["months"]) == 12


def test_list_runs_filtered_by_client(s, run_id):
    r = s.get(f"{BASE_URL}/api/gst-recon/runs",
              params={"client_id": CLIENT_ID})
    assert r.status_code == 200
    assert run_id in {x["id"] for x in r.json()}


# ---- Mapping upload populates rules + unmapped -----------------------------
def test_upload_mapping_populates_rules_and_unmapped(s, run_id):
    r = _upload(s, run_id, "A_519_2024_2025_v10_ledger_mapping.xlsx",
                synthetic_mapping_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buckets"]["mapping"] == 1
    # unmapped 'Writeoff ITC Expenses' surfaces
    assert "Writeoff ITC Expenses" in body.get("mapping_unmapped_ledgers", [])
    # run doc carries mapping_rules with the expected three keys
    d = _run_doc(run_id)
    rules = d.get("mapping_rules") or {}
    assert {"revenue", "output_tax", "input_tax"} <= set(rules.keys())
    assert "Sales Account" in rules["revenue"]
    assert "Output CGST @ 9%" in rules["output_tax"]
    assert "Input CGST @ 9%" in rules["input_tax"]


# ---- C.2: GSTR-1 aggregator + invoice persistence ---------------------------
def test_upload_gstr1_persists_r1_outward(s, run_id):
    r = _upload(s, run_id, f"{GSTIN}_GSTR1_April_2024-2025_0.json",
                json.dumps(GSTR1_OBJ).encode("utf-8"))
    assert r.status_code == 200, r.text
    assert r.json()["buckets"]["gstr1"] == 1
    d = _run_doc(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr1"), None)
    assert f and f["period"] == "042024"
    assert f["r1_outward"] == {"taxable": 1000.0, "igst": 0.0,
                                "cgst": 90.0, "sgst": 90.0, "cess": 0.0}


# ---- C.2: GSTR-2B aggregator -----------------------------------------------
def test_upload_gstr2b_persists_r2b_itc(s, run_id):
    r = _upload(s, run_id, f"returns_R2B_{GSTIN}_042024.json",
                json.dumps(GSTR2B_OBJ).encode("utf-8"))
    assert r.status_code == 200, r.text
    d = _run_doc(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr2b"), None)
    assert f and f["period"] == "042024"
    r2b = f["r2b_itc"]
    assert r2b["cgst"] == 90.0 and r2b["sgst"] == 90.0


# ---- C.2: GSTR-3B PDF stub --------------------------------------------------
def test_upload_gstr3b_pdf_persists_table_keys(s, run_id):
    r = _upload(s, run_id, f"GSTR3B_{GSTIN}_042024.pdf", PDF_STUB,
                "application/pdf")
    assert r.status_code == 200
    d = _run_doc(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "gstr3b"), None)
    assert f
    assert isinstance(f.get("table_3_1"), dict)
    assert isinstance(f.get("table_4"), dict)


# ---- C.2 Books — mapping was uploaded above, so books_per_month is populated
BOOKS_OBJ = {
    "company": {"booksFromDate": "2024-04-01",
                "booksToDate": "2025-03-31", "gstin": GSTIN},
    "vouchers": [
        # plain dict to verify the contract via books_payload below
    ],
}


def test_upload_books_persists_books_per_month(s, run_id):
    content = books_payload(
        [sales_voucher("S-1", "2024-04-15", "33XXXXX1234X1Z5")],
        gstin=GSTIN,
    )
    r = _upload(s, run_id, "Allman_Knit_Wear_IT_24-25_01042024-31032025-165633.json",
                content)
    assert r.status_code == 200, r.text
    body = r.json()
    # Mapping was uploaded earlier in this module → books_reprocessed should be true
    assert body.get("books_reprocessed") is True
    d = _run_doc(run_id)
    f = next((x for x in d["files"] if x["bucket"] == "books"), None)
    assert f, "books file entry missing"
    bpm = f.get("books_per_month") or {}
    assert "042024" in bpm, f"expected 042024 in {list(bpm.keys())}"
    apr = bpm["042024"]
    assert apr["out_taxable"] == 1000.0
    assert apr["out_cgst"] == 90.0
    assert apr["out_sgst"] == 90.0


# ---- C.2 Books WITHOUT mapping = empty books_per_month (new contract) ------
def test_books_without_mapping_yields_empty_per_month(s):
    r0 = s.post(f"{BASE_URL}/api/gst-recon/runs",
                json={"client_id": CLIENT_ID, "fy": FY,
                      "name": "TEST_books_only"})
    rid = r0.json()["id"]
    try:
        content = books_payload(
            [sales_voucher("S-1", "2024-04-15", "33XXXXX1234X1Z5")],
            gstin=GSTIN,
        )
        rr = _upload(s, rid,
                     "Allman_Knit_Wear_IT_24-25_01042024-31032025-165633.json",
                     content)
        assert rr.status_code == 200, rr.text
        d = _mongo.gst_recon_runs.find_one({"id": rid}, {"_id": 0})
        f = next((x for x in d["files"] if x["bucket"] == "books"), None)
        assert f
        # No mapping uploaded → aggregator returns empty dict
        assert f.get("books_per_month") in (None, {})
    finally:
        s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# ---- Books-first then Mapping → auto reprocess -----------------------------
def test_books_first_then_mapping_auto_reprocesses(s):
    r0 = s.post(f"{BASE_URL}/api/gst-recon/runs",
                json={"client_id": CLIENT_ID, "fy": FY,
                      "name": "TEST_books_first"})
    rid = r0.json()["id"]
    try:
        content = books_payload(
            [sales_voucher("S-1", "2024-04-15", "33XXXXX1234X1Z5")],
            gstin=GSTIN,
        )
        _upload(s, rid, "Allman_Knit_Wear_IT_24-25_01042024-31032025-165633.json",
                content)
        # Now upload mapping
        rm = _upload(s, rid, "ledger_mapping.xlsx",
                     synthetic_mapping_xlsx(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        body = rm.json()
        assert body.get("books_reprocessed") is True
        d = _mongo.gst_recon_runs.find_one({"id": rid}, {"_id": 0})
        f = next((x for x in d["files"] if x["bucket"] == "books"), None)
        bpm = f.get("books_per_month") or {}
        assert "042024" in bpm
        assert bpm["042024"]["out_taxable"] == 1000.0
        # voucher-level invoices also re-extracted
        cnt = _mongo.gst_recon_invoices.count_documents(
            {"run_id": rid, "source": "books"})
        assert cnt == 1
    finally:
        s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# ---- Validate ---------------------------------------------------------------
def test_validate_endpoint(s, run_id):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs/{run_id}/validate")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
    d = s.get(f"{BASE_URL}/api/gst-recon/runs/{run_id}").json()
    assert d["validation"] is not None


# ---- C.3 summary math (books non-zero now) ---------------------------------
def test_summary_shape_and_math(s, run_id):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs/{run_id}/summary")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["fy"] == FY
    rows = summary["rows"]
    assert len(rows) == 12
    apr = rows[0]
    assert apr["period"] == "042024"
    assert apr["books_outward_taxable"] == 1000.0
    assert apr["r1_outward_taxable"] == 1000.0
    assert apr["r2b_itc_total"] == 180.0
    assert apr["var_books_vs_r1_outward"] == 0.0
    # totals
    t = summary["totals"]
    assert t["r1_outward_taxable"] == 1000.0
    assert t["books_outward_taxable"] == 1000.0


def test_summary_persisted_status_summarized(s, run_id):
    d = _run_doc(run_id)
    assert d["status"] == "summarized"
    assert isinstance(d.get("summary"), dict)


# ---- empty run summary still 12 zero rows ----------------------------------
def test_empty_run_summary_zero_rows(s):
    r = s.post(f"{BASE_URL}/api/gst-recon/runs",
               json={"client_id": CLIENT_ID, "fy": FY,
                     "name": "TEST_empty_summary"})
    rid = r.json()["id"]
    try:
        sm = s.post(f"{BASE_URL}/api/gst-recon/runs/{rid}/summary")
        assert sm.status_code == 200
        body = sm.json()
        assert len(body["rows"]) == 12
        for k, v in body["totals"].items():
            assert v == 0.0
    finally:
        s.delete(f"{BASE_URL}/api/gst-recon/runs/{rid}")


# ---- regression: clients + clause44 ----------------------------------------
def test_clients_endpoint_has_seeded_client(s):
    r = s.get(f"{BASE_URL}/api/clients")
    assert r.status_code == 200
    items = r.json().get("clients") if isinstance(r.json(), dict) else r.json()
    found = next((c for c in items if c.get("client_id") == CLIENT_ID), None)
    assert found and found.get("gstin") == GSTIN


def test_clause44_runs_endpoint_reachable(s):
    r = s.get(f"{BASE_URL}/api/runs")
    assert r.status_code == 200
