"""Independent impact fits and opt-in hourly cost assumptions."""
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from gym.domain.execution_costs import fit_square_root_impact
from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from gym.services.paper_twap import simulate_twap
from tests.support import START


def impact_profile(as_of=None):
    return {"schema": "sqrt-impact/1", "symbol": "BTCUSDT",
            "a": "1.2", "b": "0.7", "volatility_bps": "200",
            "volume_base": "100", "fit_rmse_bps": "1",
            "holdout_rmse_bps": "2", "sample_count": 40,
            "trained_until": iso(as_of or START - timedelta(hours=1)),
            "source": "PUBLIC_TRADE_VS_PRIOR_MID_PROXY"}


def hourly_profile(as_of=None):
    return {"schema": "hourly-costs/1", "symbol": "BTCUSDT",
            "trained_until": iso(as_of or START - timedelta(hours=1)),
            "hours": {"12": {"spread_bps": "30", "quote_samples": 40,
                             "taker_fee_rate": "0.002", "maker_fee_rate": "0.001",
                             "fee_observed_at": iso(START - timedelta(hours=2))}}}


def test_square_root_fit_recovers_two_parameters_on_held_out_prints():
    samples = []
    with localcontext() as ctx:
        ctx.prec = 60
        for i in range(1, 51):
            spread = Decimal(4 + i % 7)
            sigma = Decimal(80 + i % 5 * 20)
            fraction = Decimal(i) / 100
            cost = Decimal("1.2") * spread / 2 + Decimal("0.7") * sigma * fraction
            samples.append({"spread_bps": str(spread), "volatility_bps": str(sigma),
                            "quantity": str(Decimal(i) ** 2),
                            "volume_base": "10000", "observed_cost_bps": str(cost)})
    report = fit_square_root_impact("BTCUSDT", samples, trained_until=START)
    assert report["status"] == "AVAILABLE"
    assert abs(Decimal(report["a"]) - Decimal("1.2")) < Decimal("1e-25")
    assert abs(Decimal(report["b"]) - Decimal("0.7")) < Decimal("1e-25")
    assert Decimal(report["fit_rmse_bps"]) < Decimal("1e-20")
    assert Decimal(report["holdout_rmse_bps"]) < Decimal("1e-20")
    assert report["sample_count"] == 50


def test_impact_fit_fails_closed_without_independent_explanatory_variation():
    assert fit_square_root_impact("BTCUSDT", [], trained_until=START)["status"] == "INSUFFICIENT_DATA"
    same = [{"spread_bps": "2", "volatility_bps": "100", "quantity": "1",
             "volume_base": "100", "observed_cost_bps": "2"}] * 40
    assert fit_square_root_impact("BTCUSDT", same, trained_until=START)["status"] == "UNIDENTIFIABLE"


def test_impact_is_priced_in_paper_fill_and_never_spends_more_than_cash():
    top = BookTop("BTCUSDT", START + timedelta(seconds=1),
                  Decimal(100), Decimal("100.2"), Decimal(1000),
                  Decimal(1000), frozenset())
    inst = InstrumentId.wallex("BTCUSDT")
    legacy = CashBook({"USDT": Decimal(1000)})
    calibrated = CashBook({"USDT": Decimal(1000)})
    normal = market_order(legacy, inst, "BUY", Decimal(1), START, top.ask,
                          [top], 0, CostModel(), Spec(qty_decimals=8), [], {}, "plain")
    enhanced = market_order(calibrated, inst, "BUY", Decimal(1), START, top.ask,
                            [top], 0, CostModel(impact_models={"BTCUSDT": impact_profile()}),
                            Spec(qty_decimals=8), [], {}, "modeled")
    assert normal["status"] == enhanced["status"] == "FILLED"
    assert Decimal(enhanced["price"]) > Decimal(normal["price"])
    assert enhanced["pricing"]["impact_extra_bps"] != "0"
    assert Decimal(enhanced["qty"]) < Decimal(normal["qty"])
    assert calibrated.get("USDT") >= 0
    assert "impact_models" not in CostModel().describe()


def test_hourly_table_raises_observed_spread_floor_and_uses_observed_fee():
    hour = START.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Tehran")).hour
    model = hourly_profile()
    model["hours"] = {str(hour): model["hours"]["12"]}
    cost = CostModel(hourly_costs={"BTCUSDT": model})
    b = CashBook({"USDT": Decimal(1000)})
    top = BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100),
                  Decimal("100.2"), Decimal(1000), Decimal(1000), frozenset())
    fill = market_order(b, InstrumentId.wallex("BTCUSDT"), "BUY", Decimal("0.2"),
                        START, top.ask, [top], 0, cost, Spec(qty_decimals=8), [], {}, "t")
    assert fill["status"] == "FILLED"
    assert fill["pricing"]["modeled_spread_bps"] == "30"
    assert fill["pricing"]["observed_spread_bps"] != "30"
    assert fill["pricing"]["applied_fee_rate"] == "0.002"
    assert Decimal(fill["price"]) > top.ask
    assert cost.describe()["hourly_costs"]["BTCUSDT"]["hours"][str(hour)]["quote_samples"] == 40


def test_future_cost_profile_is_never_usable_for_historical_replay():
    with pytest.raises(ValueError, match="future"):
        CostModel(impact_models={"BTCUSDT": impact_profile(START + timedelta(hours=1))}).assert_causal(START)
    with pytest.raises(ValueError, match="future"):
        CostModel(hourly_costs={"BTCUSDT": hourly_profile(START + timedelta(hours=1))}).assert_causal(START)


def test_twap_preview_applies_the_same_opt_in_impact_profile():
    instrument = InstrumentId.wallex("BTCUSDT")
    quotes = [
        BookTop("BTCUSDT", START + timedelta(seconds=10 + i * 60),
                Decimal(100), Decimal("100.2"), Decimal(1000),
                Decimal(1000), frozenset())
        for i in range(3)
    ]
    kwargs = {"side": "BUY", "quantity": Decimal(3), "slices": 3,
              "participation": Decimal(1), "fee_rate": "0.001",
              "available_quote": Decimal(1000), "available_base": Decimal(0),
              "max_delay_seconds": 30, "store": "demo"}
    legacy = simulate_twap(instrument, quotes, Spec(qty_decimals=8),
                           START, START + timedelta(minutes=3), **kwargs)
    modeled = simulate_twap(instrument, quotes, Spec(qty_decimals=8),
                            START, START + timedelta(minutes=3),
                            cost=CostModel(impact_models={"BTCUSDT": impact_profile()}), **kwargs)
    assert Decimal(modeled["spent_quote"]) > Decimal(legacy["spent_quote"])
    assert modeled["children"][0]["pricing"]["impact_extra_bps"] != "0"
    assert modeled["funded_authority"] is False
