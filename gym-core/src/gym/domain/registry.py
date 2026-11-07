"""Explicit, versioned paper strategies and their public parameter schemas."""
import re

from .bars import FIXED_RESOLUTIONS
from .compound_strategies import PARAMETERS as COMPOUND_PARAMETERS
from .compound_strategies import AdaptiveChannel, TrendPullback
from .strategy import (
    BollingerReversion,
    ConfirmedTrend,
    EmaTrend,
    RelativeMomentum,
    SmaCross,
    SmaReversion,
    digest,
)
from .technical_strategies import KeltnerBreakout, MacdCross, RsiRebound, TrixCross

STRATEGIES = {
    "ema-trend": (EmaTrend, "EMA trend", {
        "fast": {"type": "integer", "default": 8, "minimum": 1, "maximum": 10000},
        "slow": {"type": "integer", "default": 21, "minimum": 2, "maximum": 10000},
    }),
    "sma-reversion": (SmaReversion, "SMA reversion", {
        "lookback": {"type": "integer", "default": 20, "minimum": 2, "maximum": 10000},
        "entry_bps": {"type": "integer", "default": 50, "minimum": 0, "maximum": 1000},
    }),
    "sma-cross": (SmaCross, "SMA crossover", {
        "fast": {"type": "integer", "default": 8, "minimum": 1, "maximum": 10000},
        "slow": {"type": "integer", "default": 21, "minimum": 2, "maximum": 10000},
    }),
    "bollinger-reversion": (BollingerReversion, "Bollinger reversion", {
        "lookback": {"type": "integer", "default": 20, "minimum": 2, "maximum": 10000},
        "deviations": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
    }),
    "ema-confirmed": (ConfirmedTrend, "EMA timeframe confirmation", {
        "fast": {"type": "integer", "default": 8, "minimum": 1, "maximum": 10000},
        "slow": {"type": "integer", "default": 21, "minimum": 2, "maximum": 10000},
        "confirmation": {"type": "string", "default": "1h", "enum": list(FIXED_RESOLUTIONS)},
    }),
    "relative-momentum": (RelativeMomentum, "Relative momentum", {
        "lookback": {"type": "integer", "default": 20, "minimum": 2, "maximum": 10000},
        "reference": {"type": "string", "default": "ETHUSDT", "pattern": "^[A-Z0-9]{2,24}$"},
    }),
    "rsi-rebound": (RsiRebound, "RSI rebound (30/70)", {}),
    "macd-cross": (MacdCross, "MACD crossover (12/26/9)", {}),
    "trix-cross": (TrixCross, "TRIX crossover (15/9)", {}),
    "keltner-breakout": (KeltnerBreakout, "Keltner breakout (20/14/2, ADX25)", {}),
    "trend-pullback": (TrendPullback, "Cost-aware trend pullback", COMPOUND_PARAMETERS),
    "adaptive-channel": (AdaptiveChannel, "Regime-adaptive channel", COMPOUND_PARAMETERS),
}


def catalog():
    return [{"id": name, "title": title, "version": getattr(constructor,"version",1), "mode": "PAPER_ONLY",
             "parameters": {"type": "object", "properties": properties, "additionalProperties": False},
             "constraints": ["fast < slow"] if "fast" in properties else []}
            for name, (constructor, title, properties) in STRATEGIES.items()]


def create_strategy(name="ema-trend", params=None):
    if not isinstance(name, str) or name not in STRATEGIES:
        raise ValueError("unknown paper strategy")
    constructor, _, properties = STRATEGIES[name]
    if params is None:
        params = {}
    if not isinstance(params, dict) or params.keys() - properties.keys():
        raise ValueError("unsupported strategy parameters")
    values = {key: params.get(key, spec["default"]) for key, spec in properties.items()}
    for key, value in values.items():
        spec = properties[key]
        if spec["type"] == "integer":
            valid = type(value) is int and spec["minimum"] <= value <= spec["maximum"]
        else:
            valid = isinstance(value, str) and (value in spec["enum"] if "enum" in spec else re.fullmatch("[A-Z0-9]{2,24}", value) is not None)
        if not valid:
            raise ValueError(f"invalid strategy parameter: {key}")
    strategy = constructor(**values)
    strategy.version = getattr(constructor,"version",1)
    strategy.config_hash = digest({"strategy": name, "version": strategy.version, "params": strategy.params})
    return strategy
