"""Risk-balanced weights for the passive multi-asset mix: inverse volatility, scaled to a yearly volatility target.

Weights are a decision, so floats are fine here; every fill that follows them uses exact decimals.
"""
import math

LOOKBACK, TARGET_VOL, BAND = 60, 0.15, 0.05


def inverse_vol_targets(returns: dict[str, list[float]], i: int, lookback: int = LOOKBACK,
                        target_vol: float = TARGET_VOL) -> dict[str, float]:
    """Weights from the `lookback` daily returns before index `i`; their sum never exceeds one (the rest is cash)."""
    if i < lookback:
        raise ValueError("not enough history for volatility weights")
    names = list(returns)
    window = {a: returns[a][i - lookback:i] for a in names}
    vols = {a: math.sqrt(sum(x * x for x in window[a]) / lookback) or 1e-9 for a in names}
    raw = {a: (1 / vols[a]) / sum(1 / v for v in vols.values()) for a in names}
    daily = [sum(raw[a] * window[a][k] for a in names) for k in range(lookback)]
    portfolio_vol = math.sqrt(sum(x * x for x in daily) / lookback) * math.sqrt(365)
    scale = min(1.0, target_vol / portfolio_vol) if portfolio_vol else 1.0
    return {a: raw[a] * scale for a in names}


def needs_rebalance(wanted: dict[str, float], held: dict[str, float], band: float = BAND) -> bool:
    return max(abs(wanted[a] - held.get(a, 0.0)) for a in wanted) > band
