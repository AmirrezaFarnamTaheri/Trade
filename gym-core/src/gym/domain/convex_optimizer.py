"""Convex single-period trade optimizer with exact ADMM + Dykstra projection (spec §4.3 & v2 §1)."""
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
    expected_returns: tuple[float, ...]     # decimal gross horizon returns (e.g. 0.0020 = +20 bps)
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


def portfolio_utility(weights: tuple[float, ...] | list[float], problem: OptimizationProblem) -> float:
    """Exact net utility maximized by the solver: mu^T w - 0.5*lambda*w^T Sigma w - L1 - L2."""
    n = len(weights)
    ret_term = sum(problem.expected_returns[i] * weights[i] for i in range(n))
    risk_term = 0.5 * problem.risk_aversion * sum(
        weights[i] * problem.covariance[i][j] * weights[j]
        for i in range(n)
        for j in range(n)
    )
    l1_term = sum(problem.l1_fee_costs[i] * abs(weights[i] - problem.current_weights[i]) for i in range(n))
    l2_term = 0.5 * sum(problem.l2_impact_costs[i] * (weights[i] - problem.current_weights[i]) ** 2 for i in range(n))
    return ret_term - risk_term - l1_term - l2_term


def _soft_threshold(value: float, threshold: float) -> float:
    if value > threshold:
        return value - threshold
    if value < -threshold:
        return value + threshold
    return 0.0


def _project_box_and_sum_le(vec: list[float], upper: float, max_sum: float) -> list[float]:
    """Exact Euclidean projection onto {0 <= z_i <= upper, sum(z) <= max_sum}."""
    clipped = [max(0.0, min(upper, v)) for v in vec]
    if sum(clipped) <= max_sum + 1e-15:
        return clipped
    if max_sum <= 0.0:
        return [0.0] * len(vec)
    # Find shift nu >= 0 such that sum(clip(v_i - nu, 0, upper)) == max_sum via bisection
    lo = 0.0
    hi = max(vec) if vec else 0.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        s = sum(max(0.0, min(upper, v - mid)) for v in vec)
        if s > max_sum:
            lo = mid
        else:
            hi = mid
    return [max(0.0, min(upper, v - hi)) for v in vec]


def _project_group_cap(vec: list[float], indices: tuple[int, ...], cap: float) -> list[float]:
    """Exact Euclidean projection onto halfspace sum_{i in indices} z_i <= cap."""
    s = sum(vec[i] for i in indices)
    if s <= cap + 1e-15 or not indices:
        return vec
    out = vec[:]
    shift = (s - cap) / len(indices)
    for i in indices:
        out[i] -= shift
    return out


def _project_feasible(vec: list[float], problem: OptimizationProblem) -> list[float]:
    """Dykstra's alternating projection onto box + total budget + underlying/issuer group caps."""
    max_sum = max(0.0, 1.0 - problem.cash_buffer - problem.reserved_open_weight)
    caps: list[tuple[tuple[int, ...], float]] = []
    if problem.underlying_groups:
        for grp in problem.underlying_groups.values():
            if grp:
                caps.append((grp, problem.max_underlying_weight))
    if problem.issuer_groups:
        for grp in problem.issuer_groups.values():
            if grp:
                caps.append((grp, problem.max_issuer_weight))
    if not caps:
        return _project_box_and_sum_le(vec, problem.max_weight, max_sum)

    n = len(vec)
    x = vec[:]
    n_sets = 1 + len(caps)
    increments = [[0.0] * n for _ in range(n_sets)]
    for _ in range(40):
        prev = x[:]
        # Set 0: box + total sum
        y0 = [x[i] + increments[0][i] for i in range(n)]
        x = _project_box_and_sum_le(y0, problem.max_weight, max_sum)
        increments[0] = [y0[i] - x[i] for i in range(n)]
        # Group cap halfspaces
        for idx_c, (grp, cap) in enumerate(caps, start=1):
            yc = [x[i] + increments[idx_c][i] for i in range(n)]
            x = _project_group_cap(yc, grp, cap)
            increments[idx_c] = [yc[i] - x[i] for i in range(n)]
        if max(abs(x[i] - prev[i]) for i in range(n)) < 1e-11:
            break
    return _project_box_and_sum_le(x, problem.max_weight, max_sum)


def solve_convex_portfolio(
    problem: OptimizationProblem,
    *,
    max_iter: int = 400,
    tol: float = 1e-7,
) -> OptimizationResult:
    """Solve convex L1/L2 trade optimization via ADMM splitting L1/quadratic from feasibility projection."""
    n = len(problem.symbols)
    if n == 0:
        return OptimizationResult((), 0, 0.0, True)

    diag_scale = sum(problem.risk_aversion * problem.covariance[i][i] + problem.l2_impact_costs[i] for i in range(n)) / n
    rho = max(0.05, diag_scale)

    z = _project_feasible(list(problem.current_weights), problem)
    w = z[:]
    u = [0.0] * n  # scaled dual variable

    residual = float("inf")
    iters = 0
    for iters in range(1, max_iter + 1):
        # 1. Exact unconstrained w-update via cyclical L1 coordinate descent (no binding simplex stall)
        for _ in range(6):
            for i in range(n):
                denom = problem.risk_aversion * problem.covariance[i][i] + problem.l2_impact_costs[i] + rho
                cross = sum(problem.covariance[i][j] * w[j] for j in range(n) if j != i)
                w0 = problem.current_weights[i]
                g0 = (
                    problem.risk_aversion * (cross + problem.covariance[i][i] * w0)
                    - problem.expected_returns[i]
                    + rho * (w0 - z[i] + u[i])
                )
                step = _soft_threshold(-g0, problem.l1_fee_costs[i]) / denom
                w[i] = w0 + step

        # 2. Exact Euclidean projection onto feasible set C
        z_prev = z
        z = _project_feasible([w[i] + u[i] for i in range(n)], problem)

        # 3. Dual update and primal/dual KKT residual
        for i in range(n):
            u[i] += w[i] - z[i]
        r_primal = max(abs(w[i] - z[i]) for i in range(n))
        r_dual = rho * max(abs(z[i] - z_prev[i]) for i in range(n))
        residual = max(r_primal, r_dual)
        if residual < tol:
            return OptimizationResult(tuple(z), iters, residual, True)

    return OptimizationResult(tuple(z), iters, residual, residual < tol)


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
