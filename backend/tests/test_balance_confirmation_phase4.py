"""Balance Confirmation Phase 4 — Public recipient response loop.

Covers:
  - GET  /api/balance-confirmation/public/confirmation/{token} — public, no-auth, returns ctx + submitted_response
  - POST /api/balance-confirmation/public/confirmation/{token}/confirm — flips status to 'confirmed'
  - POST /api/balance-confirmation/public/confirmation/{token}/dispute — multipart with optional file
  - Telemetry guard: terminal status NOT downgraded by /track/pixel after confirm
  - Auditor: GET /runs/{rid}/responses (auth + decision filter + enrichment)
  - Auditor: GET /runs/{rid}/responses/{response_id}/attachment (auth + content-type)
  - Cascade: DELETE /runs/{rid} drops bc_responses
"""
import base64
import gzip
import io
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-tax-tools.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "qa_test_session_token_20260429_dev"
SEED_CLIENT = "cli_7f0b86b1ab0b"


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
def public_client():
    """A SEPARATE session — no cookie — to prove public endpoints don't require auth."""
    return requests.Session()


@pytest.fixture(scope="session")
def books_json_bytes():
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    async def _load():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        run = await db.gst_recon_runs.find_one({"client_id": SEED_CLIENT})
        rid = (run or {}).get("run_id") or (run or {}).get("id")
        doc = await db.gst_recon_books_raw.find_one({"run_id": rid}) if rid else await db.gst_recon_books_raw.find_one({})
        cli.close()
        return doc

    doc = asyncio.get_event_loop().run_until_complete(_load())
    if not doc or not doc.get("content_b64"):
        pytest.skip("No gst_recon_books_raw seed for SEED_CLIENT")
    return gzip.decompress(base64.b64decode(doc["content_b64"]))


