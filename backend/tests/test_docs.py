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
