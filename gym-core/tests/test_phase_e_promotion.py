"""Phase E items 40–41: causal shadow drift and bounded paper promotion screens."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.services.promotion_gates import promotion_screen
from gym.services.shadow_drift import shadow_drift
from tests.support import START


def source(days, daily_returns, *, prospective=False):
    """Generate disjoint native-like signed paper equity curves over closed UTC days."""
    start = START + timedelta(days=days)
    equity, curve = Decimal(1000), [(iso(start), "1000")]
    for i, change in enumerate(daily_returns, 1):
        equity *= 1 + Decimal(change)
        curve.append((iso(start + timedelta(days=i)), str(equity)))
    end = start + timedelta(days=len(daily_returns))
    inputs = {"symbol": "BTCUSDT", "strategy": "ema-trend", "config_hash": "sha",
              "resolution": "1day", "cash": "1000", "cost": {"fee_rate": "0.001"},
              "rules_mode": "point-in-time", "store": "demo",
              "from": iso(start), "to": iso(end)}
    if prospective:
        inputs["kind"] = "live-session"
    return {"run_id": "x" * 16, "outputs_digest": "y" * 16,
            "inputs": inputs, "result": {"curve": curve}}


def test_shadow_breach_below_two_sigma_blocks_research_promotion():
    """Prior 20-day sample is fixed; later adverse day triggers paper demotion evidence."""
    historical = source(0, ["0.01", "-0.01"] * 12)
    observed = source(25, ["-0.08", "0.01", "0.00"], prospective=True)
    report = shadow_drift(historical, observed, observed_at=START + timedelta(days=30))
    assert report["schema"] == "paper-shadow-drift/1"
    assert report["status"] == "PAPER_ONLY_DEMOTION"
    assert report["promotion_blocked"] is True
    assert report["alerts"][0]["z_score"] is not None
    assert Decimal(report["alerts"][0]["z_score"]) < Decimal(-2)
    assert report["funded_authority"] is False


def test_shadow_gap_and_insufficient_training_never_manufacture_confidence():
    """Training stdev and forward complete-day coverage must be identifiable."""
    historical = source(0, ["0.01"] * 20)
    observed = source(25, ["-0.1"], prospective=True)
    assert shadow_drift(historical, observed, observed_at=START + timedelta(days=30))["status"] == "UNIDENTIFIABLE_BASELINE"
    short = source(0, ["0.01", "-0.01"] * 4)
    assert shadow_drift(short, observed, observed_at=START + timedelta(days=30))["status"] == "INSUFFICIENT_HISTORY"
    observed["inputs"]["config_hash"] = "changed"
    with pytest.raises(ValueError, match="matching"):
        shadow_drift(historical, observed, observed_at=START + timedelta(days=30))


def test_shadow_does_not_consume_later_as_of_prices():
    historical = source(0, ["0.01", "-0.01"] * 12)
    observed = source(25, ["-0.08", "0.02"], prospective=True)
    report = shadow_drift(historical, observed, observed_at=START + timedelta(days=26))
    assert report["status"] == "NO_COMPLETE_SHADOW_DAYS"
    assert report["alerts"] == []


def gates(**changes):
    """All evidence values here are local claims; none is independent approval."""
    row = {"deflated_sharpe_probability": "0.97", "closed_trades": 310,
           "track_record_days": 92, "spa_p_value": "0.02",
           "prospective_status": "PASS", "shadow_status": "WITHIN_BAND",
           "shadow_days": 22}
    return promotion_screen({**row, **changes})


def test_fixed_promotion_gates_never_grant_funded_or_operator_authority():
    report = gates()
    assert report["schema"] == "paper-promotion-gates/1"
    assert report["local_criteria_pass"] is True
    assert report["status"] == "INDEPENDENT_EVIDENCE_REQUIRED"
    assert report["funded_authority"] is False
    assert report["operator_approval"] is False
    assert report["missing_external_gates"]
    assert gates(shadow_status="PAPER_ONLY_DEMOTION")["local_criteria_pass"] is False
    assert gates(spa_p_value="0.08")["local_criteria_pass"] is False
    assert gates(deflated_sharpe_probability="0.92")["local_criteria_pass"] is False
    assert gates(closed_trades=299)["local_criteria_pass"] is False


@pytest.mark.parametrize("value", ["NaN", "1.2", -1, True])
def test_promotional_probability_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        gates(deflated_sharpe_probability=value)
