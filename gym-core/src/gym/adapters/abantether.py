"""Phase B AbanTether OTC RWA adapter, InstrumentMaster catalog & 5 hardcoded guards (spec §8.2)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..domain.quoting_policy import is_nyse_core_session_open
from ..domain.venue_contracts import (
    FeeSchedule,
    FeeTier,
    InstrumentMaster,
    NavReference,
)

ZERO_VOLUME_EXCLUDED: frozenset[str] = frozenset({"NFLXON", "SKHYB"})
LEVERAGED_3X_EXCLUDED: frozenset[str] = frozenset({"TQQQB", "SOXLB", "KORUB", "MUUB"})


def abantether_otc_fee_schedule(
    quote_asset: str = "USDT",
    *,
    observed_at: datetime | None = None,
) -> FeeSchedule:
    """OTC quote schedule: 0% separate commission because the 0.558% round-trip spread is embedded in buy/sell quotes."""
    return FeeSchedule(
        venue="abantether",
        venue_kind="OTC_QUOTE",
        quote_asset=quote_asset.upper(),
        tiers=(FeeTier("OTC", None, Decimal("0"), Decimal("0")),),
        permanent_discount=Decimal("0"),
        discount_expires_at=None,
        fee_in_received_asset=False,
        observed_at=observed_at or datetime.now(UTC),
        source="ABANTETHER_OTC_EMBEDDED_SPREAD",
    )


def _rwa_instrument(symbol: str, underlying_id: str, issuer: str, product_kind: str) -> InstrumentMaster:
    return InstrumentMaster(
        venue="abantether",
        symbol=symbol,
        underlying_id=underlying_id,
        issuer=issuer,
        product_kind=product_kind,
        trading_calendar="NYSE_CORE",
        price_decimals=4,
        qty_decimals=6,
        min_qty=Decimal("0.0001"),
        min_notional=Decimal("10"),
        market_order_enabled=True,
        post_only_supported=False,
        custody_eligible=False,  # research visibility until Stage 6 custody qualification
    )


ABANTETHER_INSTRUMENT_CATALOG: dict[str, InstrumentMaster] = {
    "SPYON": _rwa_instrument("SPYON", "SPY", "ondo", "TOKENIZED_ETF"),
    "QQQON": _rwa_instrument("QQQON", "QQQ", "ondo", "TOKENIZED_ETF"),
    "IEFAON": _rwa_instrument("IEFAON", "IEFA", "ondo", "TOKENIZED_ETF"),
    "TLTON": _rwa_instrument("TLTON", "TLT", "ondo", "TOKENIZED_ETF"),
    "AGGON": _rwa_instrument("AGGON", "AGG", "ondo", "TOKENIZED_ETF"),
    "IAUON": _rwa_instrument("IAUON", "IAU", "ondo", "TOKENIZED_COMMODITY"),
    "SLVON": _rwa_instrument("SLVON", "SLV", "ondo", "TOKENIZED_COMMODITY"),
    "USOON": _rwa_instrument("USOON", "USO", "ondo", "TOKENIZED_ETF"),       # USO oil futures fund, NOT spot crude
    "COPXON": _rwa_instrument("COPXON", "COPX", "ondo", "TOKENIZED_ETF"),    # COPX copper miners equity ETF, NOT spot copper
}


@dataclass(frozen=True)
class OtcQuote:
    symbol: str
    quote_asset: str
    buy_price: Decimal                # price client pays to BUY token
    sell_price: Decimal               # price client receives to SELL token
    quoted_at: datetime
    ttl_seconds: float
    max_size_quote: Decimal

    @property
    def expires_at(self) -> datetime:
        return self.quoted_at + timedelta(seconds=self.ttl_seconds)

    @property
    def mid(self) -> Decimal:
        return (self.buy_price + self.sell_price) / Decimal(2)

    @property
    def round_trip_spread_pct(self) -> Decimal:
        if self.buy_price <= 0:
            return Decimal(0)
        return (self.buy_price - self.sell_price) / self.buy_price * Decimal(100)


@dataclass(frozen=True)
class RwaGuardDecision:
    allowed: bool
    reasons: tuple[str, ...]
    nav_deviation_pct: Decimal | None


def evaluate_abantether_guards(
    quote: OtcQuote,
    nav_ref: NavReference,
    *,
    as_of: datetime,
    order_notional_quote: Decimal,
    current_issuer_weight: Decimal,
    current_venue_weight: Decimal,
    proposed_delta_weight: Decimal,
    max_issuer_weight: Decimal = Decimal("0.20"),
    max_venue_weight: Decimal = Decimal("0.35"),
    max_nav_deviation: Decimal = Decimal("0.015"),
) -> RwaGuardDecision:
    """Enforce all 5 hardcoded AbanTether RWA guards (spec §8.2)."""
    reasons: list[str] = []
    sym = quote.symbol.upper()
    if sym in ZERO_VOLUME_EXCLUDED:
        reasons.append("ZERO_VOLUME_EXCLUDED")
    if sym in LEVERAGED_3X_EXCLUDED:
        reasons.append("LEVERAGED_3X_EXCLUDED")
    if as_of >= quote.expires_at:
        reasons.append("OTC_QUOTE_EXPIRED")
    if order_notional_quote > quote.max_size_quote:
        reasons.append("EXCEEDS_OTC_SIZE_LIMIT")
    if not nav_ref.session_open or not is_nyse_core_session_open(as_of.astimezone(UTC)):
        reasons.append("NYSE_SESSION_CLOSED")

    fair = nav_ref.fair_quote_price()
    dev = abs(quote.mid - fair) / fair if fair > 0 else None
    if dev is None or dev > max_nav_deviation:
        reasons.append("NAV_PREMIUM_EXCEEDS_LIMIT")

    if current_issuer_weight + proposed_delta_weight > max_issuer_weight:
        reasons.append("ISSUER_CUSTODY_CAP_EXCEEDED")
    if current_venue_weight + proposed_delta_weight > max_venue_weight:
        reasons.append("VENUE_CUSTODY_CAP_EXCEEDED")

    return RwaGuardDecision(allowed=not reasons, reasons=tuple(reasons), nav_deviation_pct=dev)
