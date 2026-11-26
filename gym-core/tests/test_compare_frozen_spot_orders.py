import hashlib
import json
from copy import deepcopy

import pytest

from gym.domain.model import iso
from gym.domain.strategy import digest
from scripts.compare_frozen_spot_orders import compare
from tests.support import START


def test_comparison_reports_changed_fills_and_unmatched_decisions():
    at = iso(START)
    inputs = {"data": "archive", "cost": {"max_participation": "1"}}
    intents = [{"symbol": symbol, "side": "BUY", "decision_at": at, "ref": symbol,
                "amount_asset": "Q", "amount": "10"} for symbol in ("A", "B")]
    tape = {"source_inputs": inputs, "intents": intents, "intents_digest": digest(intents), "run_id": "source"}
    fill = {"status": "FILLED", "qty": "1.00", "fill_time": at}
    frozen = {"participation": "0.25", "source_run": "source", "intents_digest": tape["intents_digest"],
              "orders": {"A": fill, "B": fill}}
    order = {**fill, "decision_time": at, "side": "BUY"}
    continuous = {"run_id": "candidate", "inputs": {**inputs, "cost": {"max_participation": "0.25"}},
                  "result": {"markets": {"A": {"orders": [{**order, "qty": "0.5"}]}, "C": {"orders": [order]}}}}
    assert compare(tape, frozen, continuous)["counts"] == {"OUTCOME_DIFFERS": 1, "FROZEN_ONLY": 1, "CONTINUOUS_ONLY": 1}
    continuous["result"]["markets"]["A"]["orders"][0]["qty"] = "1"
    assert compare(tape, frozen, continuous)["counts"]["MATCH"] == 1
    other = deepcopy(continuous)
    other["inputs"]["data"] = "other archive"
    with pytest.raises(ValueError, match="differs in data"):
        compare(tape, frozen, other)
    captured = [{**intents[0], "amount": "5"}, {**intents[1], "symbol": "C"}]
    canonical = json.dumps(continuous, sort_keys=True, separators=(",", ":"))
    capture = {"intents": captured, "intents_digest": digest(captured),
               "run_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
    differences = compare(tape, frozen, continuous, continuous_tape=capture)["differences"]
    assert differences[0]["continuous_decision_amount"] is None
    assert differences[1]["continuous_decision_amount"] == {"asset": "Q", "amount": "10"}
    capture["run_sha256"] = "wrong"
    with pytest.raises(ValueError, match="does not match"):
        compare(tape, frozen, continuous, continuous_tape=capture)
