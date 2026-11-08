"""Strict opt-in quote coverage never fabricates prices or treats holes as market closures."""
from datetime import timedelta

from gym.domain.model import iso
from gym.services.data_quality_gate import quote_coverage
from gym.services.research_actions import research_action
from gym.services.research_market import screen_markets
from tests.support import START, market_db, quote_history


def _quotes_with_hole(n=180):
    return [q for q in quote_history(n=n)
            if not START + timedelta(minutes=10) <= q.ts_avail < START + timedelta(minutes=20)]


def test_missing_buckets_trigger_insufficient_data_and_report_exact_shares(tmp_path):
    """Ten out of thirty market-open buckets have zero observed receipts."""
    db = market_db(tmp_path, _quotes_with_hole())
    try:
        start, end = START, START + timedelta(minutes=30)
        refused = quote_coverage(db, "BTCUSDT", start, end, "1min", max_bad_share="0.1")
        assert refused["status"] == "INSUFFICIENT_DATA"
        assert refused["counts"]["MISSING"] == 10
        assert refused["eligible_buckets"] == 30
        assert refused["coverage_share"] == "0.6666666666666666666666666667"
        allowed = quote_coverage(db, "BTCUSDT", start, end, "1min", max_bad_share="0.4")
        assert allowed["status"] == "AVAILABLE"
        assert allowed["funded_authority"] is False
    finally:
        db.c.close()


def test_quality_screen_excludes_incomplete_window_without_hiding_evidence(tmp_path):
    db = market_db(tmp_path, _quotes_with_hole())
    request = {"from": iso(START), "to": iso(START + timedelta(minutes=30)),
               "resolution": "1min", "symbols": ["BTCUSDT"],
               "reference": "BTCUSDT", "quote_currency": "USDT",
               "metric": "momentum_percent", "quality_max_bad_share": "0.1"}
    try:
        result = screen_markets(db, request, store="live")
        assert not result["ranked"]
        assert result["excluded"][0]["quality_gate"]["status"] == "INSUFFICIENT_DATA"
    finally:
        db.c.close()


def test_quality_gated_portfolio_abstains_without_creating_saved_run(tmp_path):
    from tests.test_portfolio_workflow import request

    db = market_db(tmp_path, _quotes_with_hole() + quote_history(n=180, sym="ETHUSDT"))
    db.c.close()
    value = {**request(), "quality_max_bad_share": "0.1"}
    report = research_action(tmp_path, "portfolio-replay", value)
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["run_saved"] is False
    assert report["quality_gate"]["BTCUSDT"]["counts"]["MISSING"] == 10
    assert not (tmp_path / "runs" / "portfolios").exists()
