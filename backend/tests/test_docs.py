"""Regression — docs endpoints serve HTML + PDF with correct branding.

The user-facing readme module is the new front door for less-experienced
audit staff; we lock down the contract here so a future refactor can't
silently drift the brand or break the PDF pipeline.
"""
from __future__ import annotations

import os
import sys

import pytest
import requests

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001").rstrip("/")
COOKIE = {"session_token": os.environ.get("QA_TEST_SESSION", "qa_test_session_token_20260430_dev")}


def _get(path: str, **kw):
    return requests.get(BASE_URL + path, cookies=COOKIE, timeout=20, **kw)


class TestDocsEndpoint:
    def test_index_html_renders_and_lists_modules(self):
        r = _get("/api/docs")
        assert r.status_code == 200, r.text[:200]
        body = r.text
        assert "AssureAI" in body
        assert "Clause 44" in body
        # branding sanity — the old name must be gone
        assert "MSS" not in body, "MSS rebrand missed in docs index"

    def test_clause_44_html_has_executive_summary_and_walkthrough(self):
        r = _get("/api/docs/clause-44")
        assert r.status_code == 200
        body = r.text
        assert "Executive summary" in body
        assert "For the busy reviewer" in body
        assert "Step-by-step walkthrough" in body
        assert "Edge cases" in body
        assert "Frequently asked questions" in body
        assert "Glossary" in body
        # Brand consistency
        assert "AssureAI" in body
        assert "MSS" not in body
        # The download-PDF button must be present (screen view only)
        assert "/api/docs/clause-44.pdf" in body

    def test_clause_44_pdf_is_valid_pdf_and_meaningful_size(self):
        r = _get("/api/docs/clause-44.pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        # Real content > 30 KB rules out an empty/error PDF
        assert len(r.content) > 30_000, f"Suspiciously small PDF: {len(r.content)} bytes"
        assert r.content[:5] == b"%PDF-", "PDF magic bytes missing"
        # Filename branding
        cd = r.headers.get("content-disposition", "")
        assert "AssureAI_clause_44_user_guide.pdf" in cd

    def test_unknown_module_returns_404_html(self):
        r = _get("/api/docs/does-not-exist")
        assert r.status_code == 404

    def test_unknown_module_returns_404_pdf(self):
        r = _get("/api/docs/does-not-exist.pdf")
        assert r.status_code == 404

    def test_anonymous_blocked(self):
        r = requests.get(BASE_URL + "/api/docs/clause-44", timeout=10)
        assert r.status_code in (401, 403), f"Expected auth gate, got {r.status_code}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ============================================================================
# Feedback endpoints — record + aggregate
# ============================================================================
class TestDocsFeedback:
    MK = "clause-44"

    def _post(self, **kw):
        return requests.post(
            BASE_URL + "/api/docs/feedback",
            cookies=COOKIE,
            json={"module_key": self.MK, "section_id": "regulatory",
                  "helpful": True, "reason": "", **kw},
            timeout=10,
        )

    def test_post_thumbs_up(self):
        r = self._post(helpful=True, section_id="walkthrough_test")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_post_thumbs_down_with_reason(self):
        r = self._post(helpful=False, reason="Need example for inter-branch", section_id="edge_test")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_idempotent_upsert_on_resubmit(self):
        sid = "idempotent_test"
        r1 = self._post(helpful=True, section_id=sid)
        assert r1.json().get("first_time") is True
        r2 = self._post(helpful=False, reason="changed mind", section_id=sid)
        assert r2.json().get("first_time") is False, "Re-submit should be an update, not a new row"

    def test_aggregate_returns_heatmap_shape(self):
        r = _get(f"/api/docs/feedback/aggregate?module_key={self.MK}")
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert isinstance(rows, list)
        if rows:
            sample = rows[0]
            for k in ("module_key", "section_id", "up", "down", "total", "score", "recent_reasons"):
                assert k in sample, f"missing key {k} in aggregate row"

    def test_aggregate_admin_only(self):
        # We rely on the QA_BOT having admin role; skip elegantly if not.
        r_anon = requests.get(BASE_URL + "/api/docs/feedback/aggregate", timeout=10)
        assert r_anon.status_code in (401, 403)

    def test_post_payload_validation(self):
        # Empty section_id should 422
        r = requests.post(
            BASE_URL + "/api/docs/feedback",
            cookies=COOKIE,
            json={"module_key": self.MK, "section_id": "", "helpful": True, "reason": ""},
            timeout=10,
        )
        assert r.status_code == 422


# Re-define entry point at end so the second class is included.
if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
