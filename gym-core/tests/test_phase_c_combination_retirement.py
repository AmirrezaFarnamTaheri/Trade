"""Phase C items 28-30: past-only combination and evidence-gated catalog governance."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.registry import catalog
from gym.services.oos_combination import combine_oos_curves
from gym.services.strategy_retirement import assess_retirement, meta_label_eligibility
from tests.support import START


def _paths():
    """Two matched, separately observed USDT paper equity paths."""
    fast, stable = Decimal(1000), Decimal(1000)
    a, b = [], []
    for i in range(28):
        if i:
            fast *= Decimal("1.01") if i % 2 else Decimal("0.99")
            stable *= Decimal("1.0005")
        t = (START + timedelta(minutes=i)).isoformat()
        a.append({"at": t, "equity_usdt": str(fast)})
        b.append({"at": t, "equity_usdt": str(stable)})
    return [{"run_id": "a" * 16, "strategy": "ema-trend", "marks": a},
            {"run_id": "b" * 16, "strategy": "sma-cross", "marks": b}]


def test_oos_combination_weights_use_only_earlier_squared_errors():
    report = combine_oos_curves(_paths(), lookback=6, rebalance_cost_bps=Decimal(5))
    assert report["schema"] == "oos-strategy-combination/1"
    assert report["status"] == "MODELED_PROXY_ONLY"
    assert report["funded_authority"] is False
    assert len(report["components"]) == 2
    assert report["modeled_combination_net_usdt"] is not None
    assert report["modeled_combination_net_usdt"] != report["gross_combination_net_usdt"]
    assert Decimal(report["weights"][0]["sma-cross"]) > Decimal("0.5")
    future = _paths()
    for mark in future[1]["marks"][20:]:
        mark["equity_usdt"] = str(Decimal(mark["equity_usdt"]) * 10)
    changed = combine_oos_curves(future, lookback=6, rebalance_cost_bps=Decimal(5))
    assert changed["weights"][:10] == report["weights"][:10]
    assert changed["curve"][:10] == report["curve"][:10]


@pytest.mark.parametrize("mutation", ["clock", "duplicate", "invalid", "money"])
def test_oos_combination_rejects_incomparable_or_malformed_paths(mutation):
    paths = _paths()
    if mutation == "clock":
        paths[1]["marks"][9]["at"] = (START + timedelta(minutes=9, seconds=2)).isoformat()
    elif mutation == "duplicate":
        paths[1]["run_id"] = paths[0]["run_id"]
    elif mutation == "invalid":
        paths[1]["marks"][5]["equity_usdt"] = "NaN"
    else:
        paths[1]["marks"][0]["equity_usdt"] = "1100"
    with pytest.raises(ValueError):
        combine_oos_curves(paths, lookback=6, rebalance_cost_bps=Decimal(5))


def test_combination_refuses_to_claim_net_with_unknown_switch_cost():
    out = combine_oos_curves(_paths(), lookback=6, rebalance_cost_bps=None)
    assert out["status"] == "COST_UNAVAILABLE"
    assert out["modeled_combination_net_usdt"] is None
    assert out["gross_combination_net_usdt"] is not None


def _retirement_rows(percentile=10):
    return [{"strategy": "ema-trend", "symbol": symbol,
             "closed_trades": 35, "random_entry_status": "EXPLORATORY",
             "random_entry_percentile": percentile, "valuation": "CURRENT",
             "run_id": ch * 16, "store": "live", "locally_verified": True}
            for symbol, ch in (("BTCUSDT", "a"), ("ETHUSDT", "b"), ("SOLUSDT", "c"))]


def test_retirement_requires_complete_frozen_universe_and_real_oos_evidence():
    frozen = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    local = assess_retirement(_retirement_rows(), frozen, independent_final=False)
    assert local["status"] == "REVIEW_REQUIRED"
    assert local["hidden_by_default"] is False
    assert local["independent_evidence"] is False
    missing = assess_retirement(_retirement_rows()[:2], frozen, independent_final=False)
    assert missing["status"] == "INSUFFICIENT_EVIDENCE"
    stronger = assess_retirement(_retirement_rows(75), frozen, independent_final=False)
    assert stronger["status"] == "NOT_RETIRED"
    assert {item["id"] for item in catalog()} >= {"ema-trend", "sma-cross"}


def test_retirement_rejects_duplicate_markets_unready_runs_and_unsafe_claims():
    frozen = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    rows = _retirement_rows()
    rows[1]["symbol"] = "BTCUSDT"
    with pytest.raises(ValueError):
        assess_retirement(rows, frozen, independent_final=False)
    rows = _retirement_rows()
    rows[1]["valuation"] = "STALE"
    assert assess_retirement(rows, frozen, independent_final=False)["status"] == "INSUFFICIENT_EVIDENCE"
    with pytest.raises(ValueError):
        assess_retirement(_retirement_rows(), frozen, independent_final=True)


def test_meta_label_remains_deferred_below_three_hundred_closed_trades():
    assert meta_label_eligibility(299)["status"] == "DEFERRED"
    assert meta_label_eligibility(300)["status"] == "RESEARCH_ELIGIBLE_NOT_TRAINED"
    assert meta_label_eligibility(300)["funded_authority"] is False
    assert "meta-labeling" not in [row["id"] for row in catalog()]
    with pytest.raises(ValueError):
        meta_label_eligibility(-1)
