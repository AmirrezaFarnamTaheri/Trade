"""Unit tests for Nobitex bulk orderbooks, liquidity pools, Centrifugo WS, and Wallex ratio/fairPrice feeds."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.adapters.nobitex import (
    parse_nobitex_all_orderbooks,
    parse_nobitex_centrifugo_push,
    parse_nobitex_liquidity_pools,
)
from gym.adapters.wallex_public_feeds import (
    parse_wallex_centrifugo_fair_price_push,
    parse_wallex_fair_prices,
    parse_wallex_margin_ratio,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from record_multi_venue_quotes import (  # noqa: E402
    init_quote_db,
    persist_fair_prices,
    persist_liquidity_pools,
    persist_margin_ratios,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def test_parse_nobitex_bulk_orderbooks_and_liquidity_pools() -> None:
    bulk = {
        "status": "ok",
        "BTCUSDT": {"bids": [["95000", "0.5"]], "asks": [["95010", "0.4"]]},
        "USDTIRT": {"bids": [["700000", "1000"]], "asks": [["700500", "900"]]},
    }
    snaps = parse_nobitex_all_orderbooks(bulk, ("BTCUSDT", "USDTIRT", "MISSING"), NOW)
    assert len(snaps) == 2
    assert snaps[0].symbol == "BTCUSDT" and snaps[0].bid == Decimal("95000")
    assert snaps[1].symbol == "USDTTMN" and snaps[1].bid == Decimal("70000")

    pools = parse_nobitex_liquidity_pools(
        {
            "status": "ok",
            "pools": {
                "usdt": {
                    "capacity": "7000000",
                    "filledCapacity": "6580000",
                    "APR": "2.64",
                    "profitPeriod": 31,
                    "minDelegation": "10",
                    "maxDelegation": "100000",
                },
                "btc": {"capacity": "40", "filledCapacity": "40", "APR": "3.78", "profitPeriod": 31},
            },
        },
        NOW,
    )
    assert len(pools) == 2
    usdt = next(p for p in pools if p.currency == "USDT")
    assert usdt.utilization_pct == Decimal("94.00")
    assert usdt.apr_pct == Decimal("2.64")


def test_parse_nobitex_centrifugo_ping_orderbook_and_trade() -> None:
    assert parse_nobitex_centrifugo_push("{}", NOW) == ("PING", None)

    ob_frame = json.dumps({
        "push": {
            "channel": "public:orderbook-ETHUSDT",
            "pub": {"data": json.dumps({"bids": [["3100", "2"]], "asks": [["3101", "1.5"]]}), "offset": 12},
        }
    })
    kind, qs = parse_nobitex_centrifugo_push(ob_frame, NOW)
    assert kind == "ORDERBOOK" and qs is not None and qs.symbol == "ETHUSDT"

    tr_frame = {
        "push": {
            "channel": "public:trades-BTCIRT",
            "pub": {"data": {"price": "65000000000", "volume": "0.01", "time": 1762781164192, "type": "sell"}},
        }
    }
    tkind, trade = parse_nobitex_centrifugo_push(tr_frame, NOW)
    assert tkind == "TRADE" and trade is not None
    assert trade.symbol == "BTCTMN" and trade.price == Decimal("6500000000") and trade.side == "SELL"


def test_parse_wallex_margin_ratio_and_fair_prices_and_sqlite_persistence(tmp_path: Path) -> None:
    ratio = parse_wallex_margin_ratio("BTCUSDT", {"success": True, "result": {"long_percents": 52, "short_percents": 48}}, NOW)
    assert ratio is not None and ratio.long_pct == Decimal("52") and ratio.short_pct == Decimal("48")
    assert parse_wallex_margin_ratio("BTCUSDT", {"success": False}, NOW) is None

    fp_rest = parse_wallex_fair_prices(
        {"ts": "2026-11-25T12:00:00Z", "prices": {"BTCUSDT": "95005.5", "ETHUSDT": "3100.25", "SHIBTMN": "1.2"}},
        NOW,
        symbols=("BTCUSDT", "ETHUSDT"),
    )
    assert len(fp_rest) == 2 and fp_rest[0].symbol == "BTCUSDT"

    kind, fp_ws = parse_wallex_centrifugo_fair_price_push(
        {"push": {"channel": "public:all@fairPrice", "pub": {"data": {"ts": "2026-11-25T12:00:05Z", "prices": {"BTCUSDT": "95010"}}}}},
        NOW,
        symbols=("BTCUSDT",),
    )
    assert kind == "FAIR_PRICE" and len(fp_ws) == 1 and fp_ws[0].fair_price == Decimal("95010")
    assert parse_wallex_centrifugo_fair_price_push("{}", NOW) == ("PING", [])

    db_path = tmp_path / "mv.sqlite3"
    con = init_quote_db(db_path)
    try:
        pools = parse_nobitex_liquidity_pools({"pools": {"usdt": {"capacity": "100", "filledCapacity": "90", "APR": "2.64"}}}, NOW)
        persist_liquidity_pools(con, pools)
        persist_margin_ratios(con, [ratio])
        persist_fair_prices(con, fp_ws)
        assert con.execute("SELECT COUNT(*) FROM venue_liquidity_pools").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM venue_margin_ratios").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM venue_fair_prices").fetchone()[0] == 1
    finally:
        con.close()
