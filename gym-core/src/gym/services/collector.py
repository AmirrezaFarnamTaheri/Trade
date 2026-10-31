"""Public market-data collector actor: raw segments, change-only book tops, trades, quality."""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal

import aiohttp

from ..adapters import wallex
from ..adapters.store import MarketDB, SegmentWriter
from ..domain.bars import qualified
from ..domain.model import UTC, BookSide, InstrumentId, QualityLimits, TradeTick, book_top, iso, levels, loads, parse_ts
from ..domain.units import UnitWatch, unit_freeze_rule
from .rules import RuleService

HEARTBEAT_S = 60
CATALOG_PATH = "/hector/web/v1/markets"
CANDLE_REFRESH_S = 60
CANDLE_BATCH = 10
RESEED_BATCH = 5
REST_REQUESTS_PER_SECOND = 4
MIN_ASSETS = 25
MAX_ASSETS = 500


def now_utc() -> datetime:
    return datetime.now(UTC)


def _value(m: dict, snake: str, camel: str | None = None):
    return m.get(snake) if snake in m else m.get(camel or snake)


def _positive_decimal(value) -> Decimal:
    try:
        n = Decimal(str(value or 0))
    except ArithmeticError:
        return Decimal(0)
    return n if n.is_finite() and n > 0 else Decimal(0)


