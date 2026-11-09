"""Long-history study: verified downloads, no leakage across splits, margin mechanics, reference results."""

import contextlib
import hashlib
import importlib.util
import io
import math
import zipfile
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pytest


@pytest.fixture
def lhs():
    spec = importlib.util.spec_from_file_location(
        "long_history_study", Path(__file__).parents[1] / "scripts/long_history_study.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def series(n=1500, phase=0.0, swing=0.05):
    closes = [100.0]
    for i in range(1, n):
        closes.append(closes[-1] * (1 + swing * math.sin(i * 1.7 + phase) + 0.02 * math.sin(i * 0.05) + 0.0005))
    return closes


def days(n, start=date(2018, 1, 1)):
    return [(start + timedelta(i)).strftime("%Y-%m-%dT00:00") for i in range(n)]


def kline_zip(rows):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("k.csv", "\n".join(rows))
    return buffer.getvalue()


def test_results_match_the_reference_implementation(lhs):
    closes = series()
    signals, vol = lhs.trend_signals(closes, 1), lhs.realized_vol(closes, 1)
    # Values from the straightforward (non-incremental) browser implementation the report used.
    for rule, vt, band, equity, trades in (
        (("sma", 50), None, 0, 129.3493327900889, 48),
        (("sma", 50), 0.5, 0, 40.553652543926574, 735),
        (("sma", 50), 0.5, 0.2, 35.02705406351086, 48),
        (("mom", 90), 0.5, 0.2, 0.007303590376379373, 44),
    ):
        moves = [0.0] + [b / a - 1 for a, b in pairwise(closes)]
        r, _, n, _ = lhs.run(moves, lhs.target(signals[rule], vol, vt), 0.003, band)
        assert math.prod(1 + v for v in r) == pytest.approx(equity, rel=1e-6)
        assert n == trades


def shocked(closes, times, cut):
    k = times.index(cut)
    return closes[:k] + [v * (3 if i % 2 else 0.3) for i, v in enumerate(closes[k:])]


def test_train_choice_and_walk_forward_ignore_later_prices(lhs):
    a, b = series(), series(phase=1.0)
    times = days(len(a))
    quiet = contextlib.redirect_stdout(io.StringIO())
    with quiet:
        base = lhs.report({"A": (times, a), "B": (times, b)}, 0.003, "1d", "2020-01-01", "2021-01-01")
        moved = lhs.report(
            {"A": (times, shocked(a, times, "2020-01-01T00:00")), "B": (times, shocked(b, times, "2020-01-01T00:00"))},
            0.003, "1d", "2020-01-01", "2021-01-01",
        )
    assert moved["chosen"] == base["chosen"]  # validation and test bars never reach the ranking
    assert base["walk_forward"][0].startswith("2020:") and moved["walk_forward"][0] == base["walk_forward"][0]


def test_fetch_keeps_only_checksum_matches(lhs, tmp_path, monkeypatch):
    body = kline_zip(["1704067200000,1,1,1,42000.5,0"])
    good = f"{hashlib.sha256(body).hexdigest()}  BTCUSDT-1d-2024-01.zip".encode()
    monkeypatch.setattr(lhs, "get", lambda url: good if url.endswith(".CHECKSUM") else body)
    lhs.fetch(["BTCUSDT"], (2024, 1), "1d", tmp_path)
    assert (tmp_path / "1d/BTCUSDT-1d-2024-01.zip").read_bytes() == body
    monkeypatch.setattr(lhs, "get", lambda url: good if url.endswith(".CHECKSUM") else body + b"x")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        lhs.fetch(["ETHUSDT"], (2024, 1), "1d", tmp_path)
    assert not list((tmp_path / "1d").glob("ETHUSDT*"))


def test_load_reads_millisecond_and_microsecond_files_and_rejects_holes(lhs, tmp_path):
    folder = tmp_path / "1d"
    folder.mkdir()
    (folder / "BTCUSDT-1d-2024-12.zip").write_bytes(kline_zip(["open_time,o,h,l,close,v", "1735603200000,1,1,1,93000,0"]))
    (folder / "BTCUSDT-1d-2025-01.zip").write_bytes(kline_zip(["1735689600000000,1,1,1,94000,0"]))
    assert lhs.load("BTCUSDT", "1d", tmp_path) == (["2024-12-31T00:00", "2025-01-01T00:00"], [93000.0, 94000.0])
    (folder / "BTCUSDT-1d-2025-02.zip").write_bytes(kline_zip(["1738454400000000,1,1,1,95000,0"]))  # 2025-02-02
    with pytest.raises(SystemExit, match="holes"):
        lhs.load("BTCUSDT", "1d", tmp_path)


def test_every_signal_family_ignores_later_prices(lhs):
    times = days(1500)
    data = {"BTCUSDT": (times, series()), "ETHUSDT": (times[200:], series(1300, 1.0)), "XRPUSDT": (times, series(phase=2.0))}
    later = {s: (t, shocked(c, t, "2020-06-01T00:00")) for s, (t, c) in data.items()}
    base, _, base_skill = lhs.signals(data, 1)
    moved, _, moved_skill = lhs.signals(later, 1)
    assert {"btcf", "xsm", "ridge", "don", "tsm"} <= {family for family, _ in base}
    for family, per_symbol in base.items():
        for symbol, values in per_symbol.items():
            k = data[symbol][0].index("2020-06-01T00:00")
            assert moved[family][symbol][:k] == values[:k], (family, symbol)
            assert any(v is not None for v in values), (family, symbol)
    # Forecasts made before the shock are identical too: the model never fitted on later outcomes.
    for lam, pairs in base_skill.items():
        before = [f for t, f, _ in pairs if t < "2020-05-20"]
        assert before and before == [f for t, f, _ in moved_skill[lam] if t < "2020-05-20"]


def test_donchian_matches_a_brute_force_scan(lhs):
    closes = series(600)
    pos, expected = 0.0, []
    for i, c in enumerate(closes):
        if i < 20:
            expected.append(None)
            continue
        if c > max(closes[i - 20:i]):
            pos = 1.0
        elif c < min(closes[i - 10:i]):
            pos = 0.0
        expected.append(pos)
    assert lhs.donchian(closes, 1, 20) == expected


def test_solver_recovers_known_coefficients(lhs):
    assert lhs.solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0]) == pytest.approx([1.0, 3.0])
    assert lhs.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0]) is None


