"""T14 holds the strongest qualifying coin, waits in USDT otherwise, and charges both legs of a rotation."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("strongest_coin", SCRIPTS / "strongest_coin.py")
strongest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strongest)

DAYS = [f"d{i:04}" for i in range(400)]


def test_the_faster_riser_is_held_and_fallers_leave_the_rule_in_usdt():
    rows = strongest.rotate({"UP": (DAYS, [100 * 1.003 ** i for i in range(400)]),
                             "FAST": (DAYS, [100 * 1.006 ** i for i in range(400)]),
                             "DOWN": (DAYS, [100 * 0.997 ** i for i in range(400)])}, 90)
    held = {h for _, _, h in rows[strongest.ELIGIBLE + strongest.WEEK:]}
    assert held == {"FAST"}
    assert all(h is None for _, _, h in rows[:strongest.ELIGIBLE - 1])


def test_a_rotation_pays_both_legs_and_entry_pays_one():
    up = [100.0] * 200 + [100 * 1.01 ** i for i in range(200)]
    later = [100.0] * 300 + [100 * 1.03 ** i for i in range(100)]
    rows = strongest.rotate({"A": (DAYS, up), "B": (DAYS, later)}, 30)
    returns = {day: r for day, r, _ in rows}
    entry = next(i for i, (_, _, h) in enumerate(rows) if h == "A")
    switch = next(i for i, (_, _, h) in enumerate(rows) if h == "B")
    assert returns[DAYS[entry]] == pytest.approx(1.01 * (1 - strongest.COST) - 1)
    assert returns[DAYS[switch]] == pytest.approx(1.03 * (1 - 2 * strongest.COST) - 1)


def test_reviews_never_use_later_closes():
    base = {"A": (DAYS, [100 + (i % 23) + i * 0.2 for i in range(400)]), "B": (DAYS, [100 + (i % 31) + i * 0.25 for i in range(400)])}
    changed = {coin: (days, closes[:300] + [c * 5 for c in closes[300:]]) for coin, (days, closes) in base.items()}
    assert [h for _, _, h in strongest.rotate(base, 30)][:299] == [h for _, _, h in strongest.rotate(changed, 30)][:299]
