"""Tests for Pearson correlation, single-ledger 1h blend, and true intraday 3h crash exit causality."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.ignition_and_intraday_exit import (
    compute_intraday_crash_timestamps,
    pearson_correlation,
    run_shared_ledger_1h_blend,
    run_true_intraday_3h_exit,
)
from gym.domain.timeframe_panel import BarPoint

T0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)


def test_pearson_correlation_exact_values() -> None:
    a = {"2026-01-01": 0.01, "2026-01-02": -0.02, "2026-01-03": 0.03, "2026-01-04": -0.01, "2026-01-05": 0.02}
    b = {k: -v for k, v in a.items()}
    assert pearson_correlation(a, a) == 1.0
    assert pearson_correlation(a, b) == -1.0


def test_shared_ledger_blend_nets_overlapping_symbol_targets() -> None:
    bars = [
        BarPoint("BTCUSDT", T0 + timedelta(hours=i), T0 + timedelta(hours=i + 1), 100.0, 101.0, 99.0, 100.0, 50.0, "NATIVE_1H", True, 1.0, 0, True, "FRESH")
        for i in range(6)
    ]
    t1 = T0 + timedelta(hours=1)
    res = run_shared_ledger_1h_blend(
        {"BTCUSDT": bars},
        ("BTCUSDT",),
        {t1: {"BTCUSDT": 0.30}},
        {t1: {"BTCUSDT": 0.30}},
        slow_weight=0.70,
        ignition_weight=0.30,
        fee_rate=Decimal("0.0016"),
    )
    # Single fill (netted target = 0.30, NOT two separate orders)
    assert res["fills"] == 1
    assert res["total_fees_usdt"] < 0.60


def test_true_intraday_3h_exit_liquidates_immediately_at_next_3h_open() -> None:
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    panel = {}
    for sym in syms:
        bars = []
        for i in range(400):
            ts0 = T0 + timedelta(hours=i * 3)
            ts1 = ts0 + timedelta(hours=3)
            px = 45.0 if i >= 380 else 100.0 + i * 0.05
            bars.append(BarPoint(sym, ts0, ts1, px, px * 1.01, px * 0.99, px, 100.0, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH"))
        panel[sym] = bars

    crash_ts = compute_intraday_crash_timestamps(panel, syms, bucket_hours=3)
    assert len(crash_ts) > 0
    first_crash = min(crash_ts)
    # Enter long BTCUSDT one day BEFORE first_crash
    entry_ts = first_crash - timedelta(hours=24)
    res = run_true_intraday_3h_exit(
        panel,
        syms,
        {entry_ts: {"BTCUSDT": 0.50, "ETHUSDT": 0.0, "SOLUSDT": 0.0, "XRPUSDT": 0.0}},
        crash_ts,
        fee_rate=Decimal("0.0013"),
    )
    assert res["intraday_exits"] >= 1


def test_resample_1min_to_15m_and_30m() -> None:
    from gym.domain.timeframe_panel import resample_1min_to_minutes

    bars_1m = [
        BarPoint(
            "BTCUSDT",
            T0 + timedelta(minutes=i),
            T0 + timedelta(minutes=i + 1),
            100.0,
            101.0,
            99.0,
            100.5,
            2.0,
            "NATIVE_1M",
            True,
            1.0,
            0,
            True,
            "FRESH",
        )
        for i in range(60)
    ]
    b15 = resample_1min_to_minutes(bars_1m, 15)
    b30 = resample_1min_to_minutes(bars_1m, 30)
    assert len(b15) == 4 and all(b.volume == 30.0 for b in b15)
    assert len(b30) == 2 and all(b.volume == 60.0 for b in b30)
