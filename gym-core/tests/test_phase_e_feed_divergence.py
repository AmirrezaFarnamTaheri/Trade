"""Phase E item 42: feed disagreement must block new paper entries."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.services.feed_divergence import evaluate_divergence
from tests.support import START


def row(i, midpoint):
    """A qualified source midpoint with identical availability on both streams."""
    at = START + timedelta(seconds=60 * i)
    middle = Decimal(midpoint)
    return {"at": iso(at), "mid": str(middle), "qualified": True}


def samples(*, divergent=False):
    """Twenty historical pair differences train the baseline; the last is holdout."""
    wallex = [row(i, "100") for i in range(22)]
    other = [row(i, "100.01" if i % 2 else "99.99") for i in range(22)]
    if divergent:
        other[-1]["mid"] = "110"
    return wallex, other


def test_reference_divergence_trips_paper_entry_block():
    local, external = samples(divergent=True)
    report = evaluate_divergence(local, external, symbol="BTCUSDT",
                                 as_of=START + timedelta(minutes=22),
                                 training_samples=20, alert_sigma=3)
    assert report["schema"] == "paper-feed-divergence/1"
    assert report["status"] == "DIVERGENT"
    assert report["block_entry"] is True
    assert Decimal(report["deviation_bps"]) > Decimal(report["threshold_bps"])
    assert report["funded_authority"] is False


def test_future_reference_quote_does_not_change_earlier_alarm():
    wallex, external = samples()
    earlier = START + timedelta(minutes=21, seconds=30)
    before = evaluate_divergence(wallex, external, symbol="BTCUSDT", as_of=earlier,
                                 training_samples=20, alert_sigma=3)
    external[-1]["mid"] = "999999"
    after = evaluate_divergence(wallex, external, symbol="BTCUSDT", as_of=earlier,
                                training_samples=20, alert_sigma=3)
    assert before == after
    assert before["status"] == "ALIGNED"


def test_stale_reference_fails_closed_without_interpolation():
    wallex, external = samples()
    external = external[:-4]
    report = evaluate_divergence(wallex, external, symbol="BTCUSDT",
                                 as_of=START + timedelta(minutes=22),
                                 training_samples=16, alert_sigma=3)
    assert report["status"] == "STALE_OR_UNAVAILABLE"
    assert report["block_entry"] is True


@pytest.mark.parametrize("sigma", [0, 1, 101, True])
def test_feed_threshold_rejects_invalid_sigmas(sigma):
    wallex, other = samples()
    with pytest.raises(ValueError):
        evaluate_divergence(wallex, other, symbol="BTCUSDT",
                            as_of=START + timedelta(minutes=22),
                            training_samples=20, alert_sigma=sigma)
