"""Raw-archive guards: disk floor, exclusive segment names, raw-move, streamed manifest hash."""
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from gym.adapters import store
from gym.adapters.store import DiskLow, MarketDB, SegmentWriter
from gym.cli import main
from gym.domain.model import BookTop
from tests.support import START


def test_low_disk_stops_collection_instead_of_filling_the_volume(tmp_path, monkeypatch):
    db = MarketDB(tmp_path / "market.db")
    monkeypatch.setattr(store, "MIN_FREE_BYTES", 1 << 62)
    with pytest.raises(DiskLow, match="raw-move"):
        SegmentWriter(tmp_path / "raw", db).write("ws", "{}", START)


def test_concurrent_writers_never_share_or_truncate_a_segment(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    first, second = SegmentWriter(tmp_path / "raw", db), SegmentWriter(tmp_path / "raw", db)
    a, b = first.write("ws", "a", START), second.write("ws", "b", START)
    assert a.split("#")[0] != b.split("#")[0]
    first.close(), second.close()
    rows = db.c.execute("SELECT path, sha256, bytes FROM segments ORDER BY seg_id").fetchall()
    for path, sha, size in rows:
        data = Path(path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha and len(data) == size
    assert [r["raw"] for r in store.read_segment(rows[0][0])] == ["a"]


def test_raw_move_moves_only_finished_days_and_refuses_clashes(tmp_path, capsys):
    raw = tmp_path / "live" / "raw"
    for day in ("20261101", "20261102", "29991231"):
        (raw / day).mkdir(parents=True)
        (raw / day / "00-0.jsonl.zst").write_bytes(b"x")
    dest = tmp_path / "archive"
    assert main(["--data", str(tmp_path), "raw-move", "--before", "20261102", "--to", str(dest)]) == 0
    assert sorted(p.name for p in dest.iterdir()) == ["20261101"] and (raw / "20261102").exists()
    (raw / "20261101").mkdir()
    assert main(["--data", str(tmp_path), "raw-move", "--before", "29991231", "--to", str(dest)]) == 2
    assert "nothing moved" in capsys.readouterr().err and (raw / "20261102").exists()


def test_collector_archives_old_days_and_reports_a_free_space_forecast(tmp_path):
    from datetime import timedelta

    from gym.adapters.store import storage_forecast
    from gym.domain.model import UTC
    from gym.services.collector import Collector
    db = MarketDB(tmp_path / "market.db")
    raw = tmp_path / "raw"
    for day in ("20261101", "20261105", "20261107"):
        (raw / day).mkdir(parents=True)
    col = Collector(db, SegmentWriter(raw, db), ["BTCUSDT"], archive=(tmp_path / "cold", 3))
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    col.archive_raw(now)
    assert sorted(p.name for p in (tmp_path / "cold").iterdir()) == ["20261101"]
    assert col.status["archived"]["days"] == ["20261101"]
    (tmp_path / "cold" / "20261105").mkdir()
    failed = col.archive_raw(now + timedelta(days=2))  # clash: nothing moves, the failure becomes a quality event
    assert (raw / "20261105").is_dir() and failed[0][0] == "ARCHIVE_FAILED"
    db.add_segment("a", raw / "a", 1, 2, "x", 3600 * 1000, now - timedelta(hours=2))
    db.add_segment("b", raw / "b", 3, 4, "x", 3600 * 1000, now - timedelta(hours=1))
    forecast = storage_forecast(db, raw, now)
    assert forecast["growth_bytes_per_hour"] == 3600 * 1000 and forecast["free_bytes"] > 0


def test_compaction_keeps_the_last_quote_per_bucket_and_replays_warn(tmp_path):
    from datetime import timedelta

    from gym.adapters.store import compact_quotes
    from gym.services.paper import paper
    from tests.support import market_db, quote_history
    db = market_db(tmp_path, quote_history(n=360, step=1))  # one quote per second for six minutes
    removed = compact_quotes(db, START + timedelta(minutes=3), "1min", START + timedelta(hours=1))
    assert removed == 180 - 3  # three whole minutes keep one row each
    kept = db.c.execute("SELECT count(*) FROM book_top WHERE ts_avail < ?", ((START + timedelta(minutes=3)).isoformat(),)).fetchone()[0]
    assert kept == 3
    out = paper(db, "BTCUSDT", START, START + timedelta(minutes=6), resolution="1min", fast=2, slow=3)
    assert any("compacted" in w for w in out["warnings"])
    with pytest.raises(ValueError):
        compact_quotes(db, START, "5min", START)


def test_segment_sweep_finds_missing_and_altered_files(tmp_path):
    from gym.adapters.store import verify_segments
    db = MarketDB(tmp_path / "market.db")
    writer = SegmentWriter(tmp_path / "raw", db)
    writer.write("ws", "a", START)
    writer.close()
    writer.write("ws", "b", START.replace(hour=START.hour + 1))
    writer.close()
    ids = [row[0] for row in db.c.execute("SELECT seg_id FROM segments ORDER BY seg_id")]
    assert verify_segments(db, [tmp_path / "raw"]) == {"checked": 2, "missing": [], "mismatched": []}
    (tmp_path / "raw" / ids[0]).write_bytes(b"tampered")
    archive = tmp_path / "cold"
    (archive / ids[1]).parent.mkdir(parents=True)
    (tmp_path / "raw" / ids[1]).rename(archive / ids[1])
    report = verify_segments(db, [tmp_path / "raw", archive])
    assert report == {"checked": 2, "missing": [], "mismatched": [ids[0]]}
    assert verify_segments(db, [tmp_path / "raw"])["missing"] == [ids[1]]


def test_quote_gaps_are_found_inside_the_window(tmp_path):
    from datetime import timedelta

    from gym.services.data_portal import quote_gaps
    from tests.support import market_db, quote
    rows = [quote(START + timedelta(seconds=s), "100", "101") for s in (0, 10, 400, 410, 1000)]
    db = market_db(tmp_path, rows)
    gaps = quote_gaps(db, "BTCUSDT", START, START + timedelta(hours=1))
    assert gaps == [(START + timedelta(seconds=10), START + timedelta(seconds=400)),
                    (START + timedelta(seconds=410), START + timedelta(seconds=1000))]


def test_quality_report_grades_markets_by_flagged_share_and_silence(tmp_path):
    from datetime import timedelta

    from gym.services.data_portal import quality_report
    from tests.support import market_db, quote
    rows = [quote(START + timedelta(seconds=10 * i), "100", "101", ["STALE"] if i % 2 else []) for i in range(10)]
    rows += [BookTop("ETHUSDT", START + timedelta(seconds=10 * i), Decimal(1), Decimal(2), Decimal(1), Decimal(1), frozenset()) for i in range(10)]
    report = quality_report(market_db(tmp_path, rows), START - timedelta(hours=1))
    assert report["BTCUSDT"] == {"rows": 10, "flagged_share": 0.5, "longest_gap_s": 10.0, "grade": "POOR"}
    assert report["ETHUSDT"]["grade"] == "OK"


def test_maintenance_jobs_run_on_worker_threads_without_the_collector_connection(tmp_path):
    import asyncio

    from gym.services.collector import Collector
    from tests.support import market_db, quote_history
    db = market_db(tmp_path, quote_history(n=20))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    from datetime import timedelta
    now = START + timedelta(hours=1)

    async def run():
        await col._maintain(col.refresh_quality, now)
        await col._maintain(col.verify_raw, now)
    asyncio.run(run())
    assert "BTCUSDT" in col.data_quality and col.status["integrity"]["checked"] == 0
    assert not [row for row in db.quality(10) if row[2] == "MAINTENANCE_FAILED"]
