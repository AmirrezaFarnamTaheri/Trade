"""Whole-universe selection never depends on liquidity, returns or a short token list."""
from collections import Counter

import pytest

from gym.services.paper_campaign import (
    historical_groups,
    market_universe,
    prospective_cases,
    strategy_trials,
)


def listing(symbol, base, quote, **extra):
    return {"symbol": symbol, "base_asset": base, "quote_asset": quote, "is_spot": True, **extra}


def test_every_supported_spot_market_gets_identical_matrix_including_risky_and_unobserved():
    rows = [listing("ADAUSDT", "ADA", "USDT"), listing("ETHTMN", "ETH", "TMN", flags=["isRisky"]),
            listing("1INCHUSDT", "1INCH", "USDT"), listing("XUSDT", "X", "USDT", is_spot=False),
            listing("XEUR", "X", "EUR")]
    universe = market_universe(rows)
    assert {row["symbol"]: row["spot_status"] for row in universe} == {
        "ADAUSDT": "ELIGIBLE_SPOT", "ETHTMN": "ELIGIBLE_SPOT", "1INCHUSDT": "ELIGIBLE_SPOT",
        "XUSDT": "VENUE_NOT_SPOT", "XEUR": "UNSUPPORTED_QUOTE"}
    windows = [{"from": "2026-11-05T00:00:00Z", "to": "2026-11-05T01:00:00Z"}] * 2
    scenarios = [{"fee_rate": "0", "latency_ms": 0, "outages": []}] * 4
    groups = historical_groups(universe, windows, scenarios)
    attempts = Counter()
    for group in groups:
        request = group["request"]
        count = len(request["trials"]) * len(request["windows"]) * len(request["scenarios"])
        assert count <= 32
        attempts[request["symbol"]] += count
    assert attempts == {"ADAUSDT": 544, "ETHTMN": 544, "1INCHUSDT": 544}
    assert Counter(case["symbol"] for case in prospective_cases(universe)) == {
        "ADAUSDT": 2, "ETHTMN": 2, "1INCHUSDT": 2}
    for market in universe[:3]:
        if market["spot_status"] == "ELIGIBLE_SPOT":
            trials = strategy_trials("relative-momentum", market["symbol"], market["quote"], "1min")
            assert all(trial["reference"] != market["symbol"] and trial["reference"].endswith(market["quote"]) for trial in trials)


@pytest.mark.parametrize("rows", [[], [{}], [listing("BAD", "ADA", "USDT")],
                                    [listing("../USDT", "../", "USDT")],
                                    [listing("adaUSDT", "ada", "USDT")],
                                    [listing("ADAUSDT", "ADA", "USDT")] * 2])
def test_invalid_catalogues_are_refused(rows):
    with pytest.raises(ValueError):
        market_universe(rows)
