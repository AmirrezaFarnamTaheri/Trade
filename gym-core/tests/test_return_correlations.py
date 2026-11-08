"""Alignment, missingness and zero variance cannot be replaced with filled price levels."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from gym.services.research_market import return_correlations
from tests.support import START, market_db, quote_history


def request(**changes):
    return {"symbols": ["BTCUSDT", "ETHUSDT"], "quote_currency": "USDT", "from": iso(START),
            "to": iso(START + timedelta(minutes=30)), "resolution": "1min", "min_overlap": 10, **changes}


def test_identical_returns_have_exact_unit_correlation_and_snapshot_identity(tmp_path):
    tops = quote_history(n=180)
    db = market_db(tmp_path, tops + [replace(t, symbol="ETHUSDT") for t in tops])
    try:
        out = return_correlations(db, request(), store="live")
        pair = out["pairs"][1]
        assert pair["left"] == "BTCUSDT" and pair["right"] == "ETHUSDT"
        assert Decimal(pair["correlation"]) == 1 and pair["overlap"] == 29
        assert pair["left_only"] == pair["right_only"] == 0
        assert out["report_id"] == research_action(tmp_path, "return-correlations", request(), store="live")["report_id"]
        assert not out["funded_authority"] and not db.c.in_transaction
    finally:
        db.c.close()


def test_gap_does_not_generate_returns_and_flat_series_is_unavailable(tmp_path):
    tops = quote_history(n=180)
    other = [replace(t, symbol="ETHUSDT", bid=Decimal(100), ask=Decimal(102)) for t in tops
             if not START + timedelta(minutes=10) <= t.ts_avail < START + timedelta(minutes=12)]
    db = market_db(tmp_path, tops + other)
    try:
        out = return_correlations(db, request(), store="live")
        pair = out["pairs"][1]
        assert pair["overlap"] == 26 and pair["left_only"] == 3
        assert pair["correlation"] is None and pair["unavailable_reason"] == "ZERO_VARIANCE"
        assert out["coverage"][1]["discarded_nonadjacent_intervals"] == 1
        out = return_correlations(db, request(min_overlap=29), store="live")
        assert out["pairs"][1]["unavailable_reason"] == "INSUFFICIENT_OVERLAP"
    finally:
        db.c.close()


def test_stale_market_is_visible_but_excluded(tmp_path):
    tops = quote_history(n=180)
    db = market_db(tmp_path, tops + [replace(t, symbol="ETHUSDT") for t in tops[:60]])
    try:
        out = return_correlations(db, request(), store="live")
        assert out["coverage"][1]["excluded_reason"] == "STALE_AT_WINDOW_END"
        assert out["pairs"][1]["overlap"] == 0 and out["pairs"][1]["correlation"] is None
    finally:
        db.c.close()


@pytest.mark.parametrize("change", [{"symbols": ["BTCUSDT"]}, {"symbols": ["BTCUSDT"] * 2},
                                    {"symbols": ["BTCUSDT", "USDTTMN"]}, {"min_overlap": True}, {"min_overlap": 1}])
def test_invalid_universe_or_threshold_is_rejected(tmp_path, change):
    db = market_db(tmp_path, [])
    try:
        with pytest.raises(ValueError):
            return_correlations(db, request(**change), store="live")
    finally:
        db.c.close()
