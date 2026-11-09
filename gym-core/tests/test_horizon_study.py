"""Multi-horizon study: complete buckets only, no lookahead at any frame, honest maker fills, train-only weights."""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


@pytest.fixture
def hz():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("horizon_study", SCRIPTS / "horizon_study.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def minutes(n=6000, start=1_767_225_600, phase=0.0):  # 2026-01-01T00:00Z
    out, price = {}, 100.0
    for i in range(n):
        price *= 1 + 0.002 * math.sin(i * 0.37 + phase) + 0.001 * math.sin(i * 0.011)
        volume = 10 + 5 * math.sin(i * 0.13)
        out[start + 60 * i] = (price * 1.001, price * 0.999, price, volume, volume * (0.5 + 0.3 * math.sin(i * 0.05)))
    return out


def test_resample_keeps_only_complete_buckets(hz):
    bars = minutes(30)
    del bars[1_767_225_600 + 60 * 7]  # a hole inside the second 5-minute bucket
    times, highs, lows, closes, volume, _ = hz.resample(bars, 5)
    assert len(times) == 5 and 1_767_225_600 + 300 not in times
    first = [bars[1_767_225_600 + 60 * i] for i in range(5)]
    assert (highs[0], lows[0], closes[0]) == (max(b[0] for b in first), min(b[1] for b in first), first[-1][2])
    assert volume[0] == pytest.approx(sum(b[3] for b in first))


def test_every_signal_at_every_frame_ignores_later_minutes(hz):
    base = minutes()
    cut = 1_767_225_600 + 60 * 4000
    later = {t: (b if t < cut else (b[0] * 3, b[1] * 3, b[2] * 3, b[3] * 7, b[4])) for t, b in base.items()}
    for frame in hz.FRAMES[:5]:
        a, b = hz.resample(base, frame), hz.resample(later, frame)
        k = next(i for i, t in enumerate(a[0]) if t + frame * 60 > cut)  # bars whose close is before the cut
        for family, values in hz.signals(base, a, frame).items():
            assert hz.signals(later, b, frame)[family][:k] == values[:k], (frame, family)


def test_maker_fills_only_when_the_next_bar_trades_through(hz):
    highs, lows, closes = [100.0, 100.5, 100.5], [100.0, 99.96, 99.9], [100.0, 100.2, 100.0]
    r, x, trades = hz.maker(highs, lows, closes, [1.0, 1.0, 1.0], 0.001, 0.0005)
    assert x == [0.0, 0.0, 1.0] and trades == 1  # 99.96 does not trade through the 99.95 limit; 99.9 does
    assert r[2] == pytest.approx(100.0 / (100.2 * 0.9995) - 1 - 0.001)


def test_combined_weights_come_from_train_days_only(hz):
    sleeves = {"a": {d: (0.01 if d % 2 else -0.01) for d in range(10)}, "b": {d: (0.02 if d % 2 else -0.02) for d in range(10)}}
    days, _, weights = hz.combine(sleeves, [0, 5, 8, 10])
    assert days == list(range(10)) and weights["a"] == pytest.approx(2 / 3)
    sleeves["b"].update({d: 0.5 for d in range(5, 10)})  # later days never move the weights
    assert hz.combine(sleeves, [0, 5, 8, 10])[2] == weights


def test_report_runs_end_to_end_on_synthetic_minutes(hz, capsys):
    data = {"AUSDT": minutes(30000), "BUSDT": minutes(30000, phase=1.0)}
    splits = ("2026-01-01", "2026-01-10", "2026-01-15", "2026-01-21")
    out = hz.report(data, {"AUSDT": 0.0002, "BUSDT": 0.0005}, margin={"AUSDT"}, splits=splits)
    text = capsys.readouterr().out
    assert "Gross edge before costs" in text and "Multi-horizon portfolio" in text
    assert set(out) >= {"all", "high", "mid", "weights"}
