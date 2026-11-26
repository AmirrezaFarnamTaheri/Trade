"""Pure domain contracts and 4 competing per-moment instrument/action resolvers (v3 architecture).

Determines Spot vs. Isolated Margin (تعهدی) vs. Future Perp, Long vs. Short, Leverage (1x..5x),
and Open/Hold/Reduce/Sell/Switch/Idle-Pool dynamically at decision time t for every market/position.
Strictly pure (zero filesystem, network, or DB IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .diffusion_and_netting import SECTOR_CLUSTERS
from .venue_leverage_models import NOBITEX_MARGIN_ELIGIBLE_USDT

NOBITEX_LEVERAGE_STEPS: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
WALLEX_LEVERAGE_STEPS: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0)


@dataclass(frozen=True)
class MarketView:
    """Venue-agnostic per-market forecast at bar close ts_avail."""

    symbol: str
    ts_avail: datetime
    expected_return_bps: float  # Signed: >0 bullish, <0 bearish
    horizon_hours: float
    stop_distance_bps: float
    realized_vol_ann: float
    confidence: float  # [0, 1] calibrated rank / conviction
    regime_breadth: float
    source_tag: str = "combined"


@dataclass(frozen=True)
class InstrumentOffer:
    """Live feasible venue instrument available for a market at time t."""

    venue: str
    symbol: str
    instrument_type: str  # IDLE_POOL | SPOT | ISOLATED_MARGIN | PERP_FUTURE
    direction: int  # 1 (long), -1 (short), 0 (cash/pool)
    allowed_leverages: tuple[float, ...]
    entry_cost_bps: float
    exit_cost_bps: float
    carry_model: str  # NONE | EOD_DAILY_BORROW | INTERVAL_4H_BORROW | POOL_YIELD | FUNDING_RATE
    carry_rate_bps: float  # Per day (EOD), per 4h (Wallex), per 8h (funding), or annual bps (pool)
    maintenance_margin_rate: float = 0.10
    available_capacity_usdt: float = 100_000.0


@dataclass(frozen=True)
class PositionState:
    """Current open position for one symbol (one active instrument per symbol)."""

    symbol: str
    venue: str
    instrument_type: str
    direction: int  # 1 or -1
    leverage: float
    collateral_usdt: float
    notional_usdt: float
    entry_price: float
    stop_price: float
    liquidation_price: float
    held_hours: float
    unrealized_pnl_bps: float
    entry_ts: datetime
    horizon_hours: float = 16.0


@dataclass(frozen=True)
class ResolvedAction:
    """Per-market decision emitted by any resolver for bar close t."""

    symbol: str
    action: str  # OPEN | HOLD | REDUCE | SELL_CLOSE | FLIP | SWITCH_INSTRUMENT | PARK_POOL
    venue: str
    instrument_type: str
    direction: int
    leverage: float
    target_collateral_usdt: float
    target_notional_usdt: float
    stop_distance_bps: float
    expected_net_edge_bps: float
    rationale: str


@dataclass(frozen=True)
class ResolverConfig:
    """Risk, survival, and portfolio guardrails shared across all 4 competing resolvers."""

    max_venue_leverage: float = 5.0
    liquidation_safety_factor: float = 0.75
    worst_slippage_bps: float = 35.0
    max_trade_risk_pct: float = 0.012
    max_position_collateral_pct: float = 0.25
    max_portfolio_gross_leverage: float = 2.0
    max_sector_gross_pct: float = 0.55
    dd_throttle_start_pct: float = 3.0
    dd_spot_only_pct: float = 6.0
    idle_pool_apr: float = 0.0264
    min_open_edge_bps: float = 15.0
    min_switch_edge_gain_bps: float = 18.0
    allow_shorts: bool = True
    short_confidence_floor: float = 0.60


@dataclass(frozen=True)
class CandidateQuote:
    """Evaluated net-edge & sizing summary for one (offer, leverage) pair."""

    offer: InstrumentOffer
    leverage: float
    net_edge_bps_on_notional: float
    net_edge_bps_on_collateral: float
    utility: float
    target_collateral_usdt: float
    target_notional_usdt: float
    carry_bps: float
    effective_cost_bps: float


def build_local_venue_offers(
    symbol: str,
    *,
    nobitex_leg_bps: float = 16.0,
    wallex_leg_bps: float = 25.0,
    idle_pool_apr: float = 0.0264,
    nobitex_margin_eligible: bool | None = None,
    nobitex_pool_capacity_usdt: float = 100_000.0,
    include_wallex_margin: bool = True,
    include_perp_future: bool = False,
    perp_leg_bps: float = 5.0,
    perp_funding_8h_bps: float = 1.0,
) -> tuple[InstrumentOffer, ...]:
    """Construct live feasible local (Nobitex + Wallex) and optional future Hyperliquid Perp offers."""
    elig = (symbol in NOBITEX_MARGIN_ELIGIBLE_USDT) if nobitex_margin_eligible is None else nobitex_margin_eligible
    offers: list[InstrumentOffer] = [
        InstrumentOffer(
            venue="nobitex", symbol=symbol, instrument_type="SPOT", direction=1,
            allowed_leverages=(1.0,), entry_cost_bps=nobitex_leg_bps, exit_cost_bps=nobitex_leg_bps,
            carry_model="NONE", carry_rate_bps=0.0, maintenance_margin_rate=0.0,
        ),
        InstrumentOffer(
            venue="wallex", symbol=symbol, instrument_type="SPOT", direction=1,
            allowed_leverages=(1.0,), entry_cost_bps=wallex_leg_bps, exit_cost_bps=wallex_leg_bps,
            carry_model="NONE", carry_rate_bps=0.0, maintenance_margin_rate=0.0,
        ),
        InstrumentOffer(
            venue="nobitex", symbol="USDT", instrument_type="IDLE_POOL", direction=0,
            allowed_leverages=(1.0,), entry_cost_bps=0.0, exit_cost_bps=0.0,
            carry_model="POOL_YIELD", carry_rate_bps=idle_pool_apr * 10000.0, maintenance_margin_rate=0.0,
        ),
    ]
    if elig and nobitex_pool_capacity_usdt > 0:
        for direction in (1, -1):
            offers.append(
                InstrumentOffer(
                    venue="nobitex", symbol=symbol, instrument_type="ISOLATED_MARGIN", direction=direction,
                    allowed_leverages=NOBITEX_LEVERAGE_STEPS, entry_cost_bps=nobitex_leg_bps,
                    exit_cost_bps=nobitex_leg_bps, carry_model="EOD_DAILY_BORROW", carry_rate_bps=5.0,
                    maintenance_margin_rate=0.10, available_capacity_usdt=nobitex_pool_capacity_usdt,
                )
            )
    if include_wallex_margin:
        for direction in (1, -1):
            offers.append(
                InstrumentOffer(
                    venue="wallex", symbol=symbol, instrument_type="ISOLATED_MARGIN", direction=direction,
                    allowed_leverages=WALLEX_LEVERAGE_STEPS, entry_cost_bps=wallex_leg_bps,
                    exit_cost_bps=wallex_leg_bps, carry_model="INTERVAL_4H_BORROW", carry_rate_bps=1.5,
                    maintenance_margin_rate=0.15, available_capacity_usdt=50_000.0,
                )
            )
    if include_perp_future:
        for direction in (1, -1):
            offers.append(
                InstrumentOffer(
                    venue="hyperliquid", symbol=symbol, instrument_type="PERP_FUTURE", direction=direction,
                    allowed_leverages=NOBITEX_LEVERAGE_STEPS, entry_cost_bps=perp_leg_bps,
                    exit_cost_bps=perp_leg_bps, carry_model="FUNDING_RATE",
                    carry_rate_bps=perp_funding_8h_bps, maintenance_margin_rate=0.05,
                    available_capacity_usdt=500_000.0,
                )
            )
    return tuple(offers)


def liquidation_distance_bps(offer: InstrumentOffer, leverage: float) -> float:
    """Adverse move (in bps from entry) that triggers isolated liquidation on this offer."""
    if offer.instrument_type in {"SPOT", "IDLE_POOL"} or leverage <= 1.0:
        return 10_000.0 if offer.direction >= 0 else 8_500.0
    if offer.instrument_type == "ISOLATED_MARGIN" and offer.venue == "nobitex":
        if offer.direction > 0:
            liq_px_ratio = max(1.1 * (leverage - 1.0) / leverage, 1.0 - 0.85 / leverage)
            return max(0.0, (1.0 - liq_px_ratio) * 10_000.0)
        # Isolated short: equity / borrowed_notional <= maint -> adverse up move approx (1/L - 0.10)
        return max(0.0, ((1.0 / leverage) - offer.maintenance_margin_rate) * 10_000.0)
    return max(0.0, ((1.0 / leverage) - offer.maintenance_margin_rate) * 10_000.0)


def expected_carry_bps(
    offer: InstrumentOffer,
    leverage: float,
    horizon_hours: float,
    hours_to_utc_eod: float,
) -> float:
    """Expected holding carry (positive = cost, negative = earned yield) in bps of notional."""
    h = max(0.0, horizon_hours)
    if offer.carry_model == "NONE":
        return 0.0
    if offer.carry_model == "POOL_YIELD":
        return -(offer.carry_rate_bps * (h / 8760.0))
    if offer.carry_model == "FUNDING_RATE":
        # Positive funding rate costs longs (+1) and PAYS shorts (-1)
        periods = h / 8.0
        return offer.direction * periods * offer.carry_rate_bps

    borrowed_frac = 1.0 if offer.direction < 0 else max(0.0, (leverage - 1.0) / max(1.0, leverage))
    if borrowed_frac <= 0.0:
        return 0.0
    if offer.carry_model == "EOD_DAILY_BORROW":
        if h < max(0.0, hours_to_utc_eod):
            return 0.0  # Intraday round-trip closed before 00:00 UTC costs $0 borrow on Nobitex
        eod_crossings = 1 + int(max(0.0, h - max(0.0, hours_to_utc_eod)) // 24.0)
        return eod_crossings * offer.carry_rate_bps * borrowed_frac
    if offer.carry_model == "INTERVAL_4H_BORROW":
        blocks = max(1, math.ceil(h / 4.0))
        return blocks * offer.carry_rate_bps * borrowed_frac
    return 0.0


def dd_governor_leverage_cap(current_dd_pct: float, cfg: ResolverConfig) -> float:
    """Portfolio trailing-drawdown leverage governor: up to 5x when healthy, 1x spot-only at >=6% DD."""
    if current_dd_pct <= cfg.dd_throttle_start_pct:
        return cfg.max_venue_leverage
    if current_dd_pct >= cfg.dd_spot_only_pct:
        return 1.0
    span = max(1e-6, cfg.dd_spot_only_pct - cfg.dd_throttle_start_pct)
    frac = (current_dd_pct - cfg.dd_throttle_start_pct) / span
    mid_cap = min(cfg.max_venue_leverage, 2.5)
    return max(1.0, mid_cap * (1.0 - frac) + 1.0 * frac)


def max_liquidation_safe_leverage(
    offer: InstrumentOffer,
    stop_distance_bps: float,
    cfg: ResolverConfig,
    dd_cap_leverage: float,
) -> float:
    """Highest discrete leverage allowed on this offer with zero-liquidation stop cushion."""
    if offer.instrument_type == "SPOT":
        return 1.0
    if offer.instrument_type == "IDLE_POOL":
        return 0.0
    cap = min(cfg.max_venue_leverage, dd_cap_leverage)
    required_clearance = max(10.0, stop_distance_bps) + cfg.worst_slippage_bps
    best = 0.0
    for lev in offer.allowed_leverages:
        if lev > cap + 1e-9:
            continue
        if lev > 1.0 and offer.direction > 0 and stop_distance_bps > 900.0:
            # Wide-stop daily trends stay capped at <=1.5x even if liquidation is further
            if lev > 1.5:
                continue
        liq_bps = liquidation_distance_bps(offer, lev)
        if required_clearance <= liq_bps * cfg.liquidation_safety_factor:
            best = max(best, lev)
    return best


def _is_same_instrument(pos: PositionState | None, offer: InstrumentOffer, leverage: float) -> bool:
    if pos is None:
        return False
    return (
        pos.venue == offer.venue
        and pos.instrument_type == offer.instrument_type
        and pos.direction == offer.direction
        and abs(pos.leverage - leverage) < 0.25
    )


def score_candidate_offer(
    view: MarketView,
    offer: InstrumentOffer,
    leverage: float,
    position: PositionState | None,
    equity: float,
    hours_to_eod: float,
    cfg: ResolverConfig,
) -> CandidateQuote | None:
    """Compute net expected edge, risk-adjusted utility, and Equal Risk-to-Stop collateral."""
    if offer.instrument_type == "IDLE_POOL" or leverage <= 0.0:
        return None
    if offer.direction < 0 and (not cfg.allow_shorts or view.confidence < cfg.short_confidence_floor):
        return None
    # High leverage (>2x) strictly requires short-horizon tight-stop conviction
    if leverage > 2.0 and (view.horizon_hours > 36.0 or view.confidence < 0.72):
        return None
    if leverage > 3.5 and (view.horizon_hours > 24.0 or view.confidence < 0.85):
        return None

    directional_edge_bps = offer.direction * view.expected_return_bps
    if directional_edge_bps <= 0.0:
        return None

    carry_bps = expected_carry_bps(offer, leverage, view.horizon_hours, hours_to_eod)
    pool_opp_bps_on_col = (cfg.idle_pool_apr * 10_000.0) * (max(1.0, view.horizon_hours) / 8760.0)
    pool_opp_bps_on_notional = pool_opp_bps_on_col / leverage

    same_pos = _is_same_instrument(position, offer, leverage)
    if same_pos:
        txn_bps = 0.0
    elif position is not None:
        txn_bps = offer.entry_cost_bps + offer.exit_cost_bps + cfg.min_switch_edge_gain_bps
    else:
        txn_bps = offer.entry_cost_bps + offer.exit_cost_bps

    net_notional_bps = directional_edge_bps - txn_bps - carry_bps - pool_opp_bps_on_notional
    net_col_bps = net_notional_bps * leverage

    # Equal Risk-to-Stop sizing: collateral * L * stop_dist <= max_trade_risk_pct * equity
    stop_frac = max(0.01, (view.stop_distance_bps + cfg.worst_slippage_bps) / 10_000.0)
    max_notional_by_risk = (cfg.max_trade_risk_pct * equity) / stop_frac
    max_col_by_cap = cfg.max_position_collateral_pct * equity
    max_col_by_liq = offer.available_capacity_usdt / max(1.0, leverage)
    # Conviction scaling [0.35..1.0]
    conv_scale = 0.35 + 0.65 * max(0.0, min(1.0, view.confidence))
    tgt_col = min(max_col_by_cap, max_notional_by_risk / leverage, max_col_by_liq) * conv_scale
    tgt_notional = tgt_col * leverage
    if tgt_col < 5.0:
        return None

    # Risk-adjusted utility (variance penalty scales with L^2 * vol^2 * horizon)
    horizon_yr = max(1.0, view.horizon_hours) / 8760.0
    vol_bps = max(50.0, view.realized_vol_ann * 10_000.0 * math.sqrt(horizon_yr))
    risk_pen = 0.35 * ((leverage * vol_bps) ** 2) / 10_000.0
    utility = net_col_bps - risk_pen
    return CandidateQuote(
        offer=offer,
        leverage=leverage,
        net_edge_bps_on_notional=net_notional_bps,
        net_edge_bps_on_collateral=net_col_bps,
        utility=utility,
        target_collateral_usdt=tgt_col,
        target_notional_usdt=tgt_notional,
        carry_bps=carry_bps,
        effective_cost_bps=txn_bps + carry_bps + pool_opp_bps_on_notional,
    )


def best_candidate_for_market(
    view: MarketView,
    offers: tuple[InstrumentOffer, ...],
    position: PositionState | None,
    equity: float,
    hours_to_eod: float,
    current_dd_pct: float,
    cfg: ResolverConfig,
    *,
    direction_filter: int | None = None,
) -> CandidateQuote | None:
    """Evaluate every feasible (offer, leverage) for one market and return the highest-utility choice."""
    dd_cap = dd_governor_leverage_cap(current_dd_pct, cfg)
    best: CandidateQuote | None = None
    for offer in offers:
        if offer.instrument_type == "IDLE_POOL":
            continue
        if direction_filter is not None and offer.direction != direction_filter:
            continue
        max_lev = max_liquidation_safe_leverage(offer, view.stop_distance_bps, cfg, dd_cap)
        if max_lev <= 0.0:
            continue
        for lev in offer.allowed_leverages:
            if lev > max_lev + 1e-9:
                continue
            cand = score_candidate_offer(view, offer, lev, position, equity, hours_to_eod, cfg)
            if cand is None:
                continue
            if best is None or cand.utility > best.utility:
                best = cand
    return best


def _action_label(position: PositionState | None, cand: CandidateQuote | None) -> str:
    if cand is None:
        return "SELL_CLOSE" if position is not None else "PARK_POOL"
    if position is None:
        return "OPEN"
    if position.direction != cand.offer.direction:
        return "FLIP"
    if _is_same_instrument(position, cand.offer, cand.leverage):
        if cand.target_notional_usdt < position.notional_usdt * 0.85:
            return "REDUCE"
        return "HOLD"
    return "SWITCH_INSTRUMENT"


def _scale_collateral_budget(
    chosen: dict[str, CandidateQuote],
    equity: float,
    cfg: ResolverConfig,
) -> dict[str, tuple[float, float]]:
    """Enforce total collateral <= 0.95*equity, portfolio gross leverage cap, and 55% sector caps."""
    if not chosen or equity <= 0:
        return {}
    cols = {s: c.target_collateral_usdt for s, c in chosen.items()}
    nots = {s: c.target_notional_usdt for s, c in chosen.items()}

    # Sector gross cap
    for members in SECTOR_CLUSTERS.values():
        grp_syms = [s for s in members if s in nots]
        if len(grp_syms) < 2:
            continue
        grp_not = sum(nots[s] for s in grp_syms)
        cap_not = cfg.max_sector_gross_pct * equity * max(1.0, cfg.max_portfolio_gross_leverage * 0.65)
        if grp_not > cap_not > 0:
            sc = cap_not / grp_not
            for s in grp_syms:
                cols[s] *= sc
                nots[s] *= sc

    tot_col = sum(cols.values())
    if tot_col > 0.95 * equity:
        sc = (0.95 * equity) / tot_col
        for s in cols:
            cols[s] *= sc
            nots[s] *= sc

    tot_not = sum(nots.values())
    max_gross = cfg.max_portfolio_gross_leverage * equity
    if tot_not > max_gross > 0:
        sc = max_gross / tot_not
        for s in cols:
            cols[s] *= sc
            nots[s] *= sc
    return {s: (cols[s], nots[s]) for s in chosen}


def _should_hold_active_horizon(
    pos: PositionState | None,
    view: MarketView | None,
    cfg: ResolverConfig,
) -> bool:
    """Prevent premature 2h churn closes while an open position is still inside its declared horizon."""
    if pos is None or pos.held_hours >= pos.horizon_hours:
        return False
    if view is None:
        return True
    # Exit early only if a clear opposing directional view exceeds the switching hurdle
    return (view.expected_return_bps * pos.direction) >= -cfg.min_switch_edge_gain_bps


def _hold_action_for(pos: PositionState, tag: str) -> ResolvedAction:
    return ResolvedAction(
        symbol=pos.symbol, action="HOLD", venue=pos.venue,
        instrument_type=pos.instrument_type, direction=pos.direction,
        leverage=pos.leverage, target_collateral_usdt=pos.collateral_usdt,
        target_notional_usdt=pos.notional_usdt, stop_distance_bps=0.0,
        expected_net_edge_bps=0.0, rationale=f"{tag}:hold_within_horizon",
    )


def resolve_a1_utility(
    views: dict[str, MarketView],
    offers_by_sym: dict[str, tuple[InstrumentOffer, ...]],
    positions: dict[str, PositionState],
    equity: float,
    hours_to_eod: float,
    current_dd_pct: float,
    cfg: ResolverConfig,
) -> dict[str, ResolvedAction]:
    """Approach 1: Pure Two-Stage MarketView -> Per-Moment Utility Solver."""
    chosen: dict[str, CandidateQuote] = {}
    forced_holds: dict[str, ResolvedAction] = {}
    all_syms = sorted(set(views) | set(positions))
    for sym in all_syms:
        view = views.get(sym)
        pos = positions.get(sym)
        if _should_hold_active_horizon(pos, view, cfg):
            forced_holds[sym] = _hold_action_for(pos, "a1_utility")
            continue
        if view is None:
            continue
        cand = best_candidate_for_market(
            view, offers_by_sym.get(sym, ()), pos, equity, hours_to_eod, current_dd_pct, cfg,
        )
        min_req = 0.0 if (cand and _is_same_instrument(pos, cand.offer, cand.leverage)) else cfg.min_open_edge_bps
        if cand is not None and cand.net_edge_bps_on_notional >= min_req and cand.utility > 0.0:
            chosen[sym] = cand

    scaled = _scale_collateral_budget(chosen, equity, cfg)
    actions = _emit_actions(tuple(all_syms), views, positions, chosen, scaled, "a1_utility")
    actions.update(forced_holds)
    return actions


def _solve_signed_box_qp(
    symbols: tuple[str, ...],
    mu_bps: dict[str, float],
    cost_bps: dict[str, float],
    cur_w: dict[str, float],
    lb: dict[str, float],
    ub: dict[str, float],
    cov: dict[tuple[str, str], float],
    gross_cap: float,
    risk_aversion: float = 2.6,
) -> dict[str, float]:
    """Coordinate-descent signed box QP with L1 turnover fee-zone and gross leverage projection."""
    w = {s: max(lb[s], min(ub[s], cur_w.get(s, 0.0))) for s in symbols}
    for _ in range(18):
        for sym in symbols:
            var = max(1e-5, cov.get((sym, sym), 0.0025))
            denom = 2.0 * risk_aversion * var
            cross = sum(cov.get((sym, other), 0.0) * w[other] for other in symbols if other != sym)
            lin = (mu_bps[sym] / 10_000.0) - 2.0 * risk_aversion * cross
            fee = cost_bps[sym] / 10_000.0
            c0 = cur_w.get(sym, 0.0)
            # Soft-thresholding around c0 for L1 turnover penalty
            raw_up = (lin - fee) / denom
            raw_dn = (lin + fee) / denom
            if raw_up > c0:
                val = raw_up
            elif raw_dn < c0:
                val = raw_dn
            else:
                val = c0
            w[sym] = max(lb[sym], min(ub[sym], val))
        gross = sum(abs(v) for v in w.values())
        if gross > gross_cap > 0:
            sc = gross_cap / gross
            w = {s: v * sc for s, v in w.items()}
    return {s: (0.0 if abs(v) < 0.02 else v) for s, v in w.items()}


def resolve_a2_signed_admm(
    views: dict[str, MarketView],
    offers_by_sym: dict[str, tuple[InstrumentOffer, ...]],
    positions: dict[str, PositionState],
    equity: float,
    hours_to_eod: float,
    current_dd_pct: float,
    cov: dict[tuple[str, str], float],
    cfg: ResolverConfig,
) -> dict[str, ResolvedAction]:
    """Approach 2: Signed continuous portfolio QP first, then post-solve cheapest-instrument router."""
    all_syms = tuple(sorted(set(views) | set(positions)))
    dd_cap = dd_governor_leverage_cap(current_dd_pct, cfg)
    cur_w = {
        s: (positions[s].direction * positions[s].notional_usdt / max(1.0, equity)) if s in positions else 0.0
        for s in all_syms
    }
    mu_bps, cost_bps, lb, ub = {}, {}, {}, {}
    for sym in all_syms:
        v = views.get(sym)
        if v is None:
            mu_bps[sym], cost_bps[sym], lb[sym], ub[sym] = 0.0, 20.0, 0.0, 0.0
            continue
        mu_bps[sym] = v.expected_return_bps
        cost_bps[sym] = 32.0
        max_w_pos = min(cfg.max_position_collateral_pct * min(dd_cap, 2.5), 0.50)
        ub[sym] = max_w_pos
        lb[sym] = -max_w_pos if (cfg.allow_shorts and v.confidence >= cfg.short_confidence_floor) else 0.0

    gross_cap = min(cfg.max_portfolio_gross_leverage, max(1.0, dd_cap * 0.75))
    target_w = _solve_signed_box_qp(all_syms, mu_bps, cost_bps, cur_w, lb, ub, cov, gross_cap)

    chosen: dict[str, CandidateQuote] = {}
    for sym in all_syms:
        tw = target_w.get(sym, 0.0)
        v = views.get(sym)
        if abs(tw) < 0.02 or v is None:
            continue
        direction = 1 if tw > 0 else -1
        cand = best_candidate_for_market(
            v, offers_by_sym.get(sym, ()), positions.get(sym), equity, hours_to_eod, current_dd_pct, cfg,
            direction_filter=direction,
        )
        if cand is None or cand.net_edge_bps_on_notional < 0.0:
            continue
        desired_notional = min(abs(tw) * equity, cand.target_notional_usdt)
        desired_col = desired_notional / max(1.0, cand.leverage)
        if desired_col >= 5.0:
            chosen[sym] = CandidateQuote(
                offer=cand.offer, leverage=cand.leverage,
                net_edge_bps_on_notional=cand.net_edge_bps_on_notional,
                net_edge_bps_on_collateral=cand.net_edge_bps_on_collateral,
                utility=cand.utility, target_collateral_usdt=desired_col,
                target_notional_usdt=desired_notional, carry_bps=cand.carry_bps,
                effective_cost_bps=cand.effective_cost_bps,
            )

    scaled = _scale_collateral_budget(chosen, equity, cfg)
    actions = _emit_actions(all_syms, views, positions, chosen, scaled, "a2_signed_admm")
    for sym, pos in positions.items():
        if _should_hold_active_horizon(pos, views.get(sym), cfg) and actions[sym].action in {"SELL_CLOSE", "PARK_POOL"}:
            actions[sym] = _hold_action_for(pos, "a2_signed_admm")
    return actions


def resolve_a3_state_machine(
    views: dict[str, MarketView],
    offers_by_sym: dict[str, tuple[InstrumentOffer, ...]],
    positions: dict[str, PositionState],
    equity: float,
    hours_to_eod: float,
    current_dd_pct: float,
    cfg: ResolverConfig,
) -> dict[str, ResolvedAction]:
    """Approach 3: Explicit discrete per-position state machine with conformal/ATR leverage tiers."""
    all_syms = tuple(sorted(set(views) | set(positions)))
    dd_cap = dd_governor_leverage_cap(current_dd_pct, cfg)
    chosen: dict[str, CandidateQuote] = {}
    for sym in all_syms:
        v = views.get(sym)
        pos = positions.get(sym)
        if v is None:
            continue
        direction = 1 if v.expected_return_bps >= 0 else -1
        if direction < 0 and (not cfg.allow_shorts or v.confidence < cfg.short_confidence_floor):
            continue
        # Discrete tier ladder based on confidence + horizon + stop tightness
        if v.confidence >= 0.88 and v.horizon_hours <= 24.0 and v.stop_distance_bps <= 550.0:
            tier_lev = min(5.0, dd_cap)
        elif v.confidence >= 0.76 and v.horizon_hours <= 36.0 and v.stop_distance_bps <= 700.0:
            tier_lev = min(3.0, dd_cap)
        elif v.confidence >= 0.62 and v.horizon_hours <= 48.0:
            tier_lev = min(2.0, dd_cap)
        else:
            tier_lev = 1.0

        # Pick cheapest eligible offer matching direction & tier_lev
        best_c: CandidateQuote | None = None
        for offer in offers_by_sym.get(sym, ()):
            if offer.direction != direction:
                continue
            safe_l = max_liquidation_safe_leverage(offer, v.stop_distance_bps, cfg, min(dd_cap, tier_lev))
            if safe_l <= 0.0:
                continue
            cand = score_candidate_offer(v, offer, safe_l, pos, equity, hours_to_eod, cfg)
            if cand is None:
                continue
            # Explicit hysteresis: staying in current state needs > 0 net edge; entering/switching needs >= 25 bps
            hurdle = 0.0 if _is_same_instrument(pos, offer, safe_l) else max(25.0, cfg.min_open_edge_bps)
            if cand.net_edge_bps_on_notional >= hurdle and (best_c is None or cand.utility > best_c.utility):
                best_c = cand
        if best_c is not None:
            chosen[sym] = best_c

    scaled = _scale_collateral_budget(chosen, equity, cfg)
    actions = _emit_actions(all_syms, views, positions, chosen, scaled, "a3_state_machine")
    for sym, pos in positions.items():
        if _should_hold_active_horizon(pos, views.get(sym), cfg) and actions[sym].action in {"SELL_CLOSE", "PARK_POOL"}:
            actions[sym] = _hold_action_for(pos, "a3_state_machine")
    return actions


def resolve_h12_hybrid(
    views: dict[str, MarketView],
    offers_by_sym: dict[str, tuple[InstrumentOffer, ...]],
    positions: dict[str, PositionState],
    equity: float,
    hours_to_eod: float,
    current_dd_pct: float,
    cov: dict[tuple[str, str], float],
    cfg: ResolverConfig,
) -> dict[str, ResolvedAction]:
    """Hybrid (A1 + A2 + A3): Per-moment instrument pre-pricing -> instrument-aware signed QP -> anti-churn guard."""
    all_syms = tuple(sorted(set(views) | set(positions)))
    dd_cap = dd_governor_leverage_cap(current_dd_pct, cfg)
    cur_w = {
        s: (positions[s].direction * positions[s].notional_usdt / max(1.0, equity)) if s in positions else 0.0
        for s in all_syms
    }

    # Step 1: Pre-price best live instrument per symbol & direction (A1 physics)
    pre_priced: dict[tuple[str, int], CandidateQuote] = {}
    mu_eff, cost_eff, lb, ub = {}, {}, {}, {}
    for sym in all_syms:
        v = views.get(sym)
        pos = positions.get(sym)
        if v is None:
            mu_eff[sym], cost_eff[sym], lb[sym], ub[sym] = 0.0, 25.0, 0.0, 0.0
            continue
        offers = offers_by_sym.get(sym, ())
        long_c = best_candidate_for_market(v, offers, pos, equity, hours_to_eod, current_dd_pct, cfg, direction_filter=1)
        short_c = best_candidate_for_market(v, offers, pos, equity, hours_to_eod, current_dd_pct, cfg, direction_filter=-1)
        if long_c is not None:
            pre_priced[(sym, 1)] = long_c
        if short_c is not None:
            pre_priced[(sym, -1)] = short_c

        ub[sym] = (long_c.target_notional_usdt / max(1.0, equity)) if long_c else 0.0
        lb[sym] = -(short_c.target_notional_usdt / max(1.0, equity)) if short_c else 0.0
        dom = long_c if (long_c and (not short_c or long_c.utility >= short_c.utility)) else short_c
        if dom is not None:
            # Feed live instrument-adjusted net edge & effective carry+cost hurdle into QP
            mu_eff[sym] = dom.offer.direction * max(0.0, dom.net_edge_bps_on_notional + dom.effective_cost_bps)
            cost_eff[sym] = max(10.0, dom.effective_cost_bps)
        else:
            mu_eff[sym], cost_eff[sym] = 0.0, 40.0

    # Step 2: Joint covariance-aware signed QP with live per-market bounds & costs (A2)
    gross_cap = min(cfg.max_portfolio_gross_leverage, max(1.0, dd_cap * 0.85))
    target_w = _solve_signed_box_qp(all_syms, mu_eff, cost_eff, cur_w, lb, ub, cov, gross_cap)

    # Step 3: Anti-churn hysteresis & final instrument assignment (A3)
    chosen: dict[str, CandidateQuote] = {}
    for sym in all_syms:
        tw = target_w.get(sym, 0.0)
        pos = positions.get(sym)
        if abs(tw) < 0.02:
            continue
        direction = 1 if tw > 0 else -1
        cand = pre_priced.get((sym, direction))
        if cand is None:
            continue
        hurdle = 0.0 if _is_same_instrument(pos, cand.offer, cand.leverage) else cfg.min_open_edge_bps
        if cand.net_edge_bps_on_notional < hurdle:
            continue
        notional = min(abs(tw) * equity, cand.target_notional_usdt)
        col = notional / max(1.0, cand.leverage)
        if col >= 5.0:
            chosen[sym] = CandidateQuote(
                offer=cand.offer, leverage=cand.leverage,
                net_edge_bps_on_notional=cand.net_edge_bps_on_notional,
                net_edge_bps_on_collateral=cand.net_edge_bps_on_collateral,
                utility=cand.utility, target_collateral_usdt=col,
                target_notional_usdt=notional, carry_bps=cand.carry_bps,
                effective_cost_bps=cand.effective_cost_bps,
            )

    scaled = _scale_collateral_budget(chosen, equity, cfg)
    actions = _emit_actions(all_syms, views, positions, chosen, scaled, "h12_hybrid")
    for sym, pos in positions.items():
        if _should_hold_active_horizon(pos, views.get(sym), cfg) and actions[sym].action in {"SELL_CLOSE", "PARK_POOL"}:
            actions[sym] = _hold_action_for(pos, "h12_hybrid")
    return actions


def _emit_actions(
    all_syms: tuple[str, ...],
    views: dict[str, MarketView],
    positions: dict[str, PositionState],
    chosen: dict[str, CandidateQuote],
    scaled: dict[str, tuple[float, float]],
    tag: str,
) -> dict[str, ResolvedAction]:
    actions: dict[str, ResolvedAction] = {}
    for sym in all_syms:
        pos = positions.get(sym)
        cand = chosen.get(sym)
        view = views.get(sym)
        if cand is None or sym not in scaled:
            actions[sym] = ResolvedAction(
                symbol=sym, action=_action_label(pos, None), venue="nobitex",
                instrument_type="IDLE_POOL", direction=0, leverage=1.0,
                target_collateral_usdt=0.0, target_notional_usdt=0.0,
                stop_distance_bps=0.0, expected_net_edge_bps=0.0,
                rationale=f"{tag}:park_usdt_pool",
            )
            continue
        col, notional = scaled[sym]
        actions[sym] = ResolvedAction(
            symbol=sym, action=_action_label(pos, cand), venue=cand.offer.venue,
            instrument_type=cand.offer.instrument_type, direction=cand.offer.direction,
            leverage=cand.leverage, target_collateral_usdt=col, target_notional_usdt=notional,
            stop_distance_bps=view.stop_distance_bps if view else 0.0,
            expected_net_edge_bps=cand.net_edge_bps_on_notional,
            rationale=f"{tag}:{cand.offer.venue}:{cand.offer.instrument_type}:{cand.leverage:.1f}x",
        )
    return actions
