"""Balance Confirmation utility — Phase 1 + Phase 2 backend regression tests.

Covers:
  - Run CRUD with auth gate + 400 validation
  - Tally JSON books upload (classification, balance/dr-cr, response_token)
  - Ledger workbench (filter by category + missing_email, PATCH, summary recompute)
  - CSV export+import round-trip (BOM + UTF-8, ledger_id + name fallback match)
  - Email templates auto-seed (3 defaults), custom CRUD, default-protect on delete
  - Authorization PDF upload/get/file/delete (PDF-only validation)
  - Authorization Word template (.docx) generation (>10KB, openable)
"""
import base64
import gzip
import io
import json
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-tax-tools.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "qa_test_session_token_20260429_dev"
SEED_CLIENT = "cli_7f0b86b1ab0b"          # Allman Knitwear (has gst_recon_books_raw)
EMPTY_CLIENT = "cli_ad137f29aebb"          # ABC Textile Mills (clean)


# ============================ Fixtures =======================================
@pytest.fixture(scope="session")
def auth_client():
    s = requests.Session()
    s.cookies.set("session_token", TOKEN, domain="unified-tax-tools.preview.emergentagent.com")
    s.headers.update({"Accept": "application/json"})
    r = s.get(f"{API}/auth/me", timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Auth bypass token rejected ({r.status_code}); re-seed via /app/memory/test_credentials.md")
    return s


@pytest.fixture(scope="session")
def books_json_bytes():
    """Pull Tally JSON from gst_recon_books_raw and return decoded bytes."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    async def _load():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        # books_raw rows are keyed by run_id; find any run for SEED_CLIENT first
        run = await db.gst_recon_runs.find_one({"client_id": SEED_CLIENT})
        rid = (run or {}).get("run_id") or (run or {}).get("id")
        if rid:
            doc = await db.gst_recon_books_raw.find_one({"run_id": rid})
        else:
            doc = await db.gst_recon_books_raw.find_one({})
        cli.close()
        return doc

    doc = asyncio.get_event_loop().run_until_complete(_load())
    if not doc or not doc.get("content_b64"):
        pytest.skip("No gst_recon_books_raw seed for SEED_CLIENT")
    raw = gzip.decompress(base64.b64decode(doc["content_b64"]))
    # Quick sanity — must have ledgers
    parsed = json.loads(raw)
    assert isinstance(parsed.get("ledgers"), list) and len(parsed["ledgers"]) > 0
    return raw


@pytest.fixture(scope="session")
def created_run(auth_client):
    payload = {"client_id": SEED_CLIENT, "fy": "2024-25", "name": "TEST_BC_phase12_regression"}
    r = auth_client.post(f"{API}/balance-confirmation/runs", json=payload, timeout=20)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    yield rid
    # Cleanup
    try:
        auth_client.delete(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
    except Exception:
        pass


# ============================ Auth + Run CRUD ================================
class TestRunsCrud:
    def test_auth_gate_runs_list(self):
        r = requests.get(f"{API}/balance-confirmation/runs", timeout=15)
        assert r.status_code in (401, 403)

    def test_create_run_missing_client_id(self, auth_client):
        r = auth_client.post(f"{API}/balance-confirmation/runs", json={"fy": "2024-25"}, timeout=15)
        # FastAPI/Pydantic returns 422 for missing required field
        assert r.status_code in (400, 422), r.text

    def test_create_run_missing_fy(self, auth_client):
        r = auth_client.post(f"{API}/balance-confirmation/runs",
                             json={"client_id": SEED_CLIENT, "fy": ""}, timeout=15)
        assert r.status_code == 400, r.text
        assert "fy" in r.text.lower()

    def test_create_run_empty_client_id(self, auth_client):
        r = auth_client.post(f"{API}/balance-confirmation/runs",
                             json={"client_id": "", "fy": "2024-25"}, timeout=15)
        assert r.status_code == 400

    def test_runs_list_filter_by_client(self, auth_client, created_run):
        r = auth_client.get(f"{API}/balance-confirmation/runs?client_id={SEED_CLIENT}", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert any(d["id"] == created_run for d in rows)

    def test_get_run_returns_with_summary_field(self, auth_client, created_run):
        r = auth_client.get(f"{API}/balance-confirmation/runs/{created_run}", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == created_run
        assert d["client_id"] == SEED_CLIENT
        assert d["fy"] == "2024-25"
        # as_at_date defaulted to FY end
        assert d["as_at_date"] == "2025-03-31"
        assert "summary" in d  # may be None until books uploaded

    def test_get_run_404(self, auth_client):
        r = auth_client.get(f"{API}/balance-confirmation/runs/{uuid.uuid4()}", timeout=15)
        assert r.status_code == 404


# ============================ Books JSON upload ==============================
class TestBooksUpload:
    def test_upload_books_classifies_ledgers(self, auth_client, created_run, books_json_bytes):
        files = {"file": ("books.json", books_json_bytes, "application/json")}
        r = auth_client.post(
            f"{API}/balance-confirmation/runs/{created_run}/upload-books",
            files=files, timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Expected split per problem statement: 195 ledgers (58 receivable, 46 payable, 2 bank, 89 other)
        assert data["ledger_count"] == 195, f"Expected 195 ledgers, got {data['ledger_count']}"
        s = data["summary"]
        assert s["total"] == 195
        c = s["categories"]
        assert c["trade_receivable"]["count"] == 58
        assert c["trade_payable"]["count"] == 46
        assert c["bank"]["count"] == 2
        assert c["other"]["count"] == 89

    def test_run_status_now_ingested(self, auth_client, created_run):
        r = auth_client.get(f"{API}/balance-confirmation/runs/{created_run}", timeout=15)
        d = r.json()
        assert d["status"] == "ingested"
        assert d["source_filename"] == "books.json"

    def test_ledgers_have_response_token_and_balances(self, auth_client, created_run):
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers", timeout=20)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 195
        # Every ledger must carry UUID-shaped response_token and dr_cr indicator
        sample = rows[0]
        assert sample.get("response_token") and len(sample["response_token"]) >= 16
        assert "closing_balance" in sample and isinstance(sample["closing_balance"], (int, float))
        assert sample.get("dr_cr") in ("dr", "cr", "")
        # All tokens unique
        tokens = {r["response_token"] for r in rows}
        assert len(tokens) == 195

    def test_upload_books_invalid_json(self, auth_client, created_run):
        # Should NOT corrupt the existing run: send a malformed file under a fresh run
        # to avoid wiping the seeded run.
        new = auth_client.post(f"{API}/balance-confirmation/runs",
                               json={"client_id": SEED_CLIENT, "fy": "2024-25",
                                     "name": "TEST_BC_invalid_upload"}, timeout=15)
        rid2 = new.json()["id"]
        try:
            files = {"file": ("bad.json", b"not-json{", "application/json")}
            r = auth_client.post(f"{API}/balance-confirmation/runs/{rid2}/upload-books",
                                 files=files, timeout=20)
            assert r.status_code == 400
            assert "invalid" in r.text.lower() or "books json" in r.text.lower()
        finally:
            auth_client.delete(f"{API}/balance-confirmation/runs/{rid2}")


# ============================ Ledgers workbench ==============================
class TestLedgersWorkbench:
    def test_filter_by_category(self, auth_client, created_run):
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers?category=trade_receivable",
            timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 58
        assert all(L["category"] == "trade_receivable" for L in rows)

    def test_filter_missing_email(self, auth_client, created_run):
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers?missing_email=true",
            timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        # All ledgers start with empty email → all 195 missing
        assert len(rows) == 195
        assert all(L.get("email", "") == "" for L in rows)

    def test_patch_ledger_email_and_summary_recomputes(self, auth_client, created_run):
        rows = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers?category=trade_receivable",
            timeout=15).json()["rows"]
        target = rows[0]
        lid = target["ledger_id"]
        patch = {"email": "TEST_party@example.com",
                 "cc_emails": ["TEST_cc@example.com"],
                 "contact_name": "Mr. Test"}
        r = auth_client.patch(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/{lid}",
            json=patch, timeout=15)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["email"] == "TEST_party@example.com"
        assert updated["cc_emails"] == ["TEST_cc@example.com"]
        assert updated["contact_name"] == "Mr. Test"
        # Verify summary.with_email got bumped
        run = auth_client.get(f"{API}/balance-confirmation/runs/{created_run}", timeout=15).json()
        assert run["summary"]["with_email"] >= 1
        assert run["summary"]["categories"]["trade_receivable"]["with_email"] >= 1

    def test_patch_ledger_invalid_category(self, auth_client, created_run):
        rows = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers", timeout=15).json()["rows"]
        lid = rows[0]["ledger_id"]
        r = auth_client.patch(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/{lid}",
            json={"category": "garbage_value"}, timeout=15)
        assert r.status_code == 400

    def test_patch_ledger_404(self, auth_client, created_run):
        r = auth_client.patch(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/{uuid.uuid4()}",
            json={"email": "x@y.com"}, timeout=15)
        assert r.status_code == 404


# ============================ CSV export / import ============================
class TestCsvRoundtrip:
    def test_export_csv_has_bom_and_columns(self, auth_client, created_run):
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/export.csv", timeout=20)
        assert r.status_code == 200
        assert r.headers["content-type"].lower().startswith("text/csv")
        body = r.content
        # UTF-8 BOM
        assert body[:3] == b"\xef\xbb\xbf", f"Missing UTF-8 BOM, got {body[:3]!r}"
        text = body.decode("utf-8-sig")
        first_line = text.splitlines()[0]
        for col in ("ledger_id", "name", "closing_balance", "email"):
            assert col in first_line, f"Column {col} missing in CSV header"

    def test_import_csv_matches_by_ledger_id_and_by_name(self, auth_client, created_run):
        # Pull two ledgers
        rows = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers", timeout=15).json()["rows"]
        a = rows[10]
        b = rows[20]
        # Build CSV: row1 by ledger_id, row2 by name only, row3 unknown
        csv_text = (
            "ledger_id,name,email,cc_emails,contact_name\n"
            f"{a['ledger_id']},,TEST_a@example.com,,Contact A\n"
            f",\"{b['name']}\",TEST_b@example.com,TEST_b_cc@example.com;TEST_b_cc2@example.com,Contact B\n"
            f",DEFINITELY_NOT_A_LEDGER_NAME_xyz,TEST_no@example.com,,\n"
        )
        files = {"file": ("emails.csv", csv_text.encode("utf-8-sig"), "text/csv")}
        r = auth_client.post(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/import.csv",
            files=files, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rows_in_csv"] == 3
        assert d["matched"] == 2, f"Expected 2 matched, got {d}"
        assert any("DEFINITELY_NOT_A_LEDGER_NAME" in n for n in d["not_found"])

        # Verify persistence
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers/{a['ledger_id']}",
            timeout=15)
        # No GET-by-id endpoint — fetch list and find
        rows2 = auth_client.get(
            f"{API}/balance-confirmation/runs/{created_run}/ledgers", timeout=15).json()["rows"]
        idx = {x["ledger_id"]: x for x in rows2}
        assert idx[a["ledger_id"]]["email"] == "TEST_a@example.com"
        # Find b by name
        b_match = [x for x in rows2 if x["name"] == b["name"]][0]
        assert b_match["email"] == "TEST_b@example.com"
        assert "TEST_b_cc@example.com" in b_match["cc_emails"]


# ============================ Templates =====================================
class TestTemplates:
    def test_default_templates_auto_seed(self, auth_client):
        r = auth_client.get(f"{API}/balance-confirmation/templates", timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        kinds = {row["kind"] for row in rows if row.get("is_default")}
        assert {"customer", "vendor", "bank"}.issubset(kinds), f"Defaults missing: got {kinds}"

    def test_default_templates_idempotent(self, auth_client):
        rows1 = auth_client.get(f"{API}/balance-confirmation/templates", timeout=15).json()["rows"]
        defaults_count_1 = len([t for t in rows1 if t.get("is_default")])
        # Call again
        rows2 = auth_client.get(f"{API}/balance-confirmation/templates", timeout=15).json()["rows"]
        defaults_count_2 = len([t for t in rows2 if t.get("is_default")])
        assert defaults_count_1 == defaults_count_2 == 3

    def test_default_template_has_assureai_green(self, auth_client):
        rows = auth_client.get(f"{API}/balance-confirmation/templates?kind=customer", timeout=15).json()["rows"]
        cust = [t for t in rows if t.get("is_default") and t["kind"] == "customer"][0]
        assert "#047857" in cust["html_body"]

    def test_create_custom_template_then_patch_then_delete(self, auth_client):
        # Create
        payload = {
            "kind": "customer", "name": "TEST_Custom_Customer",
            "subject": "TEST subject {{client_name}}",
            "html_body": "<p>Hi {{contact_name_or_party}}</p>",
        }
        r = auth_client.post(f"{API}/balance-confirmation/templates", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        tid = r.json()["template_id"]
        assert r.json()["is_default"] is False

        # Patch
        payload["name"] = "TEST_Custom_Customer_v2"
        r = auth_client.patch(f"{API}/balance-confirmation/templates/{tid}",
                              json=payload, timeout=15)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Custom_Customer_v2"

        # Delete
        r = auth_client.delete(f"{API}/balance-confirmation/templates/{tid}", timeout=15)
        assert r.status_code == 200
        assert r.json().get("deleted") is True

    def test_delete_default_rejected(self, auth_client):
        rows = auth_client.get(f"{API}/balance-confirmation/templates", timeout=15).json()["rows"]
        default = [t for t in rows if t.get("is_default")][0]
        r = auth_client.delete(
            f"{API}/balance-confirmation/templates/{default['template_id']}", timeout=15)
        assert r.status_code == 400
        assert "default" in r.text.lower()

    def test_create_invalid_kind(self, auth_client):
        r = auth_client.post(f"{API}/balance-confirmation/templates",
                             json={"kind": "alien", "name": "x", "subject": "y", "html_body": "z"},
                             timeout=15)
        assert r.status_code == 400


# ============================ Authorization PDF + Word =======================
class TestAuthorization:
    def test_word_template_returns_valid_docx(self, auth_client):
        r = auth_client.get(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization/template.docx",
            timeout=20)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "wordprocessingml" in ct or "officedocument" in ct
        assert len(r.content) > 10_000, f"docx too small: {len(r.content)} bytes"
        # Open with python-docx to validate it's a real document
        try:
            from docx import Document
            doc = Document(io.BytesIO(r.content))
            assert len(doc.paragraphs) > 5
        except ImportError:
            pytest.skip("python-docx not available in this env")

    def test_upload_authorization_rejects_non_pdf(self, auth_client):
        files = {"file": ("not_a_pdf.txt", b"hello world", "text/plain")}
        r = auth_client.post(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization",
            files=files, timeout=15)
        assert r.status_code == 400

    def test_upload_get_download_delete_pdf_cycle(self, auth_client):
        # Minimal valid-ish PDF byte signature
        pdf_bytes = b"%PDF-1.4\n%\xc7\xec\x8f\xa2\n" + b"x" * 1024 + b"\n%%EOF\n"
        files = {"file": ("TEST_auth.pdf", pdf_bytes, "application/pdf")}
        r = auth_client.post(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization",
            files=files, timeout=15)
        assert r.status_code == 200, r.text
        meta = r.json()
        assert meta["client_id"] == SEED_CLIENT
        assert meta["filename"] == "TEST_auth.pdf"
        assert meta["size"] == len(pdf_bytes)

        # GET metadata
        r = auth_client.get(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization", timeout=15)
        assert r.status_code == 200
        m = r.json()
        assert m and m["filename"] == "TEST_auth.pdf"

        # Stream file
        r = auth_client.get(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization/file", timeout=15)
        assert r.status_code == 200
        assert r.content == pdf_bytes
        assert r.headers["content-type"].startswith("application/pdf")

        # Delete
        r = auth_client.delete(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization", timeout=15)
        assert r.status_code == 200

        # GET file → now 404
        r = auth_client.get(
            f"{API}/balance-confirmation/clients/{SEED_CLIENT}/authorization/file", timeout=15)
        assert r.status_code == 404


# ============================ Cascade delete =================================
class TestCascadeDelete:
    def test_delete_run_cascades_ledgers(self, auth_client, books_json_bytes):
        # Create dedicated run, upload, then delete
        r = auth_client.post(f"{API}/balance-confirmation/runs",
                             json={"client_id": SEED_CLIENT, "fy": "2024-25",
                                   "name": "TEST_BC_cascade_delete"}, timeout=15)
        rid = r.json()["id"]
        files = {"file": ("books.json", books_json_bytes, "application/json")}
        up = auth_client.post(
            f"{API}/balance-confirmation/runs/{rid}/upload-books", files=files, timeout=60)
        assert up.status_code == 200
        # Verify ledgers exist
        rows = auth_client.get(
            f"{API}/balance-confirmation/runs/{rid}/ledgers", timeout=15).json()["rows"]
        assert len(rows) == 195
        # Delete run
        d = auth_client.delete(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
        assert d.status_code == 200
        # Verify run is gone
        r = auth_client.get(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
        assert r.status_code == 404
        # Verify ledger query returns 404 (run check happens first)
        r = auth_client.get(f"{API}/balance-confirmation/runs/{rid}/ledgers", timeout=15)
        assert r.status_code == 404
