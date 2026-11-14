"""The six checks on the Version 1 USDTTMN rule: leakage, shock, quota, session close, resting state, cost."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from gym.domain.intraday import DAILY_BUY_QUOTA, Params, run_session
from gym.domain.model import TEHRAN, BookTop, iso

OPEN = datetime(2026, 11, 4, 11, 30, tzinfo=TEHRAN)
FEE = Decimal("0.001")
FAST = {"lookback": 3, "entry_bps": 50, "halt_bps": 1000}


def quote(minute, mid, spread=2, size=5000, second=30):
    half = Decimal(spread) / 2
    return BookTop("USDTTMN", OPEN + timedelta(minutes=minute, seconds=second), Decimal(mid) - half, Decimal(mid) + half,
                   Decimal(size), Decimal(size), frozenset())


def path(mids, **kwargs):
    """One quote in the middle of each five-minute bar."""
    return [quote(5 * i + 2, mid, **kwargs) for i, mid in enumerate(mids)]


RICH_THEN_BACK = [100000, 100000, 100000, 102000, 102000, 100000, 100000, 100000]


def run(quotes, fee=FEE, quota_used=0, **params):
    return run_session(quotes, Params(**(FAST | params)), fee_rate=fee, quota_used=Decimal(quota_used))


def test_resting_state_is_usdt_and_a_quiet_session_nets_exactly_zero():
    result = run(path([100000] * 30))
    assert result["net_usdt"] == "0" and result["fills"] == [] and result["state"] == "FLAT"
    assert result["decisions"] == 29


def test_cost_a_round_trip_at_one_price_loses_the_spread_and_both_fees_and_a_higher_fee_loses_more():
    stays_rich = [100000, 100000, 100000, 102000, 102000, 102000, 102000, 102000]
    trip = run(path(stays_rich))
    assert [fill["side"] for fill in trip["fills"]] == ["SELL", "BUY"]
    sold, bought_back = Decimal(101999), Decimal(102001)  # both fills land on quotes at the same mid
    assert abs(Decimal(trip["net_usdt"]) - (1000 * sold * (1 - FEE) / bought_back * (1 - FEE) - 1000)) < Decimal("1e-20")
    assert Decimal(run(path(stays_rich), fee=Decimal("0.003"))["net_usdt"]) < Decimal(trip["net_usdt"]) < 0
    # The entry is a limit at the signal threshold: a price that has already come back is not chased.
    assert run(path([100000, 100000, 100000, 102000, 100000, 100000, 100000]))["fills"] == []
    profit = run(path(RICH_THEN_BACK))
    assert Decimal(profit["net_usdt"]) > 15 and profit["round_trips"] == 1 and profit["state"] == "FLAT"


def test_leakage_a_decision_never_changes_when_later_quotes_change():
    quotes = path(RICH_THEN_BACK + [100000] * 6)
    full = run(quotes)
    for cut in range(1, len(quotes)):
        prefix = run(quotes[:cut])
        assert prefix["fills"] == full["fills"][:len(prefix["fills"])]
    crashed = run(quotes[:5] + path([50000] * 9)[5:])
    assert crashed["fills"][0] == full["fills"][0]
    # The signal bar closes at minute 20; the entry cannot fill on the quote that closed it, only on a later one.
    assert full["fills"][0]["at"] > iso(OPEN + timedelta(minutes=20))


def test_shock_a_large_bar_move_halts_the_session_and_exits_by_limit_never_at_any_price():
    spike = [100000, 100000, 100000, 101000, 112000, 113000, 100500, 100000, 103000, 103000, 103000]
    result = run(path(spike), halt_bps=300, max_slip_bps=50)
    assert result["halted"] is True
    sides = [(fill["side"], fill["reason"]) for fill in result["fills"]]
    assert sides == [("SELL", "SIGNAL"), ("BUY", "HALT")]  # no new entry at 103000 after the halt
    # The exit limit was set at 113001 * 1.005; every buy is at or below it.
    assert all(Decimal(fill["price"]) <= Decimal(113001) * Decimal("1.005") for fill in result["fills"] if fill["side"] == "BUY")
    empty_ask = path(spike[:5]) + [quote(27, 113000, size=0), quote(32, 125000), quote(37, 126000)]
    gap = run(empty_ask, halt_bps=300, max_slip_bps=50)
    assert gap["state"] == "STRANDED" and [fill["side"] for fill in gap["fills"]] == ["SELL"]
    assert Decimal(gap["net_usdt"]) < -100  # the price ran past the limit: valued at the last ask, not ignored


def test_quota_buys_never_exceed_the_daily_limit_and_a_used_quota_shrinks_the_trade():
    waves = [100000, 100000, 100000] + [102000, 100000, 100000, 100000] * 6
    result = run(path(waves), size_usdt=Decimal(900))
    assert Decimal(result["bought_usdt"]) <= DAILY_BUY_QUOTA
    assert sum(Decimal(fill["usdt"]) for fill in result["fills"] if fill["side"] == "BUY") <= DAILY_BUY_QUOTA
    limited = run(path(RICH_THEN_BACK), quota_used=1800)
    assert limited["fills"][0]["usdt"] == "200"
    assert run(path(RICH_THEN_BACK), quota_used=2000)["fills"] == []
    assert run(path(RICH_THEN_BACK, size=40))["fills"][0]["usdt"] == "40"  # never more than the displayed touch


def test_session_close_forces_the_exit_early_and_takes_no_entry_after_it():
    late = 12 * 60 - 40  # minutes after the open: 22:50 Tehran
    quotes = [quote(late + 5 * i + 2, mid) for i, mid in enumerate([100000, 100000, 100000, 102000, 102000, 102000, 102000, 102000])]
    result = run(quotes)
    assert [(fill["side"], fill["reason"]) for fill in result["fills"]] == [("SELL", "SIGNAL"), ("BUY", "SESSION_CLOSE")]
    assert result["state"] == "FLAT" and result["fills"][-1]["at"] < "2026-11-04T20:00"  # 23:30 Tehran is 20:00 UTC
    after = [quote(12 * 60 - 14 + i, mid, second=0) for i, mid in enumerate([100000, 100000, 100000, 102000, 102000])]
    assert run(after, lookback=2)["fills"] == []


def test_buy_cheap_is_the_mirror_and_pays_financing():
    cheap = [100000, 100000, 100000, 98000, 98000, 100000, 100000, 100000]
    free = run(path(cheap), direction="BUY_CHEAP")
    assert [fill["side"] for fill in free["fills"]] == ["BUY", "SELL"] and free["state"] == "FLAT"
    financed = run(path(cheap), direction="BUY_CHEAP", financing_bps=Decimal(20))
    assert 0 < Decimal(financed["net_usdt"]) < Decimal(free["net_usdt"])
    assert Decimal(free["net_usdt"]) - Decimal(financed["net_usdt"]) == pytest.approx(Decimal("1.96"), abs=Decimal("0.05"))


def test_invalid_parameters_and_mixed_days_are_refused():
    for bad in ({"direction": "SHORT"}, {"size_usdt": Decimal(2001)}, {"entry_bps": 0}, {"financing_bps": Decimal(5)}):
        with pytest.raises(ValueError):
            Params(**bad)
    with pytest.raises(ValueError, match="one Tehran day"):
        run([quote(0, 100000), quote(24 * 60, 100000)])
