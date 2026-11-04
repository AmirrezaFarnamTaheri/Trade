"""Saved-run resampling remains reproducible and never promotes a strategy."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.services.paper import paper
from gym.services.return_bootstrap import return_bootstrap
from tests.support import START, market_db, quote_history


def test_saved_costed_returns_have_repeatable_bounded_null_diagnostic(tmp_path):
    db = market_db(tmp_path, quote_history(n=300))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=49), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    value = {"run_id": out["run_id"], "seed": 21, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 120}
    result = return_bootstrap(tmp_path / "runs", value, store="live")
    assert result == return_bootstrap(tmp_path / "runs", value, store="live")
    assert result["observations"] >= 20
    assert Decimal(0) < Decimal(result["null_upper_tail_fraction"]) <= 1
    assert result["status"] == "DESCRIPTIVE_ONLY"
    assert not result["trials_accounted_for"] and not result["funded_authority"]
    assert result["source_outputs_digest"] == out["outputs_digest"]
    with pytest.raises(ValueError):
        return_bootstrap(tmp_path / "runs", value, store="demo")


@pytest.mark.parametrize("value", [
    {"seed": True}, {"simulations": 0}, {"simulations": 2001}, {"mean_block_length": 0},
    {"max_gap_seconds": 0}, {"seed": -1},
])
def test_limits_are_checked_before_loading_a_run(tmp_path, value):
    request = {"run_id": "unavailable", "seed": 21, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 120}
    with pytest.raises(ValueError):
        return_bootstrap(tmp_path, {**request, **value}, store="live")


def test_blocks_do_not_continue_across_a_real_feed_gap(tmp_path):
    quotes = [q for q in quote_history(n=420) if not START + timedelta(minutes=25) <= q.ts_avail < START + timedelta(minutes=35)]
    db = market_db(tmp_path, quotes)
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=69), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    result = return_bootstrap(tmp_path / "runs", {"run_id": out["run_id"], "seed": 21, "simulations": 100,
                              "mean_block_length": 5, "max_gap_seconds": 90}, store="live")
    assert result["excluded_gap_intervals"] > 0 and result["eligible_segments"] > 1
