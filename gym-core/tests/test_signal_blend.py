from decimal import Decimal
from types import SimpleNamespace

import pytest

from gym.domain.blend_strategies import SignalBlend
from gym.domain.registry import create_strategy


class Scripted:
    """A member that wants the scripted target each bar: 1 long, 0 flat, None warming up."""
    params: dict = {}

    def __init__(self, targets):
        self.targets, self.i = list(targets), 0

    def decide(self, snap, holding):
        target = self.targets[self.i]
        self.i += 1
        if target is None:
            return "ABSTAIN_WARMUP", Decimal(0), ("warming",), ""
        if target and not holding:
            return "BUY_REQUEST", Decimal(1), ("in",), ""
        if not target and holding:
            return "SELL_REQUEST", Decimal(1), ("out",), ""
        return "HOLD", Decimal(0), ("stay",), ""


SNAP = SimpleNamespace(bid=Decimal(100), ask=Decimal(101))


def actions(blend, bars):
    holding, out = False, []
    for _ in range(bars):
        action = blend.decide(SNAP, holding)[0]
        holding = {"BUY_REQUEST": True, "SELL_REQUEST": False}.get(action, holding)
        out.append(action)
    return out


def test_vote_enters_on_consensus_and_exits_only_below_the_band():
    members = [Scripted([1, 1, 1, 1, 0]), Scripted([0, 1, 1, 0, 0]), Scripted([0, 1, 0, 0, 0])]
    blend = SignalBlend(members, form="vote", enter_pct=67, exit_pct=34)
    # consensus 1/3, 3/3, 2/3, 1/3, 0/3: enter at 3/3, stay at 2/3 (inside the band), leave at 1/3
    assert actions(blend, 5) == ["HOLD", "BUY_REQUEST", "HOLD", "SELL_REQUEST", "HOLD"]


def test_vote_waits_until_every_member_is_ready():
    blend = SignalBlend([Scripted([None, 1]), Scripted([1, 1])], form="vote", enter_pct=100, exit_pct=0)
    assert actions(blend, 2) == ["ABSTAIN_WARMUP", "BUY_REQUEST"]


def test_confirm_lets_the_primary_time_entries_only_when_the_others_agree():
    primary = Scripted([1, 0, 1, 1])
    filter_ = Scripted([0, 0, 1, 0])
    blend = SignalBlend([primary, filter_], form="confirm", enter_pct=100, exit_pct=0)
    # bar 1: primary long, filter flat -> no entry; bar 3: both long -> enter; bar 4: filter drops, primary holds
    assert actions(blend, 4) == ["HOLD", "HOLD", "BUY_REQUEST", "HOLD"]


def test_calm_vote_gives_a_churning_member_less_say():
    churner = Scripted([1, 0, 1, 0, 1, 0, 1])
    steady = Scripted([0, 0, 0, 0, 0, 0, 0])
    steady2 = Scripted([0, 0, 0, 0, 0, 0, 1])
    blend = SignalBlend([churner, steady, steady2], form="calm-vote", enter_pct=50, exit_pct=10, calm_bars=6)
    # last bar: churner (6 flips, weight 1/7) and steady2 (1 flip, weight 1/2) are long, steady (weight 1) is flat:
    # (1/7 + 1/2) / (1/7 + 1 + 1/2) = 0.39 < 0.50, so no entry even though two of three members are long
    assert actions(blend, 7)[-1] == "HOLD"
    assert blend.feature_values["consensus"] == pytest.approx((1 / 7 + 1 / 2) / (1 / 7 + 1 + 1 / 2))


def test_min_hold_bars_caps_turnover():
    members = [Scripted([1, 0, 0, 0, 0])]
    blend = SignalBlend(members, form="vote", enter_pct=100, exit_pct=0, min_hold_bars=3)
    assert actions(blend, 5) == ["BUY_REQUEST", "HOLD", "HOLD", "SELL_REQUEST", "HOLD"]


def test_registry_builds_named_members_and_hashes_the_blend():
    blend = create_strategy("signal-blend", {"members": "ema-trend,rsi-rebound", "form": "vote"})
    other = create_strategy("signal-blend", {"members": "ema-trend,macd-cross", "form": "vote"})
    assert blend.config_hash != other.config_hash
    assert [m.name for m in blend.members] == ["ema-trend", "rsi-rebound"]
    with pytest.raises(ValueError, match="member"):
        create_strategy("signal-blend", {"members": "lead-lag,ema-trend"})
    with pytest.raises(ValueError, match="exit_pct"):
        create_strategy("signal-blend", {"enter_pct": 50, "exit_pct": 60})


