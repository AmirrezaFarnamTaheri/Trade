"""Combine single-market rules into one long/flat decision.

Each member runs on every closed bar with its own virtual position, so its target (long, flat or warming up) is
what it would hold alone. The blend maps the members' targets to one target:

  vote       consensus c = share of members long; enter at c >= enter_pct, exit at c <= exit_pct.
             enter_pct 100 is AND, just over 50 is majority; the gap between the two is a churn band.
  confirm    the first member times entries and exits; the others must agree at >= enter_pct before an entry.
  calm-vote  vote, each member weighted 1 / (1 + its target flips over the last calm_bars bars): a member that
             churns, and so pays the most spread, gets less say. Learned from the member's own past only.

min_hold_bars keeps a position at least that many bars after entry: a direct cap on turnover.
"""
from collections import deque
from decimal import Decimal

from .signals import SIGNALS, OnBalanceVolume
from .strategy import digest

FORMS = ("vote", "confirm", "calm-vote")
# Single-market members only: no reference symbol, extra resolution or execution context to supply.
RULES = ("ema-trend", "sma-cross", "sma-reversion", "bollinger-reversion", "rsi-rebound", "macd-cross",
         "trix-cross", "keltner-breakout", "donchian-breakout", "compression-breakout")
# Signed bar signals from domain/signals.py; on spot a short condition means cash.
SIGNAL_MEMBERS = ("ema-cross", "tsmom", "donchian", "efficiency", "obv", "rsi-reversion")
MEMBERS = RULES + SIGNAL_MEMBERS
WINDOWED_SIGNALS = {"tsmom", "efficiency", "donchian"}
WINDOW_BARS = 21
TARGET = {"BUY_REQUEST": True, "SELL_REQUEST": False}


class SignalBlend:
    name = "signal-blend"
    version = 1

    def __init__(self, members, *, form="vote", enter_pct=67, exit_pct=34, min_hold_bars=0, calm_bars=24, params=None):
        if form not in FORMS:
            raise ValueError("invalid strategy parameter: form")
        if not 0 <= exit_pct < enter_pct <= 100:
            raise ValueError("invalid strategy parameter: exit_pct must be below enter_pct")
        if len(members) < (2 if form == "confirm" else 1):
            raise ValueError("invalid strategy parameter: members")
        self.members, self.form = list(members), form
        self.enter, self.exit = Decimal(enter_pct) / 100, Decimal(exit_pct) / 100
        self.min_hold, self.calm_bars = min_hold_bars, calm_bars
        self.params = params or {"form": form, "enter_pct": enter_pct, "exit_pct": exit_pct,
                                 "min_hold_bars": min_hold_bars, "calm_bars": calm_bars}
        self.held = [False] * len(self.members)
        self.targets: list[bool | None] = [None] * len(self.members)
        self.flips = [deque(maxlen=calm_bars) for _ in self.members]
        self.bars_held, self.feature_values = 0, {}

    def _observe(self, snap):
        no_volume = False
        for i, member in enumerate(self.members):
            action = member.decide(snap, self.held[i])[0]
            if action.startswith("ABSTAIN"):
                no_volume |= action == "ABSTAIN_NO_VOLUME"
                self.targets[i] = None if action == "ABSTAIN_WARMUP" else self.targets[i]
                self.flips[i].append(False)
                continue
            target = TARGET.get(action, self.held[i])
            self.flips[i].append(self.targets[i] is not None and target != self.targets[i])
            self.held[i] = self.targets[i] = target
        return no_volume

    def _consensus(self, members):
        if self.form == "calm-vote":
            weights = [Decimal(1) / (1 + sum(self.flips[i])) for i in members]
            return sum(w for w, i in zip(weights, members) if self.targets[i]) / sum(weights)
        return Decimal(sum(bool(self.targets[i]) for i in members)) / len(members)

    def decide(self, snap, holding):
        no_volume = self._observe(snap)
        everyone = range(len(self.members))
        consensus = self._consensus(range(1, len(self.members)) if self.form == "confirm" else everyone)
        self.feature_values = {"consensus": float(consensus), "targets": list(self.targets), "bars_held": self.bars_held}
        if no_volume:
            self.feature_values["obv_volume"] = "MISSING" if snap.observed_trade_volume is None else "ZERO"
        fingerprint = digest(self.feature_values)[:16]
        if no_volume:
            self.bars_held = self.bars_held + 1 if holding else 0
            return "ABSTAIN_NO_VOLUME", Decimal(0), ("OBV needs positive trade volume",), fingerprint
        if any(t is None for t in self.targets):
            return "ABSTAIN_WARMUP", Decimal(0), ("a member is warming up",), fingerprint
        if snap.bid is None:
            return "ABSTAIN_NO_QUOTE", Decimal(0), ("no qualified quote at decision time",), fingerprint
        self.bars_held = self.bars_held + 1 if holding else 0
        if self.form == "confirm":
            want = (self.targets[0] and consensus >= self.enter) if not holding else self.targets[0]
        else:
            want = consensus >= self.enter if not holding else consensus > self.exit
        if holding and not want and self.bars_held < self.min_hold:
            want = True  # inside the minimum holding period
        if want and not holding:
            return "BUY_REQUEST", Decimal(1), (f"{self.form} consensus {float(consensus):.2f}",), fingerprint
        if holding and not want:
            return "SELL_REQUEST", Decimal(1), (f"{self.form} consensus {float(consensus):.2f}",), fingerprint
        return "HOLD", Decimal(0), (f"{self.form} consensus {float(consensus):.2f}",), fingerprint


