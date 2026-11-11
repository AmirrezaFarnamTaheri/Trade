import json
import sqlite3

import pytest

from gym.services.operator_timeline import timeline


def _db(path, ddl, rows):
    conn = sqlite3.connect(path)
    conn.executescript(ddl)
    conn.executemany(rows[0], rows[1])
    conn.commit()
    conn.close()


def test_merges_sources_newest_first_without_creating_or_writing_stores(tmp_path):
    _db(tmp_path / "experiments.sqlite3", "CREATE TABLE events(seq INTEGER PRIMARY KEY, id, kind, parent, body);",
        ("INSERT INTO events(id, kind, parent, body) VALUES (?,?,?,?)",
         [("e1", "RESULT", None, json.dumps({"recorded_at": "2026-11-10T10:00:00Z", "run_id": "r1", "state": "OK",
                                             "net_quote": "-3"})),
          ("e2", "ATTEMPT", None, json.dumps({"recorded_at": "naive-or-bad"}))]))
    _db(tmp_path / "backup_status.sqlite3", "CREATE TABLE receipts(seq INTEGER PRIMARY KEY, kind, body);",
        ("INSERT INTO receipts(kind, body) VALUES (?,?)",
         [("RESTORE", json.dumps({"recorded_at": "2026-11-10T12:00:00+03:30", "status": "PASS"}))]))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = timeline(tmp_path, limit=10)
    assert [(e["source"], e["kind"]) for e in report["events"]] == [("experiments", "RESULT"), ("backups", "RESTORE")]
    assert report["events"][0]["summary"] == "r1 OK net -3"
    assert report["events"][1]["at"] == "2026-11-10T08:30:00+00:00"
    assert report["sources"]["experiments"] == 1 and report["sources"]["venue-facts"] == "absent"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert timeline(tmp_path, limit=10, sources={"backups"})["sources"] == {"backups": 1}


def test_rejects_bad_limits_and_unknown_sources(tmp_path):
    with pytest.raises(ValueError):
        timeline(tmp_path, limit=0)
    with pytest.raises(ValueError):
        timeline(tmp_path, sources={"nope"})
