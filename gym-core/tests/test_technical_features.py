"""Independent range/streaming fixtures and causal indicator strategy behavior."""
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from gym.domain.bars import Bar, BarSpec
from gym.domain.indicators import bar_indicator_values, indicator_values
from gym.domain.registry import create_strategy
from gym.domain.strategy import Snapshot
from gym.domain.technical_features import TechnicalFeatures
from tests.support import START


def bar(i, value, width=1):
    value, width = Decimal(value), Decimal(width)
    at = START + timedelta(minutes=i)
    return Bar("BTCUSDT", BarSpec("1min"), at, at + timedelta(minutes=1), at + timedelta(minutes=1),
               value, value + width, value - width, value, Decimal(0), 1)


def test_historical_correction_recomputes_recursive_values_beyond_rolling_cache():
    from dataclasses import replace
    bars = [bar(i, 100 + i) for i in range(230)]
    corrected = list(bars)
    corrected[10] = replace(bars[10], open=Decimal(119), close=Decimal(119), high=Decimal(120), low=Decimal(118))
    assert bar_indicator_values(bars[:10]) == bar_indicator_values(corrected[:10])
    original, revised = bar_indicator_values(bars), bar_indicator_values(corrected)
    assert original["ema_200"]["value"] != revised["ema_200"]["value"]
    with localcontext() as context:
        context.prec = 160
        alpha, expected = Decimal(2) / 201, corrected[0].close
        for current in corrected[1:]:
            expected = alpha * current.close + (1 - alpha) * expected
        # Algebraically equivalent EMA forms can round differently at the 160-digit boundary.
        assert abs(Decimal(revised["ema_200"]["value"]) - expected) < Decimal("1e-150")


def test_wilder_true_range_adx_and_flat_zero_are_measured_values():
    state = TechnicalFeatures()
    for i in range(28):
        result = state.update(Decimal(100 + i), high=Decimal(101 + i), low=Decimal(99 + i))
        assert (result["atr_14"]["value"] is None) == (i < 14)
        assert (result["adx_14"]["value"] is None) == (i < 27)
    assert Decimal(result["atr_14"]["value"]) == 2
    assert Decimal(result["adx_14"]["value"]) == 100
    assert Decimal(result["adx_14"]["plus_di"]) == 50
    assert Decimal(result["adx_14"]["minus_di"]) == 0
    assert Decimal(result["keltner_20_14_2"]["upper"]) - Decimal(result["keltner_20_14_2"]["lower"]) == 8
    flat = TechnicalFeatures()
    for _ in range(28):
        result = flat.update(Decimal(100), high=Decimal(100), low=Decimal(100))
    assert Decimal(result["atr_14"]["value"]) == Decimal(result["adx_14"]["value"]) == 0


def test_true_range_includes_previous_close_and_wilder_update():
    state = TechnicalFeatures()
    state.update(Decimal(100), high=Decimal(101), low=Decimal(99))
    for _ in range(14):
        result = state.update(Decimal(110), high=Decimal(111), low=Decimal(109))
    with localcontext() as ctx:
        ctx.prec = 160
        assert Decimal(result["atr_14"]["value"]).quantize(Decimal("1e-20")) == (Decimal(37) / 14).quantize(Decimal("1e-20"))
        result = state.update(Decimal(110), high=Decimal(112), low=Decimal(108))
        expected = (Decimal(37) / 14 * 13 + 4) / 14
        assert Decimal(result["atr_14"]["value"]).quantize(Decimal("1e-20")) == expected.quantize(Decimal("1e-20"))


def test_trix_warmup_long_ema_slopes_and_bounded_memory():
    state = TechnicalFeatures()
    for i in range(210):
        result = state.update(Decimal(100))
        assert (result["trix_15_9"]["signal"] is None) == (i < 51)
        assert (result["ema_200"]["slope_5_bars"] is None) == (i < 204)
    assert Decimal(result["trix_15_9"]["value"]) == Decimal(result["trix_15_9"]["signal"]) == 0
    assert Decimal(result["ema_200"]["slope_5_bars"]) == 0
    assert len(state.closes) == 200 and len(state.medians) == 0 and all(len(q) == 6 for q in state.slopes.values())
    assert result["atr_14"]["value"] is None


def test_long_average_distance_is_descriptive_and_uses_the_average_denominator():
    state = TechnicalFeatures()
    for _ in range(199):
        result = state.update(Decimal(100))
    assert result["sma_200"]["value"] is None
    assert result["sma_distance_200_percent"]["value"] is None
    result = state.update(Decimal(200))
    assert Decimal(result["sma_200"]["value"]) == Decimal("100.5")
    with localcontext() as context:
        context.prec = 160
        assert Decimal(result["sma_distance_200_percent"]["value"]) == 100 * (Decimal(200) / Decimal("100.5") - 1)
    assert result["sma_distance_200_percent"]["unit"] == "percent"
    assert result["awesome_5_34"]["value"] is None


