"""Public market-data collector actor: raw segments, change-only book tops, trades, quality."""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections import deque
from datetime import datetime
from decimal import Decimal

import aiohttp

from ..adapters import wallex
from ..adapters.store import MarketDB, SegmentWriter
from ..domain.model import UTC, BookSide, InstrumentId, QualityLimits, TradeTick, book_top, iso, levels, loads, parse_ts

HEARTBEAT_S = 60
CATALOG_KEYS = ("baseAsset", "quoteAsset", "baseAssetPrecision", "quotePrecision", "stepSize", "tickSize",
                "minQty", "minNotional", "isZeroFee", "isNew", "isMarketTypeEnable", "createdAt")


def now_utc() -> datetime:
    return datetime.now(UTC)


class Collector:
    def __init__(self, db: MarketDB, seg: SegmentWriter, symbols: list[str], *, demo: bool = False,
                 lim: QualityLimits = QualityLimits()):
        wallex.channels(symbols)  # fail fast on the channel cap
        self.db, self.seg, self.demo, self.lim = db, seg, demo, lim
        self.insts = {s: InstrumentId.wallex(s) for s in symbols}
        self.names = {s: {"en": s, "fa": s} for s in symbols}
        self.books: dict[str, dict[str, BookSide | None]] = {s: {"bid": None, "ask": None} for s in symbols}
        self.depth_ref: dict[str, str] = {}
        self.tops = {}
        self.written: dict[str, tuple] = {}
        self.trades = {s: deque(maxlen=30) for s in symbols}
        self._seen = deque(maxlen=1000)
        self.last_trade_ts = {}
        for s in symbols:
            row = db.c.execute("select max(ts_event) from trades where instrument_id=?", (f"wallex:{s}",)).fetchone()
            if row[0]:
                self.last_trade_ts[s] = parse_ts(row[0])
        self.status = {"connected": False, "last_frame": None, "reconnects": 0, "fatal": None, "errors": deque(maxlen=20)}

    # --- ingestion (shared by live, REST seeding and demo) ---
    def quality(self, now, symbol, flag, detail=""):
        self.db.add_quality(now, symbol, flag, detail)
        if flag == "SOURCE_ERROR":
            self.status["errors"].appendleft(f"{iso(now)} {symbol or ''} {detail}"[:300])

    def handle_frame(self, raw: str, now: datetime):
        self.status["last_frame"] = now
        if raw.strip() == "{}":
            return  # server ping
        ref = self.seg.write("ws", raw, now)
        for line in raw.split("\n"):
            if not line.strip() or line.strip() == "{}":
                continue
            try:
                m = loads(line)
                if "error" in m:
                    self.quality(now, None, "SOURCE_ERROR", "ws command error " + json.dumps(m["error"], default=str))
                    continue
                push = m.get("push") or {}
                p = wallex.parse_channel(push.get("channel", ""))
                if not p or p[1] not in self.books or "pub" not in push:
                    continue
                data = push["pub"].get("data", {})
                if p[0] == "depth":
                    self.on_depth(p[1], p[2], levels(data["message"] if isinstance(data, dict) else data), now, ref)
                else:
                    self.on_trade(p[1], data, now, ref)
            except (ValueError, KeyError, TypeError, ArithmeticError) as e:
                self.quality(now, None, "SOURCE_ERROR", f"unparseable frame: {type(e).__name__}: {e}")

    def on_depth(self, sym, side, lv, now, ref):
        self.books[sym][side] = BookSide(lv, now)  # each message is a full side snapshot: replace
        self.depth_ref[sym] = ref

    def on_trade(self, sym, d, now, ref, only_after: datetime | None = None) -> bool:
        t = TradeTick.wallex(sym, d, now)
        key = (sym, t.ts_event, t.price, t.qty, t.aggressor)
        # ponytail: no venue trade ids, so identical trades in the same second collapse; add ids when Wallex exposes them
        if key in self._seen or (only_after and t.ts_event <= only_after):
            return False
        self._seen.append(key)
        self.db.add_trade(t, ref)
        self.trades[sym].appendleft(t)
        if sym not in self.last_trade_ts or t.ts_event > self.last_trade_ts[sym]:
            self.last_trade_ts[sym] = t.ts_event
        return True

    def tick(self, now: datetime):
        for sym, b in self.books.items():
            top = book_top(sym, b["bid"], b["ask"], now, self.lim)
            prev = self.tops.get(sym)
            for f in top.flags - (prev.flags if prev else frozenset()):
                self.quality(now, sym, f, f"bid={top.bid} ask={top.ask} spread_bps={top.spread_bps}")
            self.tops[sym] = top
            last = self.written.get(sym)
            if not last or last[0] != top.key() or (now - last[1]).total_seconds() >= HEARTBEAT_S:
                self.db.add_book_top(top, self.depth_ref.get(sym))
                self.written[sym] = (top.key(), now)

    # --- live Wallex ---
    async def load_catalog(self, session):
        now = now_utc()
        try:
            raw = await wallex.get_text(session, "/v1/markets")
            self.seg.write("rest:/v1/markets", raw, now)
            symbols = loads(raw)["result"]["symbols"]
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
            self.quality(now, None, "SOURCE_ERROR", f"catalog: {type(e).__name__}: {e}")
            return
        for s in self.insts:
            m = symbols.get(s)
            if not m:
                self.quality(now, s, "SOURCE_ERROR", "symbol missing from /v1/markets")
                continue
            self.insts[s] = InstrumentId.wallex(s, m["baseAsset"], m["quoteAsset"])
            self.names[s] = {"en": m.get("enName", s), "fa": m.get("faName", s)}
            self.db.upsert_instrument(self.insts[s], self.names[s], {k: m.get(k) for k in CATALOG_KEYS}, "rest:/v1/markets", now)

    async def seed(self, session, symbols=None, trades=True):
        """REST snapshot at start, after every reconnect, and for quiet (stale) sides."""
        for s in symbols or list(self.insts):
            now = now_utc()
            try:
                raw = await wallex.get_text(session, "/v1/depth", symbol=s)
                ref = self.seg.write("rest:/v1/depth", raw, now)
                res = loads(raw)["result"]
                self.on_depth(s, "bid", levels(res["bid"]), now, ref)
                self.on_depth(s, "ask", levels(res["ask"]), now, ref)
                if trades:
                    raw = await wallex.get_text(session, "/v1/trades", symbol=s)
                    ref = self.seg.write("rest:/v1/trades", raw, now)
                    rows = loads(raw)["result"]["latestTrades"]
                    prev = self.last_trade_ts.get(s)
                    ticks = [TradeTick.wallex(s, d, now) for d in rows]
                    if prev and ticks and min(t.ts_event for t in ticks) > prev:
                        self.quality(now, s, "GAP", f"trades between {iso(prev)} and {iso(min(t.ts_event for t in ticks))} lost")
                    for d in reversed(rows):
                        self.on_trade(s, d, now, ref, only_after=prev)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, ArithmeticError) as e:
                self.quality(now, s, "SOURCE_ERROR", f"REST seed: {type(e).__name__}: {e}")
            await asyncio.sleep(0.2)

    async def _ws_once(self, session) -> int | None:
        async with session.ws_connect(wallex.WS, heartbeat=None, receive_timeout=60, max_msg_size=wallex.MAX_BODY) as ws:
            for cmd in wallex.connect_cmds(wallex.channels(list(self.insts))):
                await ws.send_str(cmd)
            self.status["connected"] = True
            await self.seed(session)
            async for msg in ws:  # 60 s of total silence (pings come every 25 s) raises TimeoutError
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if "{}" in msg.data.split("\n"):
                        await ws.send_str("{}")  # pong within 8 s or the server closes with 3012
                    self.handle_frame(msg.data, now_utc())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
            return ws.close_code

    async def _housekeeping(self, session):
        last_reseed = time.monotonic()
        while True:
            await asyncio.sleep(2)
            self.tick(now_utc())
            if session and time.monotonic() - last_reseed > 60:
                last_reseed = time.monotonic()
                stale = [s for s, t in self.tops.items() if "STALE" in t.flags]
                if stale and self.status["connected"]:
                    await self.seed(session, stale, trades=False)

    async def run(self):
        if self.demo:
            return await asyncio.gather(self._housekeeping(None), self._demo())
        async with aiohttp.ClientSession(headers={"User-Agent": "TradingGYM/0.1 (observatory)"}) as session:
            await self.load_catalog(session)
            hk = asyncio.create_task(self._housekeeping(session))
            backoff = 1
            try:
                while True:
                    started, code = time.monotonic(), None
                    try:
                        code = await self._ws_once(session)
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                        self.status["errors"].appendleft(f"{iso(now_utc())} ws {type(e).__name__}: {e}"[:300])
                    self.status["connected"] = False
                    if code is not None and code >= 3500:
                        self.status["fatal"] = f"close code {code}: client-side fault, not retrying"
                        self.quality(now_utc(), None, "SOURCE_ERROR", self.status["fatal"])
                        return
                    backoff = 1 if time.monotonic() - started > 60 else min(backoff * 2, 60)
                    self.status["reconnects"] += 1
                    await asyncio.sleep(backoff)
            finally:
                hk.cancel()

    # --- demo replay: synthetic Wallex-shaped frames through the same ingestion path ---
    async def _demo(self):
        rng = random.Random(7)
        px = {"USDTTMN": Decimal(273500), "BTCTMN": Decimal(21040000000), "BTCUSDT": Decimal("76950"),
              "ETHTMN": Decimal(1000000000), "ETHUSDT": Decimal("3650")}
        self.status["connected"] = True
        while True:
            for s, inst in self.insts.items():
                tick = Decimal(1) if inst.quote == "TMN" else Decimal("0.01")
                mid = px.setdefault(s, Decimal(1000)) * (1 + Decimal(rng.gauss(0, 0.0004)).quantize(Decimal("1e-6")))
                px[s] = mid
                half = (mid * Decimal("0.0006")).quantize(tick)
                for side, sign in (("buyDepth", -1), ("sellDepth", 1)):
                    lv = [((mid + sign * (half + tick * k * 3)).quantize(tick), Decimal(rng.randint(1, 900)) / 100) for k in range(10)]
                    msg = ",".join(f'{{"price":{p},"quantity":{q},"sum":{p * q}}}' for p, q in lv)
                    self.handle_frame(f'{{"push":{{"channel":"orderbook:{s}@{side}","pub":{{"data":{{"message":[{msg}]}}}}}}}}', now_utc())
                if rng.random() < 0.4:
                    buy = rng.random() < 0.5
                    p = (mid + (-half if buy else half)).quantize(tick)
                    d = json.dumps({"isBuyOrder": buy, "price": str(p), "quantity": str(Decimal(rng.randint(1, 500)) / 100),
                                    "timestamp": iso(now_utc().replace(microsecond=0))})
                    self.handle_frame(f'{{"push":{{"channel":"public:{s}@trade","pub":{{"data":{d}}}}}}}', now_utc())
            await asyncio.sleep(1)
