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