def select_universe(markets: list[dict], asset_count: int) -> tuple[list[str], dict]:
    """Pick liquid, non-risky spot assets; observe both TMN/USDT legs when listed."""
    if not MIN_ASSETS <= asset_count <= MAX_ASSETS:
        raise ValueError(f"assets must be {MIN_ASSETS}..{MAX_ASSETS}")
    active = [m for m in markets if m.get("symbol") and _value(m, "base_asset", "baseAsset")
              and m.get("is_spot") is True and _value(m, "quote_asset", "quoteAsset") in {"TMN", "USDT"}]
    safe = [m for m in active if "isRisky" not in (m.get("flags") or [])]
    fx_market = next((m for m in active if str(m.get("symbol")).upper() == "USDTTMN"), {})
    fx = _positive_decimal(fx_market.get("price"))
    by_base: dict[str, list[dict]] = {}
    for m in safe:
        by_base.setdefault(_value(m, "base_asset", "baseAsset"), []).append(m)

    def score(item):
        base, rows = item
        total = Decimal(0)
        for m in rows:
            volume = _positive_decimal(m.get("quote_volume_24h"))
            quote = _value(m, "quote_asset", "quoteAsset")
            total += volume / fx if quote == "TMN" and fx > 0 else volume if quote == "USDT" else 0
        return -total, base

    ranked = [base for base, _ in sorted(by_base.items(), key=score)]
    if "USDT" in by_base:
        ranked = ["USDT", *(b for b in ranked if b != "USDT")]
    bases = ranked[:asset_count]
    rank = {base: i for i, base in enumerate(bases)}
    selected = sorted(
        (m for m in safe if _value(m, "base_asset", "baseAsset") in rank),
        key=lambda m: (rank[_value(m, "base_asset", "baseAsset")], 0 if _value(m, "quote_asset", "quoteAsset") == "TMN" else 1),
    )
    symbols = list(dict.fromkeys(str(m["symbol"]).upper() for m in selected))
    return symbols, {
        "mode": "ranked-spot",
        "requested_assets": asset_count,
        "selected_assets": bases,
        "available_safe_assets": len(by_base),
        "observed_markets": len(symbols),
        "websocket_shards": (len(symbols) + wallex.MAX_CHANNELS // 3 - 1) // (wallex.MAX_CHANNELS // 3),
        "rest_requests_per_second": REST_REQUESTS_PER_SECOND,
        "excludes": ["not active spot", "isRisky"],
    }


class RestRate:
    def __init__(self, requests_per_second: int = REST_REQUESTS_PER_SECOND):
        self.floor = 1 / requests_per_second
        self.interval = self.floor
        self.next = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            await asyncio.sleep(max(0, self.next - now))
            self.next = max(now, self.next) + self.interval

    async def penalize(self):
        async with self.lock:
            self.interval = min(self.interval * 2, 5.0)


class Collector:
    def __init__(self, db: MarketDB, seg: SegmentWriter, symbols: list[str] | None, *, demo: bool = False,
                 lim: QualityLimits = QualityLimits(), asset_count: int = MIN_ASSETS,
                 add_symbols: tuple[str, ...] = (), remove_symbols: tuple[str, ...] = ()):
        self.db, self.seg, self.demo, self.lim = db, seg, demo, lim
        self.explicit_symbols = symbols
        self.asset_count = asset_count
        self.add_symbols = tuple(s.upper() for s in add_symbols)
        self.remove_symbols = frozenset(s.upper() for s in remove_symbols)
        self.insts: dict[str, InstrumentId] = {}
        self.names: dict[str, dict] = {}
        self.books: dict[str, dict[str, BookSide | None]] = {}
        self.depth_ref: dict[str, str] = {}
        self.tops = {}
        self.written: dict[str, tuple] = {}
        self.trades: dict[str, deque] = {}
        self.last_trade_ts = {}
        self.universe = {"mode": "explicit", "requested_assets": None, "selected_assets": [], "observed_markets": 0}
        self.rest_rate = RestRate()
        self.seeding: set[str] = set()
        self.connected_shards: set[int] = set()
        self.units = UnitWatch()
        self.status = {"connected": False, "shards": 0, "last_frame": None, "reconnects": 0, "fatal": None,
                       "errors": deque(maxlen=20)}
        if symbols is not None:
            self.configure(symbols)

    def configure(self, symbols: list[str], catalog: dict[str, dict] | None = None):
        symbols = list(dict.fromkeys(s.upper() for s in symbols))
        self.insts = {}
        self.names = {}
        self.books = {s: {"bid": None, "ask": None} for s in symbols}
        self.depth_ref = {}
        self.tops = {}
        self.written = {}
        self.trades = {s: deque(maxlen=30) for s in symbols}
        self.last_trade_ts = {}
        for s in symbols:
            m = (catalog or {}).get(s, {})
            base, quote = _value(m, "base_asset", "baseAsset"), _value(m, "quote_asset", "quoteAsset")
            self.insts[s] = InstrumentId.wallex(s, base, quote) if base and quote else InstrumentId.wallex(s)
            self.names[s] = {"en": m.get("name_en") or m.get("enName") or s,
                             "fa": m.get("name_fa") or m.get("faName") or s}
            row = self.db.c.execute("select max(ts_event) from trades where instrument_id=?", (f"wallex:{s}",)).fetchone()
            if row[0]:
                self.last_trade_ts[s] = parse_ts(row[0])
        self.universe["observed_markets"] = len(symbols)
        self.universe["observed_assets"] = list(dict.fromkeys(i.base for i in self.insts.values()))
        self.universe["websocket_shards"] = (len(symbols) + wallex.MAX_CHANNELS // 3 - 1) // (wallex.MAX_CHANNELS // 3)
        if self.universe.get("mode") == "explicit":
            self.universe["selected_assets"] = self.universe["observed_assets"]

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
        if only_after and t.ts_event <= only_after:
            return False
        # ponytail: preserve ambiguous identical prints; dedupe by venue trade id when Wallex exposes one.
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
        self.watch_units(now)

    def watch_units(self, now: datetime):
        """DATA-04: a ×10^k jump in every IRT price at once freezes new IRT entries. Stored rows stay as observed."""
        mids = {(self.insts[s].base, self.insts[s].quote): (t.bid + t.ask) / 2
                for s, t in self.tops.items() if qualified(t)}
        event = self.units.observe(mids)
        if event:
            self.quality(now, None, "UNIT_DISCONTINUITY", json.dumps(event))
            RuleService(self.db).put(unit_freeze_rule(event, now), now, "add", actor="collector")

    # --- live Wallex ---
    async def rest_text(self, session, path: str, **params) -> str:
        """Conservative global pacing; 429 halves the session rate before retrying."""
        for attempt in range(4):
            await self.rest_rate.wait()
            try:
                return await wallex.get_text(session, path, **params)
            except aiohttp.ClientResponseError as e:
                if e.status != 429 or attempt == 3:
                    raise
                await self.rest_rate.penalize()
                retry_after = (e.headers or {}).get("Retry-After")
                try:
                    delay = max(float(retry_after or 0), 2 ** attempt)
                except ValueError:
                    delay = 2 ** attempt
                self.quality(now_utc(), params.get("symbol"), "RATE_LIMIT",
                             f"{path} returned 429; retry in {delay:g}s; interval={self.rest_rate.interval:g}s")
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def load_catalog(self, session):
        now = now_utc()
        try:
            raw = await self.rest_text(session, CATALOG_PATH)
            self.seg.write("rest:" + CATALOG_PATH, raw, now)
            rows = loads(raw)["result"]["markets"]
            if not isinstance(rows, list):
                raise ValueError("catalog markets is not a list")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as e:
            self.quality(now, None, "SOURCE_ERROR", f"catalog: {type(e).__name__}: {e}")
            return
        catalog = {}
        for m in rows:
            if not isinstance(m, dict) or not isinstance(m.get("symbol"), str) or not m["symbol"].strip():
                self.quality(now, None, "SOURCE_ERROR", "catalog row missing symbol")
                continue
            catalog[m["symbol"].upper()] = m
        rows = list(catalog.values())
        for s, m in catalog.items():
            base, quote = _value(m, "base_asset", "baseAsset"), _value(m, "quote_asset", "quoteAsset")
            if not base or not quote:
                self.quality(now, s, "SOURCE_ERROR", "catalog row missing base/quote")
                continue
            inst = InstrumentId.wallex(s, base, quote)
            names = {"en": m.get("name_en") or m.get("enName") or s,
                     "fa": m.get("name_fa") or m.get("faName") or s}
            self.db.upsert_instrument(inst, names, m, "rest:" + CATALOG_PATH, now)
        if self.explicit_symbols is None:
            symbols, self.universe = select_universe(rows, self.asset_count)
        else:
            symbols = self.explicit_symbols
            self.universe = {"mode": "explicit", "requested_assets": None, "selected_assets": [],
                             "observed_markets": len(symbols), "rest_requests_per_second": REST_REQUESTS_PER_SECOND}
        requested = list(dict.fromkeys(s.upper() for s in [*symbols, *self.add_symbols]))
        missing = list(dict.fromkeys([s for s in requested if s not in catalog]
                                     + [s for s in self.remove_symbols if s not in catalog]))
        for s in missing:
            self.quality(now, s, "SOURCE_ERROR", f"symbol missing from {CATALOG_PATH}")
        symbols = [s for s in requested if s in catalog and s not in self.remove_symbols]
        self.universe["added_markets"] = [s for s in self.add_symbols if s in symbols]
        self.universe["removed_markets"] = [s for s in requested if s in self.remove_symbols and s in catalog]
        self.universe["remove_requests"] = sorted(self.remove_symbols)
        self.universe["custom_note"] = "custom additions are observed only and bypass ranking filters"
        self.configure(symbols, catalog)

    async def seed(self, session, symbols=None, trades=True):
        """Rate-limited REST snapshots after subscribe/reconnect and for a bounded stale batch."""
        for s in symbols or list(self.insts):
            if s in self.seeding:
                continue
            self.seeding.add(s)
            now = now_utc()
            try:
                raw = await self.rest_text(session, "/v1/depth", symbol=s)
                ref = self.seg.write("rest:/v1/depth", raw, now)
                res = loads(raw)["result"]
                self.on_depth(s, "bid", levels(res["bid"]), now, ref)
                self.on_depth(s, "ask", levels(res["ask"]), now, ref)
                if trades:
                    raw = await self.rest_text(session, "/v1/trades", symbol=s)
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
            finally:
                self.seeding.discard(s)

    async def _ws_once(self, session, symbols: list[str], shard: int) -> int | None:
        async with session.ws_connect(wallex.WS, heartbeat=None, receive_timeout=60, max_msg_size=wallex.MAX_BODY) as ws:
            for cmd in wallex.connect_cmds(wallex.channels(symbols)):
                await ws.send_str(cmd)
            self.connected_shards.add(shard)
            self.status["connected"] = True
            self.status["shards"] = len(self.connected_shards)
            seed = asyncio.create_task(self.seed(session, symbols))
            try:
                async for msg in ws:  # 60 s of total silence (pings come every 25 s) raises TimeoutError
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if "{}" in msg.data.split("\n"):
                            await ws.send_str("{}")  # pong within 8 s or the server closes with 3012
                        self.handle_frame(msg.data, now_utc())
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        break
                return ws.close_code
            finally:
                self.connected_shards.discard(shard)
                self.status["connected"] = bool(self.connected_shards)
                self.status["shards"] = len(self.connected_shards)
                if not seed.done():
                    seed.cancel()
                await asyncio.gather(seed, return_exceptions=True)

    async def _ws_loop(self, session, symbols: list[str], shard: int):
        backoff = 1
        while True:
            started, code = time.monotonic(), None
            try:
                code = await self._ws_once(session, symbols, shard)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                self.status["errors"].appendleft(f"{iso(now_utc())} ws[{shard}] {type(e).__name__}: {e}"[:300])
            if code is not None and code >= 3500:
                self.status["fatal"] = f"shard {shard} close code {code}: client-side fault, not retrying"
                self.quality(now_utc(), None, "SOURCE_ERROR", self.status["fatal"])
                return
            backoff = 1 if time.monotonic() - started > 60 else min(backoff * 2, 60)
            self.status["reconnects"] += 1
            await asyncio.sleep(backoff)

    async def fetch_candles(self, session, symbol: str, resolution: str, start: datetime, end: datetime) -> int:
        """Venue candles for the DATA-05 cross-check; raw responses go to the segment like every other source."""
        now = now_utc()
        try:
            raw = await self.rest_text(session, "/v1/udf/history", symbol=symbol, resolution=wallex.UDF_RESOLUTIONS[resolution],
                                      **{"from": int(start.timestamp()), "to": int(end.timestamp())})
            self.seg.write("rest:/v1/udf/history", raw, now)
            candles = wallex.parse_udf(raw)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            self.quality(now, symbol, "SOURCE_ERROR", f"udf history: {type(e).__name__}: {e}")
            return 0
        self.db.upsert_candles(symbol, resolution, candles, now)
        return len(candles)

    async def _housekeeping(self, session):
        last_reseed = last_candles = time.monotonic()
        reseed_cursor = candle_cursor = 0
        while True:
            await asyncio.sleep(2)
            self.tick(now_utc())
            symbols = list(self.books)
            if session and symbols and time.monotonic() - last_reseed > 60:
                last_reseed = time.monotonic()
                ordered = symbols[reseed_cursor:] + symbols[:reseed_cursor]
                stale = [s for s in ordered if s in self.tops and "STALE" in self.tops[s].flags][:RESEED_BATCH]
                reseed_cursor = (reseed_cursor + RESEED_BATCH) % len(symbols)
                if stale and self.status["connected"]:
                    await self.seed(session, stale, trades=False)
            if session and symbols and time.monotonic() - last_candles > CANDLE_REFRESH_S:
                last_candles, now = time.monotonic(), now_utc()
                batch = (symbols[candle_cursor:] + symbols[:candle_cursor])[:CANDLE_BATCH]
                candle_cursor = (candle_cursor + CANDLE_BATCH) % len(symbols)
                for sym in batch:
                    await self.fetch_candles(session, sym, "1min", now - timedelta(hours=2), now)

    async def run(self):
        if self.demo:
            return await asyncio.gather(self._housekeeping(None), self._demo())
        async with aiohttp.ClientSession(headers={"User-Agent": "TradingGYM/0.1 (observatory)"}) as session:
            await self.load_catalog(session)
            symbols = list(self.insts)
            if not symbols:
                raise RuntimeError("catalog produced no observable markets")
            batch_size = wallex.MAX_CHANNELS // 3
            shards = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
            await asyncio.gather(self._housekeeping(session),
                                 *(self._ws_loop(session, batch, i + 1) for i, batch in enumerate(shards)))

    # --- demo: synthetic Wallex-shaped frames through the same ingestion path ---
    def demo_frames(self, rng: random.Random, st: dict, now: datetime):
        """USDT legs random-walk with slowly changing drift; TMN legs follow USDT price x USDTTMN with a small premium."""
        px = st.setdefault("px", {"USDTTMN": Decimal(273500), "BTCUSDT": Decimal("76950"), "ETHUSDT": Decimal("2240")})
        st["n"] = st.get("n", 0) + 1
        if st["n"] % 720 == 1:
            st["mu"] = {s: rng.gauss(0, 0.00001) for s in px}
        for s in px:
            px[s] *= 1 + Decimal(rng.gauss(st["mu"][s], 0.0002)).quantize(Decimal("1e-7"))
        for s, inst in self.insts.items():
            usd = px.get(inst.base + "USDT")
            mid = px.get(s) or (usd * px["USDTTMN"] * (1 + Decimal(rng.gauss(0, 0.0003))).quantize(Decimal("1e-7")) if usd else None)
            if mid is None:
                continue
            tick = Decimal(1) if inst.quote == "TMN" else Decimal("0.01")
            half = (mid * Decimal("0.0007")).quantize(tick)
            for side, sign in (("buyDepth", -1), ("sellDepth", 1)):
                lv = [((mid + sign * (half + tick * k * 3)).quantize(tick), Decimal(rng.randint(1, 900)) / 100) for k in range(10)]
                msg = ",".join(f'{{"price":{p},"quantity":{q},"sum":{p * q}}}' for p, q in lv)
                yield s, f'{{"push":{{"channel":"orderbook:{s}@{side}","pub":{{"data":{{"message":[{msg}]}}}}}}}}'
            if rng.random() < 0.4:
                buy = rng.random() < 0.5
                p = (mid + (-half if buy else half)).quantize(tick)
                d = json.dumps({"isBuyOrder": buy, "price": str(p), "quantity": str(Decimal(rng.randint(1, 500)) / 100),
                                "timestamp": iso(now.replace(microsecond=0))[:19] + "Z"})
                yield s, f'{{"push":{{"channel":"public:{s}@trade","pub":{{"data":{d}}}}}}}'

    async def _demo(self):
        rng, st = random.Random(7), {}
        self.status["connected"] = True
        while True:
            for _, f in list(self.demo_frames(rng, st, now_utc())):
                self.handle_frame(f, now_utc())
            await asyncio.sleep(1)

    def demo_history(self, start: datetime, end: datetime, closed, step: timedelta = timedelta(seconds=10)):
        """Synthetic past for the demo store. A pair the rules close goes silent, as the venue's book does."""
        rng, st, t = random.Random(11), {}, start
        self.db.c.execute("begin")
        while t < end:
            for s, f in list(self.demo_frames(rng, st, t)):
                if not closed(s, t):
                    self.handle_frame(f, t)
            self.tick(t)
            t += step
        self.db.c.execute("commit")
