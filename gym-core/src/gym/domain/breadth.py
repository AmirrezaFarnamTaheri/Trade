"""Breadth-gated trend blend: the decision of trial `breadth-trend-forward`, as a pure function of daily bars."""
from statistics import median

from .signals import blend

MEMBERS = ("tsmom", "efficiency", "obv", "donchian", "ema-cross")
MIN_QUOTE_VOLUME, VOLUME_DAYS, BREADTH_DAYS, GATE = 5000.0, 30, 50, 0.5


def liquid(bars) -> bool:
    """Median quote volume (close x base volume) of the last 30 daily candles of at least 5,000 USDT."""
    c, v = bars["close"][-VOLUME_DAYS:], bars["volume"][-VOLUME_DAYS:]
    return len(c) == VOLUME_DAYS and median(x * y for x, y in zip(c, v, strict=True)) >= MIN_QUOTE_VOLUME


def breadth_targets(bars_by_symbol: dict) -> dict:
    """Target weights (equal sleeves of 1/N liquid coins, long only) and the reasons, from completed daily bars.

    bars_by_symbol: symbol -> {"close", "high", "low", "volume"} float lists, oldest first, ending on the same day.
    """
    universe = sorted(s for s, b in bars_by_symbol.items() if liquid(b))
    above = [s for s in universe if len(bars_by_symbol[s]["close"]) >= BREADTH_DAYS
             and bars_by_symbol[s]["close"][-1] > sum(bars_by_symbol[s]["close"][-BREADTH_DAYS:]) / BREADTH_DAYS]
    measured = [s for s in universe if len(bars_by_symbol[s]["close"]) >= BREADTH_DAYS]
    breadth = len(above) / len(measured) if measured else 0.0
    trend = {s: blend(bars_by_symbol[s], MEMBERS, enter_pct=60, exit_pct=20, long_only=True)[-1] for s in universe}
    gate_open = breadth > GATE
    weights = {s: (1 / len(universe) if gate_open and trend[s] == 1 else 0.0) for s in universe}
    return {"weights": weights, "breadth": breadth, "gate_open": gate_open, "universe": universe,
            "trend_long": sorted(s for s in universe if trend[s] == 1)}