def test_short_earns_on_a_fall_and_pays_carry(lhs):
    r, x, trades, liquidated = lhs.run([0.0, -0.1, 0.0], [-1.0, -1.0, -1.0], 0.003, carry=0.001)
    assert r[1] == pytest.approx((1 - 0.003) * 1.1 - 0.001 - 1)
    assert r[2] == pytest.approx(-0.001) and x[1:] == [-1.0, -1.0] and (trades, liquidated) == (1, 0)


def test_levered_long_is_liquidated_at_the_margin_floor(lhs):
    r, x, _, liquidated = lhs.run([0.0, -0.45, 0.2], [2.0, 2.0, 2.0], 0.0, liquidation=0.15)
    assert r[1] == pytest.approx(-0.9) and liquidated == 1  # equity 0.1 is below 15% of the 1.1 still held
    assert x[2] == 2.0 and r[2] == pytest.approx(0.4)  # the target reopens the position on the next bar


def test_margin_positions_reopen_when_their_term_ends(lhs):
    _, _, trades, _ = lhs.run([0.0] * 30, [-1.0] * 30, 0.01, roll=21)
    r, *_ = lhs.run([0.0] * 30, [-1.0] * 30, 0.01, roll=21)
    assert trades == 1 and r[22] == pytest.approx(-0.02)  # one round trip charged at the 21-day reopen


def test_only_margin_markets_short_or_borrow(lhs):
    times = days(700)
    data = {"AUSDT": (times, series(700, swing=0.01)), "BUSDT": (times, series(700, 1.0, swing=0.01))}
    each, _ = lhs.sleeves(data, dict.fromkeys(data, 0.003), 1, frozenset({"AUSDT"}))
    runs = dict(each)
    shorted = [c for c in runs if c[4] == "ls" and c[5] == 2.0]
    assert shorted and any(c[5] == 4.0 for c in runs)  # credit ratios 1, 2 and 4
    assert any(min(runs[c]["AUSDT"][1]) < 0 for c in shorted) and any(max(runs[c]["AUSDT"][1]) > 1 for c in shorted)
    assert all(0 <= v <= 1 for c in shorted for v in runs[c]["BUSDT"][1])
    plain, _ = lhs.sleeves(data, dict.fromkeys(data, 0.003), 1)
    assert all(c[4] == "long" and c[5] == 1.0 for c, _ in plain)  # no margin markets: no duplicate configurations
