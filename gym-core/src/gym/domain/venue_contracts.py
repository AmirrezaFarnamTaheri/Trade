"""Venue-agnostic domain contracts and instrument master (spec §4.1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .model import BookTop, dec


@dataclass(frozen=True)
class FeeTier:
    level: str
    min_30d_quote_volume: Decimal | None  # None when threshold is unverified -> force Level-1 undiscounted fallback
    maker_rate: Decimal
    taker_rate: Decimal


@dataclass(frozen=True)
class FeeSchedule:
    venue: str                            # "wallex" | "nobitex" | "abantether"
    venue_kind: str                       # "SPOT_BOOK" | "OTC_QUOTE" | "PERPETUAL_BOOK"
    quote_asset: str                      # "USDT" | "TMN"
    tiers: tuple[FeeTier, ...]
    permanent_discount: Decimal           # Decimal("0") unless verified by account receipt
    discount_expires_at: datetime | None
    fee_in_received_asset: bool           # True on Wallex spot (base debited on BUY, quote debited on SELL)
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.tiers:
            raise ValueError("FeeSchedule requires at least one FeeTier")
        if not (Decimal(0) <= self.permanent_discount < Decimal(1)):
            raise ValueError("permanent_discount must be in [0, 1)")

    def effective_rates(
        self,
        as_of: datetime,
        rolling_30d_volume: Decimal = Decimal(0),
        *,
        zero_fee: bool = False,
    ) -> tuple[Decimal, Decimal]:
        if zero_fee:
            return Decimal(0), Decimal(0)
        selected = self.tiers[0]
        for tier in self.tiers:
            if tier.min_30d_quote_volume is not None and rolling_30d_volume >= tier.min_30d_quote_volume:
                selected = tier
        disc = (
            self.permanent_discount
            if (self.discount_expires_at is None or as_of < self.discount_expires_at)
            else Decimal(0)
        )
        mult = Decimal(1) - disc
        return selected.maker_rate * mult, selected.taker_rate * mult


@dataclass(frozen=True)
class InstrumentMaster:
    venue: str
    symbol: str
    underlying_id: str                    # e.g. "BTC", "SPY", "SLV_ETF", "COPX_EQUITY_ETF", "XAUT_GOLD"
    issuer: str | None                    # None for native crypto; "ondo" | "backed" | "tether" for tokenized assets
    product_kind: str                     # "CRYPTO_SPOT" | "TOKENIZED_ETF" | "TOKENIZED_COMMODITY" | "FIAT_FX"
    trading_calendar: str                 # "24X7" | "TEHRAN_FX_SESSION" | "NYSE_CORE"
    price_decimals: int
    qty_decimals: int
    min_qty: Decimal
    min_notional: Decimal
    market_order_enabled: bool
    post_only_supported: bool
    custody_eligible: bool                # False excludes asset from funded proposals while keeping research visibility

    def round_qty(self, qty: Decimal) -> Decimal:
        step = Decimal(10) ** (-self.qty_decimals)
        return (qty // step) * step

    def round_price(self, price: Decimal) -> Decimal:
        step = Decimal(10) ** (-self.price_decimals)
        return (price // step) * step


@dataclass(frozen=True)
class QuoteSnapshot:
    venue: str
    symbol: str
    ts_event: datetime | None             # None when venue REST omits event clock; never fabricated from ts_avail
    ts_avail: datetime
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    bid_levels: tuple[tuple[Decimal, Decimal], ...]  # ordered best-bid-first (price, qty) pairs
    ask_levels: tuple[tuple[Decimal, Decimal], ...]  # ordered best-ask-first (price, qty) pairs
    flags: frozenset[str]

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)

    @property
    def spread_bps(self) -> Decimal:
        mid = self.mid
        if mid <= 0:
            return Decimal(0)
        return (self.ask - self.bid) / mid * Decimal(10000)

    @classmethod
    def from_book_top(cls, venue: str, top: BookTop, *, ts_event: datetime | None = None) -> QuoteSnapshot | None:
        if top.bid is None or top.ask is None or top.bid <= 0 or top.ask <= 0:
            return None
        bid_qty = top.bid_qty if top.bid_qty is not None and top.bid_qty > 0 else Decimal(0)
        ask_qty = top.ask_qty if top.ask_qty is not None and top.ask_qty > 0 else Decimal(0)
        bid_lvls: tuple[tuple[Decimal, Decimal], ...] = ((top.bid, bid_qty),)
        ask_lvls: tuple[tuple[Decimal, Decimal], ...] = ((top.ask, ask_qty),)
        if top.depth and isinstance(top.depth, (list, tuple)) and len(top.depth) == 2:
            raw_b, raw_a = top.depth
            if raw_b:
                bid_lvls = tuple((dec(p), dec(q)) for p, q in raw_b)
            if raw_a:
                ask_lvls = tuple((dec(p), dec(q)) for p, q in raw_a)
        return cls(
            venue=venue,
            symbol=top.symbol,
            ts_event=ts_event,
            ts_avail=top.ts_avail,
            bid=top.bid,
            ask=top.ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            bid_levels=bid_lvls,
            ask_levels=ask_lvls,
            flags=top.flags,
        )


@dataclass(frozen=True)
class NavReference:
    symbol: str
    underlying_ticker: str                # e.g. "SPY", "TLT", "SLV", "USO", "COPX"
    underlying_usd_price: Decimal
    usdt_usd_basis: Decimal               # USDT price in USD (e.g. Decimal("1.0000"))
    fx_usdt_to_quote: Decimal             # Decimal(1) for USDT pairs; executable USDTTMN ask/bid for TMN pairs
    share_ratio: Decimal                  # point-in-time underlying shares per 1.0 token (tracks splits/distributions)
    observed_at: datetime
    session_open: bool                    # evaluated from exchange calendar (handles EDT/EST DST & early closes)

    def fair_quote_price(self) -> Decimal:
        return self.underlying_usd_price * self.share_ratio * self.usdt_usd_basis * self.fx_usdt_to_quote


def wallex_l1_fee_schedule(quote_asset: str, *, observed_at: datetime | None = None) -> FeeSchedule:
    """Published Wallex Level-1 spot fee schedule with exact received-asset debit convention."""
    quote = quote_asset.upper()
    if quote == "USDT":
        tier = FeeTier("L1", None, Decimal("0.0010"), Decimal("0.0013"))
    elif quote == "TMN":
        tier = FeeTier("L1", None, Decimal("0.0025"), Decimal("0.0030"))
    else:
        raise ValueError(f"unsupported Wallex quote asset: {quote_asset!r}")
    return FeeSchedule(
        venue="wallex",
        venue_kind="SPOT_BOOK",
        quote_asset=quote,
        tiers=(tier,),
        permanent_discount=Decimal(0),
        discount_expires_at=None,
        fee_in_received_asset=True,
        observed_at=observed_at or datetime.now(UTC),
        source="PUBLISHED_STRUCTURED_FEE_L1",
    )


def wallex_fee_schedule_from_structured(
    structured_payload: dict,
    quote_asset: str,
    *,
    observed_at: datetime | None = None,
) -> FeeSchedule:
    """Build a FeeSchedule from Wallex /v2/structured-fee snapshot, keeping unverified thresholds None."""
    quote = quote_asset.upper()
    rows = (structured_payload.get("groups") or {}).get(quote) or []
    if not rows:
        return wallex_l1_fee_schedule(quote, observed_at=observed_at)
    tiers: list[FeeTier] = []
    for idx, row in enumerate(rows):
        raw_thresh = row.get("min_30d_quote_volume")
        threshold = dec(raw_thresh) if raw_thresh is not None else None
        tiers.append(
            FeeTier(
                level=str(row.get("level") or f"L{idx + 1}"),
                min_30d_quote_volume=threshold,
                maker_rate=dec(row["maker"]),
                taker_rate=dec(row["taker"]),
            )
        )
    return FeeSchedule(
        venue="wallex",
        venue_kind="SPOT_BOOK",
        quote_asset=quote,
        tiers=tuple(tiers),
        permanent_discount=Decimal(0),
        discount_expires_at=None,
        fee_in_received_asset=True,
        observed_at=observed_at or datetime.now(UTC),
        source="PUBLIC_STRUCTURED_FEE_VINTAGE",
    )
