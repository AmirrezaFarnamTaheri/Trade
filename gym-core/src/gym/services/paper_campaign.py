"""Catalogue-wide paper definitions; venue eligibility and data readiness stay distinct."""
import re

from ..domain.bars import FIXED_RESOLUTIONS
from ..domain.registry import STRATEGIES, create_strategy
from .collector import select_universe


def market_universe(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 1000:
        raise ValueError("need a bounded venue market catalogue")
    symbols = [row.get("symbol") for row in rows if type(row) is dict]
    if len(symbols) != len(rows) or any(type(symbol) is not str for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("invalid or duplicate catalogue identities")
    selected, _ = select_universe(rows, None)
    eligible = set(selected)
    out = []
    for row in rows:
        symbol = row["symbol"]
        base, quote = row.get("base_asset", row.get("baseAsset")), row.get("quote_asset", row.get("quoteAsset"))
        if any(type(value) is not str or not re.fullmatch(r"[A-Z0-9]{1,24}", value) for value in (symbol, base, quote)) or symbol != base + quote:
            raise ValueError("catalogue base/quote identity mismatch")
        reason = ("ELIGIBLE_SPOT" if symbol in eligible else "VENUE_NOT_SPOT" if row.get("is_spot") is not True
                  else "UNSUPPORTED_QUOTE")
        out.append({"symbol": symbol, "base": base, "quote": quote, "spot_status": reason,
                    "risk_flagged": "isRisky" in (row.get("flags") or [])})
    return sorted(out, key=lambda row: row["symbol"])


def strategy_trials(strategy, symbol, quote, resolution):
    default, alternative = {}, None
    if strategy in ("ema-trend", "sma-cross", "ema-confirmed"):
        alternative = {"fast": 2, "slow": 5}
        if strategy == "ema-confirmed":
            alternative["confirmation"] = "15min" if resolution != "15min" else "1h"
    elif strategy == "sma-reversion":
        alternative = {"lookback": 5, "entry_bps": 20}
    elif strategy == "bollinger-reversion":
        alternative = {"lookback": 5, "deviations": 1}
    elif strategy == "relative-momentum":
        reference = ("BTC" if symbol == "ETH" + quote else "ETH") + quote
        default = {"reference": reference}
        alternative = {"lookback": 5, "reference": reference}
    trials = [default] + ([alternative] if alternative is not None else [])
    for params in trials:
        create_strategy(strategy, params)
    return trials


def historical_groups(universe, windows, scenarios):
    """Apply the same declared comparison matrix to every eligible spot market."""
    groups = []
    for market in universe:
        if market["spot_status"] != "ELIGIBLE_SPOT":
            continue
        symbol, quote = market["symbol"], market["quote"]
        cash = "300000000" if quote == "TMN" else "1000"
        for resolution in FIXED_RESOLUTIONS:
            strategies = STRATEGIES if resolution in ("1min", "5min", "15min") else ("ema-trend",)
            for strategy in strategies:
                detailed = resolution in ("1min", "5min", "15min")
                groups.append({"purpose": "strategy/cost/outage comparison" if detailed else "timeframe coverage",
                    "request": {"symbol": symbol, "strategy": strategy,
                        "trials": strategy_trials(strategy, symbol, quote, resolution) if detailed else [{"fast": 2, "slow": 5}],
                        "windows": windows, "resolution": resolution, "cash": cash,
                        "scenarios": scenarios if detailed else [scenarios[1]], "final_evaluation_id": None}})
    return groups


def prospective_cases(universe):
    return [{"symbol": row["symbol"], "cash": "300000000" if row["quote"] == "TMN" else "1000",
             "strategy": strategy, "params": params}
            for row in universe if row["spot_status"] == "ELIGIBLE_SPOT"
            for strategy, params in (("ema-trend", {"fast": 2, "slow": 5}),
                                     ("sma-reversion", {"lookback": 5, "entry_bps": 50}))]
