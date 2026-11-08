"""Explicit, versioned paper strategies and their public parameter schemas."""
import re

from .bars import FIXED_RESOLUTIONS
from .channel_strategies import CompressionBreakout, DonchianBreakout
from .compound_strategies import PARAMETERS as COMPOUND_PARAMETERS
from .compound_strategies import AdaptiveChannel, TrendPullback
from .cross_market_strategies import LeadLag, TomanPremium
from .exit_policy import EXIT_PARAMETERS, EXIT_VOLATILITY_MODEL, ExitPolicy
from .regime import REGIME_GATE, REGIME_VOLATILITY_MODEL, RegimeGate
from .strategy import (
    BollingerReversion,
    ConfirmedTrend,
    EmaTrend,
    RelativeMomentum,
    SmaCross,
    SmaReversion,
    digest,
)
from .technical_strategies import PARAMETERS as TECHNICAL_PARAMETERS
from .technical_strategies import KeltnerBreakout, MacdCross, RsiRebound, TrixCross

STRATEGIES = {
    "toman-premium": (TomanPremium, "TMN cross-market discount hypothesis", {
        key: {"type": "integer", "default": default, "minimum": 0, "maximum": maximum}
        for key, default, maximum in (("entry_bps", 50, 10000), ("exit_bps", 0, 10000),
                                     ("conversion_cost_bps", 20, 10000), ("max_skew_seconds", 10, 120))} | {
        "z_entry": {"type": "integer", "default": 0, "minimum": 0, "maximum": 8},
        "z_exit": {"type": "integer", "default": 0, "minimum": 0, "maximum": 8},
        "half_life_multiple": {"type": "integer", "default": 0, "minimum": 0, "maximum": 20},
    }),
    "lead-lag": (LeadLag, "Cost-aware lead-lag hypothesis", {
        "reference": {"type": "string", "default": "ETHUSDT", "pattern": "^[A-Z0-9]{2,24}$"},
        **{key: {"type": "integer", "default": default, "minimum": lo, "maximum": maximum}
           for key, default, lo, maximum in (("lookback", 20, 2, 500), ("entry_bps", 50, 0, 10000),
                                           ("lag_bps", 30, 0, 10000), ("max_skew_seconds", 10, 0, 120))},
        "delay_bars": {"type": "integer", "default": 0, "minimum": 0, "maximum": 12}}),
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
    **{name: (constructor, title, {key: {"type": "integer", "default": default, "minimum": lo, "maximum": hi}
                                 for key, (default, lo, hi) in TECHNICAL_PARAMETERS[name].items()})
       for name, constructor, title in (("rsi-rebound", RsiRebound, "RSI rebound"), ("macd-cross", MacdCross, "MACD crossover"),
                                       ("trix-cross", TrixCross, "TRIX crossover"), ("keltner-breakout", KeltnerBreakout, "Keltner breakout"))},
    "trend-pullback": (TrendPullback, "Cost-aware trend pullback", COMPOUND_PARAMETERS),
    "adaptive-channel": (AdaptiveChannel, "Regime-adaptive channel", COMPOUND_PARAMETERS),
    **{constructor.name: (constructor, title, {
        "lookback": {"type": "integer", "default": 20, "minimum": 2, "maximum": 500},
        "exit_lookback": {"type": "integer", "default": 10, "minimum": 2, "maximum": 500},
        "compression_bps": {"type": "integer", "default": compression, "minimum": 0, "maximum": 10000},
        "regime": {"type": "string", "default": "ANY", "enum": ["ANY", "UP_TREND", "RANGE"]},
    }) for constructor, title, compression in ((DonchianBreakout, "Prior Donchian breakout", 0),
                                               (CompressionBreakout, "Prior compression breakout", 100))},
}


def catalog():
    """Expose the paper-only, versioned strategy parameter catalog."""
    return [{"id": name, "title": title, "version": getattr(constructor,"version",1), "mode": "PAPER_ONLY",
             "parameters": {"type": "object", "properties": {**properties, "regime_gate": REGIME_GATE,
                            "regime_volatility_model": REGIME_VOLATILITY_MODEL,
                            "exit_volatility_model": EXIT_VOLATILITY_MODEL, **EXIT_PARAMETERS}, "additionalProperties": False},
             "constraints": ["fast < slow"] if "fast" in properties else []}
            for name, (constructor, title, properties) in STRATEGIES.items()]


def create_strategy(name="ema-trend", params=None):
    """Validate strategy inputs and derive a deterministic opt-in config hash."""
    if not isinstance(name, str) or name not in STRATEGIES:
        raise ValueError("unknown paper strategy")
    constructor, _, properties = STRATEGIES[name]
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("unsupported strategy parameters")
    params = dict(params)
    gate = params.pop("regime_gate", "ANY")
    if gate not in REGIME_GATE["enum"]:
        raise ValueError("invalid strategy parameter: regime_gate")
    regime_model = params.pop("regime_volatility_model", "atr")
    exit_model = params.pop("exit_volatility_model", "atr")
    if regime_model not in REGIME_VOLATILITY_MODEL["enum"] or (gate == "ANY" and regime_model != "atr"):
        raise ValueError("invalid strategy parameter: regime_volatility_model")
    if exit_model not in EXIT_VOLATILITY_MODEL["enum"]:
        raise ValueError("invalid strategy parameter: exit_volatility_model")
    exits = {}
    for key, spec in EXIT_PARAMETERS.items():
        value = params.pop(key, 0)
        if type(value) is not int or not 0 <= value <= spec["maximum"]:
            raise ValueError("invalid strategy parameter: " + key)
        if value:
            exits[key] = value
    if exit_model != "atr":
        if not exits.get("exit_atr_multiple"):
            raise ValueError("Parkinson exit model requires an ATR-style trailing stop")
        exits["exit_volatility_model"] = exit_model
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
    strategy.version = getattr(strategy,"version",1)
    if gate != "ANY":
        strategy = RegimeGate(strategy, gate, regime_model)
    if exits:
        strategy = ExitPolicy(strategy, exits)
    strategy.config_hash = digest({"strategy": name, "version": strategy.version, "params": strategy.params})
    return strategy
