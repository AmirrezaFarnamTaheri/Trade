"""Sequence holes, stale books and level overflows require resynchronization."""
from copy import deepcopy

import pytest

from gym.services.liquidity import audit_depth


def snapshot(seq=10):
    return {"kind": "SNAPSHOT", "sequence": seq, "previous_sequence": None,
            "event_at": "2026-11-01T00:00:00Z", "observed_at": "2026-11-01T00:00:01Z",
            "bids": [["100", "1"], ["99", "2"]], "asks": [["101", "1"]]}


def request(frames):
    return {"source_id": "supplied-test-sequence", "as_of": "2026-11-01T00:00:05Z", "max_age_seconds": 10, "max_levels": 2, "frames": frames}


def test_snapshot_delta_duplicate_gap_and_new_snapshot_recovery():
    first = snapshot()
    delta = {**snapshot(11), "kind": "DELTA", "previous_sequence": 10, "bids": [["100", "0"], ["98", "3"]], "asks": []}
    out = audit_depth(request([first, delta, delta]))
    assert out["status"] == "AVAILABLE" and out["best_bid"] == "99"
    assert out["events"][-1]["status"] == "DUPLICATE_IGNORED"
    gap = {**delta, "sequence": 13, "previous_sequence": 12}
    out = audit_depth(request([first, delta, gap, {**delta, "sequence": 14, "previous_sequence": 13}]))
    assert out["status"] == "NEEDS_SNAPSHOT" and out["best_bid"] is None
    assert audit_depth(request([first, gap, snapshot(20)]))["status"] == "AVAILABLE"
    assert not out["observations_authenticated"] and not out["funded_authority"]


def test_conflict_overflow_crossing_stale_and_future_are_not_executable_depth():
    first = snapshot()
    for delta in ({**snapshot(11), "kind": "DELTA", "previous_sequence": 10, "bids": [["98", "1"]], "asks": []},
                  {**snapshot(11), "kind": "DELTA", "previous_sequence": 10, "bids": [["101", "1"]], "asks": []},
                  {**snapshot(), "bids": [["100", "9"]]}):
        assert audit_depth(request([first, delta]))["status"] == "NEEDS_SNAPSHOT"
    value = request([first])
    value["as_of"] = "2026-11-01T01:00:00Z"
    assert audit_depth(value)["status"] == "STALE"
    value = request([first])
    value["as_of"] = first["observed_at"]
    assert audit_depth(value)["future_frames_excluded"] == 1
    bad = deepcopy(first)
    bad["bids"].append(["100", "2"])
    with pytest.raises(ValueError, match="duplicate"):
        audit_depth(request([bad]))
