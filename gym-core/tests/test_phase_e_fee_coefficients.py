"""Phase E item 44: read-only observed Wallex fill fee coefficients."""
import pytest

from gym.adapters.wallex_order_evidence import (
    InvalidOrderEvidence,
    parse_manual_order_evidence,
    validate_order_evidence,
)


def record(fee="0.0002", coefficient="0.001", maker="0.001", taker="0.002", *, extra=None):
    """One bounded raw private GET response, not a real authenticated account."""
    fill = {
        "quantity": "0.2", "price": "100", "fee": fee, "feeAsset": "BTC",
        "feeCoefficient": coefficient, "makerFeeCoefficient": maker,
        "takerFeeCoefficient": taker, "isBuyer": True, "timestamp": 1770000000,
        **(extra or {})}
    return {"success": True, "result": {
        "clientOrderId": "Manual_1", "status": "PARTIALLY_FILLED",
        "side": "BUY", "symbol": "BTCUSDT", "origQty": "1",
        "executedQty": "0.2", "fills": [fill]}}


def test_fee_coefficients_retained_without_mixing_fee_currency():
    out = parse_manual_order_evidence(record(), "Manual_1")
    item = out["fills"][0]
    assert item["fee"] == "0.0002" and item["fee_asset"] == "BTC"
    assert item["fee_coefficient"] == "0.001"
    assert item["maker_fee_coefficient"] == "0.001"
    assert item["taker_fee_coefficient"] == "0.002"
    assert item["maker_taker_attribution"] == "MAKER_RATE_MATCH"
    assert item["is_buyer"] is True
    assert out["settlement"] == "UNKNOWN"
    assert out["money_authority"] is False
    assert validate_order_evidence([out]) == [out]


def test_ambiguous_fee_rate_does_not_claim_order_maker_identity():
    out = parse_manual_order_evidence(record(maker="0.001", taker="0.001"), "Manual_1")
    assert out["fills"][0]["maker_taker_attribution"] == "AMBIGUOUS_RATE_MATCH"


@pytest.mark.parametrize("change", [
    {"feeCoefficient": "NaN"}, {"feeCoefficient": "-0.01"},
    {"feeCoefficient": "1.1"}, {"feeCoefficient": 0.001},
    {"makerFeeCoefficient": None}, {"takerFeeCoefficient": "100"},
    {"isBuyer": "true"}, {"feeCoefficient": "0.2"},
])
def test_untrusted_fee_fields_are_validated_without_fee_assumptions(change):
    with pytest.raises(InvalidOrderEvidence):
        parse_manual_order_evidence(record(extra=change), "Manual_1")
