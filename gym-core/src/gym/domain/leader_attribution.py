"""Pure domain attribution & hysteresis tools for the standing leader (S1 + S5) and S2 retention band.

Implements Astra design review §4 (factor attribution), §7 Priority 2 (entry vs. exit 2x2),
and §7 Priority 7 (low-turnover S2 incumbent retention hysteresis band). Zero I/O, zero third-party deps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from .strategy_sleeves import SleeveSignal


@dataclass(frozen=True)
class FactorAttribution:
    observations: int
    ann_alpha_pct: float
    beta_btc: float
    beta_gold: float
    r_squared: float
    residual_ann_sharpe: float
    portfolio_ann_sharpe: float


def _solve_3x3(a: list[list[float]], b: list[float]) -> tuple[float, float, float]:
    """Solve 3x3 linear system via Gaussian elimination with partial pivoting."""
    m = [row[:] + [rhs] for row, rhs in zip(a, b, strict=True)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-15:
            return 0.0, 0.0, 0.0
        for row in range(col + 1, 3):
            fac = m[row][col] / m[col][col]
            for k in range(col, 4):
                m[row][k] -= fac * m[col][k]
    x = [0.0, 0.0, 0.0]
    for col in range(2, -1, -1):
        s = m[col][3] - sum(m[col][k] * x[k] for k in range(col + 1, 3))
        x[col] = s / m[col][col]
    return x[0], x[1], x[2]


def decompose_factor_attribution(
    portfolio_rets: dict[str, float],
    btc_rets: dict[str, float],
    gold_rets: dict[str, float],
    *,
    periods_per_year: float = 365.0,
) -> FactorAttribution:
    """Regress daily portfolio returns on BTC + Gold (XAUTUSDT) returns to isolate alpha vs beta."""
    dates = sorted(set(portfolio_rets) & set(btc_rets) & set(gold_rets))
    n = len(dates)
    if n < 10:
        return FactorAttribution(n, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    ys = [portfolio_rets[d] for d in dates]
    x1 = [btc_rets[d] for d in dates]
    x2 = [gold_rets[d] for d in dates]

    s1 = sum(x1)
    s2 = sum(x2)
    s11 = sum(v * v for v in x1)
    s22 = sum(v * v for v in x2)
    s12 = sum(a * b for a, b in zip(x1, x2, strict=True))
    sy = sum(ys)
    s1y = sum(a * y for a, y in zip(x1, ys, strict=True))
    s2y = sum(b * y for b, y in zip(x2, ys, strict=True))

    alpha, beta_btc, beta_gold = _solve_3x3(
        [[float(n), s1, s2], [s1, s11, s12], [s2, s12, s22]],
        [sy, s1y, s2y],
    )
    preds = [alpha + beta_btc * a + beta_gold * b for a, b in zip(x1, x2, strict=True)]
    resids = [y - p for y, p in zip(ys, preds, strict=True)]
    mean_y = sy / n
    sst = sum((y - mean_y) ** 2 for y in ys)
    sse = sum(e * e for e in resids)
    r_sq = max(0.0, min(1.0, 1.0 - sse / sst)) if sst > 1e-15 else 0.0

    # Residual active return = alpha + eps (orthogonal to BTC and Gold)
    active = [alpha + e for e in resids]
    mean_a = sum(active) / n
    var_a = sum((v - mean_a) ** 2 for v in active) / max(1, n - 1)
    resid_sr = (mean_a / math.sqrt(var_a)) * math.sqrt(periods_per_year) if var_a > 1e-15 else 0.0

    var_y = sum((y - mean_y) ** 2 for y in ys) / max(1, n - 1)
    port_sr = (mean_y / math.sqrt(var_y)) * math.sqrt(periods_per_year) if var_y > 1e-15 else 0.0

    return FactorAttribution(
        observations=n,
        ann_alpha_pct=round(alpha * periods_per_year * 100.0, 2),
        beta_btc=round(beta_btc, 4),
        beta_gold=round(beta_gold, 4),
        r_squared=round(r_sq, 4),
        residual_ann_sharpe=round(resid_sr, 3),
        portfolio_ann_sharpe=round(port_sr, 3),
    )


def apply_s2_incumbent_hysteresis(
    signals: dict[datetime, dict[str, SleeveSignal]],
    *,
    entry_top_frac: float = 0.25,
    hold_top_frac: float = 0.55,
    hold_conviction_floor: float = 0.35,
    gold_symbol: str = "XAUTUSDT",
) -> dict[datetime, dict[str, SleeveSignal]]:
    """Apply strictly causal incumbent-retention hysteresis to S2 cross-sectional ranks.

    - Non-incumbents enter S2 only when ranked in the top ``entry_top_frac`` AND raw ``s2_residual_mom > 0``.
    - Incumbents remain active (with conviction floored at ``hold_conviction_floor``) while ranked in
      the top ``hold_top_frac`` and their raw ``s2_residual_mom >= -0.15``; otherwise they exit to 0.0.
    """
    if not (0.0 < entry_top_frac <= hold_top_frac <= 1.0):
        raise ValueError("require 0 < entry_top_frac <= hold_top_frac <= 1.0")

    incumbents: set[str] = set()
    out: dict[datetime, dict[str, SleeveSignal]] = {}

    for ts in sorted(signals):
        day = signals[ts]
        ranked = sorted(
            (
                (sym, sig.s2_residual_mom)
                for sym, sig in day.items()
                if sym != gold_symbol and sig.eligible_for_entry and sig.s2_residual_mom is not None
            ),
            key=lambda kv: (-kv[1], kv[0]),
        )
        n_ranked = len(ranked)
        entry_cut = max(1, int(math.ceil(entry_top_frac * n_ranked))) if n_ranked else 0
        hold_cut = max(entry_cut, int(math.ceil(hold_top_frac * n_ranked))) if n_ranked else 0
        rank_of = {sym: idx + 1 for idx, (sym, _) in enumerate(ranked)}

        next_incumbents: set[str] = set()
        new_day: dict[str, SleeveSignal] = {}
        for sym, sig in day.items():
            if sym == gold_symbol or sig.s2_residual_mom is None or sym not in rank_of:
                new_day[sym] = sig
                continue
            r = rank_of[sym]
            raw_s2 = sig.s2_residual_mom
            if sym in incumbents:
                if r <= hold_cut and raw_s2 >= -0.15:
                    next_incumbents.add(sym)
                    adj = max(hold_conviction_floor, raw_s2)
                else:
                    adj = 0.0
            else:
                if r <= entry_cut and raw_s2 > 0.0:
                    next_incumbents.add(sym)
                    adj = raw_s2
                else:
                    adj = 0.0
            new_day[sym] = replace(sig, s2_residual_mom=adj)

        incumbents = next_incumbents
        out[ts] = new_day
    return out