def test_awesome_oscillator_uses_range_midpoints_not_closes_and_waits_for_34_ranges():
    state = TechnicalFeatures()
    for i in range(34):
        result = state.update(Decimal(100), high=Decimal(100 + 2 * i), low=Decimal(100))
        assert (result["awesome_5_34"]["value"] is None) == (i < 33)
    # Median prices are 100..133: final SMA5=131, SMA34=116.5.
    assert Decimal(result["awesome_5_34"]["value"]) == Decimal("14.5")
    assert len(state.medians) == 34
    assert bar_indicator_values([])["awesome_5_34"]["value"] is None


@pytest.mark.parametrize("options", [{"high": "99", "low": "98"}, {"high": "101"}, {"high": "NaN", "low": "99"}])
def test_invalid_ranges_reject_without_advancing_state(options):
    state = TechnicalFeatures()
    with pytest.raises(ValueError):
        state.update(Decimal(100), **options)
    assert state.count == 0


@pytest.mark.parametrize("length", [14, 15, 20, 28, 34, 52, 80, 200, 205])
def test_streaming_and_batch_closed_bar_values_match(length):
    bars = [bar(i, str(100 + i % 17)) for i in range(length)]
    result = bar_indicator_values(bars)
    old = indicator_values([b.close for b in bars])
    for key in old:
        assert result[key] == old[key]
    state = TechnicalFeatures()
    for b in bars:
        stream = state.update(b.close, high=b.high, low=b.low)
    assert stream == result
    # Later observations must not mutate saved feature values at this cutoff.
    saved = {name: dict(value) for name, value in stream.items()}
    state.update(Decimal(1000000), high=Decimal(1000001), low=Decimal(999999))
    assert stream == saved == bar_indicator_values(bars)
    with pytest.raises(ValueError, match="contiguous"):
        bar_indicator_values([bars[0], bars[2]])
    assert all(row["status"] == "WARMUP" for row in bar_indicator_values([]).values())


@pytest.mark.parametrize("name", ["rsi-rebound", "macd-cross", "trix-cross", "keltner-breakout"])
def test_registered_rules_warmup_reset_and_do_not_repeat_entries(name):
    strategy = create_strategy(name)
    holding, actions = False, []
    for i in range(180):
        # Several actual down/up cycles, not assumed trade fills.
        b = bar(i, str(100 + (i % 60 if i % 60 < 30 else 60 - i % 60)))
        snap = Snapshot(b.avail, b.symbol, b, b.close - 1, b.close + 1, b.avail)
        action = strategy.decide(snap, holding)[0]
        assert not (action == "BUY_REQUEST" and holding)
        assert not (action == "SELL_REQUEST" and not holding)
        if action == "BUY_REQUEST":
            holding = True
        elif action == "SELL_REQUEST":
            holding = False
        actions.append(action)
    assert actions[0] == "ABSTAIN_WARMUP"
    b = bar(200, "110")
    snap = Snapshot(b.avail, b.symbol, b, b.close - 1, b.close + 1, b.avail)
    assert strategy.decide(snap, holding)[0] == "ABSTAIN_WARMUP"
    assert strategy.decide(snap, None)[0] == "ABSTAIN_UNKNOWN_HOLDINGS"


def test_rsi_entry_is_a_fresh_rebound_and_future_bar_cannot_change_state():
    strategy = create_strategy("rsi-rebound")
    prices = list(range(130, 100, -1)) + [110, 120, 130, 140]
    actions = []
    for i, price in enumerate(prices):
        b = bar(i, price)
        actions.append(strategy.decide(Snapshot(b.avail, b.symbol, b, b.close - 1, b.close + 1, b.avail), False)[0])
    assert actions.count("BUY_REQUEST") == 1
    count = strategy.features.count
    b = bar(len(prices), 140)
    assert strategy.decide(Snapshot(b.start, b.symbol, b, b.close - 1, b.close + 1, b.start), False)[0] == "ABSTAIN_UNAVAILABLE_BAR"
    assert strategy.features.count == count


@pytest.mark.parametrize("name", ["rsi-rebound", "macd-cross", "trix-cross", "keltner-breakout"])
def test_indicator_rules_replay_through_native_cost_and_availability_engine(tmp_path, name):
    from gym.services.diagnostics import diagnostics
    from gym.services.paper import paper
    from tests.support import market_db, quote_history
    db = market_db(tmp_path, quote_history(n=1500))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(hours=4), resolution="1min", strategy_id=name)
        assert out == paper(db, "BTCUSDT", START, START + timedelta(hours=4), resolution="1min", strategy_id=name)
        assert all(check["status"] == "PASS" for check in diagnostics(db, out)["checks"].values())
        assert out["inputs"]["strategy"] == name
    finally:
        db.c.close()
