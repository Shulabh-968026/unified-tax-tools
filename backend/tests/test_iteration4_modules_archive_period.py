"""Iteration 4 tests:
- Module presence & imports (server split into 6 modules)
- POST /api/clients duplicate file_number -> 409 (scoped to user)
- Period regex validation in POST /api/runs (banana => 400; FY/Q/H formats => accepted)
- Archive flow: PATCH archived true/false + GET ?archived filter
- Case-insensitive division dedup on PATCH add_divisions
"""
import io
import json as jsonlib
import os
import sys
import time
import importlib

import pytest
import requests

# Allow importing backend modules directly (db, engine, etc.)
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://form3cd-pro.preview.emergentagent.com").rstrip("/")


# ---------- Module presence (server split) ----------
class TestModuleSplit:
    def test_modules_importable(self):
        # Each module should import cleanly
        for mod in ["db", "auth_module", "engine", "exports", "clients_module", "runs_module"]:
            m = importlib.import_module(mod)
            assert m is not None

    def test_engine_period_regex(self):
        from engine import is_valid_period
        # Accept
        assert is_valid_period("2023-24")
        assert is_valid_period("2023-2024")
        assert is_valid_period("FY 2023-24")
        assert is_valid_period("FY2023-24")
        assert is_valid_period("Q1 2023-24")
        assert is_valid_period("H1 2024-25")
        assert is_valid_period("Q4 FY2023-24")
        # Reject
        assert not is_valid_period("banana")
        assert not is_valid_period("")
        assert not is_valid_period("2023")
        assert not is_valid_period("FY abc")

    def test_routes_registered(self):
        # Confirm key endpoints exist (auth required => 401, not 404)
        for path in ["/api/clients", "/api/runs"]:
            r = requests.get(f"{BASE_URL}{path}")
            assert r.status_code in (401, 403), f"{path} returned {r.status_code}"


# ---------- Duplicate file_number ----------
class TestDuplicateFileNumber:
    def test_duplicate_same_user_returns_409(self, api_client):
        suffix = str(int(time.time() * 1000))
        fn = f"ITER4_DUP_{suffix}"
        payload = {"file_number": fn, "name": "Dup1", "type": "single", "divisions": []}
        r1 = api_client.post(f"{BASE_URL}/api/clients", json=payload)
        assert r1.status_code == 200, r1.text
        r2 = api_client.post(f"{BASE_URL}/api/clients", json={**payload, "name": "Dup2"})
        assert r2.status_code == 409, r2.text
        detail = (r2.json().get("detail") or "").lower()
        assert "file number" in detail or "duplicate" in detail or "already exists" in detail

    def test_same_file_number_different_user_now_blocked(self, api_client, base_url):
        # Iter6: workspace-shared. Same file_number across users must now 409.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_iter4_conftest", os.path.join(os.path.dirname(__file__), "conftest.py")
        )
        cf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cf)
        token2, _uid2 = cf._bootstrap_session()
        s2 = requests.Session()
        s2.headers.update({"Authorization": f"Bearer {token2}"})

        suffix = str(int(time.time() * 1000))
        fn = f"ITER6_CROSS_{suffix}"
        payload = {"file_number": fn, "name": "U1", "type": "single", "divisions": []}

        r1 = api_client.post(f"{BASE_URL}/api/clients", json=payload)
        assert r1.status_code == 200, r1.text

        r2 = s2.post(f"{BASE_URL}/api/clients", json={**payload, "name": "U2"})
        assert r2.status_code == 409, f"cross-user same file_number must now 409 (workspace-shared): {r2.text}"


