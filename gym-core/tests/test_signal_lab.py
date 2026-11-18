import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from margin_hold import hold  # noqa: E402
from signal_lab import DAY, HALF_SPREAD, Position, run_coin  # noqa: E402

PATH = [(100, 104, 102), (97, 103, 99), (95, 101, 100), (99, 108, 107), (104, 110, 109)]  # (low, high, close)


@pytest.mark.parametrize(("side", "ratio"), [(1, 2), (1, 5), (-1, 1), (-1, 3)])
def test_incremental_position_matches_margin_hold_every_day(side, ratio):
    entry_close = 101.0
    position = Position(side, ratio, entry_close)
    for k, (low, high, close) in enumerate(PATH, 1):
        equity = position.step(low, high, close)
        path = [(d * DAY, lo, hi) for d, (lo, hi, _) in enumerate(PATH[:k], 1)]
        expected = hold("long" if side > 0 else "short", ratio, entry_close * (1 + HALF_SPREAD * side), path,
                        close * (1 - HALF_SPREAD * side))
        assert equity == pytest.approx(1 + expected["ret"], abs=1e-12)
        assert position.liquidated == (expected["liquidated_h"] is not None)
        if position.liquidated:
            break


def test_a_5x_short_into_a_rally_is_liquidated_at_the_floor():
    position = Position(-1, 5, 100.0)
    assert position.step(99, 125, 120) == pytest.approx(0.15)
    assert position.liquidated


def test_run_coin_logs_every_decision_and_compounds_returns():
    bars = {"days": [f"2020-01-0{i}" for i in range(1, 7)], "close": [100, 101, 103, 102, 99, 98],
            "low": [100, 100, 101, 101, 98, 97], "high": [100, 102, 104, 103, 102, 99]}
    counted = [True] * 6
    positions = [None, 1, 1, -1, -1, 0]
    series, counts, strat, hold_return = run_coin(bars, counted, positions, 1)
    assert [d for d, _ in series] == bars["days"][1:]
    assert counts["OPEN_LONG_SPOT"] == 1 and counts["FLIP"] == 1 and counts["OPEN_SHORT"] == 1
    assert counts["EXIT_SIGNAL"] == 1 and counts["HOLD"] == 2 and counts["CASH"] == 0
    assert hold_return == pytest.approx(98 / 100 - 1)
    product = 1.0
    for _, r in series:
        product *= 1 + r
    assert strat == pytest.approx(product - 1)
