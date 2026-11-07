"""Portfolio conversion uses causal FX marks and never disguises unavailable or stale rates."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from gym.domain.model import parse_ts
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote, quote_history


def replay(db):
    return portfolio(db, ["BTCTMN", "ETHTMN"], START, START + timedelta(minutes=30),
                     resolution="1min", params={"fast": 2, "slow": 3}, cash=Decimal(1000))


def rate(seconds, price):
    return replace(quote(START + timedelta(seconds=seconds), str(price - 1), str(price + 1)), symbol="USDTTMN")


def test_portfolio_fx_curve_never_reads_a_later_rate(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") +
                   [rate(0, 100), rate(900, 200)])
    try:
        out = replay(db)
        valuation = out["result"]["valuation"]
        assert out["inputs"]["portfolio_version"] == 3
        assert valuation["start"]["rate"] == "100" and valuation["end"]["rate"] == "200"
        before = [r for r in valuation["curve"] if parse_ts(r["at"]) < START + timedelta(minutes=15)]
        assert before and all(r["fx"]["rate"] == "100" for r in before)
        assert valuation["end"]["status"] == "STALE"
        expected = Decimal(out["result"]["end"]["equity"]) / 200 - Decimal(1000) / 100
        assert Decimal(out["result"]["end"]["net_usdt_eq"]) == expected.quantize(Decimal("0.0001"))
        old_id = out["run_id"]
        db.add_book_top(rate(1750, 300), None)
        changed = replay(db)
        assert changed["run_id"] != old_id
        assert changed["result"]["valuation"]["curve"][:10] == valuation["curve"][:10]
    finally:
        db.c.close()


def test_future_only_fx_cannot_value_start_or_net(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") + [rate(1500, 100)])
    try:
        out = replay(db)
        valuation = out["result"]["valuation"]
        assert valuation["start"]["status"] == "UNAVAILABLE"
        assert out["result"]["end"]["net_usdt_eq"] is None
        assert valuation["curve"][0]["equity_usdt_eq"] is None
    finally:
        db.c.close()


def test_usdt_portfolio_is_identity_valued(tmp_path):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30), resolution="1min")
        assert out["result"]["valuation"]["start"]["status"] == "IDENTITY"
        assert out["result"]["end"]["net_usdt_eq"] == out["result"]["end"]["net"]
    finally:
        db.c.close()


def test_closed_fx_boundary_keeps_old_rate_with_explicit_status(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") + [rate(0, 100)])
    try:
        out = portfolio(db, ["BTCTMN", "ETHTMN"], START, START + timedelta(hours=12), resolution="1min")
        assert out["result"]["valuation"]["end"]["status"] == "STALE_CLOSED"
        assert out["result"]["valuation"]["end"]["rate"] == "100"
    finally:
        db.c.close()
