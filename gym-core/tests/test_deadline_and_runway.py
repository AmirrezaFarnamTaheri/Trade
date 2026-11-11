"""P-2: the research deadline scales with the work; a window the archive volume cannot last through is refused."""
from datetime import UTC, datetime, timedelta

import pytest

from gym.services import research_process as rp
from gym.services import storage_runway


def test_deadline_scales_with_observations_inside_bounds():
    assert rp.deadline_for(None) == rp.DEADLINE_SECONDS
    assert rp.deadline_for(10_000) == rp.DEADLINE_SECONDS            # small work keeps the old floor
    assert rp.deadline_for(200_000) == pytest.approx(200.0)           # 80 s measured -> 2.5x headroom
    assert rp.deadline_for(10_000_000) == rp.MAX_DEADLINE_SECONDS     # the stated maximum


def test_work_estimate_counts_the_requested_window(tmp_path):
    from tests.support import START, market_db, quote_history
    market_db(tmp_path, quote_history(n=600)).c.close()
    value = {"symbols": ["BTCUSDT"], "from": START.isoformat(), "to": (START + timedelta(hours=1)).isoformat()}
    assert rp.work_estimate(tmp_path, value) == 360  # one quote every 10 s for an hour
    assert rp.work_estimate(tmp_path, {"symbol": "BTCUSDT"}) is None
    assert rp.work_estimate(tmp_path / "missing", value) is None


def test_a_window_longer_than_the_disk_runway_is_refused(tmp_path, monkeypatch):
    from tests.support import market_db, quote_history
    market_db(tmp_path, quote_history(n=10)).c.close()
    now = datetime(2026, 11, 10, tzinfo=UTC)
    monkeypatch.setattr("gym.adapters.store.storage_forecast",
                        lambda db, raw, at: {"free_bytes": 6 << 30, "floor_bytes": 5 << 30,
                                             "growth_bytes_per_hour": 200 << 20, "hours_to_floor": 5.1})
    assert storage_runway.ensure_runway(tmp_path, now + timedelta(hours=5), now)["status"] == "OK"
    with pytest.raises(ValueError, match="collection floor in 5 h, before this window ends in 24 h"):
        storage_runway.ensure_runway(tmp_path, now + timedelta(hours=24), now)
    monkeypatch.setattr("gym.adapters.store.storage_forecast",
                        lambda db, raw, at: {"free_bytes": 1, "floor_bytes": 1, "growth_bytes_per_hour": None,
                                             "hours_to_floor": None})
    assert storage_runway.ensure_runway(tmp_path, now + timedelta(days=30), now)["status"] == "UNKNOWN"
