"""Recorded trading closures must not count as open trading return periods."""
from datetime import timedelta

from gym.domain.model import iso
from gym.domain.performance import YEAR_SECONDS, _sharpe_block, market_open_annualization
from tests.support import START


def test_scheduled_twelve_hour_closure_halves_eligible_annual_slots():
    """The same return sequence has identical open-time volatility without gap-padding."""
    start, end = START, START + timedelta(days=1)
    closure = [{"from": iso(start + timedelta(hours=8)),
                "to": iso(start + timedelta(hours=20)), "reason": "VENUE_CLOSED"}]
    actual = market_open_annualization(start, end, 60, closure)
    assert actual["status"] == "AVAILABLE"
    assert actual["closed_seconds"] == 43200
    assert actual["periods_per_year"] == YEAR_SECONDS / 120
    observed_returns = [0.01, -0.01, 0.012, -0.011, 0.008]
    annual = _sharpe_block(observed_returns, actual["periods_per_year"], enhanced=True)
    compressed = _sharpe_block(observed_returns, YEAR_SECONDS / 120, enhanced=True)
    assert annual["volatility_annualized"] == compressed["volatility_annualized"]
    assert annual["sharpe_annualized_lo"] == compressed["sharpe_annualized_lo"]


def test_missing_quotes_are_not_treated_as_scheduled_market_closure():
    """No receipt is not proof that the venue was closed."""
    start, end = START, START + timedelta(days=1)
    skipped = [{"from": iso(start + timedelta(hours=8)),
                "to": iso(start + timedelta(hours=20)), "reason": "NO_OBSERVATIONS"}]
    assert market_open_annualization(start, end, 60, skipped)["periods_per_year"] == YEAR_SECONDS / 60


def test_duplicate_closure_intervals_are_union_not_double_counted():
    start, end = START, START + timedelta(days=1)
    closure = [
        {"from": iso(start + timedelta(hours=2)), "to": iso(start + timedelta(hours=6)), "reason": "VENUE_CLOSED"},
        {"from": iso(start + timedelta(hours=5)), "to": iso(start + timedelta(hours=8)), "reason": "VENUE_CLOSED"},
    ]
    out = market_open_annualization(start, end, 60, closure)
    assert out["closed_seconds"] == 6 * 3600
    assert out["observed_closure_intervals"] == 1
