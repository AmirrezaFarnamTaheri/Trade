"""Shared-cash portfolio replay over several markets."""
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import TradeTick, iso, parse_ts
from gym.domain.sim import CostModel
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
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
    fills = [order for market in result["markets"].values() for order in market["orders"]
             if order["status"] == "FILLED"]
    notional = sum(Decimal(order["qty"]) * Decimal(order["price"]) for order in fills)
    activity = out["performance"]["activity"]
    assert Decimal(activity["turnover"]) == (notional / Decimal(1000)).quantize(Decimal("0.0001"))
    assert activity["return_per_turnover"] is not None
    assert activity["exposure_matched_hold_pct"] is None
    assert out["performance"]["trade_statistics_status"] == "NOT_APPLICABLE"
    assert out["run_id"] == portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), resolution="1min",
                                      cash=Decimal(1000), params={"fast": 2, "slow": 3})["run_id"]


def test_frozen_spot_intents_keep_decision_bounds_and_replay_identity(tmp_path):
    db = market_db(tmp_path, quote_history(n=360) + quote_history(n=360, sym="ETHUSDT"))
    intents = []
    options = {"resolution": "1min", "params": {"fast": 2, "slow": 3},
               "cost": CostModel(latency=timedelta(seconds=2), max_wait=timedelta(seconds=12))}
    args = (db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1))
    try:
        out = portfolio(*args, **options, intent_sink=intents.append)
        assert out == portfolio(*args, **options)
        orders = {row["ref"]: row for market in out["result"]["markets"].values() for row in market["orders"]}
        assert len(intents) == len(orders)
        assert {row["side"] for row in intents} == {"BUY", "SELL"}
        for row in intents:
            at = parse_ts(row["decision_at"])
            assert parse_ts(row["quote_at"]) <= at
            assert parse_ts(row["arrival_at"]) == at + options["cost"].latency
            assert parse_ts(row["deadline"]) == at + options["cost"].max_wait
            assert row["amount_asset"] == ("USDT" if row["side"] == "BUY" else row["symbol"][:-4])
            assert Decimal(row["amount"]) > 0 and row["snapshot"]
            assert orders[row["ref"]]["decision_time"] == row["decision_at"]
        assert Decimal(intents[0]["amount"]) == 500
        with pytest.raises(ValueError, match="intent capture requires"):
            portfolio(*args, intent_sink=intents.append, cost=CostModel(carry_remainder=True))
    finally:
        db.c.close()


def test_portfolio_rejects_mixed_quote_currencies_and_single_markets(tmp_path):
    db = market_db(tmp_path, quote_history(n=20) + quote_history(n=20, sym="BTCTMN"))
    with pytest.raises(ValueError, match="quote currency"):
        portfolio(db, ["BTCUSDT", "BTCTMN"], START, START + timedelta(hours=1))
    with pytest.raises(ValueError, match="2..500"):
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


@pytest.mark.parametrize("walk_depth", [False, True])
def test_batched_digest_keeps_legacy_decimal_flags_and_receipt_order(tmp_path, walk_depth):
    symbols = ["BTCUSDT", "ETHUSDT"]
    rows = [top for symbol in symbols for top in quote_history(n=257, step=1, sym=symbol)]
    db = market_db(tmp_path, rows)
    end = START + timedelta(minutes=5)
    try:
        repeated = replace(rows[1], bid=Decimal("6.25E+4"))
        db.add_book_top(repeated, None, '[[["2.0", "3"]], []]')
        db.c.execute("UPDATE book_top SET flags='CROSSED,,STALE,CROSSED', bid='+00062500.00', bid_qty=NULL,"
                     " ask_qty='-0.000', ts_avail=? WHERE rowid=(SELECT max(rowid) FROM book_top)",
                     (repeated.ts_avail.strftime("%Y-%m-%dT%H:%M:%SZ"),))
        portal = DataPortal(db)
        decoded = {symbol: {"limit_trades": [],
                            "quotes": [(iso(q.ts_avail), q.bid, q.ask, q.bid_qty, q.ask_qty, sorted(q.flags),
                                        *((q.depth,) if walk_depth else ()))
                                       for q in portal.iter_tops(symbol, START, end)]}
                   for symbol in symbols}
        archived = portfolio(db, symbols, START, end, resolution="1min", cost=CostModel(walk_depth=walk_depth))
        assert archived["inputs"]["data"] == digest(decoded)
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


@pytest.mark.parametrize("mode", (1, 2))
def test_stop_trade_receipts_change_shared_cash_portfolio_identity(tmp_path, mode):
    rows = quote_history(n=100) + quote_history(n=100, sym="ETHUSDT")
    db = market_db(tmp_path, rows)
    try:
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3, "exit_stop_bps": 500, "exit_venue_stop": mode}}
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        for q in rows:
            db.add_trade(TradeTick(q.symbol, q.ts_avail, q.ts_avail, q.bid * Decimal("0.9"), Decimal(1), "SELL"), "stop-print")
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=17), **options)
        assert before["inputs"]["stop_trades"] != after["inputs"]["stop_trades"]
        assert before["run_id"] != after["run_id"]
        assert Decimal(after["result"]["balances"]["USDT"]) >= 0
        kind = "VENUE_TRAILING_STOP_MARKET" if mode == 2 else "VENUE_STOP_MARKET"
        assert any(o.get("kind") == kind for market in after["result"]["markets"].values() for o in market["orders"])
    finally:
        db.c.close()


