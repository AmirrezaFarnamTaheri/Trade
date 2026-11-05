"""Notes bind immutable evidence and paginate within a fixed journal snapshot."""
from datetime import timedelta
import json
import sqlite3

import pytest

from gym.adapters.run_store import save_run
from gym.services.experiment_registry import ExperimentRegistry
from gym.services.paper import paper
from gym.services.research_actions import research_action
from tests.support import START, market_db, quote_history


@pytest.fixture
def saved(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
        return out
    finally:
        db.c.close()


def note(out, nonce="a" * 32):
    return {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"], "decision_index": 5,
            "request_id": nonce, "text": '<script>alert("operator interpretation")</script>'}


def test_idempotent_note_is_separate_from_saved_evidence_and_survives_restart(tmp_path, saved):
    path = tmp_path / "runs" / (saved["run_id"] + ".json")
    before = path.read_bytes()
    request = note(saved)
    first = research_action(tmp_path, "annotation-add", request)
    assert research_action(tmp_path, "annotation-add", request) == first
    assert first["record"]["decision_at"] == saved["result"]["decisions"][5]["t"]
    assert not first["record"]["economic_evidence"] and path.read_bytes() == before
    with pytest.raises(ValueError, match="different content"):
        research_action(tmp_path, "annotation-add", {**request, "text": "changed"})
    for patch in ({"decision_index": True}, {"decision_index": 99999}, {"text": ""}, {"outputs_digest": "wrong"}):
        with pytest.raises(ValueError):
            research_action(tmp_path, "annotation-add", {**request, **patch})
    listed = research_action(tmp_path, "annotation-list", {"run_id": saved["run_id"], "outputs_digest": saved["outputs_digest"],
                            "after": 0, "through": None, "limit": 1})
    assert [row["id"] for row in listed["events"]] == [first["record"]["id"]]
    with ExperimentRegistry(tmp_path, store="live") as registry:
        with pytest.raises(sqlite3.IntegrityError):
            registry.conn.execute("DELETE FROM events")


def test_fixed_snapshot_pages_do_not_absorb_new_events_or_skip_byte_limited_rows(tmp_path):
    with ExperimentRegistry(tmp_path, store="live") as registry:
        for i in range(4):
            registry.append("RESEARCH_NOTES", None, {"payload": "ی" * 50000, "ordinal": i})
        request = {"kind": "RESEARCH_NOTES", "parent": None, "after": 0, "through": None, "limit": 100}
        first = registry.page(request)
        assert len(first["events"]) == 2 and first["event_bytes"] <= 262144
        registry.append("RESEARCH_NOTES", None, {"ordinal": 4})
        second = registry.page({**request, "after": first["next_after"], "through": first["through"]})
        assert [r["ordinal"] for r in first["events"] + second["events"]] == [0, 1, 2, 3]
        assert second["next_after"] is None
        registry.conn.execute("DROP TRIGGER frozen_event")
        registry.conn.execute("UPDATE events SET body=? WHERE seq=1", (json.dumps({"store": "live"}),))
        with pytest.raises(ValueError, match="digest"):
            registry.page(request)
