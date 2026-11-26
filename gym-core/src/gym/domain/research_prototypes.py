"""Causal unregistered paper research prototypes: EWMAC, vol targeting, edge-of-band, and Factor IC lab (R001-R004)."""
from __future__ import annotations

import math
from decimal import Decimal
from random import Random
from statistics import fmean

from .model import iso, parse_ts

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
    from itertools import groupby

    order = sorted(range(len(vals)), key=vals.__getitem__)
    ranks = [0.0] * len(vals)
    first = 1
    for _, group in groupby(order, key=vals.__getitem__):
        indices = list(group)
        rank = first + (len(indices) - 1) / 2
        for idx in indices:
            ranks[idx] = rank
        first += len(indices)
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
    ics, pearson_ics, placebo_ics = [], [], []
    quartile_returns = [[] for _ in range(4)]
    rng = Random(seed)
    for d in common_dates:
        f_map, r_map = factor_by_date[d], forward_returns_by_date[d]
        assets = sorted(set(f_map) & set(r_map))
        if len(assets) < min_assets_per_date:
            continue
        fv = [float(f_map[a]) for a in assets]
        rv = [float(r_map[a]) for a in assets]
        ranks = _ranks(fv)
        ic = _pearson(ranks, _ranks(rv))
        if ic is not None:
            ics.append(ic)
            pearson_ic = _pearson(fv, rv)
            if pearson_ic is not None:
                pearson_ics.append(pearson_ic)
            daily = [[] for _ in quartile_returns]
            for rank, outcome in zip(ranks, rv):
                daily[int((rank - 0.5) * 4 / len(ranks))].append(outcome)
            for quartile, values in zip(quartile_returns, daily):
                if values:
                    quartile.append(fmean(values))
            shuf = list(rv)
            rng.shuffle(shuf)
            pic = _pearson(_ranks(fv), _ranks(shuf))
            if pic is not None:
                placebo_ics.append(pic)
    if len(ics) < 3:
        return {"status": "INSUFFICIENT_DATES", "dates_evaluated": len(ics), "mean_rank_ic": None,
                "registered_trial": False}
    mean_ic = fmean(ics)
    sd = math.sqrt(math.fsum((x - mean_ic) ** 2 for x in ics) / (len(ics) - 1))
    t_stat = mean_ic / (sd / math.sqrt(len(ics))) if sd > 0 else None
    return {
        "status": "DIAGNOSTIC_ONLY",
        "dates_evaluated": len(ics),
        "purge_step": purge_step,
        "mean_rank_ic": round(mean_ic, 6),
        "mean_pearson_ic": round(fmean(pearson_ics), 6) if pearson_ics else None,
        "ic_t_stat": round(t_stat, 4) if t_stat is not None else None,
        "calibration_by_rank_quartile": [
            {"quartile": i, "dates": len(values), "mean_forward_return": fmean(values) if values else None}
            for i, values in enumerate(quartile_returns, start=1)
        ],
        "placebo_mean_rank_ic": round(fmean(placebo_ics), 6) if placebo_ics else None,
        "registered_trial": False,
        "paper_only": True,
    }


def factor_ic_lab(observations, as_of, *, seed=0):
    """Use only complete, disjoint forward-label intervals supplied to this diagnostic."""
    if not isinstance(observations, list) or not 1 <= len(observations) <= 2000:
        raise ValueError("factor lab requires 1..2000 observation rows")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("factor lab seed must be an unsigned 32-bit integer")
    rows, starts = [], set()
    for row in observations:
        if not isinstance(row, dict) or set(row) != {"at", "label_end", "factors", "forward_returns"}:
            raise ValueError("factor rows require at, label_end, factors and forward_returns")
        if not isinstance(row["at"], str) or not isinstance(row["label_end"], str):
            raise ValueError("factor and label clocks must be ISO strings")
        start, end = parse_ts(row["at"]), parse_ts(row["label_end"])
        if not start < end <= as_of or start in starts:
            raise ValueError("factor rows require distinct snapshots and complete forward labels")
        starts.add(start)
        for key in ("factors", "forward_returns"):
            values = row[key]
            if (not isinstance(values, dict) or len(values) > 500 or
                    any(not isinstance(asset, str) or not asset or len(asset) > 24 or type(value) not in (float, int)
                        or abs(value) > 1e100 or not math.isfinite(value) for asset, value in values.items())):
                raise ValueError("factor and return maps require at most 500 assets with finite values")
        rows.append((start, end, row))

    factors, returns, windows, purged = {}, {}, [], 0
    last_end = None
    for start, end, row in sorted(rows):
        if last_end is not None and start < last_end:
            purged += 1
            continue
        at = iso(start)
        factors[at], returns[at] = row["factors"], row["forward_returns"]
        windows.append({"at": at, "label_end": iso(end)})
        last_end = end
    report = factor_ic_analysis(factors, returns, seed=seed)
    return {**report, "schema": "factor-ic-lab/1", "as_of": iso(as_of), "seed": seed,
            "overlapping_rows_purged": purged, "retained_windows": windows, "paper_only": True,
            "input_provenance": "CALLER_SUPPLIED", "funded_authority": False}
