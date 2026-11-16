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


def test_a_rising_coin_pays_for_drift_back_to_its_equal_slot():
    rising = [100 * 1.01 ** i for i in range(80)]
    rows = tp.portfolio({"UP": series(rising), "FLAT": series([100.0] * 80)}, 50, "equal", 0.002)
    assert [paid for _, _, paid in rows[:49]] == [0.0] * 49
    assert rows[49][2] == pytest.approx(0.001 / 1.001)
    drifted = 0.5 * 1.01 / 1.005
    expected_sale_fee = 0.002 * (drifted - 0.5) / (1 - 0.001)
    assert rows[50][2] == pytest.approx(expected_sale_fee)
    assert all(paid > 0 for _, _, paid in rows[50:])
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


def test_a_missing_future_close_cannot_cause_a_prescient_sale():
    short = series([100 * 1.01 ** i for i in range(60)])
    with pytest.raises(ValueError, match="missing next close for A"):
        tp.portfolio({"A": short, "B": series([100.0] * 70)}, 50, "equal", 0.002)


def test_full_allocation_funds_its_fee_without_borrowing():
    rows = tp.portfolio({"A": series([100 * 1.01 ** i for i in range(52)])}, 50, "equal", 0.002)
    assert rows[49][2] == pytest.approx(0.002 / 1.002)
    assert rows[50][2] == 0.0  # a sole fully invested coin does not need daily rebalancing
    assert tp.summary(rows)["total"] == pytest.approx(1.01 ** 2 / 1.002 - 1)


def test_return_summary_compounds_both_paths_and_reconciles_cost_drag():
    report = tp.summary([("2023-01-01", 0.10, 0.01), ("2023-01-02", -0.05, 0.02)])
    assert report["gross"] == pytest.approx(1.10 * 0.95 - 1)
    assert report["total"] == pytest.approx(0.99 * 1.10 * 0.98 * 0.95 - 1)
    assert report["paid"] == pytest.approx(0.01 + 0.02 * 0.99 * 1.10)
    assert report["cost_drag"] == pytest.approx(report["gross"] - report["total"])


def test_an_unlisted_coin_keeps_its_empty_slot_without_future_information():
    rows = tp.portfolio({"A": series([100 * 1.01 ** i for i in range(60)]),
                         "LATER": series([100.0] * 10, date(2023, 2, 20))}, 50, "equal", 0.0)
    assert rows[49][1] == pytest.approx(0.005)
