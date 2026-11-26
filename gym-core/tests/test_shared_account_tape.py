import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.sim import CashBook, CostModel, SharedMarketReceipt, Spec
from gym.services.research_actions import research_action
from tests.support import START, market_db


def test_worked_shared_account_tape_reconciles_received_asset_fees():
    inst = InstrumentId.wallex("AUSDT", "A", "USDT")
    book = CashBook({"USDT": Decimal(100)})
    cost = CostModel(Decimal("0.01"), max_participation=Decimal(1))
    quotes = [
        BookTop("AUSDT", START + timedelta(seconds=1), Decimal(9), Decimal(10),
                Decimal(0), Decimal(3), frozenset()),
        BookTop("AUSDT", START + timedelta(seconds=2), Decimal(9), Decimal(10),
                Decimal(3), Decimal(10), frozenset()),
    ]
    quota = {}
    opening = SharedMarketReceipt(book, inst, quotes[0], cost, Spec(), [], quota)
    first = opening.execute("BUY", "2", START, Decimal(10), "buy-1")
    assert first["qty"] == "2" and first["cancelled_qty"] == "0"
    duplicate = opening.execute("BUY", "2", START, Decimal(10), "buy-1")
    assert duplicate["reason"] == "DUPLICATE_RECEIPT_FILL" and len(book.postings) == 3
    second = opening.execute("BUY", "2", START, Decimal(10), "buy-2")
    assert second["qty"] == "1" and second["cancelled_qty"] == "1"
    exhausted = opening.execute("BUY", "1", START, Decimal(10), "buy-3")
    assert exhausted["reason"] == "SHARED_DISPLAYED_CAPACITY_EXHAUSTED" and len(book.postings) == 6
    assert book.get("USDT") == 70 and book.get("A") == Decimal("2.97")
    assert book.equity(inst, Decimal(9)) == Decimal("96.73")
    closing = SharedMarketReceipt(book, inst, quotes[1], cost, Spec(), [], quota)
    exit_order = closing.execute("SELL", "2.97", quotes[0].ts_avail, Decimal(9), "exit")
    assert exit_order["status"] == "FILLED"
    assert book.get("A") == 0 and book.get("USDT") == Decimal("96.4627")


def test_shared_participation_cap_is_side_specific_and_nonfills_leave_capacity():
    inst = InstrumentId.wallex("AUSDT", "A", "USDT")
    book = CashBook({"USDT": Decimal(100), "A": Decimal(3)})
    at = START + timedelta(seconds=1)
    top = BookTop("AUSDT", at, Decimal(9), Decimal(10), Decimal(4), Decimal(6), frozenset())
    cost = CostModel(max_participation=Decimal("0.5"))
    batch = SharedMarketReceipt(book, inst, top, cost, Spec(min_notional=Decimal(9)), [], {})
    too_late = batch.execute("BUY", "2", at, Decimal(10), "too-late")
    assert too_late["reason"] == "NO_QUALIFIED_QUOTE" and not book.postings
    first = batch.execute("BUY", "2", START, Decimal(10), "buy-1")
    second = batch.execute("BUY", "2", START, Decimal(10), "buy-2")
    exit_order = batch.execute("SELL", "3", START, Decimal(9), "sell")
    assert (first["qty"], second["qty"], exit_order["qty"]) == ("2", "1.0", "2.0")
    assert exit_order["cancelled_qty"] == "1.0"


def test_spot_receipt_action_replays_stored_snapshot_and_refuses_ambiguous_time(tmp_path, capsys):
    from gym.cli import main

    at = START + timedelta(seconds=1)
    top = BookTop("BTCUSDT", at, Decimal(9), Decimal(10), Decimal(3), Decimal(3), frozenset())
    root = tmp_path / "live"
    db = market_db(root, [top])
    value = {"symbol": "BTCUSDT", "decision_at": iso(START), "receipt_at": iso(at), "cash_quote": "100",
             "inventory_base": "0", "fee_rate": "0.01", "max_participation": "1",
             "orders": [{"ref": ref, "side": "BUY", "quantity": "2", "decision_price": "10"} for ref in ("first", "second")]}
    try:
        replay = research_action(root, "spot-receipt-replay", value)
        assert replay["closing_balances"] == {"USDT": "70", "BTC": "2.97"}
        assert [row["cancelled_qty"] for row in replay["orders"]] == ["0", "1"]
        request = tmp_path / "request.json"
        request.write_text(json.dumps(value), encoding="utf-8")
        assert main(["--data", str(tmp_path), "research", "spot-receipt-replay", str(request)]) == 0
        assert replay == json.loads(capsys.readouterr().out)
        db.add_book_top(top, None)
        db.c.commit()
        with pytest.raises(ValueError, match="unambiguous stored book receipt"):
            research_action(root, "spot-receipt-replay", value)
    finally:
        db.c.close()
