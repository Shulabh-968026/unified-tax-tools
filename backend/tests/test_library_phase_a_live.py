"""Library Phase A — end-to-end backend tests.

Covers the file-upload → version → outdated-detect → rerun cycle.

Path: BASE_URL/api/library/...
Path: BASE_URL/api/runs/{run_id}/rerun

These tests use a unique `FIXTURE_LIB_<uuid>` client so the session-end
auto-cleanup in conftest drops them on teardown.
"""
import json
import uuid

import pytest
import requests

from tests.conftest import BASE_URL


def _hdr(client_fixture):
    return client_fixture["headers"]


@pytest.fixture(scope="module")
def lib_client(auth_headers, sample_files):
    """Spin up an isolated client + base session for the test module."""
    fno = f"FIXTURE_LIB_{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(
        f"{BASE_URL}/api/clients",
        headers=auth_headers,
        # Match the JSON's company name so the cross-client validation
        # passes (the books fixture is for ABC Textile Mills).
        json={"name": "ABC Textile Mills", "file_number": fno, "type": "single"},
    )
    assert r.status_code == 200, r.text
    return {
        "client_id": r.json()["client_id"],
        "headers": auth_headers,
        "files": sample_files,
    }


# ----------------------------------------------------------------------
def test_catalog_returns_14_file_types(lib_client):
    r = requests.get(f"{BASE_URL}/api/library/catalog", headers=_hdr(lib_client))
    assert r.status_code == 200
    types = r.json()["file_types"]
    assert len(types) == 14
    keys = {t["key"] for t in types}
    assert {"books_json", "ledger_mapping_xlsx", "form_3cd_prior_json", "itr_prior_json"}.issubset(keys)


def test_status_initially_all_missing(lib_client):
    r = requests.get(
        f"{BASE_URL}/api/library/clients/{lib_client['client_id']}/status",
        headers=_hdr(lib_client), params={"period": "2023-24"},
    )
    assert r.status_code == 200
    body = r.json()
    assert all(not f["uploaded"] for f in body["files"])
    # All modules should be flagged missing — no files uploaded yet.
    assert all(m["missing"] for m in body["modules"])


