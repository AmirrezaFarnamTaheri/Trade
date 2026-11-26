"""Read-only multi-venue public price oracle probe (Hyperliquid, Nobitex, Wallex).

Snapshots public top-of-book / mid prices on one UTC clock so cross-venue dislocations
and feed health can be measured without placing orders or storing secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from datetime import UTC, datetime
from decimal import Decimal

import aiohttp

from gym.adapters import wallex


def _mid(bid: Decimal, ask: Decimal) -> Decimal:
    return (bid + ask) / Decimal(2)


def _bps(a: Decimal, b: Decimal) -> float:
    return float((a - b) / b * Decimal(10000))


async def _fetch_hyperliquid(session: aiohttp.ClientSession, coins: list[str]) -> dict:
    try:
        async with session.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return {"ok": True, "mids": {c: data[c] for c in coins if c in data}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _fetch_nobitex(session: aiohttp.ClientSession, pairs: list[str]) -> dict:
    out = {}
    errors = {}
    for pair in pairs:
        try:
            async with session.get(f"https://apiv2.nobitex.ir/v3/orderbook/{pair}") as resp:
                resp.raise_for_status()
                body = await resp.json()
            bids = body.get("bids") or []
            asks = body.get("asks") or []
            if bids and asks:
                bid, ask = Decimal(str(bids[0][0])), Decimal(str(asks[0][0]))
                out[pair] = {"bid": str(bid), "ask": str(ask), "mid": str(_mid(bid, ask)), "spread_bps": round(_bps(ask, bid), 2)}
        except Exception as e:  # noqa: BLE001
            errors[pair] = f"{type(e).__name__}: {e}"
    return {"ok": bool(out), "books": out, "errors": errors}


async def _fetch_wallex(pairs: list[str]) -> dict:
    out = {}
    errors = {}
    async with wallex.public_session() as session:
        for pair in pairs:
            try:
                raw = await wallex.get_text(session, "/v1/depth", symbol=pair)
                res = json.loads(raw)["result"]
                bids = res.get("bid") or []
                asks = res.get("ask") or []
                if bids and asks:
                    bid, ask = Decimal(str(bids[0]["price"])), Decimal(str(asks[0]["price"]))
                    out[pair] = {"bid": str(bid), "ask": str(ask), "mid": str(_mid(bid, ask)), "spread_bps": round(_bps(ask, bid), 2)}
            except Exception as e:  # noqa: BLE001
                errors[pair] = f"{type(e).__name__}: {e}"
    return {"ok": bool(out), "books": out, "errors": errors}


async def snapshot(coins: list[str]) -> dict:
    ts = datetime.now(UTC).isoformat()
    usdt_pairs = [f"{c}USDT" for c in coins]
    nobitex_pairs = usdt_pairs + ["USDTIRT"]
    wallex_pairs = usdt_pairs + ["USDTTMN"]
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx), timeout=timeout) as session:
        hl, nb, wx = await asyncio.gather(
            _fetch_hyperliquid(session, coins),
            _fetch_nobitex(session, nobitex_pairs),
            _fetch_wallex(wallex_pairs),
        )
    dislocations = {}
    for coin in coins:
        pair = f"{coin}USDT"
        row = {}
        hl_mid = Decimal(str(hl["mids"][coin])) if hl.get("ok") and coin in hl.get("mids", {}) else None
        nb_mid = Decimal(nb["books"][pair]["mid"]) if nb.get("ok") and pair in nb.get("books", {}) else None
        wx_mid = Decimal(wx["books"][pair]["mid"]) if wx.get("ok") and pair in wx.get("books", {}) else None
        if hl_mid and nb_mid:
            row["nobitex_vs_hyperliquid_bps"] = round(_bps(nb_mid, hl_mid), 2)
        if hl_mid and wx_mid:
            row["wallex_vs_hyperliquid_bps"] = round(_bps(wx_mid, hl_mid), 2)
        if nb_mid and wx_mid:
            row["wallex_vs_nobitex_bps"] = round(_bps(wx_mid, nb_mid), 2)
        if row:
            dislocations[pair] = row
    return {
        "schema": "multi-venue-oracle-probe/1",
        "as_of": ts,
        "coins": coins,
        "hyperliquid": hl,
        "nobitex": nb,
        "wallex": wx,
        "dislocations_bps": dislocations,
        "funded_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only multi-venue public price oracle snapshot.")
    parser.add_argument("--coins", default="BTC,ETH,SOL,XRP", help="comma-separated base coins")
    args = parser.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    print(json.dumps(asyncio.run(snapshot(coins)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