def test_donchian_remembers_a_breakout_during_a_long_plateau():
    from gym.domain.blend_strategies import SignalMember

    member = SignalMember("donchian")
    for close in [100] * 20 + [101] * 510:
        bar = SimpleNamespace(close=Decimal(close), high=Decimal(close), low=Decimal(close), volume=Decimal(1))
        action = member.decide(SimpleNamespace(bar=bar), False)[0]
    assert action == "BUY_REQUEST"


def test_signal_members_match_batch_signals():
    import random
    from datetime import UTC, datetime, timedelta

    from gym.domain.blend_strategies import SIGNAL_MEMBERS, SignalMember
    from gym.domain.signals import SIGNALS

    rng = random.Random(7)
    closes, price = [], 100.0
    for _ in range(1200):  # more than twice the 500-bar window
        price *= 1 + rng.gauss(0.0005, 0.02)
        closes.append(price)
    for name in SIGNAL_MEMBERS:
        member, full = SignalMember(name), SIGNALS[name]
        history = {"close": [], "high": [], "low": [], "volume": []}
        for i, c in enumerate(closes):
            bar = SimpleNamespace(close=Decimal(str(c)), high=Decimal(str(c * 1.01)), low=Decimal(str(c * 0.99)),
                                  volume=Decimal(str(1000 + i % 37)), start=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i))
            for key, value in (("close", bar.close), ("high", bar.high), ("low", bar.low), ("volume", bar.volume)):
                history[key].append(float(value))
            member.decide(SimpleNamespace(bar=bar, bid=Decimal(1), ask=Decimal(1)), False)
            assert member.last == full(history)[-1], (name, i)


def test_obv_volume_policy_has_new_identity_and_abstains_on_zero_and_missing_volume():
    config = {"members": "obv", "enter_pct": 100, "exit_pct": 0}
    legacy = create_strategy("signal-blend", config)
    guarded = create_strategy("signal-blend", {**config, "obv_volume_policy": "require-positive"})
    assert "obv_volume_policy" not in legacy.params
    assert guarded.config_hash != legacy.config_hash
    assert create_strategy("signal-blend", guarded.params).config_hash == guarded.config_hash

    def bar(close, volume):
        return SimpleNamespace(bid=Decimal(1), observed_trade_volume=volume, bar=SimpleNamespace(close=Decimal(close)))

    for close in range(1, 21):
        result = guarded.decide(bar(close, Decimal(2)), holding=False)
    assert result[0] == "BUY_REQUEST"
    for volume, quality in [(Decimal(0), "ZERO"), (None, "MISSING")]:
        assert guarded.decide(bar(19, volume), holding=True)[0] == "ABSTAIN_NO_VOLUME"
        assert guarded.feature_values["obv_volume"] == quality
    assert guarded.decide(bar(18, Decimal(100)), holding=True)[0] == "SELL_REQUEST"
    assert len(guarded.members[0].obv.window) == 20
    assert not guarded.members[0].closes


def test_paper_replay_obv_uses_available_prints_and_hashes_them(tmp_path):
    from datetime import timedelta

    from gym.domain.model import TradeTick
    from gym.domain.sim import CostModel
    from gym.services.data_portal import DataPortal
    from gym.services.paper import run
    from tests.support import START, market_db, quote_history

    db = market_db(tmp_path, quote_history(n=24, step=60, turn=1))
    portal = DataPortal(db)
    symbol = "BTCUSDT"
    end = START + timedelta(minutes=23)
    config = {"members": "obv", "obv_volume_policy": "require-positive"}

    def replay():
        strategy = create_strategy("signal-blend", config)
        return run(portal, lambda _: (), strategy, symbol, START, end, "1min", Decimal(100), CostModel())

    def trade(minute, delay):
        event_at = START + timedelta(minutes=minute, seconds=10)
        db.add_trade(TradeTick(symbol, event_at, event_at + timedelta(seconds=delay), Decimal(70000), Decimal(2), "BUY"), "raw")

    try:
        for minute in range(21):
            trade(minute, 0)
        first = replay()
        trade(0, 60)  # after the close at which the bar was consumed
        assert replay() == first
        assert first["decisions"][0]["bar_known"]["volume_evidence"]["volume"] == "2"
        assert any(d["action"] == "BUY_REQUEST" for d in first["decisions"])
        assert first["decisions"][-1]["action"] == "ABSTAIN_NO_VOLUME"
        trade(0, 0)
        revised = replay()
        assert revised["data_digest"] != first["data_digest"]
        assert revised["decisions"][0]["snapshot"] != first["decisions"][0]["snapshot"]
    finally:
        db.c.close()