def test_upload_books_json_v1(lib_client):
    with open(lib_client["files"]["json"], "rb") as f:
        r = requests.post(
            f"{BASE_URL}/api/library/upload",
            headers=_hdr(lib_client),
            files={"file": ("books.json", f, "application/json")},
            data={"client_id": lib_client["client_id"], "period": "2023-24",
                  "file_type": "books_json"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["file"]["version_no"] == 1
    assert r.json()["file"]["is_current"] is True
    pytest.lib_books_v1 = r.json()["file"]["file_id"]


def test_upload_xlsx_v1(lib_client):
    with open(lib_client["files"]["xlsx"], "rb") as f:
        r = requests.post(
            f"{BASE_URL}/api/library/upload",
            headers=_hdr(lib_client),
            files={"file": ("ledger.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"client_id": lib_client["client_id"], "period": "2023-24",
                  "file_type": "ledger_mapping_xlsx"},
        )
    assert r.status_code == 200, r.text
    pytest.lib_xlsx_v1 = r.json()["file"]["file_id"]


def test_status_after_uploads_books_xlsx_present(lib_client):
    r = requests.get(
        f"{BASE_URL}/api/library/clients/{lib_client['client_id']}/status",
        headers=_hdr(lib_client), params={"period": "2023-24"},
    )
    body = r.json()
    file_map = {f["key"]: f for f in body["files"]}
    assert file_map["books_json"]["uploaded"] is True
    assert file_map["books_json"]["version_no"] == 1
    assert file_map["ledger_mapping_xlsx"]["uploaded"] is True
    # Clause 44 still shows missing because no run pinned yet.
    clause44 = next(m for m in body["modules"] if m["module_key"] == "clause44")
    assert clause44["missing"] is True


def test_idempotent_reupload_no_version_bump(lib_client):
    # Re-uploading the same bytes returns the same row, no new version.
    with open(lib_client["files"]["json"], "rb") as f:
        r = requests.post(
            f"{BASE_URL}/api/library/upload",
            headers=_hdr(lib_client),
            files={"file": ("books.json", f, "application/json")},
            data={"client_id": lib_client["client_id"], "period": "2023-24",
                  "file_type": "books_json"},
        )
    assert r.json()["file"]["version_no"] == 1
    assert r.json()["file"]["file_id"] == pytest.lib_books_v1


def test_clause44_upload_pins_to_library(lib_client):
    """Uploading a Clause 44 run should ALSO save into the Library and
    pin the run's `pinned_files` to the new versions."""
    with open(lib_client["files"]["json"], "rb") as fj, open(lib_client["files"]["xlsx"], "rb") as fx:
        r = requests.post(
            f"{BASE_URL}/api/runs",
            headers=_hdr(lib_client),
            files={
                "accounting_json": ("books.json", fj, "application/json"),
                "ledger_xlsx": ("ledger.xlsx", fx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
            data={"client_id": lib_client["client_id"], "period": "2023-24"},
        )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    pytest.lib_run_id = run_id
    # Fetch run + check pinned_files exist.
    r2 = requests.get(f"{BASE_URL}/api/runs/{run_id}", headers=_hdr(lib_client))
    body = r2.json()
    pf = body.get("pinned_files") or {}
    assert "books_json" in pf
    assert "ledger_mapping_xlsx" in pf
    # And library_status must show fresh.
    ls = body["library_status"]
    assert ls["outdated"] is False
    assert ls["missing"] is False


def test_uploading_v2_marks_run_outdated(lib_client):
    """Tweak the JSON content (append a comment) → re-upload to Library
    creates v2 → existing Clause 44 run flips to outdated."""
    with open(lib_client["files"]["json"], "rb") as f:
        original = f.read()
    mutated = original + b"\n"  # checksum changes
    r = requests.post(
        f"{BASE_URL}/api/library/upload",
        headers=_hdr(lib_client),
        files={"file": ("books.json", mutated, "application/json")},
        data={"client_id": lib_client["client_id"], "period": "2023-24",
              "file_type": "books_json"},
    )
    assert r.status_code == 200
    assert r.json()["file"]["version_no"] == 2
    pytest.lib_books_v2 = r.json()["file"]["file_id"]

    # Now fetch the run — library_status.outdated must be True.
    r2 = requests.get(f"{BASE_URL}/api/runs/{pytest.lib_run_id}", headers=_hdr(lib_client))
    ls = r2.json()["library_status"]
    assert ls["outdated"] is True
    deps = {d["file_type"]: d for d in ls["dependencies"]}
    assert deps["books_json"]["status"] == "outdated"
    assert deps["ledger_mapping_xlsx"]["status"] == "fresh"


def test_rerun_repins_to_v2(lib_client):
    r = requests.post(
        f"{BASE_URL}/api/runs/{pytest.lib_run_id}/rerun",
        headers=_hdr(lib_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["pinned_files"]["books_json"] == pytest.lib_books_v2
    # Run should now be flagged generated=False (auditor must Generate).
    r2 = requests.get(f"{BASE_URL}/api/runs/{pytest.lib_run_id}", headers=_hdr(lib_client))
    body = r2.json()
    assert body["generated"] is False
    assert body["library_status"]["outdated"] is False  # back to fresh


def test_pinned_version_cannot_be_soft_deleted(lib_client):
    """v1 of books_json is pinned by the run.  Soft-delete must 409."""
    # Upload a v3 first so v1 is no longer "current".
    with open(lib_client["files"]["json"], "rb") as f:
        original = f.read()
    r = requests.post(
        f"{BASE_URL}/api/library/upload",
        headers=_hdr(lib_client),
        files={"file": ("books.json", original + b"\n\n", "application/json")},
        data={"client_id": lib_client["client_id"], "period": "2023-24",
              "file_type": "books_json"},
    )
    assert r.json()["file"]["version_no"] == 3
    # v1 is now older but still pinned by the original run (before rerun).
    # Actually after rerun, v1 was unpinned.  Test against the CURRENT pinned
    # version (v2).
    r = requests.delete(
        f"{BASE_URL}/api/library/files/{pytest.lib_books_v2}",
        headers=_hdr(lib_client),
    )
    assert r.status_code == 409, "pinned versions must not be soft-deletable"


def test_unpinned_version_can_be_soft_deleted(lib_client):
    # v1 is no longer pinned (rerun re-pinned to v2).
    r = requests.delete(
        f"{BASE_URL}/api/library/files/{pytest.lib_books_v1}",
        headers=_hdr(lib_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["soft_deleted"] is True
