"""Shared exits act on actual fills, not signal prices or assumed holdings."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId
from gym.domain.registry import create_strategy
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from gym.services.paper import paper
from tests.support import START, market_db, quote_history
from tests.test_channel_strategies import snapshot


@pytest.mark.parametrize("mode", (1, 2))
def test_venue_stop_uses_received_trades_keeps_waiting_balance_free_and_works_partial_fills(tmp_path, mode):
    from gym.domain.model import BookTop, TradeTick
    from gym.services.data_portal import DataPortal
    from gym.services.session import PaperSession

    class EnterOnce:
        name, params = "probe", {"exit_venue_stop": mode, "exit_stop_bps": 500}
        requires_position_context = True
        feature_values = {}
        entered = False

        def decide(self, snap, holding):
            action = "HOLD" if self.entered else "BUY_REQUEST"
            self.entered = True
            return action, Decimal(1), (), "probe"

    db = market_db(tmp_path, [])
    try:
        session = PaperSession(DataPortal(db), lambda _: [], EnterOnce(), "BTCUSDT", START, "1min", Decimal(1000),
                               CostModel(fee_rate=Decimal(0), max_participation=Decimal("0.25")))
        def feed(seconds, bid="100", size="100"):
            session.feed(BookTop("BTCUSDT", START + timedelta(seconds=seconds), Decimal(bid), Decimal(bid) + 1,
                                 Decimal(size), Decimal(100), frozenset()))
        for at in (0, 60, 61):
            feed(at)
        assert session.venue_stop and session.pending is None
        held = session.book.get("BTC")
        if mode == 2:
            # A high print raises the stop only after receipt. Its event time follows the later-received dip.
            db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=63), START + timedelta(seconds=63),
                                   Decimal(110), Decimal(1), "BUY"), None)
        db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=62), START + timedelta(seconds=64),
                               Decimal(100 if mode == 2 else 90), Decimal(1), "SELL"), None)
        feed(63, "90")  # crossing quotes alone, and an unreceived trade, do not activate a venue stop
        assert session.book.get("BTC") == held and session.venue_stop["activation"] is None
        if mode == 2:
            assert session.venue_stop["price"] == Decimal("104.5")
        feed(64, "90", "1")
        if mode == 2:
            assert session.book.get("BTC") == held  # same-receipt quote precedes the modeled order
            feed(65, "90", "1")
        assert session.book.get("BTC") == held - Decimal("0.25")
        assert session.venue_stop["activation"] == START + timedelta(seconds=64)
        feed(122, "89")
        assert Decimal(session.decisions[-1]["balances_before"]["BTC"]) == held - Decimal("0.25")
        assert session.decisions[-1]["t"] == (START + timedelta(seconds=120)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        assert session.book.get("BTC") == 0 and session.venue_stop is None
        kind = "VENUE_TRAILING_STOP_MARKET" if mode == 2 else "VENUE_STOP_MARKET"
        stops = [o for o in session.orders if o.get("kind") == kind]
        assert len(stops) == 2 and all(o["status"] == "FILLED" for o in stops)
        assert all(Decimal(v) >= 0 for v in session.book.balances.values())
        assert stops[0]["trigger_event_time"] != stops[0]["trigger_available_at"]
        if mode == 2:
            assert stops[0]["high_water"] == "110"
            assert stops[0]["active_at"] > stops[0]["trigger_available_at"]
        with pytest.raises(ValueError, match="fixed exit stop"):
            create_strategy("ema-trend", {"exit_venue_stop": 1})
        with pytest.raises(ValueError, match="fixed stop only"):
            create_strategy("ema-trend", {"exit_venue_stop": 1, "exit_stop_bps": 500, "exit_atr_multiple": 2})
    finally:
        db.c.close()


def test_historical_stop_limit_waits_after_gap_and_recovers_without_double_spending(tmp_path):
    from gym.adapters.run_store import save_run
    from gym.domain.model import TradeTick, iso
    from gym.services.research_actions import research_action
    from tests.support import quote

    def at(seconds):
        return START + timedelta(seconds=seconds)

    partial = replace(quote(at(210), "67000", "67100"), bid_qty=Decimal("0.02"))
    tops = quote_history(n=20, turn=1) + [quote(at(200), "67000", "67100"), quote(at(205), "63000", "63100"),
        quote(at(208), "67000", "67100", ("CLOSED",)), partial, replace(partial, bid_qty=Decimal(1)),
        quote(at(220), "67000", "67100")]
    db = market_db(tmp_path, tops)
    try:
        db.add_trade(TradeTick("BTCUSDT", at(185), at(185), Decimal("70050"), Decimal(1), "BUY"), None)
        db.add_trade(TradeTick("BTCUSDT", at(195), at(200), Decimal("63000"), Decimal(1), "SELL"), None)
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3, "exit_venue_stop": 3,
                   "exit_stop_bps": 500, "exit_stop_limit_offset_bps": 100},
                   "cost": CostModel(fee_rate=Decimal(0), max_participation=Decimal("0.25"))}
        result = paper(db, "BTCUSDT", START, at(240), **options)
        order, gap, first, last = result["result"]["orders"]
        assert order["protection"]["status"] == "WAITING_FOR_TRADE"
        assert order["protection"]["reference"][1] == iso(at(185))
        assert gap["reason"] == "STOP_LIMIT_NOT_MARKETABLE" and gap["observed_at"] == iso(at(205))
        assert all(o["kind"] == "VENUE_STOP_LIMIT" for o in (gap, first, last))
        assert first["trigger_event_time"] == iso(at(195)) and first["trigger_available_at"] == iso(at(200))
        assert first["fill_time"] == iso(at(210)) and Decimal(first["qty"]) == Decimal("0.005")
        assert last["fill_time"] == iso(at(220)) and Decimal(last["residual_base"]) == 0
        assert all(Decimal(o["price"]) >= Decimal(o["limit_price"]) for o in (first, last))
        assert result["result"]["session"]["venue_stop_model"] == "received-trade-marketable-stop-limit/1"
        save_run(result, tmp_path / "runs")
        for seconds in (200, 210):
            count = sum(top.ts_avail <= at(seconds) for top in tops)
            checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": result["run_id"], "quote_count": count})["record"]
            assert checkpoint["cursor"] == iso(at(seconds))
            assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"
        db.c.execute("UPDATE trades SET price='65000' WHERE ts_avail=?", (iso(at(185)),))
        refused = paper(db, "BTCUSDT", START, at(240), **options)
        assert refused["run_id"] != result["run_id"]
        assert refused["result"]["orders"][0]["protection"]["status"] == "NOT_BELOW_REFERENCE"
    finally:
        db.c.close()


def test_sub_precision_entry_cannot_spend_cash_without_receiving_base():
    book = CashBook({"USDT": Decimal(1000), "BTC": Decimal(1)})
    top = quote_history(n=1)[0]
    before = dict(book.balances)
    result = market_order(book, InstrumentId.wallex("BTCUSDT"), "BUY", Decimal("0.0000000000000000000000000000001"),
        START - timedelta(seconds=1), top.ask, [top], 0, CostModel(), Spec(), [], {}, "tiny")
    assert result["status"] == "NONFILL" and result["reason"] == "NET_BASE_ROUNDS_TO_ZERO"
    assert book.balances == before


@pytest.mark.parametrize("params,price,reason", [({"exit_stop_bps": 100}, 98, "PAPER_STOP_EXIT"),
    ({"exit_profit_bps": 100}, 102, "PAPER_PROFIT_EXIT"), ({"exit_after_bars": 1}, 100, "PAPER_TIME_EXIT"),
    ({"exit_stop_bps": 100, "exit_venue_stop": 1, "exit_after_bars": 1}, 98, "PAPER_TIME_EXIT")])
def test_exit_from_actual_position_does_not_wait_for_entry_indicator_warmup(params, price, reason):
    strategy = create_strategy("ema-trend", params)
    snap = replace(snapshot(1, price), execution={"entry_price": "100", "entry_time": START.isoformat(),
        "position_id": "actual-fill", "fee_rate": "0.001"})
    assert strategy.decide(snap, True)[2] == (reason,)


def test_atr_trailing_exit_does_not_lower_its_stop_after_an_observation_gap():
    strategy = create_strategy("ema-trend", {"fast": 2, "slow": 3, "exit_atr_multiple": 2})
    for i in range(20):
        snap = replace(snapshot(i, 100 + i), execution={"entry_price": "100", "entry_time": START.isoformat(),
            "position_id": "actual-fill", "fee_rate": "0.001"})
        strategy.decide(snap, True)
    stop = Decimal(strategy.feature_values["exit_stop_price"])
    snap = replace(snapshot(20, 110, gap=20), execution=snap.execution)
    assert strategy.decide(snap, True)[2] == ("PAPER_STOP_EXIT",)
    assert Decimal(strategy.feature_values["exit_stop_price"]) >= stop


def test_default_exit_controls_preserve_strategy_identity():
    assert create_strategy("ema-trend", {"exit_stop_bps": 0, "exit_profit_bps": 0, "exit_atr_multiple": 0, "exit_after_bars": 0}).config_hash == create_strategy("ema-trend").config_hash


@pytest.mark.parametrize("params", [{"exit_stop_bps": True}, {"exit_stop_bps": 10000}, {"exit_atr_multiple": -1}, {"exit_after_bars": "5"}])
def test_invalid_exit_controls_fail_closed(params):
    with pytest.raises(ValueError):
        create_strategy("ema-trend", params)


@pytest.mark.parametrize("cost", [CostModel(), CostModel(max_participation=Decimal("0.001"), carry_remainder=True)])
def test_time_exit_uses_first_actual_fill_and_cancels_working_entry(tmp_path, cost):
    db = market_db(tmp_path, quote_history(n=300))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=40), resolution="1min",
                    params={"fast": 2, "slow": 3, "exit_after_bars": 2}, cost=cost)
        result = out["result"]
        sells = [d for d in result["decisions"] if "PAPER_TIME_EXIT" in d["reasons"]]
        assert sells
        for decision in sells:
            known = decision["execution_known"]
            assert known["position_id"] and known["entry_time"]
            assert Decimal(known["entry_price"]) > 0
        assert any(o["side"] == "SELL" and o["status"] == "FILLED" for o in result["orders"])
        assert Decimal(result["balances"]["USDT"]) >= 0
    finally:
        db.c.close()
