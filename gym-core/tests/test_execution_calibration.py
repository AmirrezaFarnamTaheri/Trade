"""Calibration reports from observed feed timing and saved paper fills."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.domain.model import TradeTick
from gym.services.execution_calibration import (
    calibration_report,
    feed_latency,
    fill_quality,
)
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


def test_feed_latency_percentiles_and_clock_disagreement(tmp_path):
    db = market_db(tmp_path, [])
    for i in range(100):
        event = START + timedelta(seconds=i)
        db.add_trade(TradeTick("BTCUSDT", event, event + timedelta(milliseconds=100 + i), Decimal(1), Decimal(1), "BUY"), "x")
    db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=2), START, Decimal(1), Decimal(1), "BUY"), "x")  # receipt before venue time
    report = feed_latency(db, START - timedelta(hours=1))
    assert report["trades"] == 101 and report["negative_share"] == round(1 / 101, 4)
    assert report["ms"]["p50"] == 149.5 and 185 < report["ms"]["p90"] < 192 and report["suggested_latency_ms"] == int(report["ms"]["p90"])
    assert "BTCUSDT" in report["by_symbol"]
    assert feed_latency(db, START + timedelta(days=1))["ms"] is None


def test_fill_quality_reads_saved_runs(tmp_path):
    db = market_db(tmp_path, quote_history(n=500))
    save_run(paper(db, "BTCUSDT", START, START + timedelta(hours=1), resolution="1min", fast=2, slow=3), tmp_path / "runs")
    report = fill_quality(tmp_path / "runs")
    assert report["fills"] > 0 and "NO_QUALIFIED_QUOTE" not in report["nonfills"]


@pytest.mark.parametrize("samples", [30, 25000])
def test_calibration_is_bounded_dated_and_never_a_trusted_execution_default(tmp_path, samples):
    from gym.domain.model import iso

    db = market_db(tmp_path, [])
    try:
        for i in range(samples):
            event = START + timedelta(milliseconds=i)
            db.add_trade(TradeTick("BTCUSDT", event, event + timedelta(milliseconds=200), Decimal(1), Decimal(1), "BUY"), "x")
        value = {"symbol": "BTCUSDT", "from": iso(START), "to": iso(START + timedelta(minutes=1)), "max_age_seconds": 120}
        fresh = calibration_report(db, value, store="live", at=START + timedelta(minutes=1))
        assert fresh["status"] == "PUBLIC_FEED_ONLY" and fresh["observations"]["ms"]["n"] == samples
        assert fresh["candidate_latency_ms"] is not None
        assert not fresh["automatic_application"] and not fresh["execution_costs_verified"]
        assert fresh["fee_rate"] is None and fresh["slippage_bps"] is None
        stale = calibration_report(db, value, store="live", at=START + timedelta(hours=1))
        assert stale["status"] == "STALE" and stale["candidate_latency_ms"] is None
        empty = calibration_report(db, {**value, "symbol": "ETHUSDT"}, store="live", at=START + timedelta(minutes=1))
        assert empty["status"] == "INSUFFICIENT_DATA" and empty["candidate_latency_ms"] is None
        db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=5), START, Decimal(1), Decimal(1), "BUY"), "x")
        invalid_clock = calibration_report(db, value, store="live", at=START + timedelta(minutes=1))
        assert invalid_clock["status"] == "CLOCK_DISAGREEMENT" and invalid_clock["candidate_latency_ms"] is None
    finally:
        db.c.close()


def test_calibration_excludes_later_receipts_and_does_not_create_a_model_from_demo(tmp_path):
    from gym.domain.model import iso

    db = market_db(tmp_path, [])
    try:
        for i in range(30):
            event = START + timedelta(seconds=i)
            db.add_trade(TradeTick("BTCUSDT", event, event + timedelta(milliseconds=200), Decimal(1), Decimal(1), "BUY"), "x")
        value = {"symbol": None, "from": iso(START), "to": iso(START + timedelta(seconds=10)), "max_age_seconds": 120}
        report = calibration_report(db, value, store="demo", at=START + timedelta(minutes=1))
        assert report["observations"]["trades"] == 10
        assert report["candidate_latency_ms"] is None and report["synthetic"] is True
    finally:
        db.c.close()
