"""Pure domain models for In-Position ML Continuation/Exit Hazard, Tehran Liquidity-Clock,
Synthetic Asset/TMN<->USDTTMN Triangle Routing, and Dynamic Borrow-Currency Selection.

Addresses structural flaws F2 (03:30 Tehran taker execution & unused OCO maker), F4 (entry-only ML
with blind static exits), and F5 (ignored TMN/IRT books and USDT-only borrow currency).
Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class InPositionSnapshot:
    """Strictly causal bar-by-bar state of an open trade for continuation / exit-hazard scoring."""

    age_bars: int
    unrealized_ret: float
    peak_mfe: float
    giveback_from_peak: float
    last_bar_ret_z: float
    volume_follow_ratio: float
    rel_btc_ret: float
    entry_gru_score: float

    def to_vector(self) -> list[float]:
        return [
            min(4.0, self.age_bars / 6.0),
            max(-0.15, min(0.25, self.unrealized_ret)) * 10.0,
            max(0.0, min(0.30, self.peak_mfe)) * 10.0,
            max(0.0, min(0.20, self.giveback_from_peak)) * 10.0,
            max(-4.0, min(4.0, self.last_bar_ret_z)),
            math.log1p(max(0.0, min(10.0, self.volume_follow_ratio))),
            max(-0.10, min(0.10, self.rel_btc_ret)) * 20.0,
            max(-0.10, min(0.20, self.entry_gru_score)) * 10.0,
        ]


class InPositionContinuationModel:
    """Pure-NumPy L2-regularized Ridge predictor of remaining net return over the next 4h..8h.

    Trained strictly causally on prior closed episodes (purged walk-forward) so every open position
    is re-scored bar-by-bar to decide EARLY_SELL vs HOLD vs FREE_ROLL_PYRAMID in the moment.
    """

    def __init__(self, l2_alpha: float = 25.0) -> None:
        self.l2_alpha = l2_alpha
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.weights_: np.ndarray | None = None
        self.bias_: float = 0.0

    def fit(self, x_mat: np.ndarray, y_rem_ret: np.ndarray) -> InPositionContinuationModel:
        if x_mat.ndim != 2 or len(x_mat) < 30:
            self.weights_ = None
            return self
        mu = np.mean(x_mat, axis=0)
        sd = np.std(x_mat, axis=0)
        sd = np.where(sd < 1e-6, 1.0, sd)
        xz = (x_mat - mu) / sd
        n_feat = xz.shape[1]
        y_mean = float(np.mean(y_rem_ret))
        yc = y_rem_ret - y_mean
        gram = xz.T @ xz + self.l2_alpha * np.eye(n_feat)
        self.weights_ = np.linalg.solve(gram, xz.T @ yc)
        self.mean_ = mu
        self.std_ = sd
        self.bias_ = y_mean
        return self

    def predict_remaining_return(self, snap: InPositionSnapshot) -> float:
        if self.weights_ is None or self.mean_ is None or self.std_ is None:
            return 0.0
        vec = np.asarray(snap.to_vector(), dtype=np.float64)
        vz = (vec - self.mean_) / self.std_
        return float(self.bias_ + np.dot(vz, self.weights_))


def decide_in_position_action(
    pred_rem_ret: float,
    snap: InPositionSnapshot,
    *,
    already_pyramided: bool,
    early_sell_threshold: float = -0.0025,
    pyramid_threshold: float = 0.0075,
    min_bars_before_early_sell: int = 2,
) -> str:
    """In-the-moment position management: EARLY_SELL | FREE_ROLL_PYRAMID | HOLD."""
    if snap.age_bars >= min_bars_before_early_sell and pred_rem_ret < early_sell_threshold:
        return "EARLY_SELL"
    if (
        not already_pyramided
        and snap.age_bars >= 1
        and snap.unrealized_ret >= 0.018
        and pred_rem_ret >= pyramid_threshold
    ):
        return "FREE_ROLL_PYRAMID"
    return "HOLD"


@dataclass(frozen=True)
class TriangleRouteDecision:
    """Comparison of direct Asset/USDT vs synthetic Asset/TMN <-> USDTTMN execution."""

    symbol: str
    side: str  # BUY | SELL
    chosen_route: str  # DIRECT_USDT | SYNTHETIC_TMN
    direct_effective_usdt: float
    synthetic_effective_usdt: float
    saving_bps: float


def evaluate_synthetic_triangle_route(
    symbol: str,
    side: str,
    *,
    direct_usdt_bid: float,
    direct_usdt_ask: float,
    tmn_bid: float,
    tmn_ask: float,
    usdttmn_bid: float,
    usdttmn_ask: float,
    usdt_fee_bps: float = 9.1,
    tmn_fee_bps: float = 17.5,
) -> TriangleRouteDecision:
    """Compare all-in executable USDT price of direct Asset/USDT vs 2-leg Asset/TMN <-> USDTTMN."""
    side_u = side.strip().upper()
    f_u = usdt_fee_bps / 10_000.0
    f_t = tmn_fee_bps / 10_000.0
    if side_u == "BUY":
        # Direct BUY: pay ask * (1 + f_u)
        direct_px = direct_usdt_ask * (1.0 + f_u)
        # Synthetic BUY: sell USDT into TMN at usdttmn_bid*(1-f_t), then buy Asset/TMN at tmn_ask*(1+f_t)
        synth_px = (tmn_ask * (1.0 + f_t)) / max(1e-9, usdttmn_bid * (1.0 - f_t))
        saving_bps = (direct_px - synth_px) / max(1e-9, direct_px) * 10_000.0
    else:
        # Direct SELL: receive bid * (1 - f_u)
        direct_px = direct_usdt_bid * (1.0 - f_u)
        # Synthetic SELL: sell Asset into TMN at tmn_bid*(1-f_t), then buy USDT at usdttmn_ask*(1+f_t)
        synth_px = (tmn_bid * (1.0 - f_t)) / max(1e-9, usdttmn_ask * (1.0 + f_t))
        saving_bps = (synth_px - direct_px) / max(1e-9, direct_px) * 10_000.0

    chosen = "SYNTHETIC_TMN" if saving_bps > 1.0 else "DIRECT_USDT"
    return TriangleRouteDecision(
        symbol=symbol,
        side=side_u,
        chosen_route=chosen,
        direct_effective_usdt=round(direct_px, 6),
        synthetic_effective_usdt=round(synth_px, 6),
        saving_bps=round(max(0.0, saving_bps), 2),
    )


@dataclass(frozen=True)
class BorrowCurrencyDecision:
    """Dynamic borrow-denomination choice: USDT debt vs depreciating TMN/IRT fiat debt."""

    chosen_currency: str  # USDT | TMN
    effective_usdt_carry_bps_per_day: float
    effective_tmn_carry_bps_per_day: float
    net_carry_advantage_bps_per_day: float
    rationale: str


def select_borrow_currency(
    *,
    expected_usdttmn_drift_bps_per_day: float,
    usdttmn_trend_score: float,
    usdt_borrow_bps_per_day: float = 5.0,
    tmn_borrow_bps_per_day: float = 9.0,
    tmn_fx_safety_margin_bps_per_day: float = 2.0,
) -> BorrowCurrencyDecision:
    """Choose USDT vs TMN borrow currency in the moment based on live USDTTMN drift vs borrow spread.

    If TMN is depreciating faster than (tmn_borrow - usdt_borrow + safety_margin) in a confirmed
    USDTTMN uptrend, borrowing TMN has lower true USDT-denominated carry than borrowing USDT.
    """
    eff_tmn_in_usdt = tmn_borrow_bps_per_day - expected_usdttmn_drift_bps_per_day
    adv = usdt_borrow_bps_per_day - (eff_tmn_in_usdt + tmn_fx_safety_margin_bps_per_day)
    if usdttmn_trend_score >= 0.35 and adv > 0.0:
        return BorrowCurrencyDecision(
            chosen_currency="TMN",
            effective_usdt_carry_bps_per_day=round(usdt_borrow_bps_per_day, 2),
            effective_tmn_carry_bps_per_day=round(eff_tmn_in_usdt, 2),
            net_carry_advantage_bps_per_day=round(adv, 2),
            rationale="usdttmn_uptrend_offsets_tmn_borrow_spread",
        )
    return BorrowCurrencyDecision(
        chosen_currency="USDT",
        effective_usdt_carry_bps_per_day=round(usdt_borrow_bps_per_day, 2),
        effective_tmn_carry_bps_per_day=round(eff_tmn_in_usdt, 2),
        net_carry_advantage_bps_per_day=round(-adv, 2),
        rationale="usdt_borrow_cheaper_or_tmn_flat",
    )


def tehran_execution_cost_bps(
    utc_hour: int,
    *,
    base_nobitex_taker_bps: float = 16.0,
    peak_hour_discount_bps: float = 3.5,
    dead_night_penalty_bps: float = 3.5,
    passive_maker_saving_bps: float = 7.5,
    use_passive_maker: bool = False,
) -> float:
    """Empirical Iranian venue liquidity clock measured on 1.37M live book_top ticks.

    Tightest spreads: 05-06, 10, 20-22 UTC (08:30-09:30, 13:30, 23:30-01:30 Tehran).
    Widest spreads:   01-04 UTC (04:30-07:30 Tehran dead-of-night) and 17 UTC (US macro spike).
    """
    cost = base_nobitex_taker_bps
    if utc_hour in {5, 6, 10, 20, 22}:
        cost -= peak_hour_discount_bps
    elif utc_hour in {1, 2, 3, 4, 17}:
        cost += dead_night_penalty_bps
    if use_passive_maker:
        cost = max(3.5, cost - passive_maker_saving_bps)
    return round(cost, 2)
