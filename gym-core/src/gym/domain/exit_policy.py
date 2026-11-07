"""Optional closed-bar paper exits over actual fee-inclusive entry fills."""
from decimal import Decimal

from .model import parse_ts
from .strategy import digest
from .technical_features import TechnicalFeatures

EXIT_PARAMETERS = {key: {"type": "integer", "default": 0, "minimum": 0, "maximum": maximum}
                   for key, maximum in (("exit_stop_bps", 9999), ("exit_profit_bps", 100000),
                                        ("exit_atr_multiple", 10), ("exit_after_bars", 100000))}


class ExitPolicy:
    requires_position_context = True

    def __init__(self, strategy, controls):
        self.strategy, self.controls = strategy, controls
        self.params = {**strategy.params, **controls}
        self.version = strategy.version + 1
        self.indicators, self.last_end = TechnicalFeatures(), None
        self.position_id = self.peak = self.trail = None
        self.feature_values = {}
        self.base_ready = False

    def __getattr__(self, key):
        return getattr(self.strategy, key)

    @property
    def entry_allowed(self):
        return self.base_ready and getattr(self.strategy, "entry_allowed", True) and (not self.controls.get("exit_atr_multiple") or Decimal(self.feature_values.get("exit_atr") or "0") > 0)

    @property
    def ready(self):
        return self.base_ready and (not self.controls.get("exit_atr_multiple") or self.feature_values.get("exit_atr") is not None)

    def decide(self, snap, holding):
        bar = snap.bar
        if bar.forming or bar.end > snap.as_of or bar.avail > snap.as_of or type(holding) is not bool:
            return "ABSTAIN_UNAVAILABLE_BAR", Decimal(0), ("closed available bar and actual holdings required",), ""
        if self.last_end is not None and self.last_end != bar.start:
            self.indicators = TechnicalFeatures()
        self.last_end = bar.end
        value = self.indicators.update(bar.close, high=bar.high, low=bar.low)["atr_14"]["value"]
        atr = Decimal(value) if value is not None else None
        action, fraction, reasons, _ = self.strategy.decide(snap, holding)
        self.base_ready = getattr(self.strategy, "ready", action not in ("ABSTAIN_WARMUP", "ABSTAIN_NO_REFERENCE"))
        self.feature_values = {**self.strategy.feature_values, "exit_atr": value, "exit_policy": self.controls}
        context = snap.execution
        if holding and snap.bid is not None and context and context.get("entry_price") and context.get("entry_time"):
            entry = Decimal(context["entry_price"])
            fee = Decimal(context["fee_rate"])
            if self.position_id != context["position_id"]:
                self.position_id, self.peak, self.trail = context["position_id"], entry, None
            self.peak = max(self.peak, snap.bid)
            stop_bps, multiple = self.controls.get("exit_stop_bps", 0), self.controls.get("exit_atr_multiple", 0)
            if stop_bps:
                self.trail = max(self.trail or Decimal(0), entry * (1 - Decimal(stop_bps) / 10000) / (1 - fee))
            if multiple and atr is not None and atr > 0:
                self.trail = max(self.trail or Decimal(0), self.peak - multiple * atr)
            target = entry * (1 + Decimal(self.controls.get("exit_profit_bps", 0)) / 10000) / (1 - fee)
            reason = ("PAPER_STOP_EXIT" if self.trail is not None and snap.bid <= self.trail else
                      "PAPER_PROFIT_EXIT" if self.controls.get("exit_profit_bps") and snap.bid >= target else
                      "PAPER_TIME_EXIT" if self.controls.get("exit_after_bars") and
                      snap.as_of - parse_ts(context["entry_time"]) >= bar.spec.step * self.controls["exit_after_bars"] else None)
            self.feature_values.update(exit_stop_price=None if self.trail is None else str(self.trail), exit_target_price=str(target))
            if reason:
                action, fraction, reasons = "SELL_REQUEST", Decimal(1), (reason,)
        if action == "BUY_REQUEST" and not self.entry_allowed:
            action, fraction, reasons = "ABSTAIN_STOP_WARMUP", Decimal(0), ("positive closed ATR required for trailing stop",)
        return action, fraction, reasons, digest(self.feature_values)[:16]
