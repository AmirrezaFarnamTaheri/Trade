"""T9's portfolio arithmetic: causal weights, cost on every change of weight, slots that never sum above one."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("trend_portfolio", Path(__file__).parents[1] / "scripts/trend_portfolio.py")
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)


def series(closes, start=date(2023, 1, 1)):
    return {(start + timedelta(days=i)).isoformat(): close for i, close in enumerate(closes)}


def test_a_rising_coin_is_bought_once_and_earns_its_slot_of_the_move():
    rising = [100 * 1.01 ** i for i in range(80)]
    rows = tp.portfolio({"UP": series(rising), "FLAT": series([100.0] * 80)}, 50, "equal", 0.002)
    assert [paid for _, _, paid in rows[:49]] == [0.0] * 49 and rows[49][2] == pytest.approx(0.002 * 0.5)
    assert sum(paid for _, _, paid in rows) == pytest.approx(0.001)  # one entry into half the book, nothing after
    assert rows[49][1] == pytest.approx(0.5 * 0.01) and rows[48][1] == 0.0


def test_the_weight_uses_nothing_after_the_decision_day():
    closes = [100 * 1.01 ** i for i in range(70)]
    crashed = [*closes[:60], *[1.0] * 10]
    assert tp.portfolio({"A": series(closes)}, 50, "vol", 0.0)[:59] == tp.portfolio({"A": series(crashed)}, 50, "vol", 0.0)[:59]


def test_volatility_sizing_never_exceeds_the_equal_share_and_shrinks_a_wild_coin():
    wild = [100.0]
    for i in range(80):
        wild.append(wild[-1] * (1.12 if i % 2 else 0.93))
    assert 0 < tp.weights(wild, 80, 50, "vol") < 0.5
    assert tp.weights([100 * 1.001 ** i for i in range(80)], 79, 50, "vol") == 1.0
    assert tp.weights([100 * 0.99 ** i for i in range(80)], 79, 50, "vol") == 0.0


def test_a_coin_with_no_next_close_is_sold_not_carried():
    short = series([100 * 1.01 ** i for i in range(60)])
    rows = tp.portfolio({"A": short, "B": series([100.0] * 70)}, 50, "equal", 0.002)
    assert rows[59][2] == pytest.approx(0.001) and all(gross == 0.0 for _, gross, _ in rows[59:])