# ---------- Period validation in /api/runs ----------
class TestRunPeriodValidation:
    def _make_client(self, api_client):
        suffix = str(int(time.time() * 1000))
        r = api_client.post(f"{BASE_URL}/api/clients", json={
            "file_number": f"ITER4_PER_{suffix}",
            "name": "PeriodTest",
            "type": "single",
            "divisions": [],
        })
        assert r.status_code == 200, r.text
        return r.json()["client_id"]

    def _upload(self, api_client, client_id, period, sample_files):
        with open(sample_files["json"], "rb") as fj, open(sample_files["xlsx"], "rb") as fx:
            files = {
                "accounting_json": ("sample.json", fj, "application/json"),
                "ledger_xlsx": ("sample.xlsx", fx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            }
            data = {"client_id": client_id, "period": period}
            return api_client.post(f"{BASE_URL}/api/runs", data=data, files=files)

    def test_period_banana_rejected(self, api_client, sample_files):
        client_id = self._make_client(api_client)
        r = self._upload(api_client, client_id, "banana", sample_files)
        assert r.status_code == 400, r.text
        assert "period" in (r.json().get("detail") or "").lower()

    @pytest.mark.parametrize("period", [
        "2023-24",
        "FY 2023-24",
        "FY2023-24",
        "Q1 2023-24",
        "H1 2024-25",
    ])
    def test_period_formats_accepted(self, api_client, sample_files, period):
        client_id = self._make_client(api_client)
        r = self._upload(api_client, client_id, period, sample_files)
        assert r.status_code == 200, f"period {period!r} should be accepted; got {r.status_code}: {r.text}"
        assert r.json().get("period") == period


# ---------- Archive flow ----------
class TestArchiveFlow:
    def test_archive_then_restore(self, api_client):
        suffix = str(int(time.time() * 1000))
        r = api_client.post(f"{BASE_URL}/api/clients", json={
            "file_number": f"ITER4_ARCH_{suffix}",
            "name": "ArchiveMe",
            "type": "single",
            "divisions": [],
        })
        assert r.status_code == 200, r.text
        cid = r.json()["client_id"]
        assert r.json()["archived"] is False

        # Archive
        rp = api_client.patch(f"{BASE_URL}/api/clients/{cid}", json={"archived": True})
        assert rp.status_code == 200, rp.text
        assert rp.json()["archived"] is True

        # Active list should NOT contain it
        ra = api_client.get(f"{BASE_URL}/api/clients", params={"archived": "false"})
        assert ra.status_code == 200
        assert all(c["client_id"] != cid for c in ra.json()["clients"])

        # Archived list SHOULD contain it
        rar = api_client.get(f"{BASE_URL}/api/clients", params={"archived": "true"})
        assert rar.status_code == 200
        assert any(c["client_id"] == cid for c in rar.json()["clients"])

        # Restore
        rr = api_client.patch(f"{BASE_URL}/api/clients/{cid}", json={"archived": False})
        assert rr.status_code == 200
        assert rr.json()["archived"] is False

        # Now active list contains it
        ra2 = api_client.get(f"{BASE_URL}/api/clients", params={"archived": "false"})
        assert any(c["client_id"] == cid for c in ra2.json()["clients"])


# ---------- Case-insensitive division dedup ----------
class TestDivisionDedup:
    def test_add_divisions_case_insensitive_no_dup(self, api_client):
        suffix = str(int(time.time() * 1000))
        r = api_client.post(f"{BASE_URL}/api/clients", json={
            "file_number": f"ITER4_DIV_{suffix}",
            "name": "MultiDedup",
            "type": "multi",
            "divisions": ["Alpha", "Beta"],
        })
        assert r.status_code == 200, r.text
        cid = r.json()["client_id"]
        assert len(r.json()["divisions"]) == 2

        # Try to add 'alpha' (different case) and 'Gamma' (new)
        rp = api_client.patch(f"{BASE_URL}/api/clients/{cid}", json={"add_divisions": ["alpha", "Gamma", "BETA"]})
        assert rp.status_code == 200, rp.text
        names = [d["name"] for d in rp.json()["divisions"]]
        # Only Gamma added; Alpha/Beta stay (no dup)
        assert len(names) == 3
        lower = [n.lower() for n in names]
        assert lower.count("alpha") == 1
        assert lower.count("beta") == 1
        assert lower.count("gamma") == 1
