"""
Phase C.2 smoke tests — re-verify Phase C.1 backend scope acceptance on all
6 modules with TEST_FY=2099-00 and clean up afterwards.  Heavy 9-test C.1
suite already lives in test_phase_c1_scope_runs.py (green in iteration_27);
this file is intentionally minimal.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-tax-tools.preview.emergentagent.com").rstrip("/")
TOKEN = "qa_test_session_token_20260206_dev"
MULTI_DIV_CLIENT = "cli_c5d02541264c"
SINGLE_DIV_CLIENT = "cli_ad137f29aebb"
TEST_FY = "2099-00"
TIRIUPPUR_DIV = "div_2fe99d2ccf"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", TOKEN)
    s.headers["Content-Type"] = "application/json"
    return s


# ---------- BC scope acceptance + idempotency ----------

class TestBalanceConfirmationScope:
    """POST /balance-confirmation/runs — consolidation vs division on multi-div."""

    def test_consolidation_scope(self, client):
        r = client.post(
            f"{BASE_URL}/api/balance-confirmation/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY, "scope_kind": "consolidation"},
        )
        assert r.status_code in (200, 201), r.text
        d = r.json()
        assert d.get("scope_kind") == "consolidation"
        assert d.get("scope_key") == "consolidation"
        assert d.get("scope_label") == "Consolidation"
        assert d.get("division_ids") in ([], None)

    def test_division_scope_idempotent(self, client):
        payload = {
            "client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
            "scope_kind": "division", "division_ids": [TIRIUPPUR_DIV],
        }
        r1 = client.post(f"{BASE_URL}/api/balance-confirmation/runs", json=payload)
        assert r1.status_code in (200, 201), r1.text
        d1 = r1.json()
        assert d1.get("scope_kind") == "division"
        assert d1.get("scope_key") == f"div_{TIRIUPPUR_DIV}"
        # Re-POST same payload → same id (idempotent)
        r2 = client.post(f"{BASE_URL}/api/balance-confirmation/runs", json=payload)
        assert r2.status_code in (200, 201)
        d2 = r2.json()
        assert d1.get("id") == d2.get("id"), "Re-POST not idempotent"

    def test_consolidation_and_division_distinct_docs(self, client):
        c = client.post(
            f"{BASE_URL}/api/balance-confirmation/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY, "scope_kind": "consolidation"},
        ).json()
        d = client.post(
            f"{BASE_URL}/api/balance-confirmation/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
                  "scope_kind": "division", "division_ids": [TIRIUPPUR_DIV]},
        ).json()
        assert c.get("id") != d.get("id"), "Consolidation and division share same doc"


# ---------- 1-shot smoke per remaining module ----------

class TestOtherModulesScopeAcceptance:
    """Phase C.1 already verified — confirm POST still accepts scope payload."""

    def test_fixed_assets(self, client):
        r = client.post(
            f"{BASE_URL}/api/fixed-assets/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY, "scope_kind": "consolidation"},
        )
        assert r.status_code in (200, 201), r.text
        assert r.json().get("scope_kind") == "consolidation"

    def test_gst_recon(self, client):
        # gst_recon expects gstin_group scope; consolidation may be rejected per grain.
        # Just confirm the endpoint accepts the field without 500.
        r = client.post(
            f"{BASE_URL}/api/gst-recon/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY, "scope_kind": "consolidation"},
        )
        assert r.status_code < 500, r.text  # 200/201 or validation 4xx are fine; never 5xx

    def test_fin_statement(self, client):
        # fin_statement requires fy + fy_start + fy_end
        r = client.post(
            f"{BASE_URL}/api/fin-statement/runs",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY,
                  "fy_start": "2099-04-01", "fy_end": "2100-03-31",
                  "scope_kind": "consolidation"},
        )
        assert r.status_code in (200, 201), r.text
        assert r.json().get("scope_kind") == "consolidation"

    def test_msme_sessions(self, client):
        r = client.post(
            f"{BASE_URL}/api/msme/sessions",
            json={"client_id": MULTI_DIV_CLIENT, "fy": TEST_FY, "scope_kind": "consolidation"},
        )
        assert r.status_code in (200, 201), r.text
        d = r.json()
        # session_summary exposes scope_kind on the response
        assert d.get("scope_kind") == "consolidation", f"got: {list(d.keys())}"


# ---------- MSME session_summary scope_* exposure ----------

class TestMsmeScopeFieldsExposed:
    def test_msme_list_exposes_scope_fields(self, client):
        r = client.get(f"{BASE_URL}/api/msme/sessions", params={"client_id": MULTI_DIV_CLIENT})
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        if rows:
            row = rows[0]
            for k in ("scope_kind", "scope_label", "scope_key", "division_ids"):
                assert k in row, f"missing key {k} in MSME session_summary; have {list(row.keys())}"


# ---------- Library status regression smoke ----------

class TestLibraryStatusRegression:
    def test_library_status_carries_attribution(self, client):
        # Library status requires `period` query param
        r = client.get(
            f"{BASE_URL}/api/library/clients/{MULTI_DIV_CLIENT}/status",
            params={"period": "FY 2025-26"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        files = data.get("files") if isinstance(data, dict) else data
        assert isinstance(files, list) and len(files) > 0
        sample = files[0]
        # default_attribution + division_ids must persist (Phase B regression).
        assert "default_attribution" in sample, f"missing default_attribution; have {list(sample.keys())}"
        assert "division_ids" in sample


# ---------- Cleanup TEST_FY runs ----------

@pytest.fixture(scope="module", autouse=True)
def cleanup(client):
    yield
    # best-effort: list each module and delete TEST_FY rows if delete endpoints exist
    for mod in ("balance-confirmation", "fixed-assets", "gst-recon", "fin-statement"):
        try:
            r = client.get(f"{BASE_URL}/api/{mod}/runs", params={"client_id": MULTI_DIV_CLIENT})
            if r.status_code == 200:
                for row in (r.json() or []):
                    if (row.get("fy") or "") == TEST_FY:
                        rid = row.get("id") or row.get("run_id")
                        if rid:
                            client.delete(f"{BASE_URL}/api/{mod}/runs/{rid}")
        except Exception:
            pass
    try:
        r = client.get(f"{BASE_URL}/api/msme/sessions", params={"client_id": MULTI_DIV_CLIENT})
        if r.status_code == 200:
            for row in (r.json() or []):
                if (row.get("fy") or "") == TEST_FY:
                    sid = row.get("session_id") or row.get("id")
                    if sid:
                        client.delete(f"{BASE_URL}/api/msme/sessions/{sid}")
    except Exception:
        pass
