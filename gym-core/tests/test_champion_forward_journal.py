"""Unit tests for Champion Ensemble Forward Journal (1min->1h stitching, safety guard, forward scoring)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gym.domain.timeframe_panel import BarPoint
from gym.services.experiments.champion_forward_journal import (
    _resample_1min_to_1h,
    record_champion_ensemble_journal,
    score_champion_forward_journal,
)


def test_resample_1min_to_1h_builds_complete_hour_bars_only() -> None:
    t0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    bars_full = [
        BarPoint(
            symbol="BTCUSDT",
            ts_start=t0 + timedelta(minutes=m),
            ts_avail=t0 + timedelta(minutes=m + 1),
            open=100.0 + m * 0.1,
            high=101.0 + m * 0.1,
            low=99.0,
            close=100.0 + (m + 1) * 0.1,
            volume=2.0,
            bar_source="1min",
            clock_complete=True,
            nonzero_volume_fraction=1.0,
            last_trade_age_bars=0,
            entry_eligible=True,
            mark_status="LIVE",
        )
        for m in range(60)
    ]
    # Add an incomplete 20-minute next hour that must be dropped (<45 bars)
    bars_partial = [
        BarPoint(
            symbol="BTCUSDT",
            ts_start=t0 + timedelta(hours=1, minutes=m),
            ts_avail=t0 + timedelta(hours=1, minutes=m + 1),
            open=106.0,
            high=106.5,
            low=105.5,
            close=106.1,
            volume=1.0,
            bar_source="1min",
            clock_complete=True,
            nonzero_volume_fraction=1.0,
            last_trade_age_bars=0,
            entry_eligible=True,
            mark_status="LIVE",
        )
        for m in range(20)
    ]
    out = _resample_1min_to_1h(bars_full + bars_partial)
    assert len(out) == 1
    assert out[0].ts_start == t0
    assert out[0].ts_avail == t0 + timedelta(hours=1)
    assert abs(out[0].volume - 120.0) < 1e-9
    assert out[0].open == 100.0


def test_champion_journal_refuses_to_touch_v1_mix_journal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mix-journal.jsonl"):
        record_champion_ensemble_journal(
            tmp_path / "market.db",
            tmp_path / "mix-journal.jsonl",
            tmp_path / "gru.json",
        )


def test_score_champion_forward_journal_handles_day_one_snapshot(tmp_path: Path) -> None:
    jpath = tmp_path / "champion-ensemble-journal.jsonl"
    rec = {
        "schema": "champion-forward-journal/1",
        "slot_key": "2026-11-25|2026-11-24T20:00:00+00:00",
        "as_of": "2026-11-24T21:15:00+00:00",
        "blended_weights": {},
        "cash_weight": 1.0,
        "ignition_triggers": [],
        "live_quotes": {
            "BTCUSDT": {"nobitex_spread_bps": 7.0, "wallex_spread_bps": 12.0},
        },
    }
    jpath.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    score = score_champion_forward_journal(jpath, tmp_path / "missing.db")
    assert score["status"] == "TRACKING"
    assert score["forward_days"] == 1
    assert score["paper_nav"] == 1000.0
    assert score["e_process"] == 1.0
    assert score["median_live_nobitex_spread_bps"] == 7.0
