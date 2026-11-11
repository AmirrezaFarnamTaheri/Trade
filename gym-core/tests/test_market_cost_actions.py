"""Market-hour quote cost tables and causal public-impact calibration."""
from datetime import timedelta

import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from tests.support import START, market_db, quote_history


def test_public_impact_calibration_never_invents_coefficients_without_prints(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    db.c.close()
    report = research_action(tmp_path, "execution-model-calibrate", {
        "symbol": "BTCUSDT", "from": iso(START),
        "to": iso(START + timedelta(minutes=25))}, store="live")
    assert report["schema"] == "execution-market-model/1"
    assert report["impact"]["status"] == "INSUFFICIENT_DATA"
    assert report["cost_models"].get("impact_models") is None
    hourly = report["hourly"]
    assert hourly["schema"] == "hourly-costs/1"
    assert hourly["symbol"] == "BTCUSDT"
    assert hourly["hours"]
    assert all(row["quote_samples"] >= 20 for row in hourly["hours"].values())
    assert all(row["taker_fee_rate"] is None for row in hourly["hours"].values())
    assert report["automatic_application"] is False
    assert report["funded_authority"] is False


def test_demonstration_data_never_becomes_live_calibration(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    db.c.close()
    report = research_action(tmp_path, "execution-model-calibrate", {
        "symbol": "BTCUSDT", "from": iso(START),
        "to": iso(START + timedelta(minutes=25))}, store="demo")
    assert report["synthetic"] is True
    assert report["cost_models"] == {}
    assert report["hourly"]["hours"]


@pytest.mark.parametrize("value", [
    {"symbol": "BTCUSDT", "from": iso(START + timedelta(hours=1)), "to": iso(START)},
    {"symbol": "BTCUSDT", "from": iso(START), "to": iso(START + timedelta(days=32))},
    {"symbol": "../BTCUSDT", "from": iso(START), "to": iso(START + timedelta(minutes=20))},
])
def test_calibration_rejects_invalid_or_unbounded_windows(tmp_path, value):
    db = market_db(tmp_path, quote_history(n=180))
    db.c.close()
    with pytest.raises(ValueError):
        research_action(tmp_path, "execution-model-calibrate", value)


@pytest.mark.parametrize("malformed", [None, [], "not an object", 5])
def test_twap_preview_rejects_non_object_input_without_uncaught_error(tmp_path, malformed):
    with pytest.raises(ValueError):
        research_action(tmp_path, "twap-preview", malformed)
