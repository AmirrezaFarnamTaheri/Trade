"""Phase E item 46: safe client-id and pacing contract without venue writes."""
from datetime import timedelta

import pytest

from gym.contracts.order_submission_v2 import PaperSubmissionGate, valid_submit_client_id
from tests.support import START


@pytest.mark.parametrize("identity", ["bad-hyphen", "bad.dot", "", "../bad", "bad space", "é", "x" * 65])
def test_v2_client_id_rejects_venue_invalid_characters(identity):
    with pytest.raises(ValueError):
        valid_submit_client_id(identity)


def test_v2_allows_underscore_but_never_authorizes_orders():
    assert valid_submit_client_id("Trade_123") == "Trade_123"
    assert valid_submit_client_id("_") == "_"


def test_paper_admission_refuses_duplicates_and_21st_in_ten_seconds(tmp_path):
    with PaperSubmissionGate(tmp_path / "paper_submission.sqlite3") as guard:
        for i in range(20):
            out = guard.stage("demo", f"Trade_{i}", at=START + timedelta(milliseconds=i))
            assert out["status"] == "PAPER_ADMISSION_RECORDED"
            assert out["order_submitted"] is False and out["funded_authority"] is False
        with pytest.raises(ValueError, match="rate"):
            guard.stage("demo", "Extra_21", at=START + timedelta(seconds=1))
        with pytest.raises(ValueError, match="duplicate"):
            guard.stage("demo", "Trade_0", at=START + timedelta(seconds=11))
        new = guard.stage("demo", "AfterWindow", at=START + timedelta(seconds=11))
        assert new["status"] == "PAPER_ADMISSION_RECORDED"


def test_read_order_ids_may_still_contain_hyphen():
    """V2 submit-only checks must not change the established read path."""
    from gym.adapters.wallex_order_evidence import parse_manual_order_evidence

    payload = {"success": True, "result": {
        "clientOrderId": "venue-generated-1", "symbol": "BTCUSDT",
        "side": "BUY", "status": "NEW", "origQty": "1", "executedQty": "0"}}
    assert parse_manual_order_evidence(payload, "venue-generated-1")["client_id"] == "venue-generated-1"
    with pytest.raises(ValueError):
        valid_submit_client_id("venue-generated-1")
