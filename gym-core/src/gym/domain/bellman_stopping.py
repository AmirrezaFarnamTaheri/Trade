"""Pure domain nonlinear Bellman Optimal-Stopping models and resurrected entry-signal detectors.

Upgrades E3 linear Ridge into a purged walk-forward Nonlinear Interaction + Pure-NumPy MLP + Ridge
Bellman Value-of-Waiting ensemble, adds a dedicated 1d Slow-Core Bellman exit scorer, and defines
strictly causal detectors for 3 previously defeated entry families (2h Flush Rebound, 2h Breakdown
Short, and Uncensored z>=1.5 Early Ignition) to test whether optimal closing resurrects them.

Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

import numpy as np

from .optimal_exits import OptimalStoppingState
from .timeframe_panel import BarPoint


def expand_bellman_interactions(vec10: list[float]) -> list[float]:
    """Expand 10 base OptimalStoppingState features with 6 domain-grounded nonlinear interaction terms.

    Base indices:
      0: age, 1: upnl, 2: mfe, 3: giveback_ratio, 4: upper_wick,
      5: vol_ratio, 6: bar_ret_z, 7: rel_btc, 8: hours_to_eod, 9: entry_gru
    """
    age, upnl, mfe, gb, wick, vol_r, ret_z, rel_btc, hrs_eod, gru = vec10
    return [
        *vec10,
        mfe * wick,                     # Parabolic extension + rejection wick
        mfe * gb,                       # Large open profit giving back
        gb * max(0.0, 1.5 - vol_r),     # Giveback on dying volume
        upnl * vol_r,                   # Expanding gain confirmed by volume (pyramid fuel)
        age * (1.0 - hrs_eod),          # Late-age position approaching 00:00 UTC EOD borrow
        ret_z * rel_btc,                # Momentum aligned with BTC outperformance
    ]


class NonlinearBellmanModel:
    """Purged walk-forward ensemble combining Interaction-Ridge + 2-seed Pure-NumPy Residual MLP.

    Outputs risk-adjusted Bellman continuation value E[Hold - ExitNow] in bps.
    """

    def __init__(self, l2_ridge: float = 45.0, hidden_dim: int = 12, seeds: tuple[int, ...] = (17, 43)) -> None:
        self.l2_ridge = l2_ridge
        self.hidden_dim = hidden_dim
        self.seeds = seeds
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.ridge_w_: np.ndarray | None = None
        self.ridge_b_: float = 0.0
        self.mlps_: list[tuple[np.ndarray, np.ndarray, np.ndarray, float]] = []

    def fit(self, x10: np.ndarray, y_wait_bps: np.ndarray, *, epochs: int = 35, lr: float = 3e-3) -> NonlinearBellmanModel:
        if x10.ndim != 2 or len(x10) < 50:
            self.ridge_w_ = None
            return self
        x_exp = np.asarray([expand_bellman_interactions(row.tolist()) for row in x10], dtype=np.float64)
        mu = np.mean(x_exp, axis=0)
        sd = np.std(x_exp, axis=0)
        sd = np.where(sd < 1e-6, 1.0, sd)
        xz = (x_exp - mu) / sd
        y_mean = float(np.mean(y_wait_bps))
        yc = (y_wait_bps - y_mean) / 200.0  # Scale targets to O(1) for stable tanh training

        n_feat = xz.shape[1]
        gram = xz.T @ xz + self.l2_ridge * np.eye(n_feat)
        rw = np.linalg.solve(gram, xz.T @ yc)
        self.mean_, self.std_, self.ridge_w_, self.ridge_b_ = mu, sd, rw, y_mean

        # Fit 2-seed compact residual MLP on Ridge residuals (prevents overfitting while capturing curvature)
        res_target = yc - (xz @ rw)
        self.mlps_ = []
        n = len(xz)
        for seed in self.seeds:
            rng = np.random.default_rng(seed)
            w1 = rng.normal(0.0, 0.25 / math.sqrt(n_feat), size=(n_feat, self.hidden_dim))
            b1 = np.zeros(self.hidden_dim, dtype=np.float64)
            w2 = np.zeros(self.hidden_dim, dtype=np.float64)
            b2 = 0.0
            for _ in range(epochs):
                h = np.tanh(xz @ w1 + b1)
                pred = h @ w2 + b2
                err = (pred - res_target) / n
                grad_w2 = h.T @ err + 0.02 * w2
                grad_b2 = float(np.sum(err))
                dh = np.outer(err, w2) * (1.0 - h * h)
                grad_w1 = xz.T @ dh + 0.02 * w1
                grad_b1 = np.sum(dh, axis=0)
                w2 -= lr * grad_w2
                b2 -= lr * grad_b2
                w1 -= lr * grad_w1
                b1 -= lr * grad_b1
            self.mlps_.append((w1, b1, w2, b2))
        return self

    def predict_wait_value_bps(self, state: OptimalStoppingState) -> float:
        if self.ridge_w_ is None or self.mean_ is None or self.std_ is None:
            return 0.0
        v = np.asarray(expand_bellman_interactions(state.to_vector()), dtype=np.float64)
        vz = (v - self.mean_) / self.std_
        base = float(np.dot(vz, self.ridge_w_))
        mlp_res = 0.0
        if self.mlps_:
            mlp_res = sum(float(np.tanh(vz @ w1 + b1) @ w2 + b2) for w1, b1, w2, b2 in self.mlps_) / len(self.mlps_)
        return float(self.ridge_b_ + 200.0 * (base + 0.50 * mlp_res))


@dataclass(frozen=True)
class SlowCoreStoppingState:
    """Strictly causal daily state for 1d Slow-Core Spot position Bellman exit scoring."""

    days_held: int
    unrealized_ret: float
    peak_mfe: float
    drawdown_from_peak: float
    s1_trend: float
    s1_accel: float
    crypto_breadth: float
    daily_atr_pct: float
    bar_ret_vs_atr: float

    def to_vector(self) -> list[float]:
        return [
            min(5.0, self.days_held / 10.0),
            max(-0.25, min(0.60, self.unrealized_ret)) * 5.0,
            max(0.0, min(0.80, self.peak_mfe)) * 5.0,
            max(0.0, min(0.30, self.drawdown_from_peak)) * 10.0,
            max(-1.0, min(1.0, self.s1_trend)),
            max(-1.0, min(1.0, self.s1_accel)),
            max(0.0, min(1.0, self.crypto_breadth)),
            max(0.01, min(0.15, self.daily_atr_pct)) * 20.0,
            max(-4.0, min(4.0, self.bar_ret_vs_atr)),
            self.peak_mfe * self.drawdown_from_peak * 25.0,
        ]


class SlowCoreBellmanModel:
    """Purged walk-forward Ridge Bellman continuation model for 1d Slow Spot Core positions."""

    def __init__(self, l2_alpha: float = 50.0) -> None:
        self.l2_alpha = l2_alpha
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.weights_: np.ndarray | None = None
        self.bias_: float = 0.0

    def fit(self, x_mat: np.ndarray, y_wait_5d_bps: np.ndarray) -> SlowCoreBellmanModel:
        if x_mat.ndim != 2 or len(x_mat) < 60:
            self.weights_ = None
            return self
        mu = np.mean(x_mat, axis=0)
        sd = np.std(x_mat, axis=0)
        sd = np.where(sd < 1e-6, 1.0, sd)
        xz = (x_mat - mu) / sd
        ym = float(np.mean(y_wait_5d_bps))
        gram = xz.T @ xz + self.l2_alpha * np.eye(xz.shape[1])
        self.weights_ = np.linalg.solve(gram, xz.T @ (y_wait_5d_bps - ym))
        self.mean_, self.std_, self.bias_ = mu, sd, ym
        return self

    def predict_wait_5d_bps(self, state: SlowCoreStoppingState) -> float:
        if self.weights_ is None or self.mean_ is None or self.std_ is None:
            return 0.0
        v = np.asarray(state.to_vector(), dtype=np.float64)
        return float(self.bias_ + np.dot((v - self.mean_) / self.std_, self.weights_))


def compute_bellman_path_target_bps(
    bars: list[BarPoint],
    idx: int,
    direction: int,
    peak_px: float,
    b_vol: float,
    *,
    max_lookahead: int = 6,
    downside_penalty_mult: float = 0.35,
) -> float | None:
    """Compute risk-adjusted Bellman continuation value over the next 2..max_lookahead bars.

    Rewards the best reachable horizon return while penalizing intra-path adverse excursion so the
    model prefers smooth continuations over volatile whipsaws.
    """
    if idx + max_lookahead + 1 >= len(bars):
        return None
    now_px = bars[idx + 1].open
    if now_px <= 0:
        return None
    stop_px = peak_px * (1.0 - 2.0 * b_vol) if direction > 0 else peak_px * (1.0 + 2.0 * b_vol)
    horizon_rets: list[float] = []
    worst_adverse = 0.0
    stopped_ret: float | None = None

    for step in range(1, max_lookahead + 1):
        b = bars[idx + step]
        if direction > 0:
            worst_adverse = min(worst_adverse, (b.low - now_px) / now_px)
            if stopped_ret is None and b.low <= stop_px:
                ex = min(b.open, stop_px)
                stopped_ret = (ex - now_px) / now_px
        else:
            worst_adverse = min(worst_adverse, (now_px - b.high) / now_px)
            if stopped_ret is None and b.high >= stop_px:
                ex = max(b.open, stop_px)
                stopped_ret = (now_px - ex) / now_px

        if step in {2, 4, max_lookahead}:
            if stopped_ret is not None:
                horizon_rets.append(stopped_ret)
            else:
                exit_o = bars[idx + step + 1].open
                r = direction * (exit_o - now_px) / now_px if exit_o > 0 else 0.0
                horizon_rets.append(r)

    if not horizon_rets:
        return None
    # Bellman continuation blends average multi-horizon path + upside option value minus adverse excursion penalty
    mean_h = sum(horizon_rets) / len(horizon_rets)
    best_h = max(horizon_rets)
    val = (0.60 * mean_h + 0.40 * best_h) + downside_penalty_mult * worst_adverse
    return max(-800.0, min(800.0, val * 10_000.0))


def detect_flush_rebound_trigger(
    bars: list[BarPoint],
    rets: list[float],
    vols: list[float],
    i: int,
) -> tuple[bool, float, float]:
    """Resurrection Candidate A: 2h panic flush (-2.2 sigma + volume climax + lower-wick absorption)."""
    if i < 36 or i + 1 >= len(bars):
        return False, 0.0, 0.0
    b = bars[i]
    if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
        return False, 0.0, 0.0
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.005, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    z = (rets[i] - mr) / b_vol
    mv = median(vols[i - 36 : i])
    span = max(b.high - b.low, 1e-9)
    lower_wick = max(0.0, min(b.open, b.close) - b.low) / span
    if z <= -2.2 and mv > 0 and b.volume >= 1.8 * mv and lower_wick >= 0.25:
        return True, b_vol, abs(z) * 0.01
    return False, b_vol, 0.0


def detect_breakdown_short_trigger(
    bars: list[BarPoint],
    rets: list[float],
    vols: list[float],
    lows: list[float],
    i: int,
    breadth: float,
) -> tuple[bool, float, float]:
    """Resurrection Candidate B: 2h structural breakdown short (<-2.0 sigma, 72-bar low break, breadth <= 0.45)."""
    if i < 72 or i + 1 >= len(bars) or breadth > 0.45:
        return False, 0.0, 0.0
    b = bars[i]
    if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
        return False, 0.0, 0.0
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.005, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    z = (rets[i] - mr) / b_vol
    mv = median(vols[i - 36 : i])
    if z <= -2.0 and mv > 0 and b.volume >= 1.6 * mv and b.close < min(lows[i - 72 : i]):
        return True, b_vol, abs(z) * 0.01
    return False, b_vol, 0.0


def detect_uncensored_early_ignition(
    bars: list[BarPoint],
    rets: list[float],
    vols: list[float],
    highs: list[float],
    i: int,
) -> tuple[bool, float, float]:
    """Resurrection Candidate C: Earlier/uncensored 2h breakout (z >= 1.5, vol >= 1.4x, 36-bar high break)."""
    if i < 36 or i + 1 >= len(bars):
        return False, 0.0, 0.0
    b = bars[i]
    if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
        return False, 0.0, 0.0
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.005, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    z = (rets[i] - mr) / b_vol
    mv = median(vols[i - 36 : i])
    if 1.5 <= z < 2.2 and mv > 0 and b.volume >= 1.4 * mv and b.close > max(highs[i - 36 : i]):
        return True, b_vol, z * 0.01
    return False, b_vol, 0.0
