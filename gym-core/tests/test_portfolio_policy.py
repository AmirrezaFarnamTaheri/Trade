"""Causal allocations and latched paper risk controls preserve shared capital."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import TradeTick, iso
from gym.domain.portfolio_policy import PortfolioPolicy
from gym.domain.sim import CostModel
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def test_weights_use_aligned_returns_and_conserve_cash_without_filling_missing_history():
    policy = PortfolioPolicy({"method": "inverse-volatility", "lookback": 3, "max_weight": "0.6"}, ["BTCUSDT", "ETHUSDT"])
    assert policy.weights({})["status"] == "WARMING_UP"
    observations = {"BTCUSDT": [(i, Decimal(v)) for i, v in enumerate((100, 102, 101, 103))],
                    "ETHUSDT": [(i, Decimal(v)) for i, v in enumerate((100, 104, 102, 106))]}
    result = policy.weights(observations)
    assert result["status"] == "READY"
    assert Decimal(result["weights"]["BTCUSDT"]) > Decimal(result["weights"]["ETHUSDT"])
    assert max(map(Decimal, result["weights"].values())) <= Decimal("0.6")
    assert sum(map(Decimal, result["weights"].values())) <= 1
    observations["ETHUSDT"][-1] = (99, Decimal(106))
    assert policy.weights(observations)["status"] == "WARMING_UP"


def test_risk_parity_uses_covariance_and_reports_zero_variance():
    policy = PortfolioPolicy({"method": "risk-parity", "lookback": 3}, ["BTCUSDT", "ETHUSDT"])
    observations = {s: [(i, Decimal(v)) for i, v in enumerate(values)] for s, values in
                    (("BTCUSDT", (100, 102, 101, 103)), ("ETHUSDT", (100, 104, 102, 106)))}
    report = policy.weights(observations)
    assert report["status"] == "READY" and report["risk_contribution_error"] is not None
    assert sum(map(Decimal, report["weights"].values())) <= 1
    observations["ETHUSDT"] = [(i, Decimal(100)) for i in range(4)]
    assert policy.weights(observations)["status"] == "ZERO_VARIANCE"


def test_drawdown_latches_and_daily_loss_resets_at_tehran_midnight():
    policy = PortfolioPolicy({"max_drawdown": "0.1", "daily_loss_limit": "0.05"}, ["BTCUSDT", "ETHUSDT"])
    policy.observe(START, Decimal(100))
    assert policy.observe(START + timedelta(minutes=1), Decimal(94)) == "DAILY_LOSS"
    assert policy.observe(START + timedelta(minutes=2), Decimal(100)) == "DAILY_LOSS"
    assert policy.observe(START + timedelta(days=1), Decimal(100)) is None
    assert policy.observe(START + timedelta(days=1, minutes=1), Decimal(89)) == "DRAWDOWN"
    assert policy.observe(START + timedelta(days=2), Decimal(105)) == "DRAWDOWN"


@pytest.mark.parametrize("value", [{"max_weight": 0.5}, {"method": "magic"}, {"lookback": True},
                                      {"daily_loss_limit": "0"}, {"max_drawdown": "NaN"}, {"unknown": 1}])
def test_invalid_policy_fails_before_replay(value):
    with pytest.raises(ValueError):
        PortfolioPolicy(value, ["BTCUSDT", "ETHUSDT"])


def test_native_replay_records_policy_and_cannot_spend_reserved_cash_twice(tmp_path):
    db = market_db(tmp_path, quote_history(n=500) + quote_history(n=500, sym="ETHUSDT"))
    try:
        options = {"resolution": "1min", "params": {"fast": 2, "slow": 3},
                       "policy": {"method": "inverse-volatility", "lookback": 3, "max_weight": "0.4", "max_drawdown": "0.05"}}
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), **options)
        assert out["inputs"]["policy"]["method"] == "inverse-volatility"
        assert out["result"]["policy_events"]
        assert Decimal(out["result"]["balances"]["USDT"]) >= 0
        assert all(Decimal(row["reserved_quote"]) >= 0 for row in out["result"]["policy_events"])
        reservations = [row for row in out["result"]["policy_events"] if row["kind"] == "RESERVE"]
        assert reservations and all(Decimal(row["reserved_quote"]) <= Decimal(row["cash_quote"]) for row in reservations)
    finally:
        db.c.close()


def test_correlated_markets_share_a_group_cap_and_keep_unused_cash():
    policy = PortfolioPolicy({"method": "inverse-volatility", "lookback": 3,
                              "correlation_limit": "0.8", "correlation_cap": "0.4"}, ["BTCUSDT", "ETHUSDT"])
    observations = {s: [(i, Decimal(v)) for i, v in enumerate((100, 102, 101, 103))] for s in policy.symbols}
    assert sum(map(Decimal, policy.weights(observations)["weights"].values())) <= Decimal("0.4")


def test_native_loss_latch_requests_exits_and_blocks_later_buys(tmp_path):
    db = market_db(tmp_path, quote_history(n=300) + quote_history(n=300, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=45), resolution="1min",
                        params={"fast": 2, "slow": 3}, policy={"max_drawdown": "0.00001"})
        first = next(row for row in out["result"]["policy_events"] if row["kind"] == "RISK" and row["state"] == "DRAWDOWN")
        orders = [order for row in out["result"]["markets"].values() for order in row["orders"]]
        assert any(order["side"] == "SELL" for order in orders)
        assert not any(order["status"] == "FILLED" and order["side"] == "BUY" and order["fill_time"] > first["at"] for order in orders)
        assert out["result"]["policy_state"]["risk"] == "DRAWDOWN"
    finally:
        db.c.close()


def test_policy_targets_are_invariant_to_future_prices(tmp_path):
    db = market_db(tmp_path, quote_history(n=300) + quote_history(n=300, sym="ETHUSDT"))
    options = {"resolution": "1min", "params": {"fast": 2, "slow": 3}, "policy": {"method": "inverse-volatility", "lookback": 3}}
    try:
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=45), **options)
        cutoff = iso(START + timedelta(minutes=12))
        db.c.execute("UPDATE book_top SET bid='1000000', ask='1000001' WHERE ts_avail>=?", (cutoff,))
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=45), **options)
        prefix = lambda out: [row for row in out["result"]["policy_events"] if row["at"] < cutoff]
        assert prefix(before) and prefix(before) == prefix(after)
    finally:
        db.c.close()


def test_cash_buffer_survives_an_overweight_holding_price_jump(tmp_path):
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for i, q in enumerate(quote_history(n=80, sym=symbol)):
            bid = Decimal(100 + i if i < 30 else 1000 + i) if symbol == "BTCUSDT" else Decimal(100 if i < 36 else 101 + i - 36)
            rows.append(replace(q, bid=bid, ask=bid + Decimal("0.01")))
    db = market_db(tmp_path, rows)
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=13), resolution="1min",
                        params={"fast": 2, "slow": 3}, policy={"cash_buffer": "0.2"})
        assert Decimal(out["result"]["balances"]["USDT"]) >= Decimal(500)
    finally:
        db.c.close()


def test_explicit_rebalancing_trades_targets_without_strategy_warmup_claim(tmp_path):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=25), resolution="1min",
                        policy={"rebalance": True, "rebalance_seconds": 300, "cash_buffer": "0.2"})
        assert any(row["fills"] for row in out["result"]["markets"].values())
        assert out["inputs"]["policy"]["rebalance"] is True
        assert all(order["decision_time"] >= iso(START + timedelta(minutes=21))
                   for row in out["result"]["markets"].values() for order in row["orders"])
        assert "subsequent decisions" in out["result"]["policy_state"]["scope"]
    finally:
        db.c.close()


def test_rebalancing_cannot_bypass_the_shared_regime_gate(tmp_path):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=25), resolution="1min",
                        params={"fast": 2, "slow": 3, "regime_gate": "UP_TREND"}, policy={"rebalance": True})
        assert all(row["fills"] == 0 for row in out["result"]["markets"].values())
    finally:
        db.c.close()


def test_covariance_budget_is_explicit_without_restricting_equal_weight_universe():
    symbols = [f"A{i}USDT" for i in range(373)]
    report = PortfolioPolicy({}, symbols).weights({})
    assert len(report["weights"]) == 373 and sum(map(Decimal, report["weights"].values())) <= 1
    with pytest.raises(ValueError, match="budget"):
        PortfolioPolicy({"method": "risk-parity"}, symbols)


def test_reported_risk_error_reflects_the_constrained_weights_and_gaps_are_explicit():
    policy = PortfolioPolicy({"method": "risk-parity", "lookback": 3, "max_weight": "0.4"}, ["BTCUSDT", "ETHUSDT"])
    observations = {s: [(i, Decimal(v)) for i, v in enumerate(values)] for s, values in
                    (("BTCUSDT", (100, 102, 101, 103)), ("ETHUSDT", (100, 104, 102, 106)))}
    assert Decimal(policy.weights(observations)["risk_contribution_error"]) > Decimal("0.1")
    for row in observations.values():
        row[-1] = (10, row[-1][1])
    assert policy.weights(observations)["status"] == "GAPPED_HISTORY"


def test_underweight_rebalancing_never_reverses_a_strategy_exit(tmp_path):
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for i, q in enumerate(quote_history(n=120, sym=symbol)):
            bid = Decimal(100 + i if i < 60 else 160 - (i - 60) if symbol == "BTCUSDT" else 1000 + i)
            rows.append(replace(q, bid=bid, ask=bid + Decimal("0.01")))
    db = market_db(tmp_path, rows)
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=19), resolution="1min",
                        params={"fast": 2, "slow": 3}, policy={"rebalance": True, "rebalance_threshold": "0.001"})
        orders = out["result"]["markets"]["BTCUSDT"]["orders"]
        assert any(o["side"] == "SELL" and o["decision_time"] >= iso(START + timedelta(minutes=12)) for o in orders)
        assert not any(o["side"] == "BUY" and o["decision_time"] >= iso(START + timedelta(minutes=12)) for o in orders)
    finally:
        db.c.close()


def test_resting_limit_respects_updated_cash_buffer_at_actual_settlement(tmp_path):
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for i, q in enumerate(quote_history(n=80, sym=symbol)):
            bid = Decimal(100 + i if i < 45 else 1000 + i) if symbol == "BTCUSDT" else Decimal(100 if i < 36 else 101 + i - 36)
            rows.append(replace(q, bid=bid, ask=bid + Decimal("0.01")))
    db = market_db(tmp_path, rows)
    at = START + timedelta(minutes=7, seconds=40)
    btc_fill = START + timedelta(minutes=3, seconds=20)
    db.add_trade(TradeTick("BTCUSDT", btc_fill, btc_fill, Decimal(119), Decimal(100), "SELL"), None)
    db.add_trade(TradeTick("ETHUSDT", at, at, Decimal(107), Decimal(100), "SELL"), None)
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=13), resolution="1min",
                        params={"fast": 2, "slow": 3}, policy={"cash_buffer": "0.2"}, cost=CostModel(order_type="limit"))
        assert any(o["status"] == "FILLED" for o in out["result"]["markets"]["BTCUSDT"]["orders"])
        assert not any(o["side"] == "BUY" and o["status"] == "FILLED" and o["fill_time"] >= iso(at) for o in out["result"]["markets"]["ETHUSDT"]["orders"]), out["result"]["markets"]["ETHUSDT"]["orders"]
    finally:
        db.c.close()


def test_opt_in_portfolio_volatility_target_uses_prior_joint_covariance():
    """Target the combined rather than each component's historical bar risk."""
    symbols = ["BTCUSDT", "ETHUSDT"]
    policy = PortfolioPolicy({"lookback": 3, "portfolio_volatility_target": "0.01"}, symbols)
    assert policy.weights({})["status"] == "WARMING_UP"
    history = {"BTCUSDT": [(i, Decimal(v)) for i, v in enumerate((100, 110, 100, 110))],
               "ETHUSDT": [(i, Decimal(v)) for i, v in enumerate((100, 105, 100, 105))]}
    result = policy.weights(history)
    assert result["status"] == "READY"
    assert Decimal(0) < Decimal(result["portfolio_volatility"]["scale"]) < 1
    assert Decimal(result["portfolio_volatility"]["projected_per_bar"]) <= Decimal("0.01")
    assert sum(map(Decimal, result["weights"].values())) < 1
    assert PortfolioPolicy({}, symbols).weights({})["status"] == "READY"


