"""Power-calibrated validation, path-preserving nulls, causality check & Track B v2 journal (spec §6.5)."""
from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import NormalDist

from .statistical_inference import sequential_e_process

_EULER = 0.5772156649015329
_NORM = NormalDist()


def deflated_sharpe_probability(sharpe: float, n_obs: int, n_trials: int, *, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio probability P(SR > SR*)."""
    if n_obs < 3 or n_trials < 1:
        return 0.0
    if n_trials == 1:
        sr_star = 0.0
    else:
        z1 = _NORM.inv_cdf(1.0 - 1.0 / n_trials)
        z2 = _NORM.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
        sr_star = ((1.0 - _EULER) * z1 + _EULER * z2) / math.sqrt(max(1.0, n_obs - 1.0))
    denom_sq = max(1e-12, 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * sharpe * sharpe)
    z = (sharpe - sr_star) * math.sqrt(n_obs - 1.0) / math.sqrt(denom_sq)
    return _NORM.cdf(z)


@dataclass(frozen=True)
class PowerSimulationResult:
    replications: int
    dsr_pass_rate: float
    e_process_pass_rate: float | None
    meets_80pct_power: bool


def simulate_joint_gate_power(
    daily_block_returns: list[float],
    *,
    edge_bps_per_step: float,
    horizon_steps: int,
    n_trials: int = 21,
    replications: int = 400,
    dsr_threshold: float = 0.95,
    e_lower_bound: float | None = None,
    e_threshold: float = 20.0,
    seed: int = 42,
) -> PowerSimulationResult:
    """Date-clustered block-bootstrap power simulation verifying >= 80% probability of clearing DSR/e-process."""
    if len(daily_block_returns) < 5 or horizon_steps < 5:
        raise ValueError("need >= 5 historical return blocks and horizon_steps >= 5")
    rng = random.Random(seed)
    mean_hist = sum(daily_block_returns) / len(daily_block_returns)
    centered = [r - mean_hist for r in daily_block_returns]
    shift = edge_bps_per_step / 10000.0

    dsr_passes = 0
    e_passes = 0
    for _ in range(replications):
        sample = [rng.choice(centered) + shift for _ in range(horizon_steps)]
        mean_s = sum(sample) / horizon_steps
        var_s = sum((x - mean_s) ** 2 for x in sample) / max(1, horizon_steps - 1)
        std_s = math.sqrt(max(var_s, 1e-12))
        sr = mean_s / std_s
        dsr = deflated_sharpe_probability(sr, horizon_steps, n_trials)
        if dsr >= dsr_threshold:
            dsr_passes += 1
        if e_lower_bound is not None:
            e_res = sequential_e_process(sample, lower_bound=e_lower_bound, alpha=1.0 / e_threshold)
            if e_res.get("rejected_null"):
                e_passes += 1

    dsr_rate = dsr_passes / replications
    e_rate = (e_passes / replications) if e_lower_bound is not None else None
    meets = dsr_rate >= 0.80 and (e_rate is None or e_rate >= 0.80)
    return PowerSimulationResult(replications, dsr_rate, e_rate, meets)


@dataclass(frozen=True)
class PlaceboTestResult:
    observed_metric: float
    null_mean: float
    null_std: float
    p_value: float
    monte_carlo_se: float
    replications: int


def run_path_preserving_placebo(
    real_returns: list[float],
    signal_positions: list[float],
    *,
    replications: int = 500,
    seed: int = 42,
) -> PlaceboTestResult:
    """Keep real market return path intact and circularly shift signals across days (500+ replications)."""
    n = min(len(real_returns), len(signal_positions))
    if n < 5:
        raise ValueError("need >= 5 aligned observations for placebo test")
    rets = real_returns[:n]
    sigs = signal_positions[:n]
    observed = sum(r * s for r, s in zip(rets, sigs, strict=True))

    rng = random.Random(seed)
    null_vals: list[float] = []
    ge_count = 0
    for _ in range(replications):
        shift = rng.randrange(1, n)
        shifted = sigs[shift:] + sigs[:shift]
        val = sum(r * s for r, s in zip(rets, shifted, strict=True))
        null_vals.append(val)
        if val >= observed:
            ge_count += 1

    p_val = (ge_count + 1) / (replications + 1)
    mc_se = math.sqrt(p_val * (1.0 - p_val) / replications)
    mean_null = sum(null_vals) / replications
    var_null = sum((x - mean_null) ** 2 for x in null_vals) / max(1, replications - 1)
    return PlaceboTestResult(observed, mean_null, math.sqrt(var_null), p_val, mc_se, replications)


def check_causality_perturbation(
    signal_fn: Callable[[list[float]], list[float]],
    prices: list[float],
    *,
    cutoff_index: int,
    perturbation_factor: float = 1.5,
) -> bool:
    """Return True iff perturbing prices strictly after cutoff_index leaves decisions <= cutoff_index unchanged."""
    if not (0 <= cutoff_index < len(prices) - 1):
        raise ValueError("cutoff_index must leave at least one future element to perturb")
    base = signal_fn(list(prices))
    perturbed_prices = list(prices)
    for i in range(cutoff_index + 1, len(perturbed_prices)):
        perturbed_prices[i] = perturbed_prices[i] * perturbation_factor
    pert = signal_fn(perturbed_prices)
    return all(abs(base[i] - pert[i]) <= 1e-12 for i in range(cutoff_index + 1))


@dataclass(frozen=True)
class MixJournalV2Entry:
    schema: str
    as_of: str
    start_date: str
    earliest_release: str
    min_substantive_rebalances: int
    symbol: str
    intended_size_usdt: str
    displayed_depth_usdt: str
    fee_vintage: str
    missed_qty_usdt: str
    tracking_error_bps: str
    status: str                           # "RECORDED" | "SKIPPED_BAND" | "MISSING_DATA"


def build_mix_journal_v2_entry(
    *,
    as_of: datetime,
    cohort_start: datetime,
    symbol: str,
    intended_size_usdt: Decimal,
    displayed_depth_usdt: Decimal,
    fee_vintage: str,
    missed_qty_usdt: Decimal,
    tracking_error_bps: Decimal,
    status: str = "RECORDED",
    min_substantive_rebalances: int = 4,
) -> MixJournalV2Entry:
    """Create a versioned Track B v2 shortfall entry enforcing earliest_release >= cohort_start + 90d."""
    earliest = cohort_start + timedelta(days=90)
    return MixJournalV2Entry(
        schema="mix-journal-v2/1",
        as_of=as_of.isoformat(),
        start_date=cohort_start.isoformat(),
        earliest_release=earliest.isoformat(),
        min_substantive_rebalances=min_substantive_rebalances,
        symbol=symbol,
        intended_size_usdt=str(intended_size_usdt),
        displayed_depth_usdt=str(displayed_depth_usdt),
        fee_vintage=fee_vintage,
        missed_qty_usdt=str(missed_qty_usdt),
        tracking_error_bps=str(tracking_error_bps),
        status=status,
    )


@dataclass(frozen=True)
class SealedOperationalHealth:
    cohort_name: str
    as_of: datetime
    earliest_release: datetime
    mature_for_scoring: bool
    recorded_days: int
    missing_days: int
    status: str                           # "IMMATURE_AT_CHECKPOINT" | "READY_FOR_CUSTODIAN_RELEASE"


def operational_health_check_sealed_window(
    cohort_name: str,
    *,
    as_of: datetime,
    earliest_release: datetime,
    expected_days: int,
    recorded_days: int,
) -> SealedOperationalHealth:
    """Inspect only operational continuity while a forward scoring window is open (never interim PnL)."""
    mature = as_of >= earliest_release
    missing = max(0, expected_days - recorded_days)
    status = "READY_FOR_CUSTODIAN_RELEASE" if mature else "IMMATURE_AT_CHECKPOINT"
    return SealedOperationalHealth(cohort_name, as_of, earliest_release, mature, recorded_days, missing, status)
