"""Regression contracts for causal cross-market research, paper TWAP and frozen comparisons."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId
from gym.domain.sim import Spec
from gym.services.experiment_registry import ExperimentRegistry
from gym.services.paper_twap import simulate_twap
from gym.services.premium_lead_lag import analyze_quotes
from gym.services.prospective_comparisons import evaluate_comparison, register_comparison

START = datetime(2026, 1, 1, tzinfo=UTC)


def quote(symbol, second, bid, ask, size="10", flags=()):
    return BookTop(
        symbol, START + timedelta(seconds=second), Decimal(bid), Decimal(ask),
        Decimal(size), Decimal(size), frozenset(flags),
    )


def test_premium_uses_only_quotes_available_before_each_close():
    data = {
        "BTCTMN": [quote("BTCTMN", 20, "100", "101"), quote("BTCTMN", 125, "200", "201")],
        "BTCUSDT": [quote("BTCUSDT", 20, "1", "1.01")],
        "USDTTMN": [quote("USDTTMN", 20, "99", "100")],
    }
    report = analyze_quotes("BTC", data, START, START + timedelta(seconds=180),
                            resolution="1min", max_age_seconds=65, max_skew_seconds=65,
                            fee_rate=Decimal("0.001"), store="demo")
    assert report["authority"] == "PAPER_ONLY" and report["funded_authority"] is False
    assert report["samples"][0]["at"].endswith("00:01:00.000000Z")
    assert Decimal(report["samples"][0]["premium_bps"]) < 100  # future 200 TMN quote must not leak
    assert report["coverage"]["eligible"] == 1
    assert report["coverage"]["excluded"] == 2
    assert "UNQUALIFIED_OR_MISSING" in report["coverage"]["reasons"] or "STALE_QUOTE" in report["coverage"]["reasons"]


def test_premium_rejects_closed_or_skewed_market_and_does_not_claim_edge():
    data = {
        "BTCTMN": [quote("BTCTMN", 20, "100", "101", flags=("CLOSED",))],
        "BTCUSDT": [quote("BTCUSDT", 40, "1", "1.01")],
        "USDTTMN": [quote("USDTTMN", 20, "99", "100")],
    }
    report = analyze_quotes("BTC", data, START, START + timedelta(seconds=60),
                            resolution="1min", max_age_seconds=60, max_skew_seconds=5,
                            fee_rate=Decimal("0.001"), store="demo")
    assert report["coverage"]["eligible"] == 0
    assert report["held_out"] is False
    assert report["established_edge"] is False
    assert not report["samples"]


def test_paper_twap_slices_partials_and_conserves_exact_cash_and_quantity():
    prices = [quote("BTCUSDT", 1, "9", "10", "2"),
              quote("BTCUSDT", 61, "10", "11", "1"),
              quote("BTCUSDT", 121, "11", "12", "1")]
    result = simulate_twap(
        InstrumentId.wallex("BTCUSDT"), prices, Spec(qty_decimals=2),
        START, START + timedelta(seconds=180), side="BUY", quantity=Decimal(6),
        slices=3, participation=Decimal(1), fee_rate=Decimal("0.01"),
        available_quote=Decimal(100), available_base=Decimal(0), max_delay_seconds=10, store="demo",
    )
    assert result["order_submitted"] is False
    assert result["requested_quantity"] == "6"
    assert result["filled_quantity"] == "4"
    assert result["cancelled_quantity"] == "2"
    assert result["remaining_quote"] == "57"  # 2*10 + 1*11 + 1*12
    assert result["received_base"] == "3.96"
    assert [x["status"] for x in result["children"]] == ["FILLED", "PARTIAL", "PARTIAL"]


def test_paper_twap_refuses_unknown_or_late_quotes_and_never_overspends():
    late = [quote("BTCUSDT", 40, "9", "10", "10")]
    result = simulate_twap(
        InstrumentId.wallex("BTCUSDT"), late, Spec(), START, START + timedelta(seconds=120),
        side="BUY", quantity=Decimal(5), slices=2, participation=Decimal("0.5"),
        fee_rate=Decimal(0), available_quote=Decimal(1), available_base=Decimal(0),
        max_delay_seconds=5, store="demo",
    )
    assert result["filled_quantity"] == "0"
    assert result["remaining_quote"] == "1"
    assert result["cancelled_quantity"] == "5"
    with pytest.raises(ValueError):
        simulate_twap(InstrumentId.wallex("BTCUSDT"), late, Spec(), START,
                      START + timedelta(seconds=120), side="BUY", quantity=Decimal(5),
                      slices=2, participation=Decimal("1.1"), fee_rate=Decimal(0),
                      available_quote=Decimal(100), available_base=Decimal(0),
                      max_delay_seconds=5, store="demo")


def test_prospective_registry_freezes_future_candidates(tmp_path):
    future = START + timedelta(days=2)
    request = {"symbol": "BTCUSDT", "candidates": [
        {"strategy": "ema-trend", "params": {}},
        {"strategy": "sma-cross", "params": {}},
    ], "selection_end": START.isoformat(), "test_from": (future + timedelta(hours=1)).isoformat(),
       "test_to": (future + timedelta(hours=3)).isoformat(), "resolution": "15min",
       "cash": "1000", "fee_rate": "0.001"}
    with ExperimentRegistry(tmp_path, store="demo") as registry:
        record = register_comparison(registry, request, now=START + timedelta(minutes=1))
        assert record["kind"] == "PROSPECTIVE_COMPARE"
        assert record["configuration"]["candidates"][0]["params"]["fast"] == 8
        assert record["funded_authority"] is False
        with pytest.raises(ValueError):
            register_comparison(registry, {**request, "test_from": START.isoformat()}, now=START)
        with pytest.raises(ValueError):
            evaluate_comparison(registry, record["id"], None, now=START)
        # The recorded window is closed, but an evaluation error still consumes its one attempt.
        with pytest.raises(ValueError, match="independent market read snapshot"):
            evaluate_comparison(registry, record["id"], None, now=future + timedelta(days=1))
        status = registry.read(record["id"])
        assert any(child["kind"] == "PROSPECTIVE_ATTEMPT" for child in status["events"])
        with pytest.raises(ValueError, match="consumed"):
            evaluate_comparison(registry, record["id"], None, now=future + timedelta(days=1))
