"""Read-only run reports disclose bar-coverage estimates without changing run artifacts."""
from datetime import timedelta

from gym.services.data_quality_gate import recorded_bar_coverage
from gym.services.paper import paper
from gym.services.reports import economic_report, text_report
from tests.support import START, market_db, quote_history


def test_paper_report_discloses_closed_bar_coverage_as_estimate(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30),
                    resolution="1min", fast=2, slow=3)
        coverage = recorded_bar_coverage(out)
        assert coverage["status"] == "DESCRIPTIVE"
        assert 0 <= float(coverage["coverage_share"]) <= 1
        assert economic_report(out)["observed_bar_coverage"] == coverage
        assert "Observed closed-bar coverage" in text_report(out)
        assert out["inputs"].get("quality_gate") is None
    finally:
        db.c.close()


def test_portfolio_report_does_not_mislabel_receipt_share_as_bar_coverage(tmp_path):
    from gym.services.portfolio import portfolio

    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30),
                        resolution="1min")
        coverage = recorded_bar_coverage(out)
        assert coverage["status"] == "RECEIPT_SHARE_ONLY"
        assert set(coverage["per_market_qualified_receipt_share"]) == {"BTCUSDT", "ETHUSDT"}
    finally:
        db.c.close()
