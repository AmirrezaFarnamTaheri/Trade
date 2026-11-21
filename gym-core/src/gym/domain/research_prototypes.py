"""Causal unregistered paper research prototypes: EWMAC, vol targeting, edge-of-band, and Factor IC lab (R001-R004)."""
from __future__ import annotations

import math
from decimal import Decimal
from random import Random
from statistics import fmean

_DEFAULT_SPANS = ((16, 64), (32, 128), (64, 256))


def _ewma_series(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def ewmac_forecast(
    closes: list[float],
    *,
    spans: tuple[tuple[int, int], ...] = _DEFAULT_SPANS,
    vol_lookback: int = 36,
    cap: float = 20.0,
) -> list[float | None]:
    """Strictly causal continuous multi-horizon EWMAC forecast normalized by prior-only volatility (R001)."""
    n = len(closes)
    if n < 2 or any(not math.isfinite(c) or c <= 0 for c in closes):
        raise ValueError("closes must be positive finite prices")
    diffs = [0.0] + [closes[i] - closes[i - 1] for i in range(1, n)]
    # Prior-only rolling volatility of price differences.
    ewmas = {s: _ewma_series(closes, s) for pair in spans for s in pair}
    max_slow = max(slow for _, slow in spans)
    warmup = max(max_slow, vol_lookback + 1)
    out: list[float | None] = []
    for i in range(n):
        if i < warmup:
            out.append(None)
            continue
        window = diffs[i - vol_lookback:i]  # strictly prior differences
        m = fmean(window)
        var = math.fsum((x - m) ** 2 for x in window) / max(len(window) - 1, 1)
        sigma = math.sqrt(var)
        if sigma <= 0:
            out.append(0.0)
            continue
        raw = fmean((ewmas[fast][i] - ewmas[slow][i]) / sigma for fast, slow in spans)
        # Standard fixed starting scalar (10.0) capped symmetrically at [-cap, +cap]; never fitted to future data.
        scaled = max(-cap, min(cap, raw * 10.0))
        out.append(scaled)
    return out


def vol_target_position(
    forecast: float | None,
    prior_annual_vol: float,
    *,
    vol_target: float = 0.15,
    max_leverage: float = 1.0,
    roundtrip_cost_bps: float = 20.0,
    expected_turnover_per_year: float = 6.0,
    max_cost_share_of_vol: float = 0.10,
) -> dict:
    """Causal volatility-targeted weight with zero-vol abstention and cost-of-speed gate (R002)."""
    if forecast is None or not math.isfinite(forecast) or not math.isfinite(prior_annual_vol) or prior_annual_vol <= 0:
        return {"status": "ABSTAIN_ZERO_OR_UNKNOWN_VOL", "weight": "0", "cost_drag_annual": None, "registered_trial": False}
    annual_cost = (roundtrip_cost_bps / 10000.0) * expected_turnover_per_year
    if annual_cost > max_cost_share_of_vol * vol_target:
        return {
            "status": "BLOCKED_COST_OF_SPEED",
            "weight": "0",
            "cost_drag_annual": round(annual_cost, 6),
            "cost_budget_annual": round(max_cost_share_of_vol * vol_target, 6),
            "registered_trial": False,
        }
    raw_weight = (forecast / 10.0) * (vol_target / prior_annual_vol)
    capped = max(-max_leverage, min(max_leverage, raw_weight))
    return {
        "status": "READY",
        "weight": str(Decimal(str(round(capped, 6)))),
        "cost_drag_annual": round(annual_cost, 6),
        "registered_trial": False,
        "paper_only": True,
    }


def edge_of_band_target(current_weight: Decimal, target_weight: Decimal, band: Decimal) -> dict:
    """No action inside [target-band, target+band]; trade only to the nearer band edge outside (R003)."""
    if band < 0:
        raise ValueError("band must be nonnegative")
    if target_weight == 0:
        return {"trade": current_weight != 0, "new_weight": Decimal(0), "delta": -current_weight}
    lo, hi = target_weight - band, target_weight + band
    if lo <= current_weight <= hi:
        return {"trade": False, "new_weight": current_weight, "delta": Decimal(0)}
    new_w = lo if current_weight < lo else hi
    return {"trade": True, "new_weight": new_w, "delta": new_w - current_weight}


def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=vals.__getitem__)
    ranks = [0.0] * len(vals)
    for pos, idx in enumerate(order, 1):
        ranks[idx] = float(pos)
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    mx, my = fmean(xs), fmean(ys)
    vx = math.fsum((x - mx) ** 2 for x in xs)
    vy = math.fsum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def factor_ic_analysis(
    factor_by_date: dict[str, dict[str, float]],
    forward_returns_by_date: dict[str, dict[str, float]],
    *,
    purge_step: int = 1,
    min_assets_per_date: int = 4,
    seed: int = 0,
) -> dict:
    """Cross-sectional per-date Spearman Rank-IC with horizon thinning and shuffled placebo control (R004)."""
    if purge_step < 1:
        raise ValueError("purge_step must be >= 1")
    common_dates = sorted(set(factor_by_date) & set(forward_returns_by_date))[::purge_step]
    ics, placebo_ics = [], []
    rng = Random(seed)
    for d in common_dates:
        f_map, r_map = factor_by_date[d], forward_returns_by_date[d]
        assets = sorted(set(f_map) & set(r_map))
        if len(assets) < min_assets_per_date:
            continue
        fv = [float(f_map[a]) for a in assets]
        rv = [float(r_map[a]) for a in assets]
        ic = _pearson(_ranks(fv), _ranks(rv))
        if ic is not None:
            ics.append(ic)
            shuf = list(rv)
            rng.shuffle(shuf)
            pic = _pearson(_ranks(fv), _ranks(shuf))
            if pic is not None:
                placebo_ics.append(pic)
    if len(ics) < 3:
        return {"status": "INSUFFICIENT_DATES", "dates_evaluated": len(ics), "registered_trial": False}
    mean_ic = fmean(ics)
    sd = math.sqrt(math.fsum((x - mean_ic) ** 2 for x in ics) / (len(ics) - 1))
    t_stat = mean_ic / (sd / math.sqrt(len(ics))) if sd > 0 else 0.0
    return {
        "status": "DIAGNOSTIC_ONLY",
        "dates_evaluated": len(ics),
        "purge_step": purge_step,
        "mean_rank_ic": round(mean_ic, 6),
        "ic_t_stat": round(t_stat, 4),
        "placebo_mean_rank_ic": round(fmean(placebo_ics), 6) if placebo_ics else None,
        "registered_trial": False,
        "paper_only": True,
    }
