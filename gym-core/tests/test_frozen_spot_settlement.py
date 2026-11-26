import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.domain.sim import CashBook, CostModel
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from scripts.replay_spot_intents import (
    _frozen_fx_events,
    _opening_mid,
    _settle_frozen_fx,
    replay,
)
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
                              "cost": CostModel(fee_rate=Decimal(0)).describe()}}
    try:
        result = replay(db, tape, Decimal(1))
        assert result["orders"]["first"]["status"] == "FILLED"
        assert result["orders"]["second"]["reason"] == "DISPLAYED_CAPACITY_EXHAUSTED"
        assert result["orders"]["exit"]["status"] == "INFEASIBLE"
        assert result["balances"] == {"USDT": Decimal(200), "BTC": Decimal(1)}
        reserved_intents = [{**row, "decision_at": iso(START)} for row in intents[:2]]
        tape.update(intents=reserved_intents, intents_digest=digest(reserved_intents))
        tape["source_inputs"]["cash_by_currency"]["USDT"] = "150"
        reserved = replay(db, tape, Decimal(1), reserve=True)
        assert reserved["orders"]["first"]["status"] == "FILLED"
        assert reserved["orders"]["second"]["reason"] == "INSUFFICIENT_UNRESERVED_BALANCE"
        assert [row["event"] for row in reserved["reservations"]] == ["RESERVE", "RELEASE"]

        expiry_intents = [{**reserved_intents[0], "arrival_at": iso(START), "deadline": iso(START)},
                          {**reserved_intents[1], "decision_at": iso(arrival)}]
        tape.update(intents=expiry_intents, intents_digest=digest(expiry_intents))
        expired = replay(db, tape, Decimal(1), reserve=True)
        assert expired["orders"]["first"]["reason"] == "NO_QUALIFIED_QUOTE"
        assert expired["orders"]["second"]["status"] == "FILLED"
    finally:
        db.c.close()


def test_opening_mid_uses_first_qualified_receipt_after_replay_start(tmp_path):
    before = START - timedelta(seconds=1)
    at = START + timedelta(seconds=1)
    after = START + timedelta(seconds=2)
    db = market_db(tmp_path, [quote(before, "90", "92"), quote(START, "96", "98", {"STALE"}),
                              quote(at, "99", "101"), quote(after, "103", "105")])
    try:
        portal = DataPortal(db)
        assert _opening_mid(portal, "BTCUSDT", START, START) is None
        assert _opening_mid(portal, "BTCUSDT", START, after) == Decimal(100)
    finally:
        db.c.close()


def test_frozen_fx_batch_preserves_reserved_cash_and_is_atomic():
    book = CashBook({"TMN": Decimal(100)})
    reserved = defaultdict(Decimal, {"TMN": Decimal(25)})
    rows = [{"ref": "conversion", "ccy": "TMN", "amount": "-70", "kind": "sell"},
            {"ref": "conversion", "ccy": "USDT", "amount": "1", "kind": "buy"},
            {"ref": "conversion", "ccy": "TMN", "amount": "-10", "kind": "fee"}]
    assert _settle_frozen_fx(book, reserved, START, rows)["status"] == "INFEASIBLE"
    assert book.balances == {"TMN": Decimal(100)} and not book.postings
    reserved["TMN"] = Decimal(20)
    assert _settle_frozen_fx(book, reserved, START, rows)["status"] == "SETTLED"
    assert book.balances == {"TMN": Decimal(20), "USDT": Decimal(1)}


def test_frozen_fx_events_require_original_artifact_and_preserve_settlement_batches():
    row = {"t": iso(START), "ref": "fx/1", "ccy": "USDT", "amount": "1", "kind": "buy"}
    baseline = {"result": {"fx_orders": [{"ref": "fx/1"}],
                           "postings": [row, {**row, "kind": "rounding"}, {**row, "ref": "other"}]}}
    encoded = json.dumps(baseline, sort_keys=True, separators=(",", ":"))
    tape = {"run_sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    assert _frozen_fx_events(tape, baseline) == [(START, 1, 0, None, [row])]
    row["amount"] = "2"
    with pytest.raises(ValueError, match="canonical baseline"):
        _frozen_fx_events(tape, baseline)
