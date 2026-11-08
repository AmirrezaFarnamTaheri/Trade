"""Empirical fractions require native preregistration; partial recycled cash is rejected."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, iso
from gym.domain.performance import trade_ledger
from gym.services.fractional_sizing import (
    fractional_sizing,
    growth_fraction,
    simple_roundtrips,
)
from gym.services.research_protocol import ResearchProtocol
from tests.support import START, market_db


def controls(key):
    return {"evaluation_id": key, "fraction": "0.25", "cap": "0.1", "seed": 42, "simulations": 100, "block_length": 3}


def prepared(tmp_path, *, mixed=False):
    rows = []
    for i in range(1440):
        phase = i % 40
        price = Decimal(100 + (phase if phase < 20 else 40 - phase))
        spread = Decimal(10) if mixed and (i // 40) % 2 else Decimal("0.005")
        for seconds in (0, 30):
            rows.append(BookTop("BTCUSDT", START + timedelta(minutes=i, seconds=seconds),
                price - spread, price + spread, Decimal(100), Decimal(100), frozenset()))
    db = market_db(tmp_path, rows)
    clock = {"at": START - timedelta(minutes=5)}
    protocol = ResearchProtocol(tmp_path, store="demo", clock=lambda: clock["at"])
    request = {"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
        "selection_end": iso(START - timedelta(minutes=10)), "test_from": iso(START),
        "test_to": iso(START + timedelta(minutes=1439)), "resolution": "1min", "cash": "1000", "fee_rate": "0"}
    key = protocol.register(request)["evaluation_id"]
    return db, protocol, clock, key


def test_empirical_log_growth_handles_known_solution_and_boundaries():
    # Three equal up/down returns: p=2/3, +/-0.5 -> f=2/3.
    assert abs(growth_fraction([Decimal("0.5"), Decimal("0.5"), Decimal("-0.5")]) - Decimal(2) / 3) < Decimal("0.000001")
    assert growth_fraction([Decimal("-0.1"), Decimal("0.1")]) == 0
    assert growth_fraction([Decimal("-0.2")]) == 0
    with pytest.raises(ValueError):
        growth_fraction([Decimal("-1.01")])


def test_completed_native_evaluation_is_required_and_all_wins_are_insufficient(tmp_path):
    db, protocol, clock, key = prepared(tmp_path)
    try:
        with pytest.raises(ValueError, match="completed"):
            fractional_sizing(protocol, controls(key))
        clock["at"] = START + timedelta(days=2)
        assert protocol.consume(key, db)["state"] == "EVALUATED"
        result = fractional_sizing(protocol, controls(key))
        assert result["nonoverlapping_positions"] >= 30
        assert result["status"] == "INSUFFICIENT_LOSS_EXPERIENCE"
        assert result["capped_fraction"] is None and result["synthetic"]
        assert result == fractional_sizing(protocol, controls(key))
    finally:
        protocol.conn.close()
        db.c.close()


def test_mixed_native_oos_returns_produce_bounded_repeatable_uncertainty(tmp_path):
    db, protocol, clock, key = prepared(tmp_path, mixed=True)
    try:
        clock["at"] = START + timedelta(days=2)
        protocol.consume(key, db)
        result = fractional_sizing(protocol, controls(key))
        assert result["status"] == "DESCRIPTIVE_ONLY"
        assert Decimal(0) <= Decimal(result["capped_fraction"]) <= Decimal("0.1")
        assert set(result["resampled_fraction_quantiles"]) == {"5", "50", "95"}
        assert result == fractional_sizing(protocol, controls(key))
        assert not result["funded_authority"] and not result["independent_final_evidence"]
    finally:
        protocol.conn.close()
        db.c.close()


def test_recycled_partial_exit_is_not_mistaken_for_a_simple_position_return():
    orders = [{"status": "FILLED", "side": side, "qty": qty, "price": price, "fee": "0", "fee_ccy": "USDT",
               "fill_time": iso(START + timedelta(minutes=i)), "ref": str(i)}
              for i, (side, qty, price) in enumerate((("BUY", "1", "100"), ("SELL", "0.5", "200"),
                                                     ("BUY", "1", "100"), ("SELL", "1.5", "100")))]
    ledger = trade_ledger(orders, "BTC")
    assert not simple_roundtrips(orders, ledger["trades"])


@pytest.mark.parametrize("change", [{"fraction": "0.6"}, {"cap": "0.3"}, {"simulations": True}, {"seed": -1}])
def test_unbounded_policy_is_rejected_before_reading_an_evaluation(tmp_path, change):
    with ResearchProtocol(tmp_path, store="demo") as protocol:
        with pytest.raises(ValueError):
            fractional_sizing(protocol, {**controls("missing"), **change})
