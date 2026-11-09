"""Regressions in Phase B market models: profile validation, risk parity, impact volatility and research-only gates."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.execution_costs import validate_hourly_costs, validate_impact_models
from gym.domain.model import BookTop, InstrumentId, TradeTick, iso
from gym.domain.portfolio_policy import PortfolioPolicy
from gym.domain.sim import CostModel, Spec
from gym.services.execution_market_models import _public_trade_samples
from gym.services.experimental_probabilistic_regime import (
    review_regime_prospective_evidence,
)
from gym.services.paper_twap import simulate_twap
from gym.services.research_process import HEAVY_ACTIONS, calculate
from tests.support import START, market_db, quote_history
from tests.test_phase_b_impact_costs import hourly_profile, impact_profile


def test_cli_rejects_ignored_explicit_high_low_volatility_without_target(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, quote_history(n=180)).c.close()
    status = main(["--data", str(tmp_path), "paper", "BTCUSDT", "--from", iso(START),
                   "--to", iso(START + timedelta(minutes=25)), "--res", "1min",
                   "--volatility-model", "parkinson-ewma"])
    assert status == 2
    assert "--vol-target" in capsys.readouterr().err
    assert not list((root / "runs").glob("*.json"))


@pytest.mark.parametrize(("validator", "profile", "missing"), [
    (validate_impact_models, impact_profile, "trained_until"),
    (validate_impact_models, impact_profile, "a"),
    (validate_hourly_costs, hourly_profile, "trained_until"),
])
def test_profiles_with_missing_required_fields_fail_as_validation_errors(validator, profile, missing):
    row = profile()
    row.pop(missing)
    with pytest.raises(ValueError):
        validator({"BTCUSDT": row})


@pytest.mark.parametrize(("validator", "profile"), [
    (validate_impact_models, impact_profile),
    (validate_hourly_costs, hourly_profile),
])
def test_profiles_with_nonstr_timestamps_fail_as_validation_errors(validator, profile):
    row = profile()
    row["trained_until"] = 42
    with pytest.raises(ValueError):
        validator({"BTCUSDT": row})


def test_hourly_costs_missing_spread_is_a_validation_error():
    row = hourly_profile()
    row["hours"]["12"].pop("spread_bps")
    with pytest.raises(ValueError):
        validate_hourly_costs({"BTCUSDT": row})


def test_nonconvergent_raw_covariance_does_not_abort_ready_shrunk_risk_parity():
    symbols = ["A", "B", "C"]
    series = [["100", "99", "99", "99.99"],
              ["100", "99", "99", "99.99"],
              ["100", "101", "101", "99.99"]]
    observations = {symbol: [(i, Decimal(v)) for i, v in enumerate(series[k])]
                    for k, symbol in enumerate(symbols)}
    raw = PortfolioPolicy({"method": "risk-parity", "lookback": 3}, symbols)
    assert raw.weights(observations)["status"] != "READY"
    modeled = PortfolioPolicy(
        {"method": "risk-parity", "lookback": 3,
         "covariance_shrinkage": "ledoit-wolf-constant-correlation"}, symbols)
    modeled._last_raw_weights = {s: "0.333333333333" for s in symbols}
    report = modeled.weights(observations)
    assert report["status"] == "READY"
    assert report["covariance_shrinkage"]["turnover_raw"] is None
    assert report["covariance_shrinkage"]["turnover_shrunk"] is None
    assert modeled._last_raw_weights is None


def test_gap_after_trade_finalized_bucket_resets_public_impact_volatility(tmp_path):
    quotes = []
    for minute in [*range(12), 25]:
        first = START + timedelta(minutes=minute)
        bid = Decimal(100 + minute)
        quotes.append(BookTop("BTCUSDT", first, bid, bid + 2,
                              Decimal(100), Decimal(100), frozenset()))
        quotes.append(BookTop("BTCUSDT", first + timedelta(seconds=20), bid + 1,
                              bid + 3, Decimal(100), Decimal(100), frozenset()))
    db = market_db(tmp_path, quotes)
    try:
        for minute, qty in [(2, 100), (12, 1), (26, 1)]:
            when = START + timedelta(minutes=minute, seconds=1)
            db.add_trade(TradeTick("BTCUSDT", when, when, Decimal(114 if minute == 12 else 128 if minute == 26 else 104), Decimal(qty), "BUY"),
                         "test-print")
        samples, _ = _public_trade_samples(db, "BTCUSDT", START, START + timedelta(minutes=27))
        # Minute 26 follows a 13-minute quote gap; even plausible prints must
        # not use the previous minute chain as an impact variance estimate.
        assert len(samples) == 1
    finally:
        db.c.close()


@pytest.mark.parametrize("invalid", [Decimal("-0.001"), Decimal(-1), Decimal("1.001")])
def test_regime_pvalue_must_be_valid_probability(invalid):
    with pytest.raises(ValueError, match="p-value"):
        review_regime_prospective_evidence(
            [Decimal(2)] * 30, [Decimal(1)] * 30, independent_final_evidence=True,
            prospective_registration_ids=["frozen-1"], spa_p_value=invalid)


def test_promising_regime_claim_is_still_not_promoted_without_independent_proof():
    claimed = review_regime_prospective_evidence(
        [Decimal(2)] * 30, [Decimal(1)] * 30, independent_final_evidence=True,
        prospective_registration_ids=["frozen-1"], spa_p_value=Decimal("0.01"))
    assert claimed["decision"] == "MANUAL_INDEPENDENT_REVIEW_REQUIRED"
    assert claimed["status"] == "NOT_PROMOTED"
    assert claimed["probabilistic_gate_selectable"] is False


def test_twap_child_preserves_modeled_price_guard_reason():
    profile = impact_profile()
    profile["b"] = "100"
    quotes = [BookTop("BTCUSDT", START + timedelta(seconds=10), Decimal(100),
                      Decimal("100.2"), Decimal(1000), Decimal(1000), frozenset())]
    out = simulate_twap(
        InstrumentId.wallex("BTCUSDT"), quotes, Spec(qty_decimals=8),
        START, START + timedelta(minutes=1), side="BUY", quantity=Decimal(1),
        slices=1, participation=Decimal(1), fee_rate="0.001",
        available_quote=Decimal(1000), available_base=Decimal(0),
        max_delay_seconds=30, store="demo",
        cost=CostModel(impact_models={"BTCUSDT": profile}))
    assert out["children"][0]["status"] == "NONFILL"
    assert out["children"][0]["reason"] == "MODELED_IMPACT_PRICE_GUARD"


def test_execution_model_calibration_is_bounded_by_research_supervisor(tmp_path):
    assert "execution-model-calibrate" in HEAVY_ACTIONS
    market_db(tmp_path, quote_history(n=180)).c.close()
    output = asyncio.run(calculate(tmp_path, "execution-model-calibrate", {
        "symbol": "BTCUSDT", "from": iso(START),
        "to": iso(START + timedelta(minutes=25))}, store="live", timeout_seconds=30))
    assert output["schema"] == "execution-market-model/1"
    assert output["funded_authority"] is False
