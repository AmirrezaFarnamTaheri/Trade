"""Repeatable timing-skill baselines use real holding times, not invented trades."""

from gym.services.random_entry import random_entry_percentile


def test_200_seed_random_entries_preserve_trade_count_and_holdings():
    """A synthetic trend should rank a deliberately favorable trade at the top."""
    points = [(i * 60, 100 + i * 10) for i in range(10)]
    trades = [{"holding_seconds": 60, "net_return": 0.11, "cost_drag": 0.005},
              {"holding_seconds": 120, "net_return": 0.22, "cost_drag": 0.005}]
    first = random_entry_percentile(points, trades)
    assert first == random_entry_percentile(points, trades)
    assert first["status"] == "EXPLORATORY"
    assert first["seeds"] == 200 and first["trades"] == 2
    assert 0 <= first["percentile"] <= 100


def test_missing_exact_duration_abstains_instead_of_interpolating_future_quotes():
    """No fabricated fill price is allowed between observed bars."""
    assert random_entry_percentile([(0, 100), (60, 101), (120, 100)],
                                   [{"holding_seconds": 75, "net_return": 0.01,
                                     "cost_drag": 0.001}])["reason"] == "NO_EXACT_HOLDING_WINDOW"
