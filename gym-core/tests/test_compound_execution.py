"""Compound paper orders must respect observed spread and displayed capacity at fill time."""
from datetime import timedelta
from decimal import Decimal
import pytest

from gym.domain.model import BookTop, InstrumentId
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from tests.support import START


def execute(side, bid, ask, quantity, *, limits):
    book = CashBook({"USDT":Decimal(1000),"BTC":Decimal(1) if side == "SELL" else Decimal(0)})
    top = BookTop("BTCUSDT",START+timedelta(seconds=1),Decimal(bid),Decimal(ask),quantity,quantity,frozenset())
    before = dict(book.balances)
    out = market_order(book,InstrumentId.wallex("BTCUSDT"),side,Decimal(1),START,Decimal(100),
                       [top],0,CostModel(),Spec(),[],{},"order",execution_limits=limits)
    return out,book,before


def test_widening_spread_cannot_fill_a_previously_accepted_compound_entry():
    limits = {"max_spread_bps":25,"participation_bps":1000}
    out,book,before = execute("BUY","90","110",Decimal(1000),limits=limits)
    assert out["status"] == "NONFILL" and out["reason"] == "ENTRY_SPREAD_LIMIT"
    assert book.balances == before and not book.postings


def test_compound_entry_cannot_consume_more_than_its_displayed_participation():
    limits = {"max_spread_bps":25,"participation_bps":1000}
    out,book,before = execute("BUY","99.99","100",Decimal(1),limits=limits)
    assert out["status"] == "NONFILL" and out["reason"] == "DISPLAYED_CAPACITY_LIMIT"
    assert book.balances == before and not book.postings


def test_wide_spread_does_not_suppress_a_risk_exit_with_sufficient_depth():
    out,book,_ = execute("SELL","90","110",Decimal(1000),limits={"max_spread_bps":25,"participation_bps":1000})
    assert out["status"] == "FILLED" and book.get("BTC") == 0


def test_unknown_depth_cannot_be_replaced_with_unlimited_paper_capacity():
    out,book,before = execute("SELL","99.99","100",None,limits={"max_spread_bps":25,"participation_bps":1000})
    assert out["status"] == "NONFILL" and out["reason"] == "DISPLAYED_CAPACITY_UNAVAILABLE"
    assert book.balances == before


@pytest.mark.parametrize("limits",[{}, {"max_spread_bps":True,"participation_bps":1000},
    {"max_spread_bps":25,"participation_bps":0},{"max_spread_bps":25,"participation_bps":10001}])
def test_invalid_fill_limits_are_refused(limits):
    with pytest.raises(ValueError,match="execution limits"):
        execute("BUY","99.99","100",Decimal(1000),limits=limits)


class EntryProbe:
    """Test-only fixed proposal isolates the shared native fill/context boundary."""
    name = "entry-probe"
    params = {}
    ready = True
    execution_limits = {"max_spread_bps":25,"participation_bps":1000}
    feature_values = {"stop_distance_bps":"100"}
    def decide(self,snapshot,holding):
        return ("HOLD",Decimal(0),(),"") if holding else ("BUY_REQUEST",Decimal('.001'),(),"")


def test_actual_fill_sets_cost_basis_stop_and_small_position_context(tmp_path):
    from gym.services.session import PaperSession
    from tests.support import market_db
    from gym.services.data_portal import DataPortal
    db = market_db(tmp_path,[])
    session = PaperSession(DataPortal(db),lambda _:[],EntryProbe(),"BTCUSDT",START,"1min",Decimal(1000),CostModel())
    def feed(second):
        session.feed(BookTop("BTCUSDT",START+timedelta(seconds=second),Decimal('99.99'),Decimal(100),Decimal(100),Decimal(100),frozenset()))
    try:
        feed(0)
        feed(60)
        assert session.pending is not None
        assert session.position_entry is None
        feed(61)
        assert session.orders[0]["status"] == "FILLED"
        assert session.position_entry == Decimal(1)/Decimal('.00999')
        assert session.position_stop == session.position_entry*Decimal('.99')
        feed(120)
        decision = session.decisions[-1]
        assert decision["action"] == "HOLD"  # A position below 1% of equity is still an actual position.
        assert decision["execution_known"]["entry_price"] == str(session.position_entry)
        assert decision["execution_known"]["position_id"] == session.orders[0]["ref"]
    finally:
        db.c.close()


