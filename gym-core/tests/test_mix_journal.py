"""The mix journal carries closes over missing days and gives no weight to a token whose candles stopped."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.mix import inverse_vol_targets, needs_rebalance
from gym.domain.model import parse_ts
from gym.services.mix_journal import daily_returns

DAY0 = parse_ts("2026-01-01T00:00:00Z")


def test_missing_days_carry_the_last_close_and_the_series_starts_when_all_tokens_have_one():
    closes = {"a": {DAY0: Decimal(100), DAY0 + 2 * timedelta(days=1): Decimal(110)},
              "b": {DAY0 + timedelta(days=1): Decimal(50), DAY0 + 2 * timedelta(days=1): Decimal(50)}}
    days, returns, last = daily_returns(closes, DAY0 + 2 * timedelta(days=1))
    assert days[0] == DAY0 + timedelta(days=1) and returns["a"][1] == 0.1 and last == {"a": Decimal(110), "b": Decimal(50)}


def test_weights_never_exceed_one_and_rebalance_only_past_the_band():
    returns = {"a": [0.01 * (-1) ** k for k in range(80)], "b": [0.03 * (-1) ** k for k in range(80)]}
    wanted = inverse_vol_targets(returns, 70)
    assert sum(wanted.values()) <= 1 and wanted["a"] > wanted["b"]
    assert needs_rebalance(wanted, {"a": wanted["a"] + 0.06, "b": wanted["b"]})
    assert not needs_rebalance(wanted, {"a": wanted["a"] + 0.04, "b": wanted["b"]})
