"""Promoted paper-only strategies and portfolio rules verified by post-repair research.

Contains only pure, deterministic domain logic (zero I/O, zero execution authority):
  - SlowS1Trend: multi-horizon EWMAC trend strategy with hysteresis deadband (Strategy protocol)
  - apply_cost_aware_band: S2 no-trade hysteresis band (cuts fills ~76%, lifts Sharpe & net return)
  - apply_metals_reserve: multi-issuer defensive metals reserve (XAUT/PAXG/SLVON)
  - admit_conditional_ignition: 15% slow-cash-reserve admission gate for shadow 2h ignition
  - PROMOTED_STRATEGY_MANIFEST: explicit promotion/challenger/retirement governance ledger
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .strategy import EMA, long_flat

PROMOTED_STRATEGY_MANIFEST: dict[str, dict[str, str]] = {
    "slow-s1-s5-cost-aware": {
        "tier": "REFERENCE_DEFAULT",
        "scope": "PAPER_ONLY",
        "evidence": "1d Slow S1+S5 + cost-aware band: +151.68% vs +148.29%, SR 0.790 vs 0.775, MaxDD 22.66% vs 23.65%, fills -76.2%.",
    },
    "multi-issuer-metals-reserve": {
        "tier": "REFERENCE_DEFAULT",
        "scope": "PAPER_ONLY",
        "evidence": "XAUT<=25%, PAXG<=15%, SLVON<=10% halves -3% single-issuer gold depeg shock while preserving Sharpe.",
    },
    "momentum-ignition-2h-shadow": {
        "tier": "SHADOW_CHALLENGER",
        "scope": "PAPER_ONLY",
        "evidence": "STABLE under 0h/+1h bar-offset (54.7%); -3.05% standalone; run only in shadow or under 15% slow-cash reserve.",
    },
    "conditional-capital-admission-res15": {
        "tier": "SHADOW_CHALLENGER",
        "scope": "PAPER_ONLY",
        "evidence": "15% slow cash reserve eliminates all 60 displaced slow buys ($1,101.31 -> $1,114.90) vs unguarded sharing.",
    },
    "bellman-early-exit": {
        "tier": "RETIRED_PARKED",
        "scope": "EXCLUDED",
        "evidence": "Post-F16 purged single-fork OOS mean -121.98 bps across 104 lots; retired from promotion.",
    },
    "bear-spot-buy-deferral": {
        "tier": "RETIRED_PARKED",
        "scope": "EXCLUDED",
        "evidence": "+132.98% vs +139.98% equal-exposure cash control (-7.00% drag); retired from promotion.",
    },
    "accel-execution-speed": {
        "tier": "RETIRED_PARKED",
        "scope": "EXCLUDED",
        "evidence": "+143.97% vs +148.29% baseline; retired from promotion.",
    },
    "failed-downside-auction-2h": {
        "tier": "RETIRED_PARKED",
        "scope": "EXCLUDED",
        "evidence": "TIMING_SENSITIVE (28.2% offset overlap) and -34.31 bps/intended after fees; parked.",
    },
    "four-quadrant-leveraged-macro": {
        "tier": "RETIRED_PARKED",
        "scope": "EXCLUDED",
        "evidence": "All 6 post-repair 4-quadrant arms incurred modeled liquidation; excluded from default engine.",
    },
}


@dataclass(frozen=True)
class SlowCorePolicy:
    """Versioned parameters for the promoted Slow S1+S5 cost-aware paper portfolio."""

    leg_fee_rate: float = 0.0016
    min_no_trade_band: float = 0.032
    fee_band_multiplier: float = 20.0
    max_gross_weight: float = 0.95
    slow_cash_reserve_frac: float = 0.15


def enforce_spot_only_strategy(
    strategy_id: str,
    *,
    leverage: float = 1.0,
    short_allowed: bool = False,
) -> None:
    """ADR 0009 hard spot-only gate: reject leveraged or short strategies until MarginAccount ships."""
    if short_allowed:
        raise ValueError(f"spot-only gate rejected short-enabled strategy {strategy_id!r} (ADR 0009)")
    if leverage > 1.0 + 1e-9 or leverage <= 0.0:
        raise ValueError(f"spot-only gate rejected leverage={leverage} for {strategy_id!r} (ADR 0009)")


def apply_cost_aware_band(
    target_weights: dict[str, float],
    current_weights: dict[str, float],
    *,
    leg_fee_rate: float = 0.0016,
    min_band: float = 0.032,
    fee_multiplier: float = 20.0,
    max_gross: float = 1.0,
) -> dict[str, float]:
    """Suppress small turnover inside the cost-aware deadband while always permitting full exits."""
    band = max(min_band, fee_multiplier * max(0.0, leg_fee_rate))
    adjusted: dict[str, float] = {}
    for sym in sorted(set(target_weights) | set(current_weights)):
        tw = max(0.0, float(target_weights.get(sym, 0.0)))
        cw = max(0.0, float(current_weights.get(sym, 0.0)))
        if tw > 0.0 and abs(tw - cw) < band:
            w = cw
        else:
            w = tw
        if w > 1e-6:
            adjusted[sym] = w
    gross = sum(adjusted.values())
    if gross > max_gross > 0.0:
        scale = max_gross / gross
        adjusted = {k: v * scale for k, v in adjusted.items()}
    return {k: round(v, 6) for k, v in adjusted.items() if v > 1e-6}


def apply_metals_reserve(
    slow_weights: dict[str, float],
    reserve_weights: dict[str, float],
    *,
    max_invested: float = 0.95,
) -> dict[str, float]:
    """Allocate multi-issuer defensive metals reserve strictly from unused cash headroom."""
    out = {k: max(0.0, float(v)) for k, v in slow_weights.items() if v > 1e-6}
    free_cash = max(0.0, max_invested - sum(out.values()))
    for sym in sorted(reserve_weights):
        desired = max(0.0, float(reserve_weights[sym]))
        if desired <= 0.0 or free_cash <= 1e-6:
            continue
        add = min(max(0.0, desired - out.get(sym, 0.0)), free_cash)
        if add > 1e-6:
            out[sym] = round(out.get(sym, 0.0) + add, 6)
            free_cash -= add
    return out


def admit_conditional_ignition(
    available_cash: float,
    portfolio_nav: float,
    desired_notional: float,
    *,
    slow_reserve_frac: float = 0.15,
    min_notional: float = 10.0,
) -> tuple[float, str]:
    """Admit shadow/challenger ignition capital only above the protected slow-sleeve cash reserve."""
    if desired_notional <= 0.0 or portfolio_nav <= 0.0:
        return 0.0, "REJECTED_INVALID"
    protected_floor = max(0.0, slow_reserve_frac) * portfolio_nav
    spendable = max(0.0, available_cash - protected_floor)
    if spendable >= desired_notional:
        return desired_notional, "FULL"
    if spendable >= min_notional:
        return spendable, "PARTIAL"
    return 0.0, "REJECTED_RESERVE"


class SlowS1Trend:
    """Promoted multi-horizon EWMAC trend strategy with cost-aware hysteresis deadband (PAPER_ONLY).

    Conforms to the canonical gym.domain.strategy protocol (long/flat, closed bars only, no lookahead).
    """

    name = "slow-s1-trend"
    version = 1

    def __init__(self, fast: int = 8, mid: int = 16, slow: int = 32, hysteresis_bps: int = 25):
        if not (1 <= fast < mid < slow):
            raise ValueError("need 1 <= fast < mid < slow")
        if hysteresis_bps < 0:
            raise ValueError("hysteresis_bps must be >= 0")
        self.params = {"fast": fast, "mid": mid, "slow": slow, "hysteresis_bps": hysteresis_bps}
        self._pairs = ((EMA(fast), EMA(fast * 4)), (EMA(mid), EMA(mid * 4)), (EMA(slow), EMA(slow * 4)))
        self._ema_regime = EMA(50)
        self._closes: deque[Decimal] = deque(maxlen=21)
        self.feature_values: dict = {}

    def decide(self, snap, holding):
        close = snap.bar.close
        self._closes.append(close)
        regime_val = self._ema_regime.update(close)
        pair_vals = [(f.update(close), s.update(close)) for f, s in self._pairs]
        ready = all(s.ready for _, s in self._pairs) and self._ema_regime.ready
        self.feature_values = {
            "observations": self._pairs[-1][1].count,
            "required": self._pairs[-1][1].n,
            "regime_ema": str(regime_val),
            "signal_bps": None,
            "trend": None,
        }
        if not ready or close <= 0:
            return long_flat(snap, holding, None, self.feature_values)
        raw_bps = sum(((f_v - s_v) / close) * Decimal(10000) for f_v, s_v in pair_vals) / Decimal(len(pair_vals))
        band = Decimal(self.params["hysteresis_bps"])
        above_regime = close > regime_val
        if holding:
            target = not (raw_bps < -band or not above_regime)
        else:
            target = raw_bps > band and above_regime
        self.feature_values.update(
            signal_bps=str(raw_bps.quantize(Decimal("0.01"))),
            above_regime=above_regime,
            trend=target,
        )
        return long_flat(snap, holding, target, self.feature_values)
