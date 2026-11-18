"""The spot breakout buys only on a new 20-day high and leaves on its holding limit or a new 20-day low."""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("held_out_followups", SCRIPTS / "held_out_followups.py")
followups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(followups)


def bars(closes):
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(closes))]
    return {"days": days, "close": closes, "low": closes, "high": closes, "open": closes, "volume": [1e9] * len(closes)}


def test_a_new_low_never_opens_a_short_and_a_new_high_buys():
    falling = [100.0] * 60 + [90.0, 85.0, 80.0]
    rule, hold = followups.breakout_long(bars(falling), [True] * len(falling))
    assert all(r == 0.0 for _, r in rule) and hold[-1][1] < 0
    rising = [100.0] * 60 + [110.0, 111.0, 112.0]
    rule, _ = followups.breakout_long(bars(rising), [True] * len(rising))
    assert rule[-1][1] > 0 and rule[-2][1] > 0


def test_a_new_low_closes_an_open_long():
    closes = [100.0] * 60 + [110.0, 111.0, 60.0, 61.0, 62.0]
    rule, _ = followups.breakout_long(bars(closes), [True] * len(closes))
    assert rule[-1][1] == 0.0 and rule[-2][1] == 0.0  # sold at the new low, then flat


def test_the_forward_record_refuses_to_score_before_its_last_day_has_passed():
    import pytest
    with pytest.raises(SystemExit, match="unfinished days"):
        followups.forward(today="2027-02-08")
