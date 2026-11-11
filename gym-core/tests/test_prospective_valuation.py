"""Prospective comparisons require a current terminal valuation, not just an end row."""
from datetime import timedelta

import pytest

from gym.domain.strategy import digest
from gym.services import prospective_comparisons
from gym.services.experiment_registry import ExperimentRegistry
from tests.support import START, market_db, quote_history


@pytest.mark.parametrize("valuation", ["CURRENT", "STALE", "UNAVAILABLE"])
def test_comparison_discloses_terminal_valuation(tmp_path, monkeypatch, valuation):
    db = market_db(tmp_path, quote_history(n=240, step=10))
    cutoff = START + timedelta(minutes=60 if valuation == "STALE" else 40)
    request = {
        "symbol": "BTCUSDT",
        "candidates": [
            {"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
            {"strategy": "ema-trend", "params": {"fast": 3, "slow": 5}},
        ],
        "selection_end": (START - timedelta(hours=1)).isoformat(),
        "test_from": START.isoformat(), "test_to": cutoff.isoformat(),
        "resolution": "1min", "cash": "1000", "fee_rate": "0.001",
    }
    if valuation == "UNAVAILABLE":
        native_paper = prospective_comparisons.paper

        def without_end(*args, **kwargs):
            run = native_paper(*args, **kwargs)
            run["result"]["end"] = None
            run["outputs_digest"] = digest({k: run[k] for k in ("result", "baselines", "ranking", "fx")})[:16]
            return run

        monkeypatch.setattr(prospective_comparisons, "paper", without_end)
    try:
        with ExperimentRegistry(tmp_path, store="demo") as registry:
            frozen = prospective_comparisons.register_comparison(
                registry, request, now=START - timedelta(minutes=1))
            result = prospective_comparisons.evaluate_comparison(
                registry, frozen["id"], db, now=cutoff + timedelta(minutes=1))
            report = result["report"]
            assert report["comparable"] is (valuation == "CURRENT")
            assert report["data_gaps"] == ([] if valuation == "CURRENT" else [r["run_id"] for r in report["rows"]])
            for row in report["rows"]:
                assert row["fills"] == 2
                assert row["valuation"]["status"] == valuation
                assert row["net_available"] is (valuation == "CURRENT")
                assert (row["net"] is not None) is (valuation == "CURRENT")
            assert report["funded_authority"] is False
            assert report["order_submitted"] is False
            with pytest.raises(ValueError, match="consumed"):
                prospective_comparisons.evaluate_comparison(registry, frozen["id"], db, now=cutoff)
    finally:
        db.c.close()