def test_dynamic_route_retains_ownership_through_partial_stop_limit(tmp_path):
    import asyncio

    from gym.adapters.run_store import save_run
    from gym.services.research_actions import research_action
    from gym.services.research_ledger import ResearchLedger
    from gym.services.research_process import calculate

    def at(seconds):
        return START + timedelta(seconds=seconds)

    usdt = quote_history(n=33, turn=1)
    usdt[20:] = [replace(q, bid=Decimal(63000), ask=Decimal(63100)) if q.ts_avail < at(240) else
                 replace(q, bid=Decimal(67000), ask=Decimal(67100), bid_qty=Decimal("0.01") if q.ts_avail == at(240) else Decimal(1))
                 for q in usdt[20:]]
    tmn = [replace(q, symbol="BTCTMN", bid=q.bid * 120, ask=q.ask * 120) for q in quote_history(n=33, turn=1)]
    # After activation the alternate becomes cheaper, but the first fill leaves inventory on the original route.
    fx = [replace(usdt[0], symbol="USDTTMN", ts_avail=at(seconds), bid=Decimal(bid), ask=Decimal(bid + 2))
          for seconds, bid in ((-1, 99), (100, 99), (190, 99), (230, 139))]
    db = market_db(tmp_path, usdt + tmn + fx)
    params = {"fast": 2, "slow": 3, "exit_stop_bps": 500, "exit_venue_stop": 3}
    opening = {"USDT": "1000", "TMN": "100000"}
    symbols = ["BTCUSDT", "BTCTMN"]
    try:
        db.add_trade(TradeTick("BTCUSDT", at(185), at(185), Decimal(70050), Decimal(1), "BUY"), None)
        db.add_trade(TradeTick("BTCUSDT", at(195), at(200), Decimal(63000), Decimal(1), "SELL"), None)
        out = portfolio(db, symbols, START, at(330), resolution="1min", dynamic_routes=True,
                        cash_by_currency=opening, params=params,
                        cost=CostModel(fee_rate=Decimal(0), max_participation=Decimal("0.25")))
        result = out["result"]
        stops = [o for o in result["markets"]["BTCUSDT"]["orders"] if o.get("kind") == "VENUE_STOP_LIMIT"]
        assert [o["status"] for o in stops] == ["NONFILL", "FILLED", "FILLED"]
        assert Decimal(stops[1]["residual_base"]) > 0 and Decimal(stops[2]["residual_base"]) == 0
        assert all(row["decision_time"] > stops[2]["fill_time"] for row in result["markets"]["BTCTMN"]["orders"])
        switch, = [row for row in result["route_changes"] if row["selected"] == "BTCTMN"]
        assert switch["at"] > stops[2]["fill_time"]
        direct_path = save_run(out, tmp_path / "runs" / "portfolios")
        direct_bytes = direct_path.read_bytes()
        count = sum(START <= q.ts_avail <= at(240) for q in usdt + tmn + fx)
        checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": count})["record"]
        resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})
        assert resumed["result_digest"] == out["outputs_digest"]
        due = iso(at(330))
        with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
            hypothesis = ledger.register({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": params})
            ledger.schedule({"hypothesis_id": hypothesis["hypothesis_id"], "first_at": due, "every_seconds": 3600,
                             "lookback_seconds": 330, "resolution": "1min", "cash": "1000", "fee_rate": "0",
                             "max_participation": "0.25", "dynamic_routes": True,
                             "cash_by_currency": opening, "portfolio_symbols": symbols})
        completed, = asyncio.run(calculate(tmp_path, "tick", at=due))["completed"]
        assert completed["run_id"] == out["run_id"]
        scheduled = research_action(tmp_path, "portfolio-read", {"run_id": completed["run_id"]})
        assert scheduled["outputs_digest"] == out["outputs_digest"]
        assert direct_path.read_bytes() == direct_bytes
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

def test_limit_portfolio_engine_identity_separates_diagnostic_revisions(tmp_path):
    """Limit-portfolio result changes must not reuse pre-diagnostics run identities."""
    from gym.services.session import ENGINE_VERSION, LIMIT_ENGINE_VERSION

    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3}}
        market = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30), **options)
        limit = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30),
                          cost=CostModel(order_type="limit"), **options)
        assert market["inputs"]["engine"] == ENGINE_VERSION
        assert limit["inputs"]["engine"] == LIMIT_ENGINE_VERSION
        assert market["run_id"] != limit["run_id"]
    finally:
        db.c.close()
