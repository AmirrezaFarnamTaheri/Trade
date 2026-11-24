"""Phase B Nobitex spot book adapter & pre-funded multi-venue arb accounting (spec §8.1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..domain.model import CurrencyUnit, dec
from ..domain.venue_contracts import FeeSchedule, FeeTier, QuoteSnapshot

NOBITEX_STATS_URL = "https://apiv2.nobitex.ir/market/stats"
NOBITEX_ORDERBOOK_URL = "https://apiv2.nobitex.ir/v3/orderbook/{symbol}"

NOBITEX_RIAL = CurrencyUnit(
    code="RLS",
    unit_epoch=1,
    rials_per_unit=1,
    effective_from="2020-01-01T00:00:00Z",
    evidence="Nobitex quotes IRT/RLS spot books in Iranian Rials (1 TMN = 10 RLS)",
)
RIALS_PER_TOMAN = Decimal("10")


def nobitex_fee_schedule(
    quote_asset: str,
    *,
    permanent_discount: Decimal = Decimal("0"),
    observed_at: datetime | None = None,
    source: str = "NOBITEX_L1_PUBLISHED",
) -> FeeSchedule:
    """Build Nobitex L1 FeeSchedule (7.0/9.1 bps USDT & 14.0/17.5 bps IRT with verified -30% discount)."""
    q = quote_asset.upper()
    if q == "USDT":
        tier = FeeTier("L1", None, Decimal("0.0010"), Decimal("0.0013"))
    elif q in ("TMN", "IRT", "RLS"):
        q = "TMN"
        tier = FeeTier("L1", None, Decimal("0.0020"), Decimal("0.0025"))
    else:
        raise ValueError(f"unsupported Nobitex quote asset: {quote_asset!r}")
    return FeeSchedule(
        venue="nobitex",
        venue_kind="SPOT_BOOK",
        quote_asset=q,
        tiers=(tier,),
        permanent_discount=permanent_discount,
        discount_expires_at=None,
        fee_in_received_asset=True,
        observed_at=observed_at or datetime.now(UTC),
        source=source,
    )


def parse_nobitex_orderbook(
    symbol: str,
    payload: dict,
    ts_avail: datetime,
    *,
    convert_rls_to_tmn: bool = True,
) -> QuoteSnapshot | None:
    """Parse Nobitex /v3/orderbook/{SYMBOL} payload into a venue-agnostic QuoteSnapshot."""
    raw_bids = payload.get("bids") or []
    raw_asks = payload.get("asks") or []
    if not raw_bids or not raw_asks:
        return None
    scale = RIALS_PER_TOMAN if (convert_rls_to_tmn and symbol.upper().endswith("IRT")) else Decimal(1)
    bids = tuple((dec(px) / scale, dec(qty)) for px, qty in raw_bids if dec(px) > 0 and dec(qty) > 0)
    asks = tuple((dec(px) / scale, dec(qty)) for px, qty in raw_asks if dec(px) > 0 and dec(qty) > 0)
    if not bids or not asks:
        return None
    bids_sorted = tuple(sorted(bids, key=lambda x: x[0], reverse=True))
    asks_sorted = tuple(sorted(asks, key=lambda x: x[0]))
    norm_sym = symbol.upper().replace("IRT", "TMN") if convert_rls_to_tmn and symbol.upper().endswith("IRT") else symbol.upper()
    return QuoteSnapshot(
        venue="nobitex",
        symbol=norm_sym,
        ts_event=None,
        ts_avail=ts_avail,
        bid=bids_sorted[0][0],
        ask=asks_sorted[0][0],
        bid_qty=bids_sorted[0][1],
        ask_qty=asks_sorted[0][1],
        bid_levels=bids_sorted,
        ask_levels=asks_sorted,
        flags=frozenset(),
    )


@dataclass(frozen=True)
class PreFundedArbCapitalDayReport:
    gross_edge_usdt: Decimal
    trading_fees_usdt: Decimal
    replenishment_cost_usdt: Decimal
    second_leg_residual_cost_usdt: Decimal
    net_proceeds_usdt: Decimal
    capital_days_locked: Decimal
    net_usdt_per_capital_day: Decimal


def evaluate_prefunded_arb_capital_day(
    *,
    buy_venue_ask: Decimal,
    sell_venue_bid: Decimal,
    leg1_filled_qty: Decimal,
    leg2_filled_qty: Decimal,
    buy_fee_rate: Decimal,
    sell_fee_rate: Decimal,
    replenishment_transfer_fee_usdt: Decimal,
    residual_unwind_slippage_bps: Decimal,
    total_prefunded_capital_usdt: Decimal,
    cycle_days: Decimal,
) -> PreFundedArbCapitalDayReport:
    """Round-trip pre-funded arb accounting charging replenishment, partial second-leg residual & capital-days."""
    if total_prefunded_capital_usdt <= 0 or cycle_days <= 0:
        raise ValueError("total_prefunded_capital_usdt and cycle_days must be > 0")
    matched = min(leg1_filled_qty, leg2_filled_qty)
    residual = abs(leg1_filled_qty - leg2_filled_qty)
    gross = matched * (sell_venue_bid - buy_venue_ask)
    fees = matched * buy_venue_ask * buy_fee_rate + matched * sell_venue_bid * sell_fee_rate
    mid = (buy_venue_ask + sell_venue_bid) / Decimal(2)
    residual_cost = residual * mid * (residual_unwind_slippage_bps / Decimal(10000) + sell_fee_rate)
    net = gross - fees - replenishment_transfer_fee_usdt - residual_cost
    cap_days = total_prefunded_capital_usdt * cycle_days
    return PreFundedArbCapitalDayReport(
        gross_edge_usdt=gross,
        trading_fees_usdt=fees,
        replenishment_cost_usdt=replenishment_transfer_fee_usdt,
        second_leg_residual_cost_usdt=residual_cost,
        net_proceeds_usdt=net,
        capital_days_locked=cap_days,
        net_usdt_per_capital_day=net / cap_days,
    )
