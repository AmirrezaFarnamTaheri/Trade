"""Structured event log lines."""
import json
import logging

from gym.services import event_log


def test_events_are_one_json_object_per_line(tmp_path):
    path = event_log.configure(tmp_path)
    try:
        event_log.event("comparison_finished", id="abc", runs=["r1", "r2"])
        for handler in event_log.log.handlers:
            handler.flush()
        line = json.loads(path.read_text("utf-8").splitlines()[-1])
        assert line["event"] == "comparison_finished" and line["runs"] == ["r1", "r2"] and line["level"] == "info"
        assert event_log.configure(tmp_path) == path and len(event_log.log.handlers) == 1  # idempotent
    finally:
        for handler in list(event_log.log.handlers):
            event_log.log.removeHandler(handler)
            handler.close()
        event_log.log.setLevel(logging.NOTSET)
