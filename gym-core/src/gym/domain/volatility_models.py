"""Yang-Zhang jump-safe OHLC volatility & asymmetric downside GJR-EWMA volatility (spec §6.3)."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class OhlcBar:
    open: float
    high: float
    low: float
    close: float


def yang_zhang_volatility(
    bars: list[OhlcBar],
    *,
    sigma_min: float = 1e-4,
) -> float:
    """Jump-safe Yang-Zhang per-bar volatility with explicit floor sigma_min."""
    valid = [b for b in bars if b.open > 0 and b.high > 0 and b.low > 0 and b.close > 0]
    n = len(valid)
    if n < 3:
        return sigma_min

    # Overnight log returns o_t = ln(O_t / C_{t-1}), open-to-close c_t = ln(C_t / O_t)
    o_rets = [math.log(valid[i].open / valid[i - 1].close) for i in range(1, n)]
    c_rets = [math.log(valid[i].close / valid[i].open) for i in range(1, n)]
    rs_terms = []
    for b in valid[1:]:
        u = math.log(b.high / b.open)
        d = math.log(b.low / b.open)
        c = math.log(b.close / b.open)
        rs_terms.append(u * (u - c) + d * (d - c))

    m = len(o_rets)
    if m < 2:
        return sigma_min
    o_mean = sum(o_rets) / m
    c_mean = sum(c_rets) / m
    var_o = sum((x - o_mean) ** 2 for x in o_rets) / (m - 1)
    var_c = sum((x - c_mean) ** 2 for x in c_rets) / (m - 1)
    var_rs = sum(rs_terms) / m

    k = 0.34 / (1.34 + (m + 1.0) / (m - 1.0))
    yz_var = var_o + k * var_c + (1.0 - k) * var_rs
    return max(sigma_min, math.sqrt(max(0.0, yz_var)))


def asymmetric_ewma_volatility(
    returns: list[float],
    *,
    decay_lambda: float = 0.90,
    downside_gamma: float = 0.08,
    sigma_min: float = 1e-4,
) -> float:
    """Asymmetric GJR-EWMA volatility weighting downside shocks more heavily than upside shocks."""
    if not returns:
        return sigma_min
    alpha_pos = max(0.0, 1.0 - decay_lambda - 0.5 * downside_gamma)
    var = max(sigma_min * sigma_min, returns[0] * returns[0])
    for r in returns:
        r2 = r * r
        asym = downside_gamma * r2 if r < 0 else 0.0
        var = decay_lambda * var + alpha_pos * r2 + asym
    return max(sigma_min, math.sqrt(max(0.0, var)))
