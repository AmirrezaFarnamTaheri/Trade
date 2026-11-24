"""Convex single-period trade optimizer with L1 fee-zone & post-rounding checks (spec §4.3)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .venue_contracts import InstrumentMaster


def forecast_to_expected_return_bps(
    forecast: float,
    ic_prior: float,
    horizon_vol_bps: float,
) -> float:
    """Map continuous forecast in [-20, +20] to expected horizon gross return in bps."""
    clamped = max(-20.0, min(20.0, float(forecast)))
    return (clamped / 10.0) * float(ic_prior) * float(horizon_vol_bps)


@dataclass(frozen=True)
class OptimizationProblem:
    symbols: tuple[str, ...]
    expected_returns: tuple[float, ...]     # decimal horizon returns (e.g. 0.0020 = +20 bps)
    current_weights: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    l1_fee_costs: tuple[float, ...]         # tau_i per unit |w_i - w_i^0|
    l2_impact_costs: tuple[float, ...]      # kappa_i per unit 0.5*(w_i - w_i^0)^2
    risk_aversion: float = 2.0
    max_weight: float = 0.35
    cash_buffer: float = 0.05
    reserved_open_weight: float = 0.0
    underlying_groups: dict[str, tuple[int, ...]] | None = None
    max_underlying_weight: float = 0.40
    issuer_groups: dict[str, tuple[int, ...]] | None = None
    max_issuer_weight: float = 0.30


@dataclass(frozen=True)
class OptimizationResult:
    weights: tuple[float, ...]
    iterations: int
    kkt_residual: float
    converged: bool


def _soft_threshold(value: float, threshold: float) -> float:
    if value > threshold:
        return value - threshold
    if value < -threshold:
        return value + threshold
    return 0.0


def _upper_bound_for_index(idx: int, weights: list[float], problem: OptimizationProblem) -> float:
    max_sum = max(0.0, 1.0 - problem.cash_buffer - problem.reserved_open_weight)
    other_sum = sum(weights) - weights[idx]
    ub = min(problem.max_weight, max(0.0, max_sum - other_sum))
    if problem.underlying_groups:
        for group in problem.underlying_groups.values():
            if idx in group:
                other_g = sum(weights[j] for j in group if j != idx)
                ub = min(ub, max(0.0, problem.max_underlying_weight - other_g))
    if problem.issuer_groups:
        for group in problem.issuer_groups.values():
            if idx in group:
                other_g = sum(weights[j] for j in group if j != idx)
                ub = min(ub, max(0.0, problem.max_issuer_weight - other_g))
    return ub


def _compute_kkt_residual(weights: list[float], problem: OptimizationProblem) -> float:
    n = len(weights)
    max_res = 0.0
    for i in range(n):
        grad_smooth = (
            problem.risk_aversion * sum(problem.covariance[i][j] * weights[j] for j in range(n))
            - problem.expected_returns[i]
            + problem.l2_impact_costs[i] * (weights[i] - problem.current_weights[i])
        )
        tau = problem.l1_fee_costs[i]
        diff = weights[i] - problem.current_weights[i]
        if abs(diff) > 1e-12:
            subgrad = grad_smooth + (tau if diff > 0 else -tau)
        else:
            subgrad = _soft_threshold(grad_smooth, tau)
        ub = _upper_bound_for_index(i, weights, problem)
        if weights[i] <= 1e-12 and subgrad > 0:
            res = 0.0
        elif weights[i] >= ub - 1e-12 and subgrad < 0:
            res = 0.0
        else:
            res = abs(subgrad)
        if res > max_res:
            max_res = res
    return max_res


def solve_convex_portfolio(
    problem: OptimizationProblem,
    *,
    max_iter: int = 200,
    tol: float = 1e-7,
) -> OptimizationResult:
    """Solve single-period L1/L2 convex trade optimization via cyclical coordinate descent."""
    n = len(problem.symbols)
    if n == 0:
        return OptimizationResult((), 0, 0.0, True)
    weights = [max(0.0, min(problem.max_weight, w)) for w in problem.current_weights]
    # Project initial sum into budget if needed
    max_sum = max(0.0, 1.0 - problem.cash_buffer - problem.reserved_open_weight)
    total = sum(weights)
    if total > max_sum and total > 0:
        scale = max_sum / total
        weights = [w * scale for w in weights]

    residual = 0.0
    iters = 0
    for iters in range(1, max_iter + 1):
        for i in range(n):
            denom = problem.risk_aversion * problem.covariance[i][i] + problem.l2_impact_costs[i]
            if denom <= 1e-15:
                continue
            cross = sum(problem.covariance[i][j] * weights[j] for j in range(n) if j != i)
            w0 = problem.current_weights[i]
            # Solve min 0.5*denom*(w - w0)^2 + g0*(w - w0) + tau*|w - w0|
            g0 = problem.risk_aversion * (cross + problem.covariance[i][i] * w0) - problem.expected_returns[i]
            step = _soft_threshold(-g0, problem.l1_fee_costs[i]) / denom
            ub = _upper_bound_for_index(i, weights, problem)
            weights[i] = max(0.0, min(ub, w0 + step))
        residual = _compute_kkt_residual(weights, problem)
        if residual < tol:
            return OptimizationResult(tuple(weights), iters, residual, True)
    return OptimizationResult(tuple(weights), iters, residual, residual < tol)


@dataclass(frozen=True)
class VerifiedOrderPlan:
    symbol: str
    side: str                       # "BUY" | "SELL" | "HOLD"
    delta_qty: Decimal
    estimated_notional: Decimal
    skipped_reason: str | None = None


def verify_post_solve_orders(
    symbols: tuple[str, ...],
    target_weights: tuple[float, ...],
    current_weights: tuple[float, ...],
    equity_quote: Decimal,
    free_cash_quote: Decimal,
    prices: dict[str, Decimal],
    displayed_exit_depth_qty: dict[str, Decimal],
    instruments: dict[str, InstrumentMaster],
    taker_fee_rate: Decimal,
) -> list[VerifiedOrderPlan]:
    """Convert weights to floored Decimal lots and enforce native cash, min_notional, and displayed exit depth."""
    plans: list[VerifiedOrderPlan] = []
    remaining_cash = free_cash_quote
    for sym, tw, cw in zip(symbols, target_weights, current_weights, strict=True):
        inst = instruments[sym]
        px = prices.get(sym, Decimal(0))
        if px <= 0:
            plans.append(VerifiedOrderPlan(sym, "HOLD", Decimal(0), Decimal(0), "NO_VALID_PRICE"))
            continue
        delta_w = Decimal(str(round(tw - cw, 8)))
        if delta_w == 0:
            plans.append(VerifiedOrderPlan(sym, "HOLD", Decimal(0), Decimal(0), None))
            continue
        side = "BUY" if delta_w > 0 else "SELL"
        raw_notional = abs(delta_w) * equity_quote
        raw_qty = inst.round_qty(raw_notional / px)
        if side == "SELL":
            max_depth = displayed_exit_depth_qty.get(sym, Decimal(0))
            if max_depth <= 0:
                plans.append(VerifiedOrderPlan(sym, "HOLD", Decimal(0), Decimal(0), "INSUFFICIENT_EXIT_DEPTH"))
                continue
            raw_qty = inst.round_qty(min(raw_qty, max_depth))
        if side == "BUY":
            max_affordable = inst.round_qty(remaining_cash / (px * (Decimal(1) + taker_fee_rate)))
            raw_qty = min(raw_qty, max_affordable)
        notional = raw_qty * px
        if raw_qty < inst.min_qty or notional < inst.min_notional:
            plans.append(VerifiedOrderPlan(sym, "HOLD", Decimal(0), Decimal(0), "BELOW_MIN_LOT_OR_NOTIONAL"))
            continue
        if side == "BUY":
            remaining_cash -= notional * (Decimal(1) + taker_fee_rate)
        plans.append(VerifiedOrderPlan(sym, side, raw_qty, notional, None))
    return plans


def simple_no_trade_band_allocator(
    current_weights: tuple[float, ...],
    desired_weights: tuple[float, ...],
    *,
    band: float = 0.10,
) -> tuple[float, ...]:
    """Simple fixed-band benchmark allocator on identical forecasts."""
    return tuple(
        dw if abs(dw - cw) >= band else cw
        for cw, dw in zip(current_weights, desired_weights, strict=True)
    )
