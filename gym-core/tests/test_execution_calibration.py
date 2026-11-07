"""Calibration reports from observed feed timing and saved paper fills."""
from datetime import timedelta
from decimal import Decimal

from gym.adapters.run_store import save_run
from gym.domain.model import TradeTick
from gym.services.execution_calibration import feed_latency, fill_quality
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
