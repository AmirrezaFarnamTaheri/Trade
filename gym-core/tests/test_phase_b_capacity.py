"""Phase B 23: conservative strategy capacity in USDT, from verified cost evidence."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.model import iso
from gym.services.strategy_capacity import scorecard_capacity
from tests.support import START


def run(net="20", *, quote="USDT", with_impact=True):
    profile = {"schema": "sqrt-impact/1", "symbol": "BTCUSDT",
               "a": "1", "b": "1", "volatility_bps": "100",
               "volume_base": "100", "fit_rmse_bps": "1",
               "holdout_rmse_bps": "1", "sample_count": 100,
               "trained_until": iso(START - timedelta(days=1)),
               "source": "PUBLIC_TRADE_VS_PRIOR_MID_PROXY"}
    return {"inputs": {"symbol": "BTCUSDT", "from": iso(START), "store": "live",
                       "cost": {"impact_models": {"BTCUSDT": profile}} if with_impact else {}},
            "result": {"quote": quote, "end": {"net_usdt_eq": net},
                       "orders": [{"status": "FILLED", "qty": "10", "price": "100"},
                                  {"status": "FILLED", "qty": "10", "price": "100"}],
                       "fills": 2}}


def test_capacity_is_size_where_impact_consumes_half_the_net_edge():
    capacity = scorecard_capacity(run())
    assert capacity["status"] == "MODELED_ESTIMATE"
    assert abs(Decimal(capacity["capacity_usdt"]) - Decimal("2500")) < Decimal("1e-20")
    assert Decimal(capacity["edge_bps"]) == 100
    assert Decimal(capacity["half_edge_impact_bps"]) == 50
    assert capacity["funded_authority"] is False
    assert "public" in capacity["basis"].lower()


def test_capacity_reports_unavailable_reasons_without_inventing_values():
    assert scorecard_capacity(run(with_impact=False))["capacity_usdt"] is None
    assert scorecard_capacity(run(net="-1"))["status"] == "NO_POSITIVE_NET_EDGE"
    assert scorecard_capacity(run(net="0"))["capacity_usdt"] is None
    assert scorecard_capacity(run(quote="TMN"))["status"] == "FX_AT_FILL_UNAVAILABLE"
    assert scorecard_capacity(run())["capacity_usdt"] is not None
    no_fills = run()
    no_fills["result"]["orders"] = []
    assert scorecard_capacity(no_fills)["capacity_usdt"] is None


def test_synthetic_trials_cannot_claim_trading_capacity():
    sample = run()
    sample["inputs"]["store"] = "demo"
    assert scorecard_capacity(sample)["status"] == "SYNTHETIC"
