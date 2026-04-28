"""Phase D e2e — POST /runs/{rid}/match endpoint + invoice persistence/cascade.

Covers:
  - Auth gate (401)
  - 404 unknown run
  - 400 bad direction / period
  - Books extractor B2C skip via real upload + pymongo verify
  - GSTR-1 re-upload idempotency (no duplicates) in gst_recon_invoices
  - DELETE /runs/{rid} cascades gst_recon_invoices to 0
  - Synthetic match scenario: matched / missing_in_portal / missing_in_books
  - Synthetic value-mismatch
  - Synthetic date-mismatch
  - Fuzzy match (1-char typo) returns matched + fuzzy_score>=85
  - Cross-GSTIN safety (same inv-no, different gstin)
  - direction='inward' uses gstr2b
"""
from __future__ import annotations
import json
import os
import io
import asyncio
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

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


# ---- helpers ----------------------------------------------------------------
def _create_run(name: str = "TEST_phase_d_e2e") -> str:
    r = requests.post(
        f"{API}/runs",
        cookies=COOKIES,
        json={"client_id": CLIENT_ID, "fy": "2024-25", "name": name},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _delete_run(rid: str):
    requests.delete(f"{API}/runs/{rid}", cookies=COOKIES, timeout=20)


def _upload(rid: str, files: list[tuple[str, bytes]]) -> dict:
    multi = [("files", (n, io.BytesIO(b), "application/json")) for n, b in files]
    r = requests.post(
        f"{API}/runs/{rid}/files", cookies=COOKIES, files=multi, timeout=30
    )
    assert r.status_code == 200, r.text
    return r.json()


def _gstr1(period: str, invs: list[dict], ctin: str = "33ABCDE1234F1Z5",
           seller_gstin: str = CLIENT_GSTIN) -> bytes:
    """invs: list of {inum, idt, val, txval, igst, cgst, sgst, cess}"""
    payload = {"gstin": seller_gstin, "fp": period, "b2b": [{
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


def _gstr2b(period: str, invs: list[dict], ctin: str = "33SUPPL1234F1Z5") -> bytes:
    payload = {"data": {"gstin": CLIENT_GSTIN, "rtnprd": period, "docdata": {"b2b": [{
        "ctin": ctin, "trdnm": "Suppl Vendor",
        "inv": [{
            "inum": i["inum"], "dt": i["dt"], "val": i["val"],
            "txval": i.get("txval", 0), "igst": i.get("igst", 0),
            "cgst": i.get("cgst", 0), "sgst": i.get("sgst", 0),
            "cess": i.get("cess", 0),
        } for i in invs],
    }]}}}
    return json.dumps(payload).encode("utf-8")


def _books(vouchers: list[dict],
           books_from: str = "01-04-2024", books_to: str = "31-03-2025") -> bytes:
    payload = {"company": {"booksFromDate": books_from, "booksToDate": books_to,
                            "gstin": CLIENT_GSTIN},
               "vouchers": vouchers}
    return json.dumps(payload).encode("utf-8")


def _sales_voucher(no: str, date: str, gstin: str, taxable: float = 1000.0,
                   cgst: float = 90.0, sgst: float = 90.0):
    return {
        "date": date, "voucherTypeName": "Sales", "voucherNumber": no,
        "partyGSTIN": gstin, "partyName": "Acme Ltd",
        "ledgerEntries": [
            {"ledgerName": "Sales Account", "amount": taxable},
            {"ledgerName": "Output CGST @ 9%", "amount": cgst},
            {"ledgerName": "Output SGST @ 9%", "amount": sgst},
            {"ledgerName": "Acme Ltd", "amount": -(taxable + cgst + sgst)},
        ],
    }


# ---- 1. auth + bad-input gates ---------------------------------------------
class TestMatchEndpointGates:
    def test_match_requires_auth(self):
        rid = _create_run("TEST_phase_d_auth")
        try:
            r = requests.post(f"{API}/runs/{rid}/match",
                              params={"period": PERIOD, "direction": "outward"},
                              timeout=15)
            assert r.status_code == 401, r.text
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
    def test_books_b2c_voucher_skipped_in_invoices_collection(self):
        rid = _create_run("TEST_phase_d_b2c")
        try:
            content = _books([
                _sales_voucher("S-B2B", "2024-04-15", "33ABCDE1234F1Z5"),
                {"date": "2024-04-16", "voucherTypeName": "Sales",
                 "voucherNumber": "S-B2C", "partyGSTIN": "",
                 "ledgerEntries": [{"ledgerName": "Sales Account", "amount": 100}]},
            ])
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
            cnt1 = db_sync.gst_recon_invoices.count_documents(
                {"run_id": rid, "source": "gstr1"})
            assert cnt1 == 1

            # Re-upload same filename with 2 invoices
            v2 = _gstr1(PERIOD, [
                {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
                 "txval": 1000, "cgst": 90, "sgst": 90},
                {"inum": "S-9", "idt": "20-04-2024", "val": 590,
                 "txval": 500, "cgst": 45, "sgst": 45},
            ])
            _upload(rid, [("GSTR1_042024.json", v2)])
            recs = list(db_sync.gst_recon_invoices.find(
                {"run_id": rid, "source": "gstr1"}, {"_id": 0}))
            assert len(recs) == 2  # not 3 — old deleted
            assert sorted([r["invoice_no"] for r in recs]) == ["S-1", "S-9"]
        finally:
            _delete_run(rid)

    def test_run_delete_cascades_invoices(self):
        rid = _create_run("TEST_phase_d_cascade")
        v = _gstr1(PERIOD, [{"inum": "S-1", "idt": "15-04-2024",
                              "val": 1180, "txval": 1000, "cgst": 90, "sgst": 90}])
        _upload(rid, [("GSTR1_042024.json", v)])
        assert db_sync.gst_recon_invoices.count_documents({"run_id": rid}) >= 1
        _delete_run(rid)
        assert db_sync.gst_recon_invoices.count_documents({"run_id": rid}) == 0


# ---- 3. matching scenarios -------------------------------------------------
class TestMatchScenarios:
    def _setup_outward(self, rid: str, books_invs: list[dict],
                       portal_invs: list[dict], ctin: str = "33ABCDE1234F1Z5"):
        vouchers = [_sales_voucher(b["no"], b["date"], b.get("gstin", ctin),
                                    b.get("taxable", 1000.0),
                                    b.get("cgst", 90.0), b.get("sgst", 90.0))
                    for b in books_invs]
        _upload(rid, [
            ("books_01042024-31032025.json", _books(vouchers)),
            ("GSTR1_042024.json", _gstr1(PERIOD, portal_invs, ctin=ctin)),
        ])

    def _match(self, rid: str, direction: str = "outward") -> dict:
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
                    {"no": "S-1", "date": "2024-04-15"},  # matches
                    {"no": "S-2", "date": "2024-04-16"},  # only-books
                ],
                portal_invs=[
                    {"inum": "S-1", "idt": "15-04-2024", "val": 1180,
                     "txval": 1000, "cgst": 90, "sgst": 90},
                    {"inum": "S-3", "idt": "17-04-2024", "val": 1180,
                     "txval": 1000, "cgst": 90, "sgst": 90},  # only-portal
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
            # Books total = 1000 + 90 + 90 = 1180; portal val=1500 → diff=320
            self._setup_outward(rid,
                books_invs=[{"no": "S-1", "date": "2024-04-15"}],
                portal_invs=[{"inum": "S-1", "idt": "15-04-2024", "val": 1500,
                              "txval": 1300, "cgst": 100, "sgst": 100}],
            )
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
                              "txval": 1000, "cgst": 90, "sgst": 90}],
            )
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
                              "val": 1180, "txval": 1000, "cgst": 90, "sgst": 90}],
            )
            res = self._match(rid)
            assert res["counts"]["matched"] == 1
            pair = res["matched"][0]
            assert "fuzzy_score" in pair
            assert pair["fuzzy_score"] >= 85
        finally:
            _delete_run(rid)

    def test_cross_gstin_safety(self):
        rid = _create_run("TEST_phase_d_xgstin")
        try:
            # Books voucher S-1 → gstin 33AAA…; portal invoice S-1 → ctin 33BBB…
            vouchers = [_sales_voucher("S-1", "2024-04-15",
                                        "33AAAAA1234F1Z5")]
            _upload(rid, [
                ("books_01042024-31032025.json", _books(vouchers)),
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
            # purchase voucher P-1 + GSTR-2B with P-1
            v_p = {
                "date": "2024-04-15", "voucherTypeName": "Purchase",
                "voucherNumber": "P-1", "partyGSTIN": "33SUPPL1234F1Z5",
                "ledgerEntries": [
                    {"ledgerName": "Purchase Account", "amount": -500},
                    {"ledgerName": "Input CGST @ 9%", "amount": -45},
                    {"ledgerName": "Input SGST @ 9%", "amount": -45},
                    {"ledgerName": "Suppl Vendor", "amount": 590},
                ],
            }
            _upload(rid, [
                ("books_01042024-31032025.json", _books([v_p])),
                ("GSTR2B_042024.json", _gstr2b(PERIOD, [
                    {"inum": "P-1", "dt": "15-04-2024", "val": 590,
                     "txval": 500, "cgst": 45, "sgst": 45}])),
            ])
            res = self._match(rid, direction="inward")
            assert res["counts"]["matched"] == 1
        finally:
            _delete_run(rid)


# ---- 4. schemas -------------------------------------------------------------
class TestSchemas:
    def test_runout_summary_field_round_trips(self):
        """RunOut should now expose 'summary' on GET after compute."""
        rid = _create_run("TEST_phase_d_schema")
        try:
            r = requests.post(f"{API}/runs/{rid}/summary",
                              cookies=COOKIES, timeout=20)
            assert r.status_code == 200
            r = requests.get(f"{API}/runs/{rid}", cookies=COOKIES, timeout=15)
            assert r.status_code == 200
            data = r.json()
            assert "summary" in data
            assert data["summary"] is not None
        finally:
            _delete_run(rid)