def test_portfolio_volatility_target_rejects_bad_input_and_gaps():
    """Do not apply a target when risk units or historical continuity are unknown."""
    symbols = ["BTCUSDT", "ETHUSDT"]
    for invalid in ("0", "1.1", "-0.1", "NaN", 0.1):
        with pytest.raises(ValueError):
            PortfolioPolicy({"portfolio_volatility_target": invalid}, symbols)
    policy = PortfolioPolicy({"lookback": 3, "portfolio_volatility_target": "0.01"}, symbols)
    history = {s: [(i, Decimal(v)) for i, v in enumerate((100, 110, 100, 110))]
               for s in symbols}
    history["ETHUSDT"][-1] = (10, Decimal(110))
    assert policy.weights(history)["status"] == "WARMING_UP"


def test_expected_shortfall_target_scales_joint_paper_weights_from_prior_tail():
    """One 10% historical loss among 20 bars gives a 10% empirical ES95 tail."""
    symbols = ["BTCUSDT", "ETHUSDT"]
    policy = PortfolioPolicy({"lookback": 20, "rebalance": True,
                              "expected_shortfall_limit": "0.02"}, symbols)
    prices = [Decimal(100)]
    for change in [Decimal("0.01")] * 19 + [Decimal("-0.1")]:
        prices.append(prices[-1] * (1 + change))
    observed = {symbol: [(i, price) for i, price in enumerate(prices)]
                for symbol in symbols}
    result = policy.weights(observed)
    assert result["status"] == "READY"
    tail = result["expected_shortfall"]
    assert tail["confidence"] == "0.95"
    assert tail["worst_observations"] == 1
    assert Decimal(tail["unscaled_per_bar"]) == Decimal("0.1")
    assert Decimal(tail["scale"]) == Decimal("0.2")
    assert Decimal(tail["scaled_per_bar"]) <= Decimal("0.02")
    assert sum(map(Decimal, result["weights"].values())) <= Decimal("0.2")


