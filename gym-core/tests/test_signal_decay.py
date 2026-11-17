"""Signal decay measures the move from a late entry and counts only signals with a full horizon after them."""
import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("signal_decay", SCRIPTS / "signal_decay.py")
decay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decay)


def test_a_late_entry_misses_the_part_of_the_move_already_made():
    # Bid-heavy books, and the mid climbs 1 unit per quote (10 s apart) on a price of about 100.
    book = [(10.0 * i, 99.0 + i, 101.0 + i, 9.0, 1.0) for i in range(100)]
    by_delay, spread = decay.decay(book, horizon=100, delays=(0, 5), stride=10)
    n0, move0 = by_delay[0]
    n5, move5 = by_delay[5]
    assert n0 == n5 > 0 and move0 > 0 and move5 > 0
    assert move5 < move0  # later entries start from a higher price
    assert 0 < spread < (101 / 99 - 1) * 10000  # the spread in bps shrinks as the price climbs


def test_balanced_books_give_no_signals():
    book = [(10.0 * i, 99.0, 101.0, 5.0, 5.0) for i in range(50)]
    by_delay, spread = decay.decay(book)
    assert all(n == 0 for n, _ in by_delay.values()) and spread is None
