"""Coverage gaps and ranking exclusions use real native quote bars in temporary stores."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import TradeTick, iso
from gym.services.research_market import coverage_timeline, screen_markets
from tests.support import START, market_db, quote_history


def window(**changes):
    return {"from": iso(START), "to": iso(START + timedelta(minutes=30)), "resolution": "1min", **changes}


def test_coverage_exposes_missing_buckets_and_resets_warmup(tmp_path):
    tops = quote_history(n=180)
    tops = [q for q in tops if not START + timedelta(minutes=10) <= q.ts_avail < START + timedelta(minutes=12)]
    db = market_db(tmp_path, tops)
    try:
        result = coverage_timeline(db, {"symbol": "BTCUSDT", **window()}, store="live")
        assert len(result["buckets"]) == 30 and result["counts"]["MISSING"] == 2
        assert result["buckets"][10]["indicator_readiness"] is None
        assert result["buckets"][-1]["indicator_readiness"]["sma_20"] == "WARMUP"
        assert result["funded_authority"] is False and not db.c.in_transaction
    finally:
        db.c.close()


def test_screen_retains_missing_markets_and_requires_comparable_currency(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    request = {**window(), "symbols": ["BTCUSDT", "ETHUSDT"], "reference": "BTCUSDT", "quote_currency": "USDT", "metric": "momentum_percent"}
    try:
        result = screen_markets(db, request, store="live")
        assert [r["symbol"] for r in result["ranked"]] == ["BTCUSDT"]
        assert Decimal(result["ranked"][0]["relative_momentum_percent"]) == 0
        assert result["excluded"][0]["symbol"] == "ETHUSDT"
        for change in ({"symbols": ["BTCUSDT", "USDTTMN"]}, {"metric": "confidence"}, {"symbols": ["BTCUSDT"] * 2}):
            with pytest.raises(ValueError):
                screen_markets(db, {**request, **change}, store="live")
    finally:
        db.c.close()


def test_coverage_uses_receipt_cutoff_and_exposes_age_of_a_quote_across_missing_buckets(tmp_path):
    db = market_db(tmp_path, quote_history(n=6))
    try:
        for delay, receipt in ((180, START + timedelta(minutes=4)), (180, START + timedelta(minutes=5))):
            db.add_trade(TradeTick("BTCUSDT", receipt - timedelta(seconds=delay), receipt, Decimal(100), Decimal(1), "BUY"), "fixture")
        db.c.commit()
        result = coverage_timeline(db, {"symbol": "BTCUSDT", **window(to=iso(START + timedelta(minutes=5)))}, store="live")
        assert result["trade_receipts"] == 1  # Receipt exactly at the exclusive end is future knowledge.
        assert result["buckets"][-1]["late_trade_receipts"] == 1
        assert result["buckets"][-1]["status"] == "MISSING" and result["buckets"][-1]["quote_stale"]
        assert result["buckets"][-1]["last_known_qualified_quote_age_seconds"] > 120
    finally:
        db.c.close()
