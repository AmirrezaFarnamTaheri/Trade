"""Scale checks for the hot local reads: polled run listing and research coverage."""
import json
import os
import time
from datetime import timedelta

from gym.adapters import run_store
from gym.adapters.run_store import list_runs
from gym.adapters.store import MarketDB
from gym.services.research import coverage
from tests.support import START


def test_polled_run_listing_parses_only_changed_files(tmp_path, monkeypatch):
    for i in range(400):
        (tmp_path / f"{i:016x}.json").write_text(json.dumps({"run_id": f"{i:016x}", "inputs": {"symbol": "BTCTMN"},
                                                               "result": {"end": {"net": str(i)}}}), "utf-8")
        os.utime(tmp_path / f"{i:016x}.json", ns=(i * 10**9, i * 10**9))
    assert len(list_runs(tmp_path)) == 50
    parsed = []
    original = run_store.json.loads
    monkeypatch.setattr(run_store.json, "loads", lambda text, **kw: parsed.append(1) or original(text, **kw))
    assert len(list_runs(tmp_path)) == 50 and parsed == []  # the poll after the first reads no file
    assert len(list_runs(tmp_path, symbol="BTCTMN", limit=400)) == 400 and len(parsed) == 350  # only the unseen ones


def test_coverage_of_a_large_market_stays_in_sql(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    rows = [("wallex:BTCTMN", (START + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"), None, "1", "2", "1", "1", None,
             "STALE" if i % 997 == 0 else "", None) for i in range(200_000)]
    db.c.execute("BEGIN")
    db.c.executemany("INSERT INTO book_top VALUES(?,?,?,?,?,?,?,?,?,?)", ((r[0], r[1], r[1], *r[3:]) for r in rows))
    db.c.execute("COMMIT")
    began = time.perf_counter()
    report = coverage(db, "BTCTMN")
    assert report["observations"] == 200_000 and report["gaps_over_120s"] == 0
    assert time.perf_counter() - began < 5  # generous: about 0.3 s locally; a Python loop over rows takes far longer
