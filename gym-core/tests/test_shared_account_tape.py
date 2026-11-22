from datetime import timedelta
from decimal import Decimal

from gym.domain.model import BookTop, InstrumentId
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from tests.support import START


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
    first = market_order(book, inst, "BUY", Decimal("0.2"), START, Decimal(10),
                         quotes, 0, cost, Spec(), [], quota, "buy-1")
    remaining_display = quotes[0].ask_qty - Decimal(first["qty"])
    # Supply the residual capacity explicitly. This checks the accounting primitive.
    second = market_order(book, inst, "BUY", Decimal("0.25"), START, Decimal(10),
                          quotes, 0, cost, Spec(), [], quota, "buy-2", max_qty=remaining_display)
    assert Decimal(second["qty"]) == 1
    assert book.get("USDT") == 70 and book.get("A") == Decimal("2.97")
    assert book.equity(inst, Decimal(9)) == Decimal("96.73")
    exit_order = market_order(book, inst, "SELL", Decimal(1), quotes[0].ts_avail, Decimal(9),
                              quotes, 1, cost, Spec(), [], quota, "exit")
    assert exit_order["status"] == "FILLED"
    assert book.get("A") == 0 and book.get("USDT") == Decimal("96.4627")
