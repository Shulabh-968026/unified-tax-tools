"""GST Recon Phase D e2e — REGENERATED for mapping-driven Books extraction.

Now uploads synthetic mapping XLSX before each books upload so that
extract_books_invoices yields non-empty voucher records. Tally voucher contract:
`ledger`/`partyLedgerName` keys + sign convention (+ve=Cr, -ve=Dr).
"""
from __future__ import annotations
import io
import json
import os

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._gst_recon_helpers import (
    books_payload, purchase_voucher, sales_voucher, synthetic_mapping_xlsx,
)


# ---- env --------------------------------------------------------------------
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
SESSION = "qa_test_session_token_20260427_stable"
CLIENT_ID = "cli_bdf1e22faa7c"
CLIENT_GSTIN = "33AAEFA5684J1ZC"
PERIOD = "042024"

assert BASE_URL and MONGO_URL and DB_NAME, "env not loaded"

API = f"{BASE_URL}/api/gst-recon"
COOKIES = {"session_token": SESSION}

mongo = MongoClient(MONGO_URL)
db_sync = mongo[DB_NAME]


# ---- helpers ---------------------------------------------------------------
def _create_run(name="TEST_phase_d_e2e_v2"):
    r = requests.post(f"{API}/runs", cookies=COOKIES,
                      json={"client_id": CLIENT_ID, "fy": "2024-25", "name": name},
                      timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _delete_run(rid):
    requests.delete(f"{API}/runs/{rid}", cookies=COOKIES, timeout=20)


def _upload(rid, files):
    """files: list of (name, bytes, mime). mime defaults to application/json."""
    multi = []
    for item in files:
        name, blob = item[0], item[1]
        mime = item[2] if len(item) > 2 else "application/json"
        multi.append(("files", (name, io.BytesIO(blob), mime)))
    r = requests.post(f"{API}/runs/{rid}/files", cookies=COOKIES,
                      files=multi, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload_mapping(rid):
    return _upload(rid, [("ledger_mapping.xlsx",
                          synthetic_mapping_xlsx(), XLSX_MIME)])


def _gstr1(period, invs, ctin="33ABCDE1234F1Z5", seller=CLIENT_GSTIN):
    payload = {"gstin": seller, "fp": period, "b2b": [{
        "ctin": ctin, "trdnm": "Acme Ltd",
        "inv": [{
            "inum": i["inum"], "idt": i["idt"], "val": i["val"],
            "itms": [{"itm_det": {
                "txval": i.get("txval", 0), "iamt": i.get("igst", 0),
                "camt": i.get("cgst", 0), "samt": i.get("sgst", 0),
                "csamt": i.get("cess", 0),
            }}],
        } for i in invs],
    }]}
    return json.dumps(payload).encode("utf-8")


def _gstr2b(period, invs, ctin="33SUPPL1234F1Z5"):
    payload = {"data": {"gstin": CLIENT_GSTIN, "rtnprd": period,
               "docdata": {"b2b": [{
                   "ctin": ctin, "trdnm": "Suppl Vendor",
                   "inv": [{
                       "inum": i["inum"], "dt": i["dt"], "val": i["val"],
                       "txval": i.get("txval", 0), "igst": i.get("igst", 0),
                       "cgst": i.get("cgst", 0), "sgst": i.get("sgst", 0),
                       "cess": i.get("cess", 0),
                   } for i in invs],
               }]}}}
    return json.dumps(payload).encode("utf-8")


# ---- 1. auth + bad-input gates ---------------------------------------------
class TestMatchEndpointGates:
    def test_match_requires_auth(self):
        rid = _create_run("TEST_phase_d_auth")
        try:
            r = requests.post(f"{API}/runs/{rid}/match",
                              params={"period": PERIOD, "direction": "outward"},
                              timeout=15)
            assert r.status_code == 401
        finally:
            _delete_run(rid)

    def test_match_404_for_unknown_run(self):
        r = requests.post(f"{API}/runs/does-not-exist-xyz/match",
                          params={"period": PERIOD, "direction": "outward"},
                          cookies=COOKIES, timeout=15)
        assert r.status_code == 404

    def test_match_400_for_bad_direction(self):
        rid = _create_run("TEST_phase_d_bad_dir")
        try:
            r = requests.post(f"{API}/runs/{rid}/match",
                              params={"period": PERIOD, "direction": "sideways"},
                              cookies=COOKIES, timeout=15)
            assert r.status_code == 400
        finally:
            _delete_run(rid)

    def test_match_400_for_bad_period(self):
        rid = _create_run("TEST_phase_d_bad_per")
        try:
            r = requests.post(f"{API}/runs/{rid}/match",
                              params={"period": "2024", "direction": "outward"},
                              cookies=COOKIES, timeout=15)
            assert r.status_code == 400
        finally:
            _delete_run(rid)


# ---- 2. invoice persistence + B2C skip + idempotency + cascade -------------
class TestInvoicePersistence:
    def test_books_b2c_voucher_skipped(self):
        rid = _create_run("TEST_phase_d_b2c")
        try:
            _upload_mapping(rid)
            v_b2b = sales_voucher("S-B2B", "2024-04-15", "33ABCDE1234F1Z5")
            v_b2c = {"date": "2024-04-16", "voucherTypeName": "Sales",
                     "voucherNumber": "S-B2C", "partyGSTIN": "",
                     "partyLedgerName": "Walk-In",
                     "ledgerEntries": [
                         {"ledger": "Walk-In", "isPartyLedger": "Yes",
                          "amount": -100},
                         {"ledger": "Sales Account", "amount": 100},
                     ]}
            content = books_payload([v_b2b, v_b2c], gstin=CLIENT_GSTIN)
            _upload(rid, [("books_01042024-31032025.json", content)])
            recs = list(db_sync.gst_recon_invoices.find(
                {"run_id": rid, "source": "books"}, {"_id": 0}))
            assert len(recs) == 1
            assert recs[0]["voucher_no"] == "S-B2B"
            assert recs[0]["party_gstin"] == "33ABCDE1234F1Z5"
        finally:
            _delete_run(rid)

    def test_gstr1_reupload_replaces_period_invoices(self):
        rid = _create_run("TEST_phase_d_reup")
        try:
            v1 = _gstr1(PERIOD, [{"inum": "S-1", "idt": "15-04-2024",
                                  "val": 1180, "txval": 1000, "cgst": 90, "sgst": 90}])
            _upload(rid, [("GSTR1_042024.json", v1)])
            assert db_sync.gst_recon_invoices.count_documents(
                {"run_id": rid, "source": "gstr1"}) == 1

            v2 = _gstr1(PERIOD, [
                {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
                 "txval": 1000, "cgst": 90, "sgst": 90},
                {"inum": "S-9", "idt": "20-04-2024", "val": 590,
                 "txval": 500, "cgst": 45, "sgst": 45},
            ])
            _upload(rid, [("GSTR1_042024.json", v2)])
            recs = list(db_sync.gst_recon_invoices.find(
                {"run_id": rid, "source": "gstr1"}, {"_id": 0}))
            assert len(recs) == 2
            assert sorted(r["invoice_no"] for r in recs) == ["S-1", "S-9"]
        finally:
            _delete_run(rid)

    def test_run_delete_cascades_invoices_and_books_raw(self):
        rid = _create_run("TEST_phase_d_cascade")
        _upload_mapping(rid)
        v = _gstr1(PERIOD, [{"inum": "S-1", "idt": "15-04-2024",
                              "val": 1180, "txval": 1000,
                              "cgst": 90, "sgst": 90}])
        _upload(rid, [("GSTR1_042024.json", v)])
        content = books_payload(
            [sales_voucher("S-1", "2024-04-15", "33ABCDE1234F1Z5")],
            gstin=CLIENT_GSTIN)
        _upload(rid, [("books_01042024-31032025.json", content)])
        assert db_sync.gst_recon_invoices.count_documents({"run_id": rid}) >= 2
        assert db_sync.gst_recon_books_raw.count_documents({"run_id": rid}) == 1
        _delete_run(rid)
        assert db_sync.gst_recon_invoices.count_documents({"run_id": rid}) == 0
        assert db_sync.gst_recon_books_raw.count_documents({"run_id": rid}) == 0


# ---- 3. matching scenarios -------------------------------------------------
class TestMatchScenarios:
    def _setup_outward(self, rid, books_invs, portal_invs, ctin="33ABCDE1234F1Z5"):
        _upload_mapping(rid)
        vouchers = [sales_voucher(b["no"], b["date"],
                                   b.get("gstin", ctin),
                                   b.get("taxable", 1000.0),
                                   b.get("cgst", 90.0),
                                   b.get("sgst", 90.0))
                    for b in books_invs]
        _upload(rid, [
            ("books_01042024-31032025.json",
             books_payload(vouchers, gstin=CLIENT_GSTIN)),
            ("GSTR1_042024.json", _gstr1(PERIOD, portal_invs, ctin=ctin)),
        ])

    def _match(self, rid, direction="outward"):
        r = requests.post(f"{API}/runs/{rid}/match",
                          params={"period": PERIOD, "direction": direction},
                          cookies=COOKIES, timeout=20)
        assert r.status_code == 200, r.text
        return r.json()

    def test_matched_missing_portal_missing_books(self):
        rid = _create_run("TEST_phase_d_3way")
        try:
            self._setup_outward(rid,
                books_invs=[
                    {"no": "S-1", "date": "2024-04-15"},
                    {"no": "S-2", "date": "2024-04-16"},
                ],
                portal_invs=[
                    {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
                     "txval": 1000, "cgst": 90, "sgst": 90},
                    {"inum": "S-3", "idt": "17-04-2024", "val": 1180,
                     "txval": 1000, "cgst": 90, "sgst": 90},
                ],
            )
            res = self._match(rid)
            assert res["counts"]["matched"] == 1
            assert res["counts"]["missing_in_portal"] == 1
            assert res["counts"]["missing_in_books"] == 1
            assert res["missing_in_portal"][0]["voucher_no"] == "S-2"
            assert res["missing_in_books"][0]["invoice_no"] == "S-3"
        finally:
            _delete_run(rid)

    def test_value_mismatch(self):
        rid = _create_run("TEST_phase_d_valmiss")
        try:
            self._setup_outward(rid,
                books_invs=[{"no": "S-1", "date": "2024-04-15"}],
                portal_invs=[{"inum": "S-1", "idt": "15-04-2024", "val": 1500,
                              "txval": 1300, "cgst": 100, "sgst": 100}])
            res = self._match(rid)
            assert res["counts"]["value_mismatch"] == 1
            assert res["counts"]["matched"] == 0
        finally:
            _delete_run(rid)

    def test_date_mismatch(self):
        rid = _create_run("TEST_phase_d_datemiss")
        try:
            self._setup_outward(rid,
                books_invs=[{"no": "S-1", "date": "2024-04-15"}],
                portal_invs=[{"inum": "S-1", "idt": "20-04-2024", "val": 1180,
                              "txval": 1000, "cgst": 90, "sgst": 90}])
            res = self._match(rid)
            assert res["counts"]["date_mismatch"] == 1
            assert res["counts"]["matched"] == 0
        finally:
            _delete_run(rid)

    def test_fuzzy_match_one_char_typo(self):
        rid = _create_run("TEST_phase_d_fuzzy")
        try:
            self._setup_outward(rid,
                books_invs=[{"no": "INV2024S001", "date": "2024-04-15"}],
                portal_invs=[{"inum": "INV2024S00I", "idt": "15-04-2024",
                              "val": 1180, "txval": 1000,
                              "cgst": 90, "sgst": 90}])
            res = self._match(rid)
            assert res["counts"]["matched"] == 1
            pair = res["matched"][0]
            assert pair.get("fuzzy_score", 0) >= 85
        finally:
            _delete_run(rid)

    def test_cross_gstin_safety(self):
        rid = _create_run("TEST_phase_d_xgstin")
        try:
            _upload_mapping(rid)
            vouchers = [sales_voucher("S-1", "2024-04-15", "33AAAAA1234F1Z5")]
            _upload(rid, [
                ("books_01042024-31032025.json",
                 books_payload(vouchers, gstin=CLIENT_GSTIN)),
                ("GSTR1_042024.json", _gstr1(PERIOD, [
                    {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
                     "txval": 1000, "cgst": 90, "sgst": 90}],
                    ctin="33BBBBB1234F1Z5")),
            ])
            res = self._match(rid)
            assert res["counts"]["matched"] == 0
            assert res["counts"]["missing_in_books"] == 1
            assert res["counts"]["missing_in_portal"] == 1
        finally:
            _delete_run(rid)

    def test_inward_uses_gstr2b(self):
        rid = _create_run("TEST_phase_d_inward")
        try:
            _upload_mapping(rid)
            v_p = purchase_voucher("P-1", "2024-04-15", "33SUPPL1234F1Z5")
            _upload(rid, [
                ("books_01042024-31032025.json",
                 books_payload([v_p], gstin=CLIENT_GSTIN)),
                ("GSTR2B_042024.json", _gstr2b(PERIOD, [
                    {"inum": "P-1", "dt": "15-04-2024", "val": 590,
                     "txval": 500, "cgst": 45, "sgst": 45}])),
            ])
            res = self._match(rid, direction="inward")
            assert res["counts"]["matched"] == 1
        finally:
            _delete_run(rid)


# ---- 4. RunOut schema round-trip --------------------------------------------
class TestSchemas:
    def test_runout_summary_field_round_trips(self):
        rid = _create_run("TEST_phase_d_schema")
        try:
            r = requests.post(f"{API}/runs/{rid}/summary",
                              cookies=COOKIES, timeout=20)
            assert r.status_code == 200
            r = requests.get(f"{API}/runs/{rid}", cookies=COOKIES, timeout=15)
            assert r.status_code == 200
            data = r.json()
            assert data.get("summary") is not None
        finally:
            _delete_run(rid)

    def test_runout_carries_mapping_rules_after_mapping_upload(self):
        rid = _create_run("TEST_phase_d_mapfields")
        try:
            _upload_mapping(rid)
            r = requests.get(f"{API}/runs/{rid}", cookies=COOKIES, timeout=15)
            assert r.status_code == 200
            data = r.json()
            # extra='allow' on RunOut allows mapping_rules + unmapped to flow through
            assert "mapping_rules" in data
            assert "Writeoff ITC Expenses" in (
                data.get("mapping_unmapped_ledgers") or [])
        finally:
            _delete_run(rid)