class SignalMember:
    """A signed signal as a long/flat member: +1 long, -1 or a fresh 0 flat-or-keep, None warming up."""
    version = 1

    def __init__(self, name, *, require_volume=False):
        self.name, self.signal, self.params = name, SIGNALS[name], {}
        self.closes = deque(maxlen=WINDOW_BARS if name in WINDOWED_SIGNALS else None)
        self.obv = OnBalanceVolume(require_volume=require_volume) if name == "obv" else None
        self.last = None

    def decide(self, snap, holding):
        close = float(snap.bar.close)
        if self.obv is not None:
            observed = snap.observed_trade_volume if self.obv.require_volume else snap.bar.volume
            volume = None if observed is None else float(observed)
            target = self.obv.update(close, volume)
            if self.obv.require_volume and not volume:
                self.last = target
                return "ABSTAIN_NO_VOLUME", Decimal(0), ("OBV needs positive trade volume",), ""
        else:
            self.closes.append(close)
            target = self.signal({"close": list(self.closes)})[-1]
        if self.name == "donchian" and target == 0 and self.last is not None:
            target = self.last
        self.last = target
        if target is None:
            return "ABSTAIN_WARMUP", Decimal(0), ("signal warming up",), ""
        if target > 0 and not holding:
            return "BUY_REQUEST", Decimal(1), (f"{self.name} long",), ""
        if target < 0 and holding:
            return "SELL_REQUEST", Decimal(1), (f"{self.name} short condition: cash on spot",), ""
        return "HOLD", Decimal(0), (f"{self.name} {target:+d}",), ""


def blend_from_names(members="ema-trend,macd-cross,keltner-breakout,rsi-rebound", *, obv_volume_policy="legacy", **options):
    """Registry constructor: members by name, each at its registered default parameters."""
    from .registry import create_strategy
    names = [n.strip() for n in members.split(",") if n.strip()]
    if not names or len(set(names)) != len(names) or any(n not in MEMBERS for n in names):
        raise ValueError(f"invalid strategy parameter: members must be distinct names from {', '.join(MEMBERS)}")
    require_volume = obv_volume_policy == "require-positive"
    if require_volume and "obv" not in names:
        raise ValueError("obv_volume_policy requires an obv member")
    members_ = [SignalMember(n, require_volume=require_volume) if n in SIGNAL_MEMBERS else create_strategy(n) for n in names]
    params = {"members": ",".join(names), **options}
    if require_volume:
        params["obv_volume_policy"] = obv_volume_policy
    return SignalBlend(members_, params=params, **options)


blend_from_names.version = SignalBlend.version
