"""Regression — CC/BCC recipients of a balance-confirmation email must NOT
receive a clickable Confirm/Dispute CTA.

Closes the legal lacuna where a CC'd client could self-confirm their own
ledger by clicking the button on the informational copy.
"""
from __future__ import annotations

from modules.balance_confirmation.sender import (
    build_notice_body, inject_tracking, render_template,
)
from modules.balance_confirmation.templates import (
    BANK_DEFAULT, CUSTOMER_DEFAULT, VENDOR_DEFAULT,
)


def _ctx(token: str = "TKN123"):
    return {
        "client_name": "ACME Pvt Ltd",
        "client_gstin": "29ABC1234F1Z5",
        "as_at_date": "2025-03-31",
        "party_name": "Vendor X",
        "contact_name_or_party": "Mr Y",
        "closing_balance_inr": "1,00,000.00",
        "dr_cr": "Cr",
        "response_link": f"https://app.test/confirm/{token}",
        "auditor_name": "CA Z",
        "auditor_firm": "MSS & Co",
        "address": "City",
    }


def _build(template):
    ctx = _ctx()
    body = render_template(template["html_body"], ctx)
    body = inject_tracking(
        body,
        pixel_url="https://app.test/api/balance-confirmation/track/pixel/TKN123.gif",
        response_link=ctx["response_link"],
        click_url="https://app.test/api/balance-confirmation/track/click/TKN123",
    )
    notice = build_notice_body(
        body,
        click_url="https://app.test/api/balance-confirmation/track/click/TKN123",
        response_link=ctx["response_link"],
        primary_email="vendor@example.com",
    )
    return body, notice


def test_primary_body_keeps_cta_and_pixel():
    body, _ = _build(CUSTOMER_DEFAULT)
    assert 'href="https://app.test/api/balance-confirmation/track/click/TKN123"' in body
    assert "track/pixel/TKN123" in body


def test_notice_body_strips_tracking_pixel():
    _, notice = _build(CUSTOMER_DEFAULT)
    assert "track/pixel/TKN123" not in notice


def test_notice_body_removes_clickable_cta():
    _, notice = _build(CUSTOMER_DEFAULT)
    # Neither of the two URLs the user could land on should be inside an
    # <a href="..."> in the notice copy.
    assert 'href="https://app.test/api/balance-confirmation/track/click/TKN123"' not in notice
    assert 'href="https://app.test/confirm/TKN123"' not in notice


def test_notice_body_carries_informational_banner_and_primary_email():
    _, notice = _build(CUSTOMER_DEFAULT)
    assert "Informational copy." in notice
    assert "vendor@example.com" in notice
    assert "Action required by" in notice
    # The CTA must remain VISIBLE (so cc/bcc parties know what was sent) but
    # struck through and labelled as not actionable.
    assert "line-through" in notice
    assert "Confirm or dispute balance" in notice


def test_notice_safeguard_works_for_every_default_template():
    for tpl in (CUSTOMER_DEFAULT, VENDOR_DEFAULT, BANK_DEFAULT):
        _, notice = _build(tpl)
        assert "Informational copy." in notice, tpl["kind"]
        assert "track/pixel" not in notice, tpl["kind"]
        assert 'href="https://app.test/api/balance-confirmation/track/click/TKN123"' not in notice, tpl["kind"]
        assert 'href="https://app.test/confirm/TKN123"' not in notice, tpl["kind"]
