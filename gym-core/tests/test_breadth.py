import pytest

from gym.domain.breadth import breadth_targets, liquid


def series(closes, volume=100.0):
    return {"close": list(closes), "high": list(closes), "low": list(closes), "volume": [volume] * len(closes)}


UP = [100 * 1.01 ** i for i in range(80)]
DOWN = [100 * 0.99 ** i for i in range(80)]


def test_liquidity_needs_30_days_of_median_quote_volume():
    assert liquid(series(UP, volume=100.0))  # about 100 x 150 USDT a day
    assert not liquid(series(UP, volume=1.0))
    assert not liquid(series(UP[:20], volume=1000.0))


def test_gate_open_holds_equal_sleeves_in_trending_coins_only():
    bars = {"A": series(UP), "B": series(UP), "C": series(DOWN)}
    out = breadth_targets(bars)
    assert out["breadth"] == pytest.approx(2 / 3) and out["gate_open"]
    assert out["weights"] == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": 0.0}


def test_gate_closed_holds_all_usdt_even_when_one_coin_trends():
    bars = {"A": series(UP), "B": series(DOWN), "C": series(DOWN)}
    out = breadth_targets(bars)
    assert out["breadth"] == pytest.approx(1 / 3) and not out["gate_open"]
    assert out["trend_long"] == ["A"] and set(out["weights"].values()) == {0.0}


def test_illiquid_coins_are_outside_the_universe():
    bars = {"A": series(UP), "B": series(UP, volume=0.01)}
    assert breadth_targets(bars)["universe"] == ["A"]
