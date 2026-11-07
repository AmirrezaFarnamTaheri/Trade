"""Shared-cash portfolio replay over several markets."""
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import TradeTick, iso
from gym.domain.sim import CostModel
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def test_markets_share_one_cash_balance_and_equal_target_weights(tmp_path):
    db = market_db(tmp_path, quote_history(n=500) + quote_history(n=500, sym="ETHUSDT"))
    out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), resolution="1min", cash=Decimal(1000),
                    params={"fast": 2, "slow": 3})
    result = out["result"]
    assert set(result["markets"]) == {"BTCUSDT", "ETHUSDT"} and out["mode"] == "PORTFOLIO"
    first_buys = [next(o for o in result["markets"][s]["orders"] if o["side"] == "BUY" and o["status"] == "FILLED")
                  for s in ("BTCUSDT", "ETHUSDT")]
    # Each entry targets half of portfolio equity, so neither market can take the whole balance.
    for buy in first_buys:
        assert Decimal(buy["qty"]) * Decimal(buy["price"]) <= Decimal(501)
    assert Decimal(result["balances"]["USDT"]) >= 0 and result["curve"]
    assert out["performance"]["status"] == "AVAILABLE"
    assert out["run_id"] == portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), resolution="1min",
                                      cash=Decimal(1000), params={"fast": 2, "slow": 3})["run_id"]


def test_portfolio_rejects_mixed_quote_currencies_and_single_markets(tmp_path):
    db = market_db(tmp_path, quote_history(n=20) + quote_history(n=20, sym="BTCTMN"))
    with pytest.raises(ValueError, match="quote currency"):
        portfolio(db, ["BTCUSDT", "BTCTMN"], START, START + timedelta(hours=1))
    with pytest.raises(ValueError, match="2..8"):
        portfolio(db, ["BTCUSDT"], START, START + timedelta(hours=1))


def test_later_quotes_cannot_change_earlier_portfolio_marks(tmp_path):
    cutoff = START + timedelta(minutes=6, seconds=5)
    rows = [replace(q, ts_avail=q.ts_avail + timedelta(seconds=5))
            for q in quote_history(n=100) + quote_history(n=100, sym="ETHUSDT")]
    db = market_db(tmp_path, rows)
    try:
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17),
                           resolution="1min", params={"fast": 2, "slow": 3})
        for q in rows:
            if q.symbol == "BTCUSDT" and q.ts_avail >= cutoff:
                db.c.execute("UPDATE book_top SET bid=?, ask=? WHERE instrument_id=? AND ts_avail=?",
                             (str(q.bid + 1000), str(q.ask + 1000), "wallex:BTCUSDT", iso(q.ts_avail)))
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17),
                          resolution="1min", params={"fast": 2, "slow": 3})
        def prefix(out):
            return [p for p in out["result"]["curve"] if p[0] < iso(cutoff)]
        assert prefix(before) and prefix(before) == prefix(after)
    finally:
        db.c.close()


def test_depth_changes_change_portfolio_identity(tmp_path):
    rows = quote_history(n=100) + quote_history(n=100, sym="ETHUSDT")
    db = market_db(tmp_path, rows)
    try:
        outputs = []
        for offset in (1, 1000):
            for q in rows:
                depth = [[[str(q.bid), "100"]], [[str(q.ask), "0.00001"], [str(q.ask + offset), "100"]]]
                db.c.execute("UPDATE book_top SET depth=? WHERE instrument_id=? AND ts_avail=?",
                             (json.dumps(depth), "wallex:" + q.symbol, iso(q.ts_avail)))
            outputs.append(portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17),
                                     resolution="1min", params={"fast": 2, "slow": 3}, cost=CostModel(walk_depth=True)))
        assert outputs[0]["outputs_digest"] != outputs[1]["outputs_digest"]
        assert outputs[0]["run_id"] != outputs[1]["run_id"]
    finally:
        db.c.close()


def test_limit_print_changes_change_portfolio_identity(tmp_path):
    rows = quote_history(n=100) + quote_history(n=100, sym="ETHUSDT")
    db = market_db(tmp_path, rows)
    try:
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3},
                   "cost": CostModel(order_type="limit")}
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        for q in rows:
            db.add_trade(TradeTick(q.symbol, q.ts_avail, q.ts_avail, q.bid - 1, Decimal(10), "SELL"), "test-print")
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        assert before["outputs_digest"] != after["outputs_digest"]
        assert before["run_id"] != after["run_id"]
    finally:
        db.c.close()


def test_external_reference_changes_change_portfolio_identity(tmp_path):
    db = market_db(tmp_path, quote_history(n=100) + quote_history(n=100, sym="SOLUSDT"))
    try:
        options = {"resolution": "1min", "strategy_id": "relative-momentum",
                   "params": {"lookback": 2, "reference": "ETHUSDT"}}
        before = portfolio(db, ["BTCUSDT", "SOLUSDT"], START, START + timedelta(minutes=17), **options)
        for q in quote_history(n=100, sym="ETHUSDT"):
            db.add_book_top(q, None)
        after = portfolio(db, ["BTCUSDT", "SOLUSDT"], START, START + timedelta(minutes=17), **options)
        assert before["outputs_digest"] != after["outputs_digest"]
        assert before["run_id"] != after["run_id"]
    finally:
        db.c.close()


def test_resolved_asset_identity_changes_change_portfolio_identity(tmp_path):
    db = market_db(tmp_path, quote_history(n=100) + quote_history(n=100, sym="ETHUSDT"))
    try:
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3}}
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        db.c.execute("INSERT INTO instruments(instrument_id,symbol,base,quote) VALUES(?,?,?,?)",
                     ("wallex:BTCUSDT", "BTCUSDT", "XBT", "USDT"))
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        assert before["outputs_digest"] != after["outputs_digest"]
        assert before["run_id"] != after["run_id"]
    finally:
        db.c.close()


def test_alias_markets_cannot_double_count_one_base_asset(tmp_path):
    db = market_db(tmp_path, quote_history(n=100) + quote_history(n=100, sym="XBTUSDT"))
    try:
        for symbol in ("BTCUSDT", "XBTUSDT"):
            db.c.execute("INSERT INTO instruments(instrument_id,symbol,base,quote) VALUES(?,?,?,?)",
                         ("wallex:" + symbol, symbol, "BTC", "USDT"))
        with pytest.raises(ValueError, match="distinct base assets"):
            portfolio(db, ["BTCUSDT", "XBTUSDT"], START, START + timedelta(minutes=7),
                      resolution="1min", params={"fast": 2, "slow": 3})
    finally:
        db.c.close()
