"""Read-only adapters for newly documented Wallex public feeds:
- Margin long/short retail crowding ratio: GET /margin-trade/v1/public/ratio/{market}
- Live fair-price oracle: GET /v1/all-fairPrice & Centrifugo v2 public:all@fairPrice
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..domain.model import dec

WALLEX_MARGIN_RATIO_URL = "https://api.wallex.ir/margin-trade/v1/public/ratio/{market}"
WALLEX_ALL_FAIR_PRICE_URL = "https://api.wallex.ir/v1/all-fairPrice"
WALLEX_WS_V2_URL = "wss://api.wallex.ir/connection/websocket"  # exact path; trailing slash returns 404


@dataclass(frozen=True)
class WallexMarginRatio:
    symbol: str
    ts_avail: datetime
    long_pct: Decimal
    short_pct: Decimal


@dataclass(frozen=True)
class WallexFairPrice:
    symbol: str
    ts_avail: datetime
    fair_price: Decimal
    source_ts: str | None


def parse_wallex_margin_ratio(
    symbol: str,
    payload: dict,
    ts_avail: datetime,
) -> WallexMarginRatio | None:
    """Parse GET /margin-trade/v1/public/ratio/{market} response."""
    if not isinstance(payload, dict) or not payload.get("success", True):
        return None
    res = payload.get("result")
    if not isinstance(res, dict):
        return None
    long_raw = res.get("long_percents")
    short_raw = res.get("short_percents")
    if long_raw is None or short_raw is None:
        return None
    long_p = dec(str(long_raw))
    short_p = dec(str(short_raw))
    if long_p < 0 or short_p < 0:
        return None
    return WallexMarginRatio(
        symbol=symbol.upper(),
        ts_avail=ts_avail,
        long_pct=long_p,
        short_pct=short_p,
    )


def parse_wallex_fair_prices(
    payload: dict,
    ts_avail: datetime,
    *,
    symbols: tuple[str, ...] | None = None,
) -> list[WallexFairPrice]:
    """Parse either REST GET /v1/all-fairPrice or Centrifugo v2 public:all@fairPrice payload."""
    if not isinstance(payload, dict):
        return []
    body = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    prices = body.get("prices") if isinstance(body.get("prices"), dict) else body
    if not isinstance(prices, dict):
        return []
    src_ts = str(body.get("ts")) if body.get("ts") is not None else None
    want = {s.upper() for s in symbols} if symbols is not None else None
    out: list[WallexFairPrice] = []
    for sym, raw_px in sorted(prices.items()):
        sym_u = str(sym).upper()
        if want is not None and sym_u not in want:
            continue
        if isinstance(raw_px, (dict, list)) or raw_px in (None, ""):
            continue
        try:
            px = dec(str(raw_px))
        except Exception:
            continue
        if px <= 0:
            continue
        out.append(
            WallexFairPrice(
                symbol=sym_u,
                ts_avail=ts_avail,
                fair_price=px,
                source_ts=src_ts,
            )
        )
    return out


def parse_wallex_centrifugo_fair_price_push(
    raw_msg: str | dict,
    ts_avail: datetime,
    *,
    symbols: tuple[str, ...] | None = None,
) -> tuple[str, list[WallexFairPrice]]:
    """Parse raw Centrifugo v2 frame for public:all@fairPrice (or empty {} ping)."""
    msg = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
    if not isinstance(msg, dict):
        return "OTHER", []
    if msg == {}:
        return "PING", []
    push = msg.get("push")
    if not isinstance(push, dict):
        return "OTHER", []
    if str(push.get("channel") or "") != "public:all@fairPrice":
        return "OTHER", []
    pub = push.get("pub")
    if not isinstance(pub, dict):
        return "OTHER", []
    data = pub.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return "OTHER", []
    return "FAIR_PRICE", parse_wallex_fair_prices(data, ts_avail, symbols=symbols)


async def fetch_wallex_fair_prices_ws_once(
    symbols: tuple[str, ...] | None = None,
    *,
    timeout_s: float = 28.0,
    ws_url: str = WALLEX_WS_V2_URL,
) -> list[WallexFairPrice]:
    """Capture one public:all@fairPrice snapshot over Centrifugo v2 WebSocket (zero auth)."""
    import asyncio

    import aiohttp

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    async with aiohttp.ClientSession(trust_env=False) as session:
        async with session.ws_connect(ws_url, heartbeat=None) as ws:
            await ws.send_json({"connect": {}, "id": 1})
            await ws.send_json({"id": 2, "subscribe": {"channel": "public:all@fairPrice"}})
            while loop.time() < deadline:
                rem = max(0.2, deadline - loop.time())
                try:
                    frame = await asyncio.wait_for(ws.receive(), timeout=rem)
                except TimeoutError:
                    break
                if frame.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                if frame.type != aiohttp.WSMsgType.TEXT:
                    continue
                now = datetime.now(UTC)
                for line in frame.data.splitlines():
                    if not line.strip():
                        continue
                    kind, items = parse_wallex_centrifugo_fair_price_push(line, now, symbols=symbols)
                    if kind == "PING":
                        await ws.send_str("{}")
                    elif kind == "FAIR_PRICE" and items:
                        return items
    return []
