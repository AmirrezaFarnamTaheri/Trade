import pytest

from gym.domain.signals import (
    SIGNALS,
    blend,
    donchian,
    efficiency,
    obv,
    rsi_reversion,
    tsmom,
)


def bars(closes, volume=None):
    return {"close": list(closes), "high": list(closes), "low": list(closes), "volume": volume or [1.0] * len(closes)}


def test_tsmom_signs_the_lookback_return_with_a_neutral_band():
    assert tsmom(bars([100, 100, 103, 99, 100.5]), lookback=2, band_bps=100) == [None, None, 1, -1, -1]
    assert tsmom(bars([100, 100, 100.5]), lookback=2, band_bps=100) == [None, None, 0]


def test_donchian_holds_the_last_breakout_direction():
    assert donchian(bars([10, 11, 12, 11.5, 9, 10]), lookback=2) == [None, None, 1, 1, -1, -1]


def test_efficiency_trades_only_straight_paths():
    straight = efficiency(bars([1, 2, 3, 4, 5]), lookback=4, min_er_pct=40)
    choppy = efficiency(bars([1, 3, 1, 3, 1.5]), lookback=4, min_er_pct=40)
    assert straight[-1] == 1 and choppy[-1] == 0


def test_obv_follows_volume_on_up_and_down_closes():
    assert obv(bars([1, 2, 3, 2, 1], volume=[0, 10, 10, 30, 30]), lookback=2) == [None, 1, 1, -1, -1]


def test_rsi_reversion_is_contrarian():
    falling = rsi_reversion(bars([100 - i for i in range(20)]), period=14)
    rising = rsi_reversion(bars([100 + i for i in range(20)]), period=14)
    assert falling[-1] == 1 and rising[-1] == -1 and falling[13] is None


def test_every_signal_is_causal():
    base = [100 + (i % 7) * 1.5 - (i % 3) for i in range(80)]
    for name, fn in SIGNALS.items():
        full = fn(bars(base))
        for cut in (30, 55):
            assert fn(bars(base[:cut])) == full[:cut], name


def test_blend_vote_goes_long_short_and_back_through_the_band(monkeypatch):
    import gym.domain.signals as s
    scripted = {"a": [1, 1, -1, -1, 0], "b": [1, 0, -1, 0, 0], "c": [0, 1, -1, -1, 1]}
    monkeypatch.setattr(s, "SIGNALS", {k: (lambda b, v=v: v) for k, v in scripted.items()})
    closes = bars([1, 1, 1, 1, 1])
    # consensus 2/3, 2/3, -1, -2/3, 1/3
    assert blend(closes, ["a", "b", "c"], enter_pct=67, exit_pct=34) == [0, 0, -1, -1, 0]
    assert blend(closes, ["a", "b", "c"], enter_pct=60, exit_pct=10) == [1, 1, -1, -1, 0]
    assert blend(closes, ["a", "b", "c"], enter_pct=60, exit_pct=10, long_only=True) == [1, 1, 0, 0, 0]


def test_blend_min_hold_keeps_a_side_open(monkeypatch):
    import gym.domain.signals as s
    monkeypatch.setattr(s, "SIGNALS", {"a": lambda b: [1, 0, 0, 0]})
    assert blend(bars([1] * 4), ["a"], enter_pct=100, exit_pct=0, min_hold_bars=2) == [1, 1, 1, 0]


def test_blend_rejects_an_inverted_band():
    with pytest.raises(ValueError, match="exit_pct"):
        blend(bars([1, 2]), ["tsmom"], enter_pct=30, exit_pct=40)