def test_expected_shortfall_requires_explicit_rebalancing_and_track_record():
    """Prevent pretending to cap held exposure when only new-entry sizing exists."""
    for value in ({"expected_shortfall_limit": "0.02"},
                  {"expected_shortfall_limit": "0.02", "rebalance": True, "lookback": 3},
                  {"expected_shortfall_limit": "0", "rebalance": True, "lookback": 20}):
        with pytest.raises(ValueError):
            PortfolioPolicy(value, ["BTCUSDT", "ETHUSDT"])


def test_cost_aware_rebalance_band_uses_observed_spread_and_fees(tmp_path):
    """Opt-in no-trade bands report prior quote costs and weighted drift."""
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        policy = {"rebalance": True, "rebalance_seconds": 300,
                  "rebalance_threshold": "0.0001", "cost_aware_rebalance": True}
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START,
                        START + timedelta(minutes=25), resolution="1min",
                        policy=policy, cost=CostModel(fee_rate=Decimal("0.05")))
        assert out["inputs"]["portfolio_version"] >= 11
        events = [row for row in out["result"]["policy_events"] if row["kind"] == "REBALANCE_BAND"]
        assert events
        for event in events:
            assert Decimal(event["band_fraction"]) >= Decimal("0.1")
            assert Decimal(event["tracking_error_fraction"]) >= 0
            assert Decimal(event["modeled_cost_fraction"]) >= Decimal("0.1")
            assert event["source_quote_time"] <= event["at"]
            assert event["requested"] == (Decimal(event["tracking_error_fraction"]) >
                                          Decimal(event["band_fraction"]))
    finally:
        db.c.close()


def test_cost_aware_rebalance_requires_explicit_rebalance_and_boolean():
    for params in ({"cost_aware_rebalance": True},
                   {"rebalance": True, "cost_aware_rebalance": "yes"},
                   {"rebalance": True, "cost_aware_rebalance": 1}):
        with pytest.raises(ValueError):
            PortfolioPolicy(params, ["BTCUSDT", "ETHUSDT"])
