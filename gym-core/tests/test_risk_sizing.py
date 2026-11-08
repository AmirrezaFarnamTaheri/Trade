"""Entry risk uses the native exact model and cannot reuse another order's budget."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import TradeTick, iso
from gym.domain.registry import create_strategy
from gym.domain.sim import CostModel
from gym.services.paper import paper
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history
from tests.test_simulation import _limit_session


def known_specs(db):
    for symbol in ("BTCUSDT", "ETHUSDT"):
        db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
            ("wallex:" + symbol, iso(START), '{"stepSize":8,"minNotional":"0.01"}', "synthetic test"))


def test_risk_sizing_requires_an_explicit_fixed_exit_and_preserves_disabled_identity():
    assert create_strategy("ema-trend", {"entry_risk_bps": 0}).config_hash == create_strategy("ema-trend").config_hash
    with pytest.raises(ValueError, match="fixed"):
        create_strategy("ema-trend", {"entry_risk_bps": 10})


def test_native_single_market_risk_budget_is_logged_with_exact_quantity(tmp_path):
    db = market_db(tmp_path, quote_history(n=300))
    known_specs(db)
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=40), resolution="1min",
                    params={"fast": 2, "slow": 3, "entry_risk_bps": 10, "exit_stop_bps": 100})
        entries = [d for d in out["result"]["decisions"] if d["action"] == "BUY_REQUEST"]
        assert entries and entries[0]["feature_values"]["entry_sizing"]["status"] == "SIZED"
        first = next(o for o in out["result"]["orders"] if o["side"] == "BUY" and o["status"] == "FILLED")
        assert Decimal(first["qty"]) * Decimal(first["price"]) <= Decimal("100.001")
    finally:
        db.c.close()


@pytest.mark.parametrize("cost", [CostModel(), CostModel(max_participation=Decimal("0.001"), carry_remainder=True)])
def test_shared_portfolio_budget_includes_filled_and_pending_entries(tmp_path, cost):
    db = market_db(tmp_path, quote_history(n=300) + quote_history(n=300, sym="ETHUSDT"))
    known_specs(db)
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=20), resolution="1min", cost=cost,
            params={"fast": 2, "slow": 3, "entry_risk_bps": 10, "exit_stop_bps": 100}, policy={})
        buys = [o for row in out["result"]["markets"].values() for o in row["orders"] if o["side"] == "BUY" and o["status"] == "FILLED"]
        assert buys
        assert sum(Decimal(o["qty"]) * Decimal(o["price"]) for o in buys) <= Decimal(101)
        assert Decimal(out["result"]["balances"]["USDT"]) >= Decimal(899)
    finally:
        db.c.close()


@pytest.mark.parametrize("minimum", [None, "1000"])
def test_unknown_or_unaffordable_minimum_abstains_without_orders(tmp_path, minimum):
    db = market_db(tmp_path, quote_history(n=300))
    if minimum is not None:
        known_specs(db)
        db.c.execute("UPDATE instrument_specs SET spec=?", ('{"stepSize":8,"minNotional":"1000"}',))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=20), resolution="1min",
                    params={"fast": 2, "slow": 3, "entry_risk_bps": 10, "exit_stop_bps": 100})
        assert not out["result"]["orders"]
        assert any(d["action"] == "ABSTAIN_RISK_SIZING" for d in out["result"]["decisions"])
    finally:
        db.c.close()


def test_rules_becoming_unknown_after_decision_prevent_market_fill(tmp_path):
    db = market_db(tmp_path, quote_history(n=300))
    known_specs(db)
    db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
        ("wallex:BTCUSDT", iso(START + timedelta(minutes=3, seconds=1)), '{}', "synthetic metadata loss"))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=20), resolution="1min",
                    params={"fast": 2, "slow": 3, "entry_risk_bps": 10, "exit_stop_bps": 100})
        assert not out["result"]["fills"]
        assert any(o.get("reason") == "UNKNOWN_RISK_SIZING_RULES" for o in out["result"]["orders"])
    finally:
        db.c.close()


@pytest.mark.parametrize("metadata_loss", [False, True])
def test_risk_limit_partials_recheck_capacity_and_metadata(tmp_path, metadata_loss):
    _, session = _limit_session(tmp_path, [], queue="0")
    db = session.portal.db
    known_specs(db)
    session.strategy = create_strategy("ema-trend", {"entry_risk_bps": 10, "exit_stop_bps": 100})
    session.track_positions = True
    if metadata_loss:
        db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
            ("wallex:BTCUSDT", iso(START + timedelta(seconds=24)), '{}', "synthetic metadata loss"))
    try:
        from dataclasses import replace
        top = session.portal.tops("BTCUSDT", START, START + timedelta(seconds=21))[-1]
        for seconds, quantity in ((25, "0.3"), (30, "0.3"), (35, "2")):
            at = START + timedelta(seconds=seconds)
            db.add_trade(TradeTick("BTCUSDT", at, at, Decimal(100), Decimal(quantity), "SELL"), "synthetic test")
            session.settle(replace(top, ts_avail=at), at)
        fills = [o for o in session.orders if o["status"] == "FILLED"]
        if metadata_loss:
            assert not fills and session.orders[-1]["reason"] == "UNKNOWN_RISK_SIZING_RULES"
        else:
            assert len(fills) == 3
            spent = Decimal(1000) - session.book.get("USDT")
            assert Decimal(99) < spent <= Decimal(100)
            assert all(Decimal(o["fee"]) == Decimal(o["qty"]) * session.cost.maker_fee for o in fills)
    finally:
        db.c.close()
