"""Pure domain signal geometry and risk-parity target builders for 1d core engine ablations.

Includes:
- Absolute random-walk anchored Kaufman Path Efficiency IC modulation (Idea #1 Amended)
- Causal right-endpoint Savitzky-Golay / weighted quadratic polynomial velocity & curvature (Idea #7)
- HRP-anchored trend target weights using domain/hrp.py (Idea #8)
- Multi-issuer precious-metals defensive reserve sizing (Idea #11A)
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

import numpy as np

from .hrp import hierarchical_risk_parity
from .strategy_sleeves import SleeveSignal
from .timeframe_panel import BarPoint

DEFENSIVE_METALS_CAPS: dict[str, float] = {
    "XAUTUSDT": 0.25,
    "PAXGUSDT": 0.15,
    "SLVONUSDT": 0.10,
}


def compute_path_efficiency_ic_map(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    window: int = 20,
    base_ic: float = 0.08,
    rw_floor: float = 0.10,
    er_span: float = 0.25,
    min_mult: float = 0.25,
    max_mult: float = 1.35,
) -> dict[datetime, dict[str, float]]:
    """Compute strictly causal path-efficiency modulated IC_prior anchored to absolute random-walk floor (~0.178)."""
    out: dict[datetime, dict[str, float]] = {}
    for sym in symbols:
        bars = panel_1d.get(sym, [])
        closes = [b.close for b in bars]
        for i in range(window, len(bars)):
            c_now, c_old = closes[i], closes[i - window]
            if c_now <= 0 or c_old <= 0:
                continue
            net_move = abs(c_now - c_old)
            path_len = sum(abs(closes[k] - closes[k - 1]) for k in range(i - window + 1, i + 1))
            er = (net_move / path_len) if path_len > 1e-12 else 0.0
            mult = max(min_mult, min(max_mult, (er - rw_floor) / max(er_span, 1e-6)))
            out.setdefault(bars[i].ts_avail, {})[sym] = base_ic * mult
    return out


def _build_causal_poly_kernels(window: int, decay: float = 0.94) -> tuple[np.ndarray, np.ndarray]:
    """Precompute strictly causal right-endpoint (tau=0) linear kernels for velocity (b) and curvature (c).

    Fits p(tau) = a + b*tau + 0.5*c*tau^2 over tau in [-(window-1), ..., 0] with exponential weights.
    """
    tau = np.arange(-(window - 1), 1, dtype=np.float64)
    w = decay ** (-tau)
    x = np.column_stack([np.ones_like(tau), tau, 0.5 * tau * tau])
    xt_w = x.T * w
    inv_xtwx = np.linalg.pinv(xt_w @ x)
    # Row 1 gives b (velocity at tau=0), Row 2 gives c (curvature at tau=0)
    proj = inv_xtwx @ xt_w
    return proj[1], proj[2]


def compute_savgol_velocity_curvature(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    windows: tuple[int, ...] = (21, 63),
    decay: float = 0.94,
) -> dict[datetime, dict[str, tuple[float, float]]]:
    """Compute strictly causal minimum-lag velocity & curvature in [-1, +1] via right-edge polynomial kernels."""
    kernels = [(w, *_build_causal_poly_kernels(w, decay=decay)) for w in windows]
    max_w = max(windows)
    out: dict[datetime, dict[str, tuple[float, float]]] = {}

    for sym in symbols:
        bars = panel_1d.get(sym, [])
        if len(bars) < max_w + 5:
            continue
        log_p = np.array([math.log(max(b.close, 1e-9)) for b in bars], dtype=np.float64)
        rets = np.diff(log_p, prepend=log_p[0])
        for i in range(max_w, len(bars)):
            vol = float(np.std(rets[max(1, i - 19) : i + 1]))
            vol = max(vol, 0.005)
            v_parts: list[float] = []
            c_parts: list[float] = []
            for w, kb, kc in kernels:
                seg = log_p[i - w + 1 : i + 1]
                vel_raw = float(np.dot(kb, seg)) / vol
                curv_raw = float(np.dot(kc, seg)) * (w * 0.5) / vol
                v_parts.append(max(-1.0, min(1.0, vel_raw * 2.5)))
                c_parts.append(max(-1.0, min(1.0, curv_raw * 6.0)))
            out.setdefault(bars[i].ts_avail, {})[sym] = (
                sum(v_parts) / len(v_parts),
                sum(c_parts) / len(c_parts),
            )
    return out


def compute_hrp_trend_target_weights(
    active_syms: tuple[str, ...],
    day_sigs: dict[str, SleeveSignal],
    cov_d: tuple[tuple[float, ...], ...],
    *,
    max_weight: float = 0.30,
    cash_buffer: float = 0.05,
    s1_override: dict[str, float | None] | None = None,
) -> dict[str, float]:
    """Compute trend-filtered HRP target weights using domain/hrp.py (never inverts Sigma)."""
    pos_idx: list[int] = []
    pos_scores: list[float] = []
    for i, sym in enumerate(active_syms):
        sig = day_sigs[sym]
        s1_v = s1_override[sym] if (s1_override is not None and sym in s1_override) else sig.s1_trend
        parts = [v for v in (s1_v, sig.s5_defensive_gold) if v is not None]
        raw = sum(parts) / len(parts) if parts else 0.0
        if raw > 0.05:
            pos_idx.append(i)
            pos_scores.append(min(1.0, raw))

    targets = {s: 0.0 for s in active_syms}
    if not pos_idx:
        return targets

    max_gross = max(0.0, 1.0 - cash_buffer)
    if len(pos_idx) == 1:
        idx = pos_idx[0]
        targets[active_syms[idx]] = min(max_weight, max_gross * pos_scores[0])
        return targets

    # Build exact symmetric positive-definite Decimal sub-covariance for HRP
    sub_cov: list[list[Decimal]] = []
    for r_pos, i in enumerate(pos_idx):
        row: list[Decimal] = []
        for c_pos, j in enumerate(pos_idx):
            val = 0.5 * (cov_d[i][j] + cov_d[j][i])
            if r_pos == c_pos:
                val = max(val, 1e-8)
            row.append(Decimal(f"{val:.12f}"))
        sub_cov.append(row)

    hrp_w, _ = hierarchical_risk_parity(sub_cov)
    # Tilt HRP weights gently by conviction and scale gross exposure by breadth/conviction
    avg_conv = sum(pos_scores) / len(pos_scores)
    gross_budget = min(max_gross, max_gross * min(1.0, (len(pos_idx) / max(1.0, len(active_syms) * 0.45)) * (0.45 + 0.55 * avg_conv)))
    tilted = [float(w) * (0.5 + 0.5 * sc) for w, sc in zip(hrp_w, pos_scores, strict=True)]
    tot = sum(tilted)
    if tot <= 0:
        return targets
    for idx, tw in zip(pos_idx, tilted, strict=True):
        targets[active_syms[idx]] = min(max_weight, gross_budget * (tw / tot))
    tot_final = sum(targets.values())
    if tot_final > max_gross and tot_final > 0:
        sc = max_gross / tot_final
        targets = {s: w * sc for s, w in targets.items()}
    return targets


def compute_defensive_metals_reserve(
    day_sigs_metals: dict[str, SleeveSignal],
    crypto_breadth: float | None,
    *,
    breadth_trigger: float = 0.35,
    min_metal_s1: float = 0.15,
    max_total_reserve: float = 0.50,
) -> dict[str, float]:
    """Allocate idle defensive bear-market cash into multi-issuer uptrending metals (XAUT <=25%, PAXG <=15%, SLVON <=10%)."""
    out = {sym: 0.0 for sym in DEFENSIVE_METALS_CAPS}
    if crypto_breadth is None or crypto_breadth >= breadth_trigger:
        return out
    intensity = min(1.0, (breadth_trigger - crypto_breadth) / max(breadth_trigger, 1e-6) + 0.25)
    for sym, cap in DEFENSIVE_METALS_CAPS.items():
        sig = day_sigs_metals.get(sym)
        if sig is None or not sig.eligible_for_entry or sig.s1_trend is None:
            continue
        if sig.s1_trend >= min_metal_s1:
            trend_mult = min(1.0, sig.s1_trend / 0.50)
            out[sym] = cap * intensity * trend_mult
    tot = sum(out.values())
    if tot > max_total_reserve and tot > 0:
        sc = max_total_reserve / tot
        out = {k: v * sc for k, v in out.items()}
    return out