def test_spread_rejection_does_not_create_position_or_stop_state(tmp_path):
    from gym.services.session import PaperSession
    from tests.support import market_db
    from gym.services.data_portal import DataPortal
    db = market_db(tmp_path,[])
    session = PaperSession(DataPortal(db),lambda _:[],EntryProbe(),"BTCUSDT",START,"1min",Decimal(1000),CostModel())
    try:
        for second,bid,ask in [(0,'99.99','100'),(60,'99.99','100'),(61,'90','110')]:
            session.feed(BookTop("BTCUSDT",START+timedelta(seconds=second),Decimal(bid),Decimal(ask),Decimal(100),Decimal(100),frozenset()))
        assert session.orders[0]["status"] == "NONFILL"
        assert session.position_entry is session.position_stop is None
        assert session.book.get("BTC") == 0
    finally:
        db.c.close()


def test_entry_guard_does_not_pretend_indicator_warmup_is_complete(tmp_path):
    from gym.services.session import PaperSession
    from gym.domain.registry import create_strategy
    from tests.support import market_db
    from gym.services.data_portal import DataPortal
    db = market_db(tmp_path,[])
    session = PaperSession(DataPortal(db),lambda _:[],create_strategy("trend-pullback"),"BTCUSDT",START,"1min",Decimal(1000),CostModel())
    try:
        for second in (0,60,120):
            session.feed(BookTop("BTCUSDT",START+timedelta(seconds=second),Decimal(90),Decimal(110),Decimal(100),Decimal(100),frozenset()))
        assert session.state == "WARMING_UP" and session.running_at is None
    finally:
        db.c.close()


def test_rounded_exit_retains_dust_basis_and_permits_next_entry(tmp_path):
    from gym.services.session import PaperSession
    from gym.services.data_portal import DataPortal
    from tests.support import market_db
    class RoundTrip(EntryProbe):
        def decide(self,snapshot,holding):
            return ("SELL_REQUEST",Decimal(1),(),"") if holding else super().decide(snapshot,holding)
    db = market_db(tmp_path,[])
    db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
        ("wallex:BTCUSDT",START.isoformat(),'{"stepSize":3,"minNotional":"0.5"}',"test"))
    db.c.commit()
    session = PaperSession(DataPortal(db),lambda _:[],RoundTrip(),"BTCUSDT",START,"1min",Decimal(1000),CostModel())
    try:
        for second in (0,60,61,120,121,180):
            session.feed(BookTop("BTCUSDT",START+timedelta(seconds=second),Decimal('99.99'),Decimal(100),Decimal(100),Decimal(100),frozenset()))
        assert [order["status"] for order in session.orders[:2]] == ["FILLED","FILLED"]
        assert session.book.get("BTC") == Decimal('.00099')
        decision = session.decisions[-1]
        assert decision["action"] == "BUY_REQUEST"
        assert decision["execution_known"]["position_state"] == "DUST"
        assert decision["execution_known"]["tradable_qty"] == "0"
        old_basis = session.position_entry
        old_cash = session.book.get("USDT")
        session.feed(BookTop("BTCUSDT",START+timedelta(seconds=181),Decimal('99.99'),Decimal(100),Decimal(100),Decimal(100),frozenset()))
        assert session.orders[-1]["status"] == "FILLED"
        assert session.position_entry == (Decimal('.00099')*old_basis+old_cash-session.book.get("USDT"))/session.book.get("BTC")
        assert sum(Decimal(p["amount"]) for p in session.book.postings if p["ccy"]=="BTC") == session.book.get("BTC")
    finally:
        db.c.close()
