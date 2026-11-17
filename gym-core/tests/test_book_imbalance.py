"""T13 trades only past its threshold, pays both touches and fees, and will not score before its window closes."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("book_imbalance", Path(__file__).resolve().parents[1] / "scripts/book_imbalance.py")
imbalance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imbalance)


def test_a_bid_heavy_book_buys_at_the_ask_and_sells_at_the_later_bid():
    book = [(0.0, 99.0, 101.0, 9.0, 1.0), (30.0, 99.0, 101.0, 1.0, 1.0), (61.0, 104.0, 106.0, 1.0, 1.0)]
    [(day, net)] = imbalance.trades(book, 0.6, 1)
    assert day == "1970-01-01"
    assert net == pytest.approx(104 / 101 - 1 - 2 * imbalance.FEE)


def test_balanced_books_do_not_trade_and_an_unfinished_hold_is_dropped():
    assert imbalance.trades([(0.0, 99.0, 101.0, 5.0, 5.0), (90.0, 99.0, 101.0, 5.0, 5.0)], 0.6, 1) == []
    assert imbalance.trades([(0.0, 99.0, 101.0, 1.0, 9.0), (30.0, 99.0, 101.0, 1.0, 9.0)], 0.6, 1) == []


def test_scoring_refuses_before_the_prospective_window_closes():
    with pytest.raises(SystemExit, match="would peek"):
        imbalance.score(None, 0.8, 5, now=datetime(2026, 12, 17, tzinfo=UTC))
