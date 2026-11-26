"""Pure domain optimal-closing & exit-timing engine for fast Margin lots and slow Spot lots.

Evaluates 4 orthogonal exit-optimization mechanisms strictly causally (zero lookahead):
- E1: Nonlinear MFE Chandelier Ratchet + Breakeven Lock + Dead-Money Pre-EOD Exit
- E2: Parabolic Climax / Upper-Wick Exhaustion Passive Maker Scale-Out (50% trim into strength)
- E3: Purged Walk-Forward Optimal-Stopping Bellman Value-of-Waiting Estimator (E[Hold] vs Exit Now)
- E4: Active Slow-Core Peak-Protection & Climax Trim (eliminates waiting weeks for slow EWMAC rollover)

Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .multi_horizon_book import MultiHorizonBook, ThesisLot
from .timeframe_panel import BarPoint


@dataclass(frozen=True)
class OptimalExitConfig:
    """Configuration for the unified optimal-closing evaluation stack."""

    use_e1_ratchet: bool = False
    use_e2_climax_trim: bool = False
    use_e3_optimal_stopping: bool = False
    use_e4_slow_peak_protect: bool = False
    breakeven_mfe_mult: float = 1.6
    dead_money_bars: int = 6
    dead_money_min_mfe_mult: float = 0.75
    climax_wick_ratio: float = 0.45
    climax_vol_ratio: float = 2.2
    climax_min_gain_mult: float = 2.2
    wait_exit_threshold_bps: float = -8.0
    wait_trim_threshold_bps: float = 4.0
    wait_pyramid_threshold_bps: float = 65.0
    slow_trim_gain_pct: float = 0.14
    slow_drawdown_atr_mult: float = 2.2
    maker_trim_fee_bps: float = 4.5
    taker_exit_fee_bps: float = 16.0


@dataclass(frozen=True)
class OptimalStoppingState:
    """10-feature causal bar-by-bar state for Bellman E[Wait] vs Exit Now scoring."""

    age_bars: int
    unrealized_ret: float
    peak_mfe: float
    giveback_ratio: float  # (mfe - upnl) / max(mfe, 1e-4)
    upper_wick_ratio: float  # (high - close) / max(high - low, 1e-9)
    volume_ratio: float
    bar_ret_z: float
    rel_btc_ret: float
    hours_to_utc_eod: float
    entry_gru_score: float

    def to_vector(self) -> list[float]:
        return [
            min(4.0, self.age_bars / 6.0),
            max(-0.15, min(0.30, self.unrealized_ret)) * 10.0,
            max(0.0, min(0.35, self.peak_mfe)) * 10.0,
            max(0.0, min(2.0, self.giveback_ratio)),
            max(0.0, min(1.0, self.upper_wick_ratio)),
            math.log1p(max(0.0, min(10.0, self.volume_ratio))),
            max(-4.0, min(4.0, self.bar_ret_z)),
            max(-0.10, min(0.10, self.rel_btc_ret)) * 20.0,
            max(0.0, min(24.0, self.hours_to_utc_eod)) / 24.0,
            max(-0.10, min(0.20, self.entry_gru_score)) * 10.0,
        ]


class OptimalStoppingModel:
    """Pure-NumPy L2-regularized Ridge estimator of incremental net value of waiting E[Hold - ExitNow]."""

    def __init__(self, l2_alpha: float = 30.0) -> None:
        self.l2_alpha = l2_alpha
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.weights_: np.ndarray | None = None
        self.bias_: float = 0.0

    def fit(self, x_mat: np.ndarray, y_wait_bps: np.ndarray) -> OptimalStoppingModel:
        if x_mat.ndim != 2 or len(x_mat) < 40:
            self.weights_ = None
            return self
        mu = np.mean(x_mat, axis=0)
        sd = np.std(x_mat, axis=0)
        sd = np.where(sd < 1e-6, 1.0, sd)
        xz = (x_mat - mu) / sd
        y_mean = float(np.mean(y_wait_bps))
        yc = y_wait_bps - y_mean
        gram = xz.T @ xz + self.l2_alpha * np.eye(xz.shape[1])
        self.weights_ = np.linalg.solve(gram, xz.T @ yc)
        self.mean_ = mu
        self.std_ = sd
        self.bias_ = y_mean
        return self

    def predict_wait_value_bps(self, state: OptimalStoppingState) -> float:
        if self.weights_ is None or self.mean_ is None or self.std_ is None:
            return 0.0
        v = np.asarray(state.to_vector(), dtype=np.float64)
        return float(self.bias_ + np.dot((v - self.mean_) / self.std_, self.weights_))


def compute_ratchet_stop_price(
    lot: ThesisLot,
    *,
    cur_close: float,
    cfg: OptimalExitConfig,
) -> float:
    """E1: Concave Chandelier Ratchet — wide early breathing room, tight protection on big MFE + breakeven lock."""
    b_vol = max(0.006, lot.entry_bar_vol)
    if lot.direction > 0:
        mfe_ret = max(0.0, (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
        mfe_mult = mfe_ret / b_vol
        # Concave decay from 2.5*b_vol down to 1.15*b_vol as MFE grows from 0 -> 5*b_vol
        trail_mult = 1.15 + 1.35 * math.exp(-0.42 * mfe_mult)
        cand_stop = lot.peak_price * (1.0 - trail_mult * b_vol)
        # Lock breakeven + round-trip cost once MFE clears breakeven_mfe_mult
        if mfe_mult >= cfg.breakeven_mfe_mult:
            be_floor = lot.entry_price * 1.0040
            cand_stop = max(cand_stop, be_floor)
        return max(lot.stop_price, cand_stop)
    mfe_ret = max(0.0, (lot.entry_price - lot.peak_price) / max(lot.entry_price, 1e-9))
    mfe_mult = mfe_ret / b_vol
    trail_mult = 1.15 + 1.35 * math.exp(-0.42 * mfe_mult)
    cand_stop = lot.peak_price * (1.0 + trail_mult * b_vol)
    if mfe_mult >= cfg.breakeven_mfe_mult:
        be_ceil = lot.entry_price * 0.9960
        cand_stop = min(cand_stop, be_ceil)
    return min(lot.stop_price, cand_stop) if lot.stop_price > 0 else cand_stop


def is_dead_money_pre_eod(
    lot: ThesisLot,
    *,
    hours_to_utc_eod: float,
    cfg: OptimalExitConfig,
) -> bool:
    """E1: Exit stalled margin trades (age >= 12h, low MFE) cleanly before crossing 00:00 UTC EOD borrow."""
    if lot.age_bars < cfg.dead_money_bars:
        return False
    b_vol = max(0.006, lot.entry_bar_vol)
    if lot.direction > 0:
        mfe_ret = max(0.0, (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
    else:
        mfe_ret = max(0.0, (lot.entry_price - lot.peak_price) / max(lot.entry_price, 1e-9))
    stalled = (mfe_ret / b_vol) < cfg.dead_money_min_mfe_mult
    if not stalled:
        return False
    # Exit immediately if nearing UTC EOD midnight (<=4h) OR stalled past 8 bars (16h)
    return hours_to_utc_eod <= 4.5 or lot.age_bars >= (cfg.dead_money_bars + 2)


def detect_climax_exhaustion(
    lot: ThesisLot,
    bar: BarPoint,
    volume_ratio: float,
    cfg: OptimalExitConfig,
) -> bool:
    """E2: Detect parabolic extension + upper-wick rejection or climax volume stall for passive maker trim."""
    if lot.direction <= 0 or bar.close <= 0 or lot.entry_price <= 0:
        return False
    gain_ret = (bar.close - lot.entry_price) / lot.entry_price
    b_vol = max(0.006, lot.entry_bar_vol)
    if gain_ret < cfg.climax_min_gain_mult * b_vol:
        return False
    span = max(bar.high - bar.low, 1e-9)
    upper_wick = max(0.0, bar.high - bar.close) / span
    wick_reject = upper_wick >= cfg.climax_wick_ratio and (bar.high - lot.entry_price) / lot.entry_price >= (cfg.climax_min_gain_mult + 0.5) * b_vol
    vol_blowoff = volume_ratio >= cfg.climax_vol_ratio and upper_wick >= 0.30
    return wick_reject or vol_blowoff


def decide_optimal_stopping_action(
    pred_wait_bps: float,
    state: OptimalStoppingState,
    *,
    already_pyramided: bool,
    already_trimmed: bool,
    cfg: OptimalExitConfig,
) -> str:
    """E3: Bellman optimal-stopping decision comparing E[Hold] vs immediate exit/trim/pyramid."""
    # Pre-midnight borrow penalty raises exit bar on marginal trades
    eod_penalty = 5.0 if state.hours_to_utc_eod <= 3.0 else 0.0
    eff_wait = pred_wait_bps - eod_penalty
    if state.age_bars >= 2 and eff_wait < cfg.wait_exit_threshold_bps:
        return "OPTIMAL_EXIT"
    if (
        not already_trimmed
        and state.age_bars >= 2
        and state.peak_mfe >= 0.03
        and state.giveback_ratio >= 0.35
        and eff_wait < cfg.wait_trim_threshold_bps
    ):
        return "OPTIMAL_TRIM_50"
    if (
        not already_pyramided
        and state.age_bars >= 1
        and state.unrealized_ret >= 0.018
        and eff_wait >= cfg.wait_pyramid_threshold_bps
    ):
        return "FREE_ROLL_PYRAMID"
    return "HOLD"


def trim_lot_fraction(
    book: MultiHorizonBook,
    lot_key: tuple[str, str],
    trim_fraction: float,
    exit_px: float,
    fee_bps: float,
) -> float:
    """Realize trim_fraction of an open lot with exact <1e-9 cost-basis equity conservation."""
    lot = book.lots.get(lot_key)
    if lot is None or exit_px <= 0.0 or trim_fraction <= 0.0:
        return 0.0
    if trim_fraction >= 0.98:
        return book.close_lot(lot_key, exit_px, fee_bps)
    frac_sell = max(0.0, min(1.0, trim_fraction))
    frac_keep = 1.0 - frac_sell
    trim_notional = lot.qty * exit_px * frac_sell
    fee = trim_notional * (fee_bps / 10_000.0)
    returned = max(0.0, book.lot_equity(lot, exit_px) * frac_sell - fee)
    book.free_cash += returned
    book.total_fees += fee
    lot.qty *= frac_keep
    lot.notional *= frac_keep
    lot.collateral *= frac_keep
    return returned


def evaluate_slow_core_peak_protection(
    lot: ThesisLot,
    cur_px: float,
    daily_atr_pct: float,
    breadth: float,
    *,
    already_trimmed: bool,
    cfg: OptimalExitConfig,
) -> tuple[str, float]:
    """E4: Active peak-protection for 1d slow Spot lots (trims parabolic blow-offs before weeks of giveback)."""
    if lot.thesis_id != "slow_core" or lot.entry_price <= 0 or cur_px <= 0:
        return "HOLD", 0.0
    peak_gain = (lot.peak_price - lot.entry_price) / lot.entry_price
    cur_gain = (cur_px - lot.entry_price) / lot.entry_price
    drawdown_from_peak = max(0.0, (lot.peak_price - cur_px) / max(lot.peak_price, 1e-9))
    atr = max(0.015, daily_atr_pct)

    # 1) Parabolic winner reversing >= 2.2 * daily_atr from peak -> lock 50% into USDT pool
    if not already_trimmed and peak_gain >= cfg.slow_trim_gain_pct and drawdown_from_peak >= cfg.slow_drawdown_atr_mult * atr:
        return "TRIM_50", 0.50

    # 2) Broad bear shock (breadth < 0.22) while still holding >= +8% open gain -> trim 50% defensively
    if not already_trimmed and breadth < 0.22 and cur_gain >= 0.08 and drawdown_from_peak >= 1.5 * atr:
        return "TRIM_50", 0.50

    return "HOLD", 0.0


@dataclass
class ClosedTradeCapture:
    """Per-trade MFE capture telemetry for measuring exit optimality objectively."""

    realized_ret_bps: float
    peak_mfe_bps: float
    giveback_bps: float
    held_hours: float
    exit_reason: str
    closed_before_eod_borrow: bool


def summarize_exit_efficiency(trades: list[ClosedTradeCapture]) -> dict:
    """Compute MFE capture ratio, average giveback, win rate, profit factor, and exit-reason counts."""
    if not trades:
        return {
            "closed_trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0,
            "avg_realized_bps": 0.0, "avg_mfe_bps": 0.0, "avg_giveback_bps": 0.0,
            "mfe_capture_ratio": 0.0, "avg_hold_hours": 0.0, "pre_eod_zero_borrow_pct": 0.0,
            "reasons": {},
        }
    wins = [t for t in trades if t.realized_ret_bps > 0]
    gross_win = sum(t.realized_ret_bps for t in wins)
    gross_loss = abs(sum(t.realized_ret_bps for t in trades if t.realized_ret_bps < 0))
    tot_mfe = sum(max(0.0, t.peak_mfe_bps) for t in trades)
    tot_real = sum(t.realized_ret_bps for t in trades)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    return {
        "closed_trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1),
        "profit_factor": round(gross_win / max(1.0, gross_loss), 3),
        "avg_realized_bps": round(tot_real / len(trades), 1),
        "avg_mfe_bps": round(tot_mfe / len(trades), 1),
        "avg_giveback_bps": round(sum(t.giveback_bps for t in trades) / len(trades), 1),
        "mfe_capture_ratio": round(tot_real / max(1.0, tot_mfe), 3),
        "avg_hold_hours": round(sum(t.held_hours for t in trades) / len(trades), 1),
        "pre_eod_zero_borrow_pct": round(100.0 * sum(1 for t in trades if t.closed_before_eod_borrow) / len(trades), 1),
        "reasons": reasons,
    }
