"""Wallex public REST and Centrifugo WebSocket v2 (public channels only; no keys, no orders)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import aiohttp

REST = "https://api.wallex.ir"
WS = "wss://api.wallex.ir/connection/websocket"
MAX_CHANNELS = 64
MAX_BODY = 4 * 1024 * 1024  # untrusted responses are size-bounded


def channels(symbols: list[str]) -> list[str]:
    ch = [c for s in symbols for c in (f"orderbook:{s}@buyDepth", f"orderbook:{s}@sellDepth", f"public:{s}@trade")]
    if len(ch) > MAX_CHANNELS:
        raise ValueError(f"{len(ch)} channels exceed the {MAX_CHANNELS}-per-connection cap; watch fewer pairs")
    return ch


def parse_channel(ch: str) -> tuple[str, str, str] | None:
    """'orderbook:BTCTMN@buyDepth' -> ('depth', 'BTCTMN', 'bid'); 'public:BTCTMN@trade' -> ('trade', 'BTCTMN', '')."""
    kind, _, rest = ch.partition(":")
    sym, _, topic = rest.partition("@")
    if kind == "orderbook" and topic in ("buyDepth", "sellDepth"):
        return "depth", sym, "bid" if topic == "buyDepth" else "ask"
    if kind == "public" and topic == "trade":
        return "trade", sym, ""
    return None


UDF_RESOLUTIONS = {"1min": "1", "1h": "60"}  # "D" answers no_data on the live API (probed 2026-10-31)


def parse_udf(text: str) -> list[dict]:
    """`/v1/udf/history` columns -> candles with exact decimals. `no_data` is an empty answer, not an error."""
    d = json.loads(text)
    if d.get("s") == "no_data":
        return []
    if d.get("s") != "ok":
        raise ValueError(f"udf history status {d.get('s')!r}")
    cols = [d[k] for k in "tohlcv"]
    if len({len(c) for c in cols}) != 1:
        raise ValueError("udf history columns differ in length")
    try:
        return [{"t": datetime.fromtimestamp(int(t), timezone.utc), **{k: Decimal(str(x)) for k, x in zip("ohlcv", row)}}
                for t, *row in zip(*cols)]
    except (InvalidOperation, TypeError, OverflowError) as e:
        raise ValueError(f"udf history value: {e}") from e


def connect_cmds(chs: list[str]) -> list[str]:
    return [json.dumps({"id": 1, "connect": {}})] + [
        json.dumps({"id": i, "subscribe": {"channel": c}}) for i, c in enumerate(chs, 2)]


async def get_text(session: aiohttp.ClientSession, path: str, **params) -> str:
    async with session.get(REST + path, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
        r.raise_for_status()
        body = bytearray()
        async for chunk in r.content.iter_chunked(65536):  # read(n) returns one chunk, not the whole body
            body += chunk
            if len(body) > MAX_BODY:
                raise ValueError(f"{path}: response exceeds {MAX_BODY} bytes")
        return body.decode()
