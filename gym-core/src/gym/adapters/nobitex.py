"""Nobitex spot order-book adapter, fee schedule (-30% tier), and pre-funded multi-venue arb accounting."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..domain.model import CurrencyUnit, dec
from ..domain.venue_contracts import FeeSchedule, FeeTier, QuoteSnapshot

NOBITEX_STATS_URL = "https://apiv2.nobitex.ir/market/stats"
NOBITEX_ORDERBOOK_URL = "https://apiv2.nobitex.ir/v3/orderbook/{symbol}"
NOBITEX_ORDERBOOK_ALL_URL = "https://apiv2.nobitex.ir/v3/orderbook/all"
NOBITEX_LIQUIDITY_POOLS_URL = "https://apiv2.nobitex.ir/liquidity-pools/list"
NOBITEX_MARGIN_MARKETS_URL = "https://apiv2.nobitex.ir/margin/markets/list"
NOBITEX_WS_URL = "wss://ws.nobitex.ir/connection/websocket"
NOBITEX_BOT_USER_AGENT = "TraderBot/TradingGYM-1.0"

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


def parse_nobitex_all_orderbooks(
    payload: dict,
    symbols: tuple[str, ...],
    ts_avail: datetime,
    *,
    convert_rls_to_tmn: bool = True,
) -> list[QuoteSnapshot]:
    """Parse GET /v3/orderbook/all bulk payload for requested symbols in a single HTTP round-trip."""
    if not isinstance(payload, dict):
        return []
    out: list[QuoteSnapshot] = []
    for sym in symbols:
        entry = payload.get(sym) or payload.get(sym.upper())
        if isinstance(entry, dict):
            qs = parse_nobitex_orderbook(sym, entry, ts_avail, convert_rls_to_tmn=convert_rls_to_tmn)
            if qs is not None:
                out.append(qs)
    return out


@dataclass(frozen=True)
class NobitexLiquidityPool:
    currency: str
    ts_avail: datetime
    capacity: Decimal
    filled_capacity: Decimal
    utilization_pct: Decimal
    apr_pct: Decimal | None
    profit_period_days: int | None
    min_delegation: Decimal | None
    max_delegation: Decimal | None


@dataclass(frozen=True)
class NobitexPublicTrade:
    symbol: str
    ts_avail: datetime
    ts_event_ms: int
    price: Decimal
    volume: Decimal
    side: str


def parse_nobitex_liquidity_pools(
    payload: dict,
    ts_avail: datetime,
    *,
    currencies: tuple[str, ...] | None = None,
) -> list[NobitexLiquidityPool]:
    """Parse GET /liquidity-pools/list into structured pool capacity & live APR snapshots."""
    pools = payload.get("pools") if isinstance(payload, dict) else None
    if not isinstance(pools, dict):
        return []
    want = {c.lower() for c in currencies} if currencies is not None else None
    out: list[NobitexLiquidityPool] = []
    for cur_key, item in sorted(pools.items()):
        if not isinstance(item, dict):
            continue
        if want is not None and cur_key.lower() not in want:
            continue
        cap = dec(str(item.get("capacity") or "0"))
        filled = dec(str(item.get("filledCapacity") or "0"))
        util = ((filled / cap) * Decimal(100)).quantize(Decimal("0.01")) if cap > 0 else Decimal("0.00")
        apr_raw = item.get("APR")
        apr_val = dec(str(apr_raw)) if apr_raw not in (None, "") else None
        period_raw = item.get("profitPeriod")
        period_val = int(period_raw) if period_raw is not None else None
        min_d = dec(str(item["minDelegation"])) if item.get("minDelegation") not in (None, "") else None
        max_d = dec(str(item["maxDelegation"])) if item.get("maxDelegation") not in (None, "") else None
        out.append(
            NobitexLiquidityPool(
                currency=cur_key.upper(),
                ts_avail=ts_avail,
                capacity=cap,
                filled_capacity=filled,
                utilization_pct=util,
                apr_pct=apr_val,
                profit_period_days=period_val,
                min_delegation=min_d,
                max_delegation=max_d,
            )
        )
    return out


def parse_nobitex_centrifugo_push(
    raw_msg: str | dict,
    ts_avail: datetime,
) -> tuple[str, QuoteSnapshot | NobitexPublicTrade | None]:
    """Parse a raw Centrifugo v2 WebSocket frame from wss://ws.nobitex.ir/connection/websocket.

    Returns ("PING", None), ("ORDERBOOK", QuoteSnapshot), ("TRADE", NobitexPublicTrade), or ("OTHER", None).
    """
    msg = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
    if not isinstance(msg, dict):
        return "OTHER", None
    if msg == {}:
        return "PING", None
    push = msg.get("push")
    if not isinstance(push, dict):
        return "OTHER", None
    channel = str(push.get("channel") or "")
    pub = push.get("pub")
    if not isinstance(pub, dict):
        return "OTHER", None
    data = pub.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return "OTHER", None

    if channel.startswith("public:orderbook-"):
        sym = channel.removeprefix("public:orderbook-").strip()
        qs = parse_nobitex_orderbook(sym, data, ts_avail)
        return ("ORDERBOOK", qs) if qs is not None else ("OTHER", None)

    if channel.startswith("public:trades-"):
        sym = channel.removeprefix("public:trades-").strip().upper()
        if sym.endswith("IRT"):
            sym = sym[:-3] + "TMN"
        px = dec(str(data.get("price") or "0"))
        vol = dec(str(data.get("volume") or "0"))
        if px <= 0 or vol <= 0:
            return "OTHER", None
        scale = RIALS_PER_TOMAN if channel.upper().endswith("IRT") else Decimal(1)
        return "TRADE", NobitexPublicTrade(
            symbol=sym,
            ts_avail=ts_avail,
            ts_event_ms=int(data.get("time") or 0),
            price=px / scale,
            volume=vol,
            side=str(data.get("type") or "").upper(),
        )
    return "OTHER", None


async def stream_nobitex_centrifugo(
    symbols: tuple[str, ...],
    *,
    on_orderbook=None,
    on_trade=None,
    include_trades: bool = True,
    max_seconds: float | None = None,
    ws_url: str = NOBITEX_WS_URL,
) -> dict[str, int]:
    """Read-only public Centrifugo v2 WebSocket stream for Nobitex L2 orderbooks & signed trades."""
    import asyncio

    import aiohttp

    counts = {"orderbooks": 0, "trades": 0, "pings": 0}
    headers = {"User-Agent": NOBITEX_BOT_USER_AGENT}
    loop = asyncio.get_running_loop()
    deadline = (loop.time() + max_seconds) if max_seconds is not None else None

    async with aiohttp.ClientSession(headers=headers, trust_env=False) as session:
        async with session.ws_connect(ws_url, heartbeat=None) as ws:
            await ws.send_json({"connect": {}, "id": 1})
            msg_id = 2
            for sym in symbols:
                await ws.send_json({"id": msg_id, "subscribe": {"channel": f"public:orderbook-{sym.upper()}"}})
                msg_id += 1
                if include_trades:
                    await ws.send_json({"id": msg_id, "subscribe": {"channel": f"public:trades-{sym.upper()}"}})
                    msg_id += 1

            while True:
                timeout = max(0.2, deadline - loop.time()) if deadline is not None else 25.0
                if deadline is not None and loop.time() >= deadline:
                    break
                try:
                    frame = await asyncio.wait_for(ws.receive(), timeout=timeout)
                except TimeoutError:
                    if deadline is not None:
                        break
                    continue
                if frame.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                if frame.type != aiohttp.WSMsgType.TEXT:
                    continue
                now = datetime.now(UTC)
                for line in frame.data.splitlines():
                    if not line.strip():
                        continue
                    kind, obj = parse_nobitex_centrifugo_push(line, now)
                    if kind == "PING":
                        await ws.send_str("{}")
                        counts["pings"] += 1
                    elif kind == "ORDERBOOK" and obj is not None:
                        counts["orderbooks"] += 1
                        if on_orderbook is not None:
                            on_orderbook(obj)
                    elif kind == "TRADE" and obj is not None:
                        counts["trades"] += 1
                        if on_trade is not None:
                            on_trade(obj)
    return counts


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
