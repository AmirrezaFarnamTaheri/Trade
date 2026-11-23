from datetime import timedelta
from decimal import Decimal

from gym.domain.model import iso
from gym.domain.strategy import digest
from scripts.replay_spot_intents import replay
from tests.support import START, market_db, quote


def test_frozen_orders_share_receipt_capacity_and_cannot_spend_unfilled_inventory(tmp_path):
    arrival = START + timedelta(seconds=1)
    exit_at = arrival + timedelta(seconds=1)
    db = market_db(tmp_path, [quote(arrival, "99", "100"), quote(exit_at, "99", "100")])
    buy = {"symbol": "BTCUSDT", "side": "BUY", "ref": "first", "amount_asset": "USDT", "amount": "100",
           "arrival_at": iso(arrival), "deadline": iso(arrival), "decision_price": "100"}
    intents = [buy, {**buy, "ref": "second"}, {**buy, "ref": "exit", "side": "SELL", "amount_asset": "BTC",
                                              "amount": "2", "arrival_at": iso(exit_at), "deadline": iso(exit_at)}]
    tape = {"schema": "spot-intents/1", "run_id": "fixture", "intents": intents, "intents_digest": digest(intents),
            "source_inputs": {"from": iso(START), "to": iso(exit_at + timedelta(seconds=1)),
                              "cash_by_currency": {"USDT": "300"}, "rules_mode": "point-in-time",
                              "cost": {"fee_rate": "0"}}}
    try:
        result = replay(db, tape, Decimal(1))
        assert result["orders"]["first"]["status"] == "FILLED"
        assert result["orders"]["second"]["reason"] == "DISPLAYED_CAPACITY_EXHAUSTED"
        assert result["orders"]["exit"]["status"] == "INFEASIBLE"
        assert result["balances"] == {"USDT": Decimal(200), "BTC": Decimal(1)}
    finally:
        db.c.close()
