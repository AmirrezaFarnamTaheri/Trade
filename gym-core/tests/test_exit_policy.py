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


def test_venue_stop_uses_received_trades_keeps_waiting_balance_free_and_works_partial_fills(tmp_path):
    from gym.domain.model import BookTop, TradeTick
    from gym.services.data_portal import DataPortal
    from gym.services.session import PaperSession

    class EnterOnce:
        name, params = "probe", {"exit_venue_stop": 1, "exit_stop_bps": 500}
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
        db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=62), START + timedelta(seconds=64),
                               Decimal(90), Decimal(1), "SELL"), None)
        feed(63, "90")  # crossing quotes alone, and an unreceived trade, do not activate a venue stop
        assert session.book.get("BTC") == held and session.venue_stop["activation"] is None
        feed(64, "90", "1")
        assert session.book.get("BTC") == held - Decimal("0.25")
        assert session.venue_stop["activation"] == START + timedelta(seconds=64)
        feed(122, "89")
        assert Decimal(session.decisions[-1]["balances_before"]["BTC"]) == held - Decimal("0.25")
        assert session.decisions[-1]["t"] == (START + timedelta(seconds=120)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        assert session.book.get("BTC") == 0 and session.venue_stop is None
        stops = [o for o in session.orders if o.get("kind") == "VENUE_STOP_MARKET"]
        assert len(stops) == 2 and all(o["status"] == "FILLED" for o in stops)
        assert all(Decimal(v) >= 0 for v in session.book.balances.values())
        assert stops[0]["trigger_event_time"] != stops[0]["trigger_available_at"]
        with pytest.raises(ValueError, match="fixed exit stop"):
            create_strategy("ema-trend", {"exit_venue_stop": 1})
        with pytest.raises(ValueError, match="fixed stop only"):
            create_strategy("ema-trend", {"exit_venue_stop": 1, "exit_stop_bps": 500, "exit_atr_multiple": 2})
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
    ({"exit_profit_bps": 100}, 102, "PAPER_PROFIT_EXIT"), ({"exit_after_bars": 1}, 100, "PAPER_TIME_EXIT")])
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
