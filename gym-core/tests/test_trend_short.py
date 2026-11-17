"""trend-with-short-side shorts below the average, pays carry on borrowed amounts, and stops at the ranking mark."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("trend_short", SCRIPTS / "trend_short.py")
trend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trend)

DAYS = [f"2023-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(300)]


def test_a_steady_fall_pays_the_short_and_costs_the_long_or_cash_rule_nothing():
    closes = [100 * 0.99 ** i for i in range(300)]
    short = [r for _, r in trend.returns(DAYS, closes, 50, 1.0)]
    cash = [r for _, r in trend.returns(DAYS, closes, 50, 1.0, short=False)]
    assert trend.total(short) > 0.5
    assert trend.total(cash) == 0.0


def test_borrowed_amounts_pay_carry_every_day_on_a_flat_price():
    closes = [100.0] * 300
    short = [r for _, r in trend.returns(DAYS, closes, 50, 2.0)]
    assert short[5] == pytest.approx(-2 * trend.CARRY)


def test_a_weak_ranking_stops_before_the_held_out_markets_are_read(capsys):
    flat = (DAYS, [100.0 + (i % 2) for i in range(300)])
    rank = dict.fromkeys(trend.RANK_COINS, flat)
    assert trend.verdict(rank, held_source=None) is False
    assert "held-out markets not scored" in capsys.readouterr().out
