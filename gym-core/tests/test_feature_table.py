"""Feature rows are causal, hand-checkable, and never carry a guessed label."""
import importlib.util
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("feature_table", Path(__file__).resolve().parents[1] / "scripts/feature_table.py")
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)


def series(count, step=0.001):
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(count)]
    closes = [100.0 * (1 + step) ** i for i in range(count)]
    return days, closes


def test_rows_start_after_warmup_and_match_hand_arithmetic():
    days, closes = series(210)
    rows = table.rows_for("X", days, closes, horizon=5, cost=0.004)
    assert len(rows) == 10 and rows[0]["day"] == days[200]
    first = rows[0]
    assert first["ret_1d"] == pytest.approx(0.001)
    assert first["ret_20d"] == pytest.approx(1.001 ** 20 - 1)
    assert first["sma200_gap"] == pytest.approx(closes[200] / (sum(closes[1:201]) / 200) - 1)
    assert first["dd_from_high_200"] == 0.0  # a rising series is always at its high
    assert first["range_pos_20"] == pytest.approx(1.0)
    assert first["vol20"] == pytest.approx(math.sqrt(math.log(1.001) ** 2 * 365))


def test_labels_are_forward_net_of_cost_and_the_tail_has_none():
    days, closes = series(210)
    rows = table.rows_for("X", days, closes, horizon=5, cost=0.004)
    assert rows[0]["label_net_fwd"] == pytest.approx(closes[205] / closes[200] - 1 - 0.004)
    assert rows[0]["label_win"] == 1
    assert all(row["label_net_fwd"] == "" for row in rows[-5:])  # no forward close: no label, never a guess
    assert all(row["label_net_fwd"] != "" for row in rows[:-5])


def test_features_never_see_the_future():
    days, closes = series(210)
    base = table.rows_for("X", days, closes, horizon=5, cost=0.004)[0]
    crashed = closes[:201] + [1.0] * 9  # everything after the first emitted day collapses
    again = table.rows_for("X", days, crashed, horizon=5, cost=0.004)[0]
    assert {k: v for k, v in again.items() if k in table.FEATURES} == {k: v for k, v in base.items() if k in table.FEATURES}
    assert again["label_win"] == 0  # only the label changed


def test_mismatched_inputs_are_refused():
    days, closes = series(210)
    with pytest.raises(ValueError, match="differ in length"):
        table.rows_for("X", days[:-1], closes, horizon=5, cost=0.004)
