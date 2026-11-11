"""Item 35: a verified prior fraction actually changes a saved portfolio replay."""
from datetime import timedelta

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import MarketDB
from gym.domain.model import iso
from gym.domain.sim import CostModel
from gym.services.portfolio_research import portfolio_action
from tests.support import START, quote_history
from tests.test_fractional_sizing_reference import _report, _source


def test_prior_fraction_is_consumed_by_portfolio_action_and_saved_with_provenance(tmp_path):
    """No silent default fraction: the exact source and cap survive into inputs."""
    source = _source(tmp_path)
    reference = _report(tmp_path, source)
    db = MarketDB(tmp_path / "market.db")
    try:
        for book in (*quote_history(n=900)[320:], *quote_history(n=900, sym="ETHUSDT")):
            db.add_book_top(book, None)
    finally:
        db.c.close()

    cost = CostModel().describe()
    cost["fractional_sizing_report_id"] = reference
    request = {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "from": iso(START + timedelta(minutes=60)),
        "to": iso(START + timedelta(minutes=95)),
        "resolution": "1min",
        "cash": "1000", "strategy": "ema-trend",
        "params": {"fast": 2, "slow": 3},
        "rules_mode": "point-in-time", "cost": cost,
    }
    receipt = portfolio_action(tmp_path, "portfolio-replay", request, store="demo")
    saved = load_verified_run(tmp_path / "runs" / "portfolios", receipt["run_id"], store="demo")
    applied = saved["inputs"]["cost"]
    assert saved["inputs"]["portfolio_version"] == 12
    assert applied["max_fraction"] == "0.12"
    assert applied["calibration"]["fractional_sizing_report_id"] == reference
    assert applied["calibration"]["source_run_id"] == source["run_id"]
    assert saved["inputs"]["store"] == "demo"