@pytest.fixture(scope="module")
def loaded_run(auth_client, books_json_bytes):
    payload = {"client_id": SEED_CLIENT, "fy": "2024-25", "name": "TEST_BC_phase4"}
    r = auth_client.post(f"{API}/balance-confirmation/runs", json=payload, timeout=20)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    files = {"file": ("books.json", books_json_bytes, "application/json")}
    r = auth_client.post(f"{API}/balance-confirmation/runs/{rid}/upload-books", files=files, timeout=60)
    assert r.status_code == 200, r.text
    yield rid
    try:
        auth_client.delete(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
    except Exception:
        pass


def _pick_ledger(client, rid, idx=0):
    r = client.get(f"{API}/balance-confirmation/runs/{rid}/ledgers", timeout=20)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows, "No ledgers in run"
    return rows[idx]


# ============================ Public GET =====================================
class TestPublicGet:
    def test_public_get_no_auth_returns_ctx(self, public_client, auth_client, loaded_run):
        L = _pick_ledger(auth_client, loaded_run, 0)
        token = L["response_token"]
        r = public_client.get(f"{API}/balance-confirmation/public/confirmation/{token}", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Required fields
        for k in ("party_name", "contact_name", "closing_balance", "dr_cr",
                  "as_at_date", "fy", "client_name", "client_gstin",
                  "auditor_firm", "auditor_name", "confirmation_status",
                  "submitted_response"):
            assert k in data, f"missing key: {k}"
        # closing_balance is the abs() of stored balance
        assert data["closing_balance"] >= 0
        # dr_cr is one of the allowed labels
        assert data["dr_cr"] in ("Dr", "Cr", "")
        # client_name present
        assert isinstance(data["client_name"], str) and len(data["client_name"]) > 0
        # No submission yet
        assert data["submitted_response"] is None

    def test_public_get_unknown_token_404(self, public_client):
        r = public_client.get(f"{API}/balance-confirmation/public/confirmation/bogus-{uuid.uuid4()}", timeout=15)
        assert r.status_code == 404


# ============================ Public POST /confirm ===========================
class TestPublicConfirm:
    def test_confirm_flips_status_and_writes_response(self, public_client, auth_client, loaded_run):
        L = _pick_ledger(auth_client, loaded_run, 1)
        token = L["response_token"]
        body = {
            "responder_name": "Recipient One",
            "responder_email": "recipient1@example.com",
            "note": "All matches at our end.",
        }
        r = public_client.post(
            f"{API}/balance-confirmation/public/confirmation/{token}/confirm",
            json=body, timeout=15,
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["decision"] == "confirmed"
        assert out["responder_name"] == "Recipient One"
        assert out["ledger_id"] == L["ledger_id"]
        assert "uploaded_content_b64" not in out  # never echo file bytes

        # Ledger flipped to terminal
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/ledgers", timeout=20).json()["rows"]
        l2 = next(x for x in rows if x["ledger_id"] == L["ledger_id"])
        assert l2["confirmation_status"] == "confirmed"

        # GET now echoes submitted_response
        r2 = public_client.get(f"{API}/balance-confirmation/public/confirmation/{token}", timeout=15)
        assert r2.status_code == 200
        sr = r2.json()["submitted_response"]
        assert sr and sr["decision"] == "confirmed"
        assert sr["responder_email"] == "recipient1@example.com"

        # send-log row written
        log = auth_client.get(
            f"{API}/balance-confirmation/runs/{loaded_run}/send-log?ledger_id={L['ledger_id']}",
            timeout=15).json()
        resp_rows = [x for x in log["rows"] if x["kind"] == "response"]
        assert resp_rows and resp_rows[0]["status"] == "confirmed"

    def test_confirm_idempotent_replace(self, public_client, auth_client, loaded_run):
        # Re-submit on the SAME ledger from prior test: replace_one upserts; status stays terminal.
        L = _pick_ledger(auth_client, loaded_run, 1)
        token = L["response_token"]
        body = {"responder_name": "Recipient One v2", "responder_email": "r1@example.com", "note": "still ok"}
        r = public_client.post(
            f"{API}/balance-confirmation/public/confirmation/{token}/confirm",
            json=body, timeout=15,
        )
        assert r.status_code == 200, r.text
        sr = public_client.get(f"{API}/balance-confirmation/public/confirmation/{token}", timeout=15).json()["submitted_response"]
        assert sr["responder_name"] == "Recipient One v2"
        # Status still confirmed (terminal)
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/ledgers", timeout=20).json()["rows"]
        l2 = next(x for x in rows if x["ledger_id"] == L["ledger_id"])
        assert l2["confirmation_status"] == "confirmed"

    def test_pixel_does_not_downgrade_confirmed(self, public_client, auth_client, loaded_run):
        """Telemetry guard — confirmed is terminal."""
        L = _pick_ledger(auth_client, loaded_run, 1)
        token = L["response_token"]
        r = public_client.get(f"{API}/balance-confirmation/track/pixel/{token}.gif", timeout=15)
        assert r.status_code == 200
        # Status MUST still be 'confirmed', not 'opened'
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/ledgers", timeout=20).json()["rows"]
        l2 = next(x for x in rows if x["ledger_id"] == L["ledger_id"])
        assert l2["confirmation_status"] == "confirmed", f"pixel downgraded terminal status to {l2['confirmation_status']}"


# ============================ Public POST /dispute ===========================
class TestPublicDispute:
    def test_dispute_empty_reason_400(self, public_client, auth_client, loaded_run):
        L = _pick_ledger(auth_client, loaded_run, 2)
        token = L["response_token"]
        # Empty reason field — multipart
        r = public_client.post(
            f"{API}/balance-confirmation/public/confirmation/{token}/dispute",
            data={"reason": ""},
            timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_dispute_with_attachment(self, public_client, auth_client, loaded_run):
        L = _pick_ledger(auth_client, loaded_run, 2)
        token = L["response_token"]
        pdf_bytes = b"%PDF-1.4\n%fake-test-pdf\n%%EOF\n"
        r = public_client.post(
            f"{API}/balance-confirmation/public/confirmation/{token}/dispute",
            data={
                "responder_name": "Disputer",
                "responder_email": "disp@example.com",
                "their_balance": "12345.67",
                "their_dr_cr": "Cr",
                "reason": "Our books show a different balance — see attached statement.",
            },
            files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["decision"] == "disputed"
        assert out["uploaded_filename"] == "statement.pdf"
        assert out["uploaded_size"] == len(pdf_bytes)
        assert "uploaded_content_b64" not in out

        # Ledger flipped
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/ledgers", timeout=20).json()["rows"]
        l2 = next(x for x in rows if x["ledger_id"] == L["ledger_id"])
        assert l2["confirmation_status"] == "disputed"

    def test_dispute_oversize_413(self, public_client, auth_client, loaded_run):
        L = _pick_ledger(auth_client, loaded_run, 3)
        token = L["response_token"]
        big = b"x" * (8 * 1024 * 1024 + 100)  # 8MB+1
        r = public_client.post(
            f"{API}/balance-confirmation/public/confirmation/{token}/dispute",
            data={"reason": "Too big to attach but trying anyway."},
            files={"file": ("big.bin", big, "application/octet-stream")},
            timeout=60,
        )
        assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"


# ============================ Auditor-side responses =========================
class TestAuditorResponses:
    def test_list_responses_requires_auth(self, public_client, loaded_run):
        r = public_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses", timeout=15)
        assert r.status_code == 401, r.status_code

    def test_list_responses_enriched(self, auth_client, loaded_run):
        r = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "rows" in data and "count" in data
        assert data["count"] >= 2  # confirmed + disputed
        for row in data["rows"]:
            assert "ledger_name" in row
            assert "our_balance" in row
            assert "our_dr_cr" in row
            assert "uploaded_content_b64" not in row

    def test_list_responses_filter(self, auth_client, loaded_run):
        r = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses?decision=confirmed", timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert all(x["decision"] == "confirmed" for x in rows)
        r2 = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses?decision=disputed", timeout=15)
        rows2 = r2.json()["rows"]
        assert all(x["decision"] == "disputed" for x in rows2)
        assert len(rows2) >= 1

    def test_attachment_download_pdf(self, auth_client, loaded_run):
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses?decision=disputed", timeout=15).json()["rows"]
        with_file = [x for x in rows if x.get("uploaded_filename")]
        assert with_file, "no disputed response had an attachment"
        rid_resp = with_file[0]["response_id"]
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{loaded_run}/responses/{rid_resp}/attachment",
            timeout=15,
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert b"%PDF" in r.content

    def test_attachment_download_requires_auth(self, public_client, auth_client, loaded_run):
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses?decision=disputed", timeout=15).json()["rows"]
        rid_resp = rows[0]["response_id"]
        r = public_client.get(
            f"{API}/balance-confirmation/runs/{loaded_run}/responses/{rid_resp}/attachment",
            timeout=15,
        )
        assert r.status_code == 401

    def test_attachment_404_when_no_file(self, auth_client, loaded_run):
        # The CONFIRMED response never had a file
        rows = auth_client.get(f"{API}/balance-confirmation/runs/{loaded_run}/responses?decision=confirmed", timeout=15).json()["rows"]
        assert rows
        r = auth_client.get(
            f"{API}/balance-confirmation/runs/{loaded_run}/responses/{rows[0]['response_id']}/attachment",
            timeout=15,
        )
        assert r.status_code == 404


# ============================ Cascade delete =================================
class TestCascadeDelete:
    def test_delete_run_cascades_bc_responses(self, auth_client, books_json_bytes):
        # Make a fresh run + a confirm, then delete and verify bc_responses is empty for that run
        payload = {"client_id": SEED_CLIENT, "fy": "2024-25", "name": "TEST_BC_phase4_cascade"}
        rid = auth_client.post(f"{API}/balance-confirmation/runs", json=payload, timeout=20).json()["id"]
        try:
            files = {"file": ("books.json", books_json_bytes, "application/json")}
            auth_client.post(f"{API}/balance-confirmation/runs/{rid}/upload-books", files=files, timeout=60)
            L = _pick_ledger(auth_client, rid, 0)
            token = L["response_token"]
            r = requests.post(
                f"{API}/balance-confirmation/public/confirmation/{token}/confirm",
                json={"responder_name": "X", "responder_email": "x@y.com", "note": ""},
                timeout=15,
            )
            assert r.status_code == 200

            # Confirm one row exists
            d = auth_client.get(f"{API}/balance-confirmation/runs/{rid}/responses", timeout=15).json()
            assert d["count"] >= 1

            # Delete run
            r = auth_client.delete(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
            assert r.status_code == 200

            # Direct DB check
            from motor.motor_asyncio import AsyncIOMotorClient
            import asyncio
            async def _count():
                cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
                db = cli[os.environ["DB_NAME"]]
                n = await db.bc_responses.count_documents({"run_id": rid})
                cli.close()
                return n
            n = asyncio.get_event_loop().run_until_complete(_count())
            assert n == 0, f"bc_responses cascade leaked {n} rows"
        finally:
            try:
                auth_client.delete(f"{API}/balance-confirmation/runs/{rid}", timeout=15)
            except Exception:
                pass
