"""Deterministic market observations and database factories shared by tests."""
from datetime import datetime, timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB
from gym.domain.model import UTC, BookTop
from gym.services.rules import RuleService

START = datetime(2026, 10, 29, 9, tzinfo=UTC)  # 12:30 Tehran: USDTTMN open


def quote(t, bid, ask, flags=()):
    return BookTop("BTCUSDT", t, Decimal(bid), Decimal(ask), Decimal(1), Decimal(1), frozenset(flags))


def quote_history(n=2000, step=10, sym="BTCUSDT", turn=0.5):
    """Up until `turn` of the way through, then down: EMA trades at least twice. `turn=1` only rises."""
    out, px = [], Decimal(70000)
    for i in range(n):
        px += Decimal(3) if i < n * turn else Decimal(-3)
        out.append(BookTop(sym, START + timedelta(seconds=step * i), px - 5, px + 5, Decimal(1), Decimal(1), frozenset()))
    return out


def supplied_otc_quote(*, price="98", expiry_seconds=180):
    return {"quote": {"symbol": "USDTTMN", "side": "BUY",
                      "received_at": (START + timedelta(seconds=5)).isoformat(),
                      "price": price, "price_expires_at": (START + timedelta(seconds=expiry_seconds)).isoformat()},
            "market": {"symbol": "USDTTMN", "received_at": START.isoformat(), "buyStatus": "ENABLE",
                       "sellStatus": "ENABLE", "minQty": "1", "minNotional": "1", "maxNotional": "100000"},
            "max_base_quantity": "10", "fee_rate": "0.001", "settlement_seconds": 5}


def market_db(tmp_path, rows, preset_at=START - timedelta(days=30)):
    db = MarketDB(tmp_path / "market.db")
    for x in rows:
        db.add_book_top(x, None)
    RuleService(db).preset("usdt-irt-october-2026", preset_at)
    return db


