"""Closed-bar long/flat research rules; proposals remain below execution authority."""
from decimal import Decimal

from .strategy import long_flat
from .technical_features import TechnicalFeatures


class IndicatorCross:
    params = {}

    def __init__(self):
        self.features = TechnicalFeatures()
        self.previous = self.last_bar = None
        self.feature_values = {}

    def decide(self, snap, holding):
        if type(holding) is not bool:
            return "ABSTAIN_UNKNOWN_HOLDINGS", Decimal(0), ("holding state is unknown",), ""
        bar = snap.bar
        if bar.forming or bar.avail > snap.as_of or bar.end > snap.as_of:
            return "ABSTAIN_UNAVAILABLE_BAR", Decimal(0), ("bar is not closed and available",), ""
        if self.last_bar is not None and self.last_bar.end != bar.start:
            self.features, self.previous = TechnicalFeatures(), None
        current = self.features.update(bar.close, high=bar.high, low=bar.low)
        before = self.previous
        self.previous, self.last_bar = current, bar
        self.feature_values = current
        if self.name == "rsi-rebound":
            value = current["rsi_14"]["value"]
            prior = before["rsi_14"]["value"] if before else None
            up = prior is not None and Decimal(prior) <= 30 < Decimal(value)
            down = value is not None and Decimal(value) >= 70
        elif self.name in ("macd-cross", "trix-cross"):
            key = "macd_12_26_9" if self.name == "macd-cross" else "trix_15_9"
            field = "line" if self.name == "macd-cross" else "value"
            value = current[key]["signal"]
            prior = before[key]["signal"] if before else None
            up = prior is not None and value is not None and Decimal(before[key][field]) <= Decimal(prior) and Decimal(current[key][field]) > Decimal(value)
            down = prior is not None and value is not None and Decimal(before[key][field]) >= Decimal(prior) and Decimal(current[key][field]) < Decimal(value)
        else:
            value = current["adx_14"]["value"]
            prior = before["adx_14"]["value"] if before else None
            band = current["keltner_20_14_2"]
            up = prior is not None and value is not None and Decimal(value) >= 25 and bar.close > Decimal(band["upper"]) and self.last_close <= Decimal(before["keltner_20_14_2"]["upper"])
            down = band["middle"] is not None and bar.close < Decimal(band["middle"])
        self.last_close = bar.close
        if value is None or prior is None:
            return long_flat(snap, holding, None, current)
        target = False if holding and down else True if not holding and up else holding
        return long_flat(snap, holding, target, {"indicators": current, "up_cross": up, "exit_condition": down})


class RsiRebound(IndicatorCross):
    name = "rsi-rebound"


class MacdCross(IndicatorCross):
    name = "macd-cross"


class TrixCross(IndicatorCross):
    name = "trix-cross"


class KeltnerBreakout(IndicatorCross):
    name = "keltner-breakout"
