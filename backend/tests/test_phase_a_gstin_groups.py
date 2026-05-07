"""Phase A · GSTIN Groups CRUD — live HTTP tests.

Covers:
  • Create (happy path) — returns canonical envelope with group_id + sorted division_ids
  • List
  • Update label + GSTIN + membership
  • Duplicate label rejection (409)
  • Invalid GSTIN format rejection (400)
  • Unknown division_id rejection (400)
  • Empty division_ids rejection (400)
  • Unknown client (404)
  • Unknown group (404 on update / delete)
  • Delete
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
COOKIES = {"session_token": "qa_test_session_token_20260206_dev"}

CLIENT = "cli_c5d02541264c"   # GMS Processors P Limited (real multi-div client)


def _api(p: str) -> str:
    return f"{BASE_URL}{p}"


@pytest.fixture(autouse=True)
def _cleanup():
    """Wipe any existing groups on this client before each test."""
    r = requests.get(_api(f"/api/library/clients/{CLIENT}/gstin-groups"), cookies=COOKIES, timeout=15)
    if r.status_code == 200:
        for g in r.json().get("groups", []):
            requests.delete(
                _api(f"/api/library/clients/{CLIENT}/gstin-groups/{g['group_id']}"),
                cookies=COOKIES, timeout=15,
            )
    yield


def _divs():
    """Pick the two real division ids on GMS Processors."""
    r = requests.get(_api("/api/clients"), cookies=COOKIES, timeout=15)
    items = r.json() if isinstance(r.json(), list) else r.json().get("clients", r.json().get("rows", []))
    cli = next(c for c in items if c["client_id"] == CLIENT)
    ids = [d["division_id"] for d in cli["divisions"]]
    assert len(ids) >= 2
    return ids


def test_create_and_list_group():
    [tn, mum] = _divs()[:2]
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "TN GSTIN", "gstin": "33ABCDE1234F1Z5", "division_ids": [tn]},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["label"] == "TN GSTIN"
    assert g["gstin"] == "33ABCDE1234F1Z5"
    assert g["division_ids"] == [tn]
    assert g["group_id"].startswith("gst_")

    r2 = requests.get(_api(f"/api/library/clients/{CLIENT}/gstin-groups"), cookies=COOKIES, timeout=15)
    assert r2.status_code == 200
    assert any(x["group_id"] == g["group_id"] for x in r2.json().get("groups", []))


def test_update_changes_membership_and_label():
    [tn, mum] = _divs()[:2]
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "Old", "division_ids": [tn]},
        cookies=COOKIES, timeout=15,
    )
    gid = r.json()["group_id"]
    upd = requests.patch(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups/{gid}"),
        json={"label": "Combined", "gstin": "27ABCDE1234F1Z5", "division_ids": [tn, mum]},
        cookies=COOKIES, timeout=15,
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["label"] == "Combined"
    assert body["gstin"] == "27ABCDE1234F1Z5"
    assert sorted(body["division_ids"]) == sorted([tn, mum])


def test_duplicate_label_rejected():
    [tn, mum] = _divs()[:2]
    requests.post(_api(f"/api/library/clients/{CLIENT}/gstin-groups"),
                  json={"label": "TN", "division_ids": [tn]}, cookies=COOKIES, timeout=15)
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "TN", "division_ids": [mum]},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 409, r.text


def test_invalid_gstin_rejected():
    [tn, _] = _divs()[:2]
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "Bad", "gstin": "INVALID", "division_ids": [tn]},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 400


def test_unknown_division_id_rejected():
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "X", "division_ids": ["div_not_real"]},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 400


def test_empty_division_ids_rejected():
    r = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "X", "division_ids": []},
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 400


def test_unknown_client_404():
    r = requests.get(
        _api("/api/library/clients/cli_does_not_exist/gstin-groups"),
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 404


def test_delete_removes_group():
    [tn, _] = _divs()[:2]
    g = requests.post(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups"),
        json={"label": "Z", "division_ids": [tn]},
        cookies=COOKIES, timeout=15,
    ).json()
    d = requests.delete(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups/{g['group_id']}"),
        cookies=COOKIES, timeout=15,
    )
    assert d.status_code == 200
    listed = requests.get(_api(f"/api/library/clients/{CLIENT}/gstin-groups"), cookies=COOKIES, timeout=15)
    assert all(x["group_id"] != g["group_id"] for x in listed.json().get("groups", []))


def test_delete_unknown_returns_404():
    r = requests.delete(
        _api(f"/api/library/clients/{CLIENT}/gstin-groups/gst_fake_xxx"),
        cookies=COOKIES, timeout=15,
    )
    assert r.status_code == 404


# Phase A · catalog default_attribution
def test_catalog_default_attribution_field_present():
    r = requests.get(_api("/api/library/catalog"), cookies=COOKIES, timeout=15)
    assert r.status_code == 200
    rows = r.json() if isinstance(r.json(), list) else r.json().get("catalog") or r.json().get("file_types") or []
    by_key = {x["key"]: x for x in rows}
    # Sample assertions per chosen scope.
    assert by_key["books_json"].get("default_attribution") == "current_division"
    assert by_key["itr_prior_json"].get("default_attribution") == "all_divisions"
    assert by_key["gstr_1_json"].get("default_attribution") == "pick_divisions"
    assert by_key["fa_register_xlsx"].get("default_attribution") == "all_divisions"
