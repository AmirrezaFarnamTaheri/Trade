"""Historical universes are selected before evaluation without looking at future trades."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.model import TradeTick, iso
from gym.services.historical_universe import select_universe
from gym.services.research_actions import research_action
from gym.services.research_market import screen_markets
from tests.support import START, market_db, quote_history


def _receipt(db, symbol, amount, at):
    db.add_trade(TradeTick(symbol, at, at, Decimal("100"), Decimal(amount), "BUY"), "fixture")


def test_trade_volume_selection_uses_only_pre_start_receipts(tmp_path):
    """Later publication cannot turn a historically obscure market into a winner."""
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        old = START - timedelta(minutes=2)
        _receipt(db, "BTCUSDT", "1", old)
        _receipt(db, "ETHUSDT", "10", old)
        selected = select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1)
        assert selected["symbols"] == ["ETHUSDT", "BTCUSDT"]
        assert selected["as_of_exclusive"] == iso(START)
        _receipt(db, "BTCUSDT", "100000", START + timedelta(minutes=1))
        assert select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1) == selected
        _receipt(db, "BTCUSDT", "100000", START - timedelta(seconds=1))
        assert select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1)["symbols"][0] == "BTCUSDT"
    finally:
        db.c.close()


def test_market_screen_can_rank_as_of_top_n_and_flag_collection_gap(tmp_path):
    """As-of screening retains a market that later stopped publishing rather than survivorship-filtering it."""
    data = quote_history(n=180) + quote_history(n=30, sym="ETHUSDT")
    db = market_db(tmp_path, data)
    try:
        for symbol, quantity in (("BTCUSDT", "2"), ("ETHUSDT", "3")):
            _receipt(db, symbol, quantity, START - timedelta(minutes=5))
        request = {"symbols": [], "reference": "BTCUSDT", "quote_currency": "USDT",
                   "from": iso(START), "to": iso(START + timedelta(minutes=30)),
                   "resolution": "1min", "metric": "momentum_percent", "top_n": 2,
                   "lookback_hours": 1}
        report = screen_markets(db, request, store="live")
        assert report["universe_selection"]["symbols"] == ["ETHUSDT", "BTCUSDT"]
        row = next(r for r in report["excluded"] if r["symbol"] == "ETHUSDT")
        assert row["collection_status"]["status"] == "COLLECTION_GAP_OR_STOPPED"
        assert row["collection_status"]["delisted"] is None
    finally:
        db.c.close()


def test_portfolio_opt_in_top_n_saved_identity_contains_selection_vintage(tmp_path):
    """Opt-in historical selection is in the verified portfolio run identity."""
    from tests.test_portfolio_workflow import request

    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        for symbol, qty in (("BTCUSDT", "1"), ("ETHUSDT", "2")):
            _receipt(db, symbol, qty, START - timedelta(minutes=10))
    finally:
        db.c.close()
    value = {**request(), "symbols": [], "top_n": 2,
             "quote_currency": "USDT", "lookback_hours": 1}
    record = research_action(tmp_path, "portfolio-replay", value)
    loaded = research_action(tmp_path, "portfolio-read", {"run_id": record["run_id"]})
    assert loaded["inputs"]["portfolio_version"] == 6
    assert loaded["inputs"]["universe_selection"]["symbols"] == ["ETHUSDT", "BTCUSDT"]
    assert record["universe_selection"] == loaded["inputs"]["universe_selection"]
    assert loaded["inputs"]["store"] == "live"
