"""Restart recreates pending orders and indicator history; corrected inputs cannot reuse old checkpoints."""
from datetime import timedelta
from dataclasses import replace
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.services.paper import paper
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
