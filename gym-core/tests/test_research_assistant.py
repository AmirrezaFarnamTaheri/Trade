"""Model proposals are validated, deduplicated, budgeted and tested on paper."""
import asyncio
import json
from datetime import timedelta

from gym.adapters.run_store import list_runs
from gym.services.research import tried_before
from gym.services.research_assistant import assist, parse_proposals
from tests.support import START, market_db, quote_history


def test_parse_drops_invalid_duplicate_and_already_tried_configurations():
    from gym.domain.registry import create_strategy
    tried = frozenset({create_strategy("ema-trend", {"fast": 2, "slow": 3}).config_hash})
    text = "Sure! " + json.dumps([
        {"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}, "rationale": "already tried"},
        {"strategy": "ema-trend", "params": {"fast": 5, "slow": 3}, "rationale": "fast >= slow is invalid"},
        {"strategy": "no-such", "params": {}},
        {"strategy": "ema-trend", "params": {"fast": 3, "slow": 9}, "rationale": "new"},
        {"strategy": "ema-trend", "params": {"fast": 3, "slow": 9}, "rationale": "duplicate"},
        {"strategy": "sma-reversion", "params": {}, "rationale": "defaults"},
        {"strategy": "rsi-rebound", "params": {}, "rationale": "over budget"}]) + " Good luck."
    proposals = parse_proposals(text, 2, tried)
    assert [(p["strategy"], p["rationale"]) for p in proposals] == [("ema-trend", "new"), ("sma-reversion", "defaults")]
    assert parse_proposals("no json here", 3, frozenset()) == []


def test_assistant_tests_proposals_and_they_count_as_trials(tmp_path):
    db = market_db(tmp_path, quote_history(n=500))
    runs = tmp_path / "runs"
    prompts = []

    async def complete(action, value):
        prompts.append(value["prompt"])
        return {"text": json.dumps([{"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
                                    {"strategy": "ema-trend", "params": {"fast": 3, "slow": 5}}]),
                "usage": {"input": 10, "output": 5}, "model": {"provider": "test", "id": "m"}}
    report = asyncio.run(assist(complete, db, runs, "BTCUSDT", START, START + timedelta(hours=1),
                                preset="p", budget=2, resolution="1min"))
    assert report["status"] == "TESTED" and len(report["results"]) == 2 and report["selection"]["trials"] == 2
    assert len(list_runs(runs)) == 2 and len(tried_before(runs, "BTCUSDT", "1min")) == 2 and "BTCUSDT" in prompts[0]
    again = asyncio.run(assist(complete, db, runs, "BTCUSDT", START, START + timedelta(hours=1), preset="p", budget=2, resolution="1min"))
    assert again["status"] == "TOO_FEW_NEW_PROPOSALS"  # the model repeated itself; nothing is re-run


def test_brackets_in_prose_do_not_hide_the_array_and_invalid_replies_get_one_repair(tmp_path):
    reply = 'Options [a] and [b] considered. ' + json.dumps([{"strategy": "ema-trend", "params": {"fast": 3, "slow": 9}}]) + ' [end]'
    assert [p["params"] for p in parse_proposals(reply, 2, frozenset())] == [{"fast": 3, "slow": 9}]
    db = market_db(tmp_path, quote_history(n=50))
    calls = []

    async def garbled(action, value):
        calls.append(value["prompt"])
        return {"text": "I think [ema-trend with fast=3", "usage": {"input": 1, "output": 1}, "model": None}
    report = asyncio.run(assist(garbled, db, tmp_path / "runs", "BTCUSDT", START, START + timedelta(hours=1),
                                preset="p", budget=2, resolution="1min"))
    assert report["status"] == "INVALID_MODEL_REPLY" and report["reply_attempts"] == 2 and len(calls) == 2
    assert "did not contain a valid JSON array" in calls[1] and len(report["usage"]) == 2
