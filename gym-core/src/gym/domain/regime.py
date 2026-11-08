"""One causal regime classification over already available streaming indicators."""
from decimal import Decimal

from .strategy import digest
from .technical_features import TechnicalFeatures

REGIME_GATE = {"type": "string", "default": "ANY", "enum": ["ANY", "UP_TREND", "RANGE"]}


def market_regime(features):
    required = (("ema_20", "value"), ("ema_50", "value"), ("ema_20", "slope_5_bars"),
                ("adx_14", "value"), ("adx_14", "plus_di"), ("adx_14", "minus_di"), ("atr_14", "value"))
    if any(features.get(key, {}).get(field) is None for key, field in required):
        return "WARMUP"
    fast, slow, slope, adx, plus, minus, atr = (Decimal(features[key][field]) for key, field in required)
    if adx >= 25 and fast > slow and slope > 0 and plus > minus:
        return "UP_TREND"
    if adx >= 25 and fast < slow:
        return "DOWN_TREND"
    return "RANGE" if adx <= 18 and atr > 0 and abs(fast - slow) <= atr else "TRANSITION"


class RegimeGate:
    """Filter entries while leaving the underlying strategy's exits and history intact."""

    def __init__(self, strategy, gate):
        self.strategy, self.gate = strategy, gate
        self.params = {**strategy.params, "regime_gate": gate}
        self.version = strategy.version + 1
        self.indicators, self.last_end, self.feature_values = TechnicalFeatures(), None, {}
        self.base_ready = False

    def __getattr__(self, key):
        return getattr(self.strategy, key)

    @property
    def ready(self):
        return self.feature_values.get("entry_regime", "WARMUP") != "WARMUP" and self.base_ready

    @property
    def entry_allowed(self):
        return self.feature_values.get("entry_regime") == self.gate

    def decide(self, snap, holding):
        bar = snap.bar
        if bar.forming or bar.avail > snap.as_of or bar.end > snap.as_of or type(holding) is not bool:
            return "ABSTAIN_UNAVAILABLE_BAR", Decimal(0), ("closed available bar and actual holdings required",), ""
        if self.last_end is not None and self.last_end != bar.start:
            self.indicators = TechnicalFeatures()
        self.last_end = bar.end
        state = market_regime(self.indicators.update(bar.close, high=bar.high, low=bar.low))
        action, fraction, reasons, _ = self.strategy.decide(snap, holding)
        self.base_ready = getattr(self.strategy, "ready", action not in ("ABSTAIN_WARMUP", "ABSTAIN_NO_REFERENCE"))
        self.feature_values = {**getattr(self.strategy, "feature_values", {}), "entry_regime": state, "regime_gate": self.gate}
        if action == "BUY_REQUEST" and state != self.gate:
            action, fraction, reasons = "ABSTAIN_REGIME", Decimal(0), (f"entry requires {self.gate}; observed {state}",)
        return action, fraction, reasons, digest(self.feature_values)[:16]
