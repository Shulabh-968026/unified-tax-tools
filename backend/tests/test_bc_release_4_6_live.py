"""Release 4.6 · BC Refinement Batch 1 — LIVE HTTP regression suite.

Verifies the deployed backend at REACT_APP_BACKEND_URL satisfies:

  R1.A  GET  /runs/{rid}/ledgers/export.csv   — split address columns
  R1.A  POST /runs/{rid}/ledgers/import.csv   — split + legacy backward compat
  R1.C  POST /runs/{rid}/offline-pdfs         — ZIP of valid PDFs + edge cases
  R2    GET  /runs/{rid}/analytics            — subheads array shape

Uses the QA bypass session (admin) and the seeded ABC Textile Mills run.
"""
from __future__ import annotations

import csv
import io
import os
import zipfile

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION_TOKEN = "qa_test_session_token_20260206_dev"
CLIENT_ID = "cli_ad137f29aebb"
COOKIES = {"session_token": SESSION_TOKEN}


# ---------------------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.cookies.update(COOKIES)
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def run_id(api):
    """Pick the first non-archived BC run for ABC Textile Mills."""
    r = api.get(f"{BASE_URL}/api/balance-confirmation/runs",
                params={"client_id": CLIENT_ID})
    assert r.status_code == 200, r.text
    runs = r.json()
    assert isinstance(runs, list) and runs, "No BC run for ABC Textile Mills"
    rid = runs[0]["id"]
    return rid


