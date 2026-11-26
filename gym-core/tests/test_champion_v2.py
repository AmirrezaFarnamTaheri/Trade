"""Unit tests for v2 Champion verification helpers and v2 parallel forward journal safety boundaries."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gym.services.experiments.champion_v2_journal import record_champion_v2_journal
from gym.services.experiments.champion_v2_verification import _merge_twin_schedules


def test_merge_twin_schedules_averages_0h_and_1h_phases_cleanly() -> None:
    t0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    t2 = t0 + timedelta(hours=2)
    s0 = {t0: {"BTCUSDT": 0.40}, t2: {"BTCUSDT": 0.0}}
    s1 = {t1: {"BTCUSDT": 0.20, "ETHUSDT": 0.30}}
    merged = _merge_twin_schedules(s0, s1)
    assert abs(merged[t0]["BTCUSDT"] - 0.20) < 1e-9
    assert abs(merged[t1]["BTCUSDT"] - 0.30) < 1e-9
    assert abs(merged[t1]["ETHUSDT"] - 0.15) < 1e-9
    assert abs(merged[t2]["BTCUSDT"] - 0.10) < 1e-9


def test_champion_v2_journal_refuses_to_touch_v1_journals(tmp_path: Path) -> None:
    for protected in ("mix-journal.jsonl", "champion-ensemble-journal.jsonl"):
        with pytest.raises(ValueError, match="protected journal"):
            record_champion_v2_journal(
                tmp_path / "market.db",
                tmp_path / protected,
                tmp_path / "gru-v2.json",
            )
