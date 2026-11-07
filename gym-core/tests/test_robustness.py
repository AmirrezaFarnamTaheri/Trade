"""Selection diagnostics retain incomplete samples and never manufacture new market evidence."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.services.paper import paper
from gym.services.robustness import cscv, robustness, trade_reshuffle
from tests.support import START, market_db, quote_history


def test_cscv_exposes_selection_and_rank_ties_with_exact_bounds():
    rows = [[Decimal("0.01"), Decimal("-0.01")]] * 40 + [[Decimal("-0.01"), Decimal("0.01")]] * 40
    report = cscv(rows, 4)
    assert report["combinations"] == 6
    assert report["selection_ties"] == report["median_ties"] == 4
    assert Decimal(report["below_median_fraction"]) == Decimal(2) / 6
    assert report["at_or_below_median_fraction"] == "1"
    assert report["status"] == "EXPLORATORY" and not report["independent_test"]
    assert cscv([[Decimal(0), Decimal(0)]] * 80, 4)["status"] == "INSUFFICIENT_VARIATION"
    assert cscv(rows[:20], 4)["status"] == "INSUFFICIENT_DATA"


def test_trade_reshuffle_preserves_total_realized_pnl_and_does_not_simulate_new_fills():
    pnls = [Decimal(-5), Decimal(4)] * 10
    first = trade_reshuffle(pnls, Decimal(100), seed=3, simulations=100)
    assert first == trade_reshuffle(pnls, Decimal(100), seed=3, simulations=100)
    assert first["final_realized_equity"] == "90"
    assert first["closed_trade_count"] == 20 and not first["new_market_samples"]
    assert first["status"] == "DESCRIPTIVE_ONLY"
    assert trade_reshuffle(pnls[:2], Decimal(100), seed=3, simulations=100)["status"] == "INSUFFICIENT_DATA"


def test_native_verified_comparison_reports_limitations_and_rejects_store_mismatch(tmp_path):
    db = market_db(tmp_path, quote_history(n=1000))
    try:
        records = [paper(db, "BTCUSDT", START, START + timedelta(minutes=160), resolution="1min",
                         params={"fast": n, "slow": n + 2}) for n in (2, 3)]
        for out in records:
            save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    value = {"run_ids": [out["run_id"] for out in records], "partitions": 4,
             "seed": 23, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 90}
    result = robustness(tmp_path / "runs", value, store="live")
    assert result == robustness(tmp_path / "runs", value, store="live")
    assert result["cscv"]["combinations"] == 6
    assert result["all_trials_accounted_for"] is False and result["funded_authority"] is False
    assert all(row["regimes"]["status"] == "NOT_RECORDED" for row in result["runs"])
    assert all(row["return_blocks"]["status"] == "DESCRIPTIVE_ONLY" for row in result["runs"])
    with pytest.raises(ValueError, match="store"):
        robustness(tmp_path / "runs", value, store="demo")
    value["run_ids"] = [value["run_ids"][0]] * 2
    with pytest.raises(ValueError):
        robustness(tmp_path / "runs", value, store="live")


def test_gaps_cannot_receive_a_confident_cscv_statistic(tmp_path):
    quotes = [q for q in quote_history(n=1000) if not START + timedelta(minutes=35) <= q.ts_avail < START + timedelta(minutes=55)]
    db = market_db(tmp_path, quotes)
    try:
        records = [paper(db, "BTCUSDT", START, START + timedelta(minutes=160), resolution="1min",
                         params={"fast": n, "slow": n + 2}) for n in (2, 3)]
        for out in records:
            save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    result = robustness(tmp_path / "runs", {"run_ids": [out["run_id"] for out in records], "partitions": 4,
        "seed": 23, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 90}, store="live")
    assert result["cscv"]["status"] == "INSUFFICIENT_CONTIGUOUS_DATA"
    assert "below_median_fraction" not in result["cscv"]


def test_native_compound_regimes_use_exact_saved_decision_clocks(tmp_path):
    db = market_db(tmp_path, quote_history(n=1000))
    try:
        records = [paper(db, "BTCUSDT", START, START + timedelta(minutes=160), resolution="1min",
            strategy_id="trend-pullback", params={"cooldown_bars": n}) for n in (2, 3)]
        for out in records:
            save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    report = robustness(tmp_path / "runs", {"run_ids": [r["run_id"] for r in records], "partitions": 4,
        "seed": 23, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 90}, store="live")
    assert all(row["regimes"]["status"] == "RECORDED" for row in report["runs"])
    assert any("UP_TREND" in row["regimes"]["groups"] for row in report["runs"])


def test_cost_or_window_mismatch_is_rejected_before_resampling(tmp_path):
    db = market_db(tmp_path, quote_history(n=1000))
    try:
        records = [paper(db, "BTCUSDT", START, START + timedelta(minutes=n), resolution="1min",
                         params={"fast": 2, "slow": 4}) for n in (100, 160)]
        for out in records:
            save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    with pytest.raises(ValueError, match="identical"):
        robustness(tmp_path / "runs", {"run_ids": [r["run_id"] for r in records], "partitions": 4,
            "seed": 23, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 90}, store="live")
    with pytest.raises(ValueError, match="budget"):
        cscv([[Decimal(i) for i in range(8)]] * 1000, 10)


def test_robustness_runs_in_real_bounded_worker(tmp_path):
    import asyncio

    from gym.services.research_process import calculate

    db = market_db(tmp_path, quote_history(n=1000))
    try:
        records = [paper(db, "BTCUSDT", START, START + timedelta(minutes=160), resolution="1min",
                         params={"fast": n, "slow": n + 2}) for n in (2, 3)]
        for out in records:
            save_run(out, tmp_path / "runs")
    finally:
        db.c.close()
    value = {"run_ids": [out["run_id"] for out in records], "partitions": 4,
             "seed": 23, "simulations": 100, "mean_block_length": 5, "max_gap_seconds": 90}
    result = asyncio.run(calculate(tmp_path, "robustness", value))
    assert result["common_intervals"] > 100 and result["funded_authority"] is False