@pytest.fixture(scope="module")
def first_ledger_ids(api, run_id):
    r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers",
                params={"page": 1, "limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("rows") or body.get("items") or (body if isinstance(body, list) else [])
    assert rows, "No ledger rows returned for the seeded run"
    return [r["ledger_id"] for r in rows[:3]]


# ---------------------------------------------------------------------------- #
# R1.A · CSV export header
# ---------------------------------------------------------------------------- #
class TestCsvExport:
    def test_export_csv_returns_200(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers/export.csv")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("Content-Type", "").lower() \
            or "csv" in r.headers.get("Content-Type", "").lower()

    def test_export_header_has_split_address(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers/export.csv")
        assert r.status_code == 200
        # decode utf-8-sig to drop BOM
        text = r.content.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
        for col in ("address_line_1", "address_line_2", "city", "pincode"):
            assert col in header, f"Missing split-address column: {col} (header={header})"
        # must NOT have legacy single 'address' column
        assert "address" not in header, f"Legacy 'address' column still present: {header}"
        # other expected fields
        for col in ("ledger_id", "name", "head", "subhead", "email"):
            assert col in header, f"Expected column missing: {col}"


# ---------------------------------------------------------------------------- #
# R1.A · CSV import — split + legacy backward-compat
# ---------------------------------------------------------------------------- #
class TestCsvImport:
    def test_import_split_address_csv_persists(self, api, run_id, first_ledger_ids):
        lid = first_ledger_ids[0]
        # Fetch original to restore later
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers",
                    params={"page": 1, "limit": 200})
        rows = r.json().get("rows", [])
        original = next(x for x in rows if x["ledger_id"] == lid)
        orig_email = original.get("email", "")

        new_csv = (
            "ledger_id,email,address_line_1,address_line_2,city,pincode\n"
            f'{lid},TEST_qa@x.in,12 MG Road,Floor 3,Pune,411001\n'
        ).encode("utf-8-sig")
        files = {"file": ("import.csv", new_csv, "text/csv")}
        r = api.post(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers/import.csv",
                     files=files)
        assert r.status_code in (200, 201), r.text

        # Verify persistence via re-fetch
        r2 = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers",
                     params={"page": 1, "limit": 200})
        rows2 = r2.json().get("rows", [])
        updated = next(x for x in rows2 if x["ledger_id"] == lid)
        # split fields should be persisted (either at top level or under address_*)
        line1 = updated.get("address_line_1") or ""
        city = updated.get("city") or ""
        pin = str(updated.get("pincode") or "")
        assert "12 MG Road" in line1, f"address_line_1 not persisted: {updated}"
        assert city == "Pune", f"city not persisted: {updated}"
        assert pin == "411001", f"pincode not persisted: {updated}"
        assert updated.get("email") == "TEST_qa@x.in"

        # Restore original email so we don't pollute downstream tests.
        restore_csv = (
            "ledger_id,email\n"
            f'{lid},{orig_email}\n'
        ).encode("utf-8-sig")
        api.post(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers/import.csv",
                 files={"file": ("restore.csv", restore_csv, "text/csv")})

    def test_import_legacy_single_address_column(self, api, run_id, first_ledger_ids):
        """Legacy CSV with a single `address` column must still import without 5xx."""
        lid = first_ledger_ids[1]
        legacy = (
            "ledger_id,name,address\n"
            f'{lid},Legacy Co,"12 Old Road, Bldg A, Mumbai, 400001"\n'
        ).encode("utf-8-sig")
        files = {"file": ("legacy.csv", legacy, "text/csv")}
        r = api.post(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers/import.csv",
                     files=files)
        # Backward-compat: must not 5xx; accept 200/201/400-with-message gracefully
        assert r.status_code < 500, f"Legacy CSV crashed server: {r.status_code} {r.text[:300]}"


# ---------------------------------------------------------------------------- #
# R1.C · Offline PDFs ZIP + edge cases
# ---------------------------------------------------------------------------- #
class TestOfflinePdfs:
    def test_returns_zip_with_pdf_entries(self, api, run_id, first_ledger_ids):
        r = api.post(
            f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/offline-pdfs",
            json={"ledger_ids": first_ledger_ids},
        )
        assert r.status_code == 200, r.text
        assert "application/zip" in r.headers.get("Content-Type", "").lower()
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd.lower()
        assert ".zip" in cd.lower()

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert len(names) >= 1, "ZIP must contain at least one PDF"
        for n in names:
            data = zf.read(n)
            assert data.startswith(b"%PDF"), f"{n} is not a PDF (starts with {data[:8]})"
            assert len(data) >= 2048, f"{n} is suspiciously small: {len(data)}B"

    def test_400_when_ledger_ids_empty(self, api, run_id):
        r = api.post(
            f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/offline-pdfs",
            json={"ledger_ids": []},
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    def test_404_when_run_not_found(self, api):
        r = api.post(
            f"{BASE_URL}/api/balance-confirmation/runs/nonexistent_run_id_zzz/offline-pdfs",
            json={"ledger_ids": ["x"]},
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    def test_404_when_no_matching_ledger_ids(self, api, run_id):
        r = api.post(
            f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/offline-pdfs",
            json={"ledger_ids": ["bogus_ledger_id_aaa", "bogus_ledger_id_bbb"]},
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------- #
# R2 · Analytics subheads array shape
# ---------------------------------------------------------------------------- #
class TestAnalyticsSubheads:
    def test_analytics_returns_subheads(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/analytics")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "subheads" in body, f"subheads missing from analytics: {list(body.keys())}"
        rows = body["subheads"]
        assert isinstance(rows, list) and rows, "subheads array empty"

    def test_subhead_row_carries_required_fields(self, api, run_id):
        body = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/analytics").json()
        row = body["subheads"][0]
        for field in ("subhead", "head", "parent_group",
                      "count", "amount",
                      "audit_amount_pct", "response_amount_pct"):
            assert field in row, f"Field '{field}' missing in subhead row: {row}"


# ---------------------------------------------------------------------------- #
# Regression — pre-existing BC flows still respond
# ---------------------------------------------------------------------------- #
class TestPreExistingFlows:
    def test_list_runs_ok(self, api):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs",
                    params={"client_id": CLIENT_ID})
        assert r.status_code == 200

    def test_list_ledgers_ok(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/ledgers",
                    params={"page": 1, "limit": 5})
        assert r.status_code == 200

    def test_get_run_ok(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}")
        assert r.status_code == 200
        assert r.json().get("id")

    def test_generations_endpoint_ok(self, api, run_id):
        r = api.get(f"{BASE_URL}/api/balance-confirmation/runs/{run_id}/generations")
        assert r.status_code == 200
        body = r.json()
        assert "generations" in body and isinstance(body["generations"], list)
