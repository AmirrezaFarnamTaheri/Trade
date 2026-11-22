"""Causal rank and breadth gates on the shared account and scheduled replay paths."""

import asyncio
from datetime import timedelta

import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from gym.services.research_ledger import ResearchLedger
from gym.services.research_process import calculate
from tests.support import START, market_db, quote_history
from tests.test_portfolio_workflow import request
from tests.test_research_ledger import schedule


@pytest.mark.parametrize("method", ["momentum", "placebo"])
def test_shared_rank_selection_matches_scheduler_and_restart(tmp_path, method):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    db.c.close()
    rank = {"method": method, "top_n_per_quote": 1, "min_breadth": "1", "seed": 11}
    due = iso(START + timedelta(minutes=30))
    value = {**request(), "to": due, "rank_gate": rank}
    direct = research_action(tmp_path, "portfolio-replay", value)
    run = research_action(tmp_path, "portfolio-read", {"run_id": direct["run_id"]})
    assert run["inputs"]["portfolio_version"] == 26
    trace = run["result"]["rank_gate"]
    assert trace[0]["selected"] == {}
    assert any(row["blocked_buys"] for row in trace)
    assert all(row["selected"] == {} for row in trace if row["breadth"] == "0")
    assert any(o["side"] == "BUY" and o["status"] == "FILLED"
               for m in run["result"]["markets"].values() for o in m["orders"])
    assert all(current < row["at"] and prior < current for row in trace for _, current, prior, _ in row["eligible"])
    reversed_run = research_action(tmp_path, "portfolio-replay", {**value, "symbols": value["symbols"][::-1]})
    assert reversed_run["outputs_digest"] == direct["outputs_digest"]
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        schedule(ledger, first_at=due, lookback_seconds=1800, portfolio_symbols=value["symbols"], rank_gate=rank)
    report = asyncio.run(calculate(tmp_path, "tick", at=due))["completed"]
    assert len(report) == 1 and report[0]["run_id"] == direct["run_id"]
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": direct["run_id"], "quote_count": 76})
    resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["record"]["id"]})
    assert resumed["result_digest"] == direct["outputs_digest"]
