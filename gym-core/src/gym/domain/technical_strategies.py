"""Closed-bar long/flat research rules; proposals remain below execution authority."""
from decimal import Decimal

from .strategy import long_flat
from .technical_features import TechnicalFeatures

PARAMETERS = {
    "rsi-rebound": {"period": (14, 2, 500), "entry_threshold": (30, 0, 99), "exit_threshold": (70, 1, 100)},
    "macd-cross": {"fast": (12, 1, 499), "slow": (26, 2, 500), "signal": (9, 1, 500)},
    "trix-cross": {"period": (15, 2, 500), "signal": (9, 1, 500)},
    "keltner-breakout": {"ema_period": (20, 1, 500), "range_period": (14, 2, 500),
                         "multiplier": (2, 1, 10), "adx_threshold": (25, 0, 100)},
}


class IndicatorCross:
    def __init__(self, **params):
        schema = PARAMETERS[self.name]
        if params.keys() - schema.keys():
            raise ValueError("unsupported technical rule parameters")
        values = {k: params.get(k, spec[0]) for k, spec in schema.items()}
        if any(type(values[k]) is not int or not lo <= values[k] <= hi for k, (_, lo, hi) in schema.items()):
            raise ValueError("invalid technical rule parameter")
        if (self.name == "rsi-rebound" and values["entry_threshold"] >= values["exit_threshold"]
                or self.name == "macd-cross" and values["fast"] >= values["slow"]):
            raise ValueError("need entry_threshold < exit_threshold and fast < slow")
        self.settings = values
        self.params = {k: v for k, v in values.items() if v != schema[k][0]}
        self.version = 2 if self.params else 1
        mapping = {"rsi-rebound": {"period": "rsi_period"},
                   "macd-cross": {"fast": "macd_fast", "slow": "macd_slow", "signal": "macd_signal"},
                   "trix-cross": {"period": "trix_period", "signal": "trix_signal"},
                   "keltner-breakout": {"ema_period": "keltner_period", "range_period": "range_period", "multiplier": "multiplier"}}
        self.feature_options = {target: values[key] for key, target in mapping[self.name].items()}
        self.features = TechnicalFeatures(**self.feature_options)
        self.previous = self.last_bar = None
        self.feature_values = {}

    def decide(self, snap, holding):
        if type(holding) is not bool:
            return "ABSTAIN_UNKNOWN_HOLDINGS", Decimal(0), ("holding state is unknown",), ""
        bar = snap.bar
        if bar.forming or bar.avail > snap.as_of or bar.end > snap.as_of:
            return "ABSTAIN_UNAVAILABLE_BAR", Decimal(0), ("bar is not closed and available",), ""
        if self.last_bar is not None and self.last_bar.end != bar.start:
            self.features, self.previous = TechnicalFeatures(**self.feature_options), None
        current = self.features.update(bar.close, high=bar.high, low=bar.low)
        before = self.previous
        self.previous, self.last_bar = current, bar
        self.feature_values = current
        if self.name == "rsi-rebound":
            key = self.features.rsi_key
            value = current[key]["value"]
            prior = before[key]["value"] if before else None
            up = prior is not None and Decimal(prior) <= self.settings["entry_threshold"] < Decimal(value)
            down = value is not None and Decimal(value) >= self.settings["exit_threshold"]
        elif self.name in ("macd-cross", "trix-cross"):
            key = self.features.macd_key if self.name == "macd-cross" else self.features.trix_key
            field = "line" if self.name == "macd-cross" else "value"
            value = current[key]["signal"]
            prior = before[key]["signal"] if before else None
            up = prior is not None and value is not None and Decimal(before[key][field]) <= Decimal(prior) and Decimal(current[key][field]) > Decimal(value)
            down = prior is not None and value is not None and Decimal(before[key][field]) >= Decimal(prior) and Decimal(current[key][field]) < Decimal(value)
        else:
            key = self.features.adx_key
            value = current[key]["value"]
            prior = before[key]["value"] if before else None
            band = current[self.features.keltner_key]
            up = (prior is not None and value is not None and band["upper"] is not None
                  and before[self.features.keltner_key]["upper"] is not None
                  and Decimal(value) >= self.settings["adx_threshold"] and bar.close > Decimal(band["upper"])
                  and self.last_close <= Decimal(before[self.features.keltner_key]["upper"]))
            down = band["middle"] is not None and bar.close < Decimal(band["middle"])
        self.last_close = bar.close
        if value is None or prior is None or self.name == "keltner-breakout" and band["middle"] is None:
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
