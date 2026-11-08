"""Restart recreates pending orders and indicator history; corrected inputs cannot reuse old checkpoints."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.domain.sim import CostModel
from gym.services.paper import paper
from gym.services.portfolio import portfolio
from gym.services.research_actions import research_action
from tests.support import START, market_db, quote_history


def test_rebuild_checkpoint_retains_pending_order_and_rejects_a_later_correction(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
        record = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": 19})["record"]
        assert record["pending_order"] is not None
        result = research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})
        assert result["status"] == "EXACT_MATCH" and result["continued_quotes"] == 161
        assert not result["mutable_object_deserialization"] and not result["funded_authority"]
        db.c.execute("UPDATE book_top SET bid_qty='2' WHERE rowid=1")
        with pytest.raises(ValueError, match="changed"):
            research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})
    finally:
        db.c.close()


def test_equal_timestamps_gaps_and_higher_timeframes_are_exact_across_restart(tmp_path):
    tops = [t for t in quote_history(n=180) if not START + timedelta(minutes=12) <= t.ts_avail < START + timedelta(minutes=14)]
    tops += [replace(tops[10], bid=tops[10].bid + Decimal(1))]
    db = market_db(tmp_path, tops)
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min", fast=2, slow=3, subscriptions=["15min"])
        save_run(out, tmp_path / "runs")
        for count in (10, 11, 12, len(tops)):
            record = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": count})["record"]
            assert research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})["status"] == "EXACT_MATCH"
    finally:
        db.c.close()


def test_actual_fill_exit_policy_rebuilds_identically_across_restart(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min",
                    params={"fast": 2, "slow": 3, "exit_after_bars": 2, "exit_atr_multiple": 2})
        save_run(out, tmp_path / "runs")
        assert any(o["status"] == "FILLED" for o in out["result"]["orders"])
        record = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": 100})["record"]
        assert research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})["status"] == "EXACT_MATCH"
    finally:
        db.c.close()


@pytest.mark.parametrize("cost", [CostModel(), CostModel(order_type="limit")])
def test_portfolio_restart_rebuilds_reservations_targets_and_loss_latches(tmp_path, cost):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30), resolution="1min",
            params={"fast": 2, "slow": 3}, policy={"rebalance": True, "max_drawdown": "0.00001"}, cost=cost)
        save_run(out, tmp_path / "runs" / "portfolios")
        record = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": 39})["record"]
        assert record["kind"] == "PORTFOLIO_CHECKPOINT" and record["state_digest"]
        assert research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})["status"] == "EXACT_MATCH"
        db.c.execute("UPDATE book_top SET bid_qty='2' WHERE rowid=1")
        with pytest.raises(ValueError, match="changed"):
            research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})
    finally:
        db.c.close()

def test_limit_engine_checkpoints_from_saved_native_paper_runs(tmp_path):
    """The new limit-fill provenance engine must retain verified restart support."""
    from gym.services.session import LIMIT_ENGINE_VERSION

    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min",
                    fast=2, slow=3, cost=CostModel(order_type="limit"))
        assert out["inputs"]["engine"] == LIMIT_ENGINE_VERSION
        save_run(out, tmp_path / "runs")
        record = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": 25})["record"]
        assert record["kind"] == "REPLAY_CHECKPOINT"
        assert research_action(tmp_path, "replay-resume", {"checkpoint_id": record["id"]})["status"] == "EXACT_MATCH"
    finally:
        db.c.close()
