"""Phase B read-only live market-data recorder for Nobitex & AbanTether + Wallex arb monitor (spec §8).

Observation-only public GET requests (no credentials, no order authority).
Persists normalized snapshots to data/live/phase_b_quotes.sqlite3.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
import sys
import time
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.adapters.abantether import ABANTETHER_INSTRUMENT_CATALOG
from gym.adapters.nobitex import (
    NOBITEX_ORDERBOOK_URL,
    evaluate_prefunded_arb_capital_day,
    nobitex_fee_schedule,
    parse_nobitex_orderbook,
)
from gym.domain.model import dec, iso
from gym.domain.venue_contracts import QuoteSnapshot

DEFAULT_NOBITEX_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "USDTIRT")
ABANTETHER_PUBLIC_COINS_URL = "https://abantether.com/api/v1/otc/coin-price/"


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _http_get_json(url: str, *, timeout: float = 10.0) -> dict | list:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),  # trust_env=False equivalent for *.ir direct routing
        urllib.request.HTTPSHandler(context=_tls_context()),
    )
    req = urllib.request.Request(url, headers={"User-Agent": "TradingGYM-PhaseB-Observer/1.0", "Accept": "application/json"})
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def init_quote_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS venue_quotes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "venue TEXT NOT NULL, "
        "symbol TEXT NOT NULL, "
        "ts_avail TEXT NOT NULL, "
        "bid TEXT NOT NULL, "
        "ask TEXT NOT NULL, "
        "bid_qty TEXT NOT NULL, "
        "ask_qty TEXT NOT NULL, "
        "spread_bps TEXT NOT NULL, "
        "depth_json TEXT"
        ")"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_venue_quotes_venue_sym_ts ON venue_quotes (venue, symbol, ts_avail)")
    con.commit()
    return con


def persist_quote_snapshot(con: sqlite3.Connection, qs: QuoteSnapshot) -> None:
    depth_payload = json.dumps(
        [
            [[str(p), str(q)] for p, q in qs.bid_levels[:5]],
            [[str(p), str(q)] for p, q in qs.ask_levels[:5]],
        ]
    )
    con.execute(
        "INSERT INTO venue_quotes (venue, symbol, ts_avail, bid, ask, bid_qty, ask_qty, spread_bps, depth_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            qs.venue,
            qs.symbol,
            iso(qs.ts_avail),
            str(qs.bid),
            str(qs.ask),
            str(qs.bid_qty),
            str(qs.ask_qty),
            str(qs.spread_bps.quantize(Decimal("0.01"))),
            depth_payload,
        ),
    )
    con.commit()


def fetch_nobitex_snapshots(symbols: tuple[str, ...] = DEFAULT_NOBITEX_SYMBOLS) -> list[QuoteSnapshot]:
    snaps: list[QuoteSnapshot] = []
    for sym in symbols:
        url = NOBITEX_ORDERBOOK_URL.format(symbol=sym)
        try:
            payload = _http_get_json(url, timeout=8.0)
            if isinstance(payload, dict):
                qs = parse_nobitex_orderbook(sym, payload, datetime.now(UTC))
                if qs is not None:
                    snaps.append(qs)
        except Exception as exc:
            print(f"[nobitex] fetch failed for {sym} ({url}): {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
    return snaps


def fetch_abantether_rwa_snapshots(url: str = ABANTETHER_PUBLIC_COINS_URL) -> list[QuoteSnapshot]:
    """Best-effort public OTC quote fetch for AbanTether RWA catalog symbols."""
    snaps: list[QuoteSnapshot] = []
    try:
        payload = _http_get_json(url, timeout=8.0)
    except Exception as exc:
        print(f"[abantether] fetch failed ({url}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return snaps
    rows = payload if isinstance(payload, list) else (payload.get("data") if isinstance(payload, dict) else [])
    if not isinstance(rows, list):
        return snaps
    now = datetime.now(UTC)
    for item in rows:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        if sym not in ABANTETHER_INSTRUMENT_CATALOG:
            continue
        buy_raw = item.get("usdtBuy") or item.get("priceBuy")
        sell_raw = item.get("usdtSell") or item.get("priceSell")
        if not buy_raw or not sell_raw:
            continue
        try:
            ask = dec(str(buy_raw))   # client buys at ask
            bid = dec(str(sell_raw))  # client sells at bid
        except Exception as exc:
            print(f"[abantether] invalid quote for {sym}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if bid <= 0 or ask <= 0 or bid > ask:
            continue
        snaps.append(
            QuoteSnapshot(
                venue="abantether",
                symbol=f"{sym}USDT",
                ts_event=None,
                ts_avail=now,
                bid=bid,
                ask=ask,
                bid_qty=Decimal("0"),
                ask_qty=Decimal("0"),
                bid_levels=((bid, Decimal("0")),),
                ask_levels=((ask, Decimal("0")),),
                flags=frozenset({"OTC_QUOTE"}),
            )
        )
    return snaps


def compare_live_wallex_vs_nobitex(wallex_db: Path, nobitex_snaps: list[QuoteSnapshot]) -> list[dict]:
    """Compare fresh Nobitex quotes against latest Wallex book_top using -30% Nobitex discount."""
    if not wallex_db.exists() or not nobitex_snaps:
        return []
    con = sqlite3.connect(f"file:{wallex_db.as_posix()}?mode=ro", uri=True, timeout=5.0)
    out: list[dict] = []
    nbx_sched = nobitex_fee_schedule("USDT", permanent_discount=Decimal("0.30"))
    _, nbx_taker = nbx_sched.effective_rates(datetime.now(UTC))
    try:
        for qs in nobitex_snaps:
            row = con.execute(
                "SELECT b.bid, b.ask, b.ts_avail FROM book_top b "
                "JOIN instruments i ON i.instrument_id = b.instrument_id "
                "WHERE i.symbol = ? AND b.bid IS NOT NULL AND b.ask IS NOT NULL "
                "ORDER BY b.rowid DESC LIMIT 1",
                (qs.symbol,),
            ).fetchone()
            if not row:
                continue
            w_bid, w_ask, w_ts = dec(row[0]), dec(row[1]), row[2]
            gap_buy_nbx_sell_wlx_bps = (w_bid - qs.ask) / qs.ask * Decimal(10000)
            gap_buy_wlx_sell_nbx_bps = (qs.bid - w_ask) / w_ask * Decimal(10000)
            best_dir = "BUY_NBX_SELL_WLX" if gap_buy_nbx_sell_wlx_bps >= gap_buy_wlx_sell_nbx_bps else "BUY_WLX_SELL_NBX"
            best_gap = max(gap_buy_nbx_sell_wlx_bps, gap_buy_wlx_sell_nbx_bps)
            buy_px = qs.ask if best_dir == "BUY_NBX_SELL_WLX" else w_ask
            sell_px = w_bid if best_dir == "BUY_NBX_SELL_WLX" else qs.bid
            buy_fee = nbx_taker if best_dir == "BUY_NBX_SELL_WLX" else Decimal("0.0013")
            sell_fee = Decimal("0.0013") if best_dir == "BUY_NBX_SELL_WLX" else nbx_taker
            arb = evaluate_prefunded_arb_capital_day(
                buy_venue_ask=buy_px,
                sell_venue_bid=sell_px,
                leg1_filled_qty=Decimal("1"),
                leg2_filled_qty=Decimal("1"),
                buy_fee_rate=buy_fee,
                sell_fee_rate=sell_fee,
                replenishment_transfer_fee_usdt=Decimal("0"),
                residual_unwind_slippage_bps=Decimal("0"),
                total_prefunded_capital_usdt=buy_px * Decimal("2"),
                cycle_days=Decimal("1"),
            )
            out.append(
                {
                    "symbol": qs.symbol,
                    "nobitex_bid": str(qs.bid),
                    "nobitex_ask": str(qs.ask),
                    "wallex_bid": str(w_bid),
                    "wallex_ask": str(w_ask),
                    "wallex_ts": w_ts,
                    "best_direction": best_dir,
                    "raw_cross_gap_bps": round(float(best_gap), 2),
                    "net_after_fees_per_unit": round(float(arb.net_proceeds_usdt), 4),
                }
            )
    finally:
        con.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only multi-venue Nobitex & AbanTether quote recorder")
    parser.add_argument("--db", type=Path, default=Path("D:/Github/Trade/data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--wallex-db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--once", action="store_true", help="Capture one cycle and exit")
    parser.add_argument("--interval-s", type=float, default=30.0)
    args = parser.parse_args()

    con = init_quote_db(args.db)
    try:
        while True:
            nbx = fetch_nobitex_snapshots()
            abn = fetch_abantether_rwa_snapshots()
            for qs in (*nbx, *abn):
                persist_quote_snapshot(con, qs)
            arbs = compare_live_wallex_vs_nobitex(args.wallex_db, nbx)
            print(f"Recorded nobitex={len(nbx)} abantether={len(abn)} into {args.db}")
            for row in arbs:
                print(
                    f"  {row['symbol']}: {row['best_direction']} raw_gap={row['raw_cross_gap_bps']}bps "
                    f"nbx={row['nobitex_bid']}/{row['nobitex_ask']} wlx={row['wallex_bid']}/{row['wallex_ask']}"
                )
            if args.once:
                break
            time.sleep(args.interval_s)
    finally:
        con.close()


if __name__ == "__main__":
    main()
