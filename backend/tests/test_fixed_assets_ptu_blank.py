"""Verify ingestion no longer auto-populates put_to_use_date."""
from modules.fixed_assets.service import stage_addition_rows


def _line(amount=10000.0, ledger="Plant & Machinery"):
    return {
        "is_debit":           True,
        "ledger_name":        ledger,
        "voucher_id":         "v1",
        "voucher_no":         "V/0001",
        "voucher_type":       "Purchase",
        "accounting_date":    "2024-04-15",
        "invoice_date":       "2024-04-10",
        "invoice_date_source": "narration",
        "narration":          "Test asset purchase",
        "party_name":         "Acme Inc",
        "particulars":        "Test asset",
        "amount":             amount,
    }


def test_ptu_blank_on_ingest():
    rows = stage_addition_rows(
        lines=[_line()],
        ledger_id_by_name={"Plant & Machinery": "led-1"},
        run_id="test-run",
        fy_end="2025-03-31",
    )
    assert len(rows) == 1
    a = rows[0]
    # PTU is NOT auto-populated from invoice/accounting date — auditor fills it.
    assert a["put_to_use_date"] == ""
    # Without a PTU, the addition is treated as full-rate (no half-rate
    # penalty until the auditor explicitly fills the PTU).
    assert a["is_more_than_180"] is True
    assert a["half_rate"] is False
    # Other ingest-time fields preserved
    assert a["accounting_date"] == "2024-04-15"
    assert a["invoice_date"] == "2024-04-10"
    assert a["invoice_cost"] == 10000.0
    assert a["reviewed"] is False
