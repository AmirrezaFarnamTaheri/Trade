"""Closed-bar prior-channel hypotheses; signals do not assume fills or an edge."""
from collections import deque
from decimal import Decimal

from .regime import market_regime
from .strategy import long_flat
from .technical_features import TechnicalFeatures


class DonchianBreakout:
    name = "donchian-breakout"
    version = 1

    def __init__(self, lookback=20, exit_lookback=10, compression_bps=0, regime="ANY"):
        if (type(lookback) is not int or type(exit_lookback) is not int or not 2 <= exit_lookback <= lookback <= 500
                or type(compression_bps) is not int or not 0 <= compression_bps <= 10000
                or regime not in ("ANY", "UP_TREND", "RANGE")):
            raise ValueError("invalid channel windows, compression or regime")
        self.params = {"lookback": lookback, "exit_lookback": exit_lookback, "compression_bps": compression_bps, "regime": regime}
        self.history = deque(maxlen=lookback)
        self.indicators, self.last_end, self.feature_values = TechnicalFeatures(), None, {}

    def decide(self, snap, holding):
        bar = snap.bar
        if type(holding) is not bool or bar.forming or bar.avail > snap.as_of or bar.end > snap.as_of:
            return "ABSTAIN_UNAVAILABLE_BAR", Decimal(0), ("closed available bar and actual holdings required",), ""
        if self.last_end is not None and self.last_end != bar.start:
            self.history.clear()
            self.indicators = TechnicalFeatures()
        self.last_end = bar.end
        indicators = self.indicators.update(bar.close, high=bar.high, low=bar.low)
        state = market_regime(indicators)
        previous = list(self.history)
        self.feature_values = {"observations": len(previous), "regime": state, "required": self.params["lookback"]}
        self.history.append(bar)
        if len(previous) < self.params["lookback"]:
            return long_flat(snap, holding, None, self.feature_values)
        high, low = max(b.high for b in previous), min(b.low for b in previous)
        exit_low = min(b.low for b in previous[-self.params["exit_lookback"]:])
        width = (high - low) / low * 10000
        self.feature_values.update(prior_high=str(high), prior_low=str(low), prior_exit_low=str(exit_low), width_bps=str(width))
        target = bar.close >= exit_low if holding else bar.close > high
        if not holding:
            if self.params["compression_bps"] and width > self.params["compression_bps"]:
                target = False
            if self.params["regime"] != "ANY" and state != self.params["regime"]:
                target = None if state == "WARMUP" else False
        return long_flat(snap, holding, target, self.feature_values)


class CompressionBreakout(DonchianBreakout):
    name = "compression-breakout"

    def __init__(self, lookback=20, exit_lookback=10, compression_bps=100, regime="ANY"):
        super().__init__(lookback, exit_lookback, compression_bps, regime)
