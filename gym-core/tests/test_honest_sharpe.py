"""Hand-worked checks for autocorrelation and minimum-track-record corrections."""

from math import isclose

from gym.domain.performance import (
    _sharpe_block,
    lo_annualized_sharpe,
    minimum_track_record_length,
    probabilistic_sharpe,
)


def test_lo_annualization_matches_weighted_autocorrelation_example():
    """The q=4 variance inflator includes lags 1, 2 and 3 exactly."""
    returns = [0.01, 0.02, 0.01, 0.03, 0.02, 0.02]
    assert round(lo_annualized_sharpe(returns, 4), 4) == 6.2986
    assert lo_annualized_sharpe([0.01] * 6, 4) is None
    enhanced = _sharpe_block(returns, 4, enhanced=True)
    assert round(enhanced["sharpe_annualized_lo"], 4) == 6.2986
    assert enhanced["lo_lags_used"] == 3


def test_psr_and_minimum_track_record_match_analytic_example():
    """Bailey-Lopez de Prado normal-cdf and 95% inverse-cdf cases."""
    sharpe = 2.4354409352352624
    assert round(probabilistic_sharpe(sharpe, 6, 0.0, 3.0), 4) == 0.9969
    assert round(minimum_track_record_length(sharpe, 0.0, 3.0), 4) == 2.8089
    assert minimum_track_record_length(0.0, 0.0, 3.0) is None
    assert isclose(minimum_track_record_length(sharpe, 0, 3, confidence=0.95), 2.808912937490237)


def test_short_track_record_is_explicitly_ineligible():
    """A visually high Sharpe does not imply an adequate sample length."""
    returns = [0.1, 0.11, 0.09]
    output = _sharpe_block(returns, 12, enhanced=True)
    assert output["minimum_track_record"] is not None
    assert output["track_record_status"] in ("SUFFICIENT", "NOT_ENOUGH_DATA")
    if output["minimum_track_record"] > len(returns):
        assert output["track_record_status"] == "NOT_ENOUGH_DATA"
