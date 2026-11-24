"""Multi-modal continuous forecast graph & mandatory 2x2 attribution matrix (spec §5.4)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .kalman_models import KalmanBasisOutput
from .microstructure import RichSnapshot


def clamp_forecast(value: float) -> float:
    return max(-20.0, min(20.0, float(value)))


class MultiHorizonEwmacNode:
    """G1 (Slow): Multi-horizon EWMAC forecast in [-20, +20] for parent target weights."""

    def __init__(self, pairs: tuple[tuple[int, int], ...] = ((8, 32), (16, 64), (32, 128))) -> None:
        self.pairs = pairs
        self._emas: dict[int, float] = {}
        self._vol_ewma = 0.0
        self._prev_close: float | None = None
        self._count = 0

    def update(self, close: float) -> float:
        if close <= 0:
            return 0.0
        self._count += 1
        if self._prev_close is not None and self._prev_close > 0:
            ret = (close - self._prev_close) / self._prev_close
            alpha_v = 2.0 / 37.0
            self._vol_ewma = (1.0 - alpha_v) * self._vol_ewma + alpha_v * (ret * ret)
        self._prev_close = close

        spans = {s for pair in self.pairs for s in pair}
        for span in spans:
            alpha = 2.0 / (span + 1.0)
            self._emas[span] = close if span not in self._emas else (1.0 - alpha) * self._emas[span] + alpha * close

        vol = max(self._vol_ewma ** 0.5, 1e-4)
        if self._count < max(spans) // 2:
            return 0.0
        parts = []
        for fast, slow in self.pairs:
            raw = (self._emas[fast] - self._emas[slow]) / (close * vol)
            parts.append(clamp_forecast(raw * 4.0))
        return clamp_forecast(sum(parts) / len(parts))


class MicropriceOfiNode:
    """G2 (Fast): 1-5m microstructure forecast in [-20, +20] used as execution/skew/toxicity overlay."""

    def __init__(self, *, vpin_veto_threshold: float = 0.85) -> None:
        self.vpin_veto_threshold = vpin_veto_threshold

    def evaluate(self, snap: RichSnapshot) -> tuple[float, bool]:
        mid = (snap.bid + snap.ask) / Decimal(2)
        if mid <= 0:
            return 0.0, False
        micro_edge_bps = float((snap.microprice - mid) / mid * Decimal(10000))
        l2_term = float(snap.l2_depth5_imbalance) * 6.0 if snap.l2_depth5_imbalance is not None else 0.0
        ofi_denom = float(snap.bid_qty + snap.ask_qty) + 1e-9
        ofi_term = max(-10.0, min(10.0, float(snap.ofi_l1) / ofi_denom * 5.0))
        forecast = clamp_forecast(micro_edge_bps * 1.5 + l2_term + ofi_term)
        toxicity_veto = snap.vpin is not None and snap.vpin > self.vpin_veto_threshold
        return forecast, toxicity_veto


class LeaveOneOutKalmanBasisNode:
    """G3 (Fast): Traded-leg Kalman basis forecast in [-20, +20]."""

    def evaluate(self, kalman_out: KalmanBasisOutput, *, quote_asset: str) -> float:
        if quote_asset.upper() == "USDT":
            return clamp_forecast(kalman_out.forecast_usdt_leg)
        return clamp_forecast(kalman_out.forecast_tmn_leg)


class CrossMarketBreadthRegimeNode:
    """G4 (Regime): Produces P(S_t) in [0, 1] strictly as a conditioning multiplier (never additive)."""

    def evaluate(self, fraction_positive_trend: float, *, floor: float = 0.25) -> float:
        clamped = max(0.0, min(1.0, float(fraction_positive_trend)))
        return floor + (1.0 - floor) * clamped


@dataclass(frozen=True)
class ForecastGraphOutput:
    parent_forecast: float                # slow regime-conditioned forecast in [-20, +20]
    regime_multiplier: float              # P(S_t) in [0, 1]
    fast_overlay_forecast: float          # microstructure + basis overlay in [-20, +20]
    suggested_quote_skew_bps: float
    toxicity_veto: bool


class MultiModalForecastGraph:
    """Separates slow parent target forecasts from fast execution-timing/skew overlays."""

    def __init__(self, *, fast_skew_bps_per_10: float = 4.0) -> None:
        self.fast_skew_bps_per_10 = fast_skew_bps_per_10

    def combine(
        self,
        *,
        slow_trend_forecast: float,
        regime_multiplier: float,
        microstructure_forecast: float = 0.0,
        kalman_basis_forecast: float = 0.0,
        toxicity_veto: bool = False,
    ) -> ForecastGraphOutput:
        reg = max(0.0, min(1.0, float(regime_multiplier)))
        parent = clamp_forecast(slow_trend_forecast * reg)
        fast = clamp_forecast(0.5 * microstructure_forecast + 0.5 * kalman_basis_forecast)
        skew_bps = (fast / 10.0) * self.fast_skew_bps_per_10
        return ForecastGraphOutput(
            parent_forecast=parent,
            regime_multiplier=reg,
            fast_overlay_forecast=fast,
            suggested_quote_skew_bps=skew_bps,
            toxicity_veto=toxicity_veto,
        )


@dataclass(frozen=True)
class Attribution2x2:
    arm_a_baseline: Decimal
    arm_b_new_signal: Decimal
    arm_c_new_exec: Decimal
    arm_d_combined: Decimal
    signal_effect: Decimal                # B - A
    execution_effect: Decimal             # C - A
    interaction_effect: Decimal           # D - B - C + A
    total_lift: Decimal                   # D - A (equals signal + execution + interaction identically)


def run_2x2_attribution(
    arm_a: Decimal,
    arm_b: Decimal,
    arm_c: Decimal,
    arm_d: Decimal,
) -> Attribution2x2:
    """Exact 2x2 factorial attribution summing identically to D - A."""
    sig = arm_b - arm_a
    exe = arm_c - arm_a
    inter = arm_d - arm_b - arm_c + arm_a
    total = arm_d - arm_a
    return Attribution2x2(arm_a, arm_b, arm_c, arm_d, sig, exe, inter, total)
