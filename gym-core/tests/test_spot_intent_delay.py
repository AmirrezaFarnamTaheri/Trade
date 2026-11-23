import json
from datetime import timedelta

import pytest

from gym.domain.model import iso
from gym.domain.strategy import digest
from scripts.spot_intent_delay import delay_study
from tests.support import START, market_db, quote


def test_delay_study_keeps_frozen_deadline_and_excludes_replay_end(tmp_path):
    def at(seconds):
        return START + timedelta(seconds=seconds)

    db = market_db(tmp_path, [quote(at(1), "99", "100"), quote(at(4), "99", "100", {"STALE"}),
                              quote(at(5), "99", "101"), quote(at(6), "99", "102")])
    intent = {"symbol": "BTCUSDT", "side": "BUY", "ref": "BTCUSDT#1", "arrival_at": iso(at(1)),
              "deadline": iso(at(5))}
    tape = {"schema": "spot-intents/1", "run_id": "fixture", "intents": [intent], "intents_digest": digest([intent]),
            "source_inputs": {"rules_mode": "point-in-time", "to": iso(at(6))}}
    try:
        before = json.dumps(tape)
        report = delay_study(db, tape, [0, 3000, 4000, 4001])
        rows = [scenario["rows"][0] for scenario in report["scenarios"]]
        assert [row["quote_at"] for row in rows] == [iso(at(1)), iso(at(5)), iso(at(5)), None]
        assert rows[-1]["status"] == "DEADLINE_PASSED"
        assert json.dumps(tape) == before
        tape["source_inputs"]["to"] = iso(at(5))
        assert delay_study(db, tape, [4000])["scenarios"][0]["counts"] == {"NO_QUALIFIED_QUOTE": 1}
        intent["deadline"] = iso(at(6))
        with pytest.raises(ValueError, match="digest"):
            delay_study(db, tape, [0])
    finally:
        db.c.close()
