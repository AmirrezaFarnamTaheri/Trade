"""Inventory-skewed quoting & calendar-aware fail-closed kill-switches (spec §5.5)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from .venue_contracts import NavReference

NY_TZ = ZoneInfo("America/New_York")

# Observed NYSE full-day holidays and 13:00 ET early closes for 2026-2027
NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
        date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
        date(2027, 11, 25), date(2027, 12, 24),
    }
)
NYSE_EARLY_CLOSES: frozenset[date] = frozenset(
    {
        date(2026, 11, 27), date(2026, 12, 24),
        date(2027, 11, 26),
    }
)


def is_nyse_core_session_open(at_utc: datetime) -> bool:
    """Evaluate NYSE core trading hours handling EDT/EST DST, holidays & 13:00 ET early closes."""
    local = at_utc.astimezone(NY_TZ)
    d = local.date()
    if d.weekday() >= 5 or d in NYSE_HOLIDAYS:
        return False
    t = local.time()
    close_t = time(13, 0) if d in NYSE_EARLY_CLOSES else time(16, 0)
    return time(9, 30) <= t < close_t


@dataclass(frozen=True)
class QuotePair:
    bid_price: Decimal | None
    ask_price: Decimal | None
    reservation_price: Decimal
    inventory_capped_buy: bool


class FixedOffsetQuotingPolicy:
    """Baseline control: one fixed offset delta_0 (bps) and one hard inventory cap w_max."""

    def __init__(self, offset_bps: Decimal, max_inventory_weight: Decimal) -> None:
        if offset_bps < 0 or not (Decimal(0) < max_inventory_weight <= Decimal(1)):
            raise ValueError("offset_bps >= 0 and max_inventory_weight in (0, 1] required")
        self.offset_bps = offset_bps
        self.max_inventory_weight = max_inventory_weight

    def quote(self, microprice: Decimal, inventory_weight: Decimal) -> QuotePair:
        mult = self.offset_bps / Decimal(10000)
        capped = inventory_weight >= self.max_inventory_weight
        bid = None if capped else microprice * (Decimal(1) - mult)
        ask = microprice * (Decimal(1) + mult) if inventory_weight > 0 else None
        return QuotePair(bid, ask, microprice, capped)


class AvellanedaStoikovQuotingPolicy:
    """Reservation-skewed quoting: r_t = P_micro * (1 - gamma * q_t * sigma^2 * tau)."""

    def __init__(
        self,
        base_offset_bps: Decimal,
        max_inventory_weight: Decimal,
        risk_aversion_gamma: Decimal = Decimal("1.0"),
    ) -> None:
        self.base_offset_bps = base_offset_bps
        self.max_inventory_weight = max_inventory_weight
        self.gamma = risk_aversion_gamma

    def quote(
        self,
        microprice: Decimal,
        inventory_weight: Decimal,
        sigma_horizon: Decimal,
        tau_fraction: Decimal = Decimal("1"),
    ) -> QuotePair:
        skew = self.gamma * inventory_weight * sigma_horizon * sigma_horizon * tau_fraction
        reservation = microprice * (Decimal(1) - skew)
        mult = self.base_offset_bps / Decimal(10000)
        capped = inventory_weight >= self.max_inventory_weight
        bid = None if capped else reservation * (Decimal(1) - mult)
        ask = reservation * (Decimal(1) + mult) if inventory_weight > 0 else None
        return QuotePair(bid, ask, reservation, capped)


@dataclass(frozen=True)
class KillSwitchState:
    as_of: datetime
    quote_age_s: float
    shard_connected: bool
    uncertain_cancel_active: bool
    usdttmn_spread_bps: Decimal | None = None
    pair_spread_bps: Decimal | None = None
    median_7d_spread_bps: Decimal | None = None
    vpin: float | None = None
    token_mid_quote: Decimal | None = None
    nav_reference: NavReference | None = None


@dataclass(frozen=True)
class KillSwitchDecision:
    halted: bool
    reasons: tuple[str, ...]


class KillSwitchEvaluator:
    """Hard fail-closed circuit breakers (spec §5.5)."""

    def __init__(
        self,
        *,
        max_quote_age_s: float = 10.0,
        max_usdttmn_spread_bps: Decimal = Decimal("100"),
        min_pair_spread_cap_bps: Decimal = Decimal("150"),
        pair_spread_median_mult: Decimal = Decimal("3.0"),
        max_vpin: float = 0.85,
        max_rwa_nav_deviation: Decimal = Decimal("0.015"),
    ) -> None:
        self.max_quote_age_s = max_quote_age_s
        self.max_usdttmn_spread_bps = max_usdttmn_spread_bps
        self.min_pair_spread_cap_bps = min_pair_spread_cap_bps
        self.pair_spread_median_mult = pair_spread_median_mult
        self.max_vpin = max_vpin
        self.max_rwa_nav_deviation = max_rwa_nav_deviation

    def evaluate(self, state: KillSwitchState) -> KillSwitchDecision:
        reasons: list[str] = []
        if not state.shard_connected:
            reasons.append("SHARD_DISCONNECTED")
        if state.uncertain_cancel_active:
            reasons.append("UNCERTAIN_CANCEL_ACTIVE")
        if state.quote_age_s > self.max_quote_age_s:
            reasons.append("STALE_QUOTE")
        if state.usdttmn_spread_bps is not None and state.usdttmn_spread_bps > self.max_usdttmn_spread_bps:
            reasons.append("USDTTMN_WIDE_SPREAD")
        if state.pair_spread_bps is not None:
            med = state.median_7d_spread_bps or Decimal(0)
            cap = max(self.min_pair_spread_cap_bps, self.pair_spread_median_mult * med)
            if state.pair_spread_bps > cap:
                reasons.append("PAIR_WIDE_SPREAD")
        if state.vpin is not None and state.vpin > self.max_vpin:
            reasons.append("VPIN_TOXICITY_SPIKE")
        if state.nav_reference is not None:
            nav = state.nav_reference
            if not nav.session_open or not is_nyse_core_session_open(state.as_of.astimezone(UTC)):
                reasons.append("RWA_SESSION_CLOSED")
            elif state.token_mid_quote is not None:
                fair = nav.fair_quote_price()
                if fair <= 0 or abs(state.token_mid_quote - fair) / fair > self.max_rwa_nav_deviation:
                    reasons.append("RWA_NAV_DEVIATION")
        return KillSwitchDecision(halted=bool(reasons), reasons=tuple(reasons))
