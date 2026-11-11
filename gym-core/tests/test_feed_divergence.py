"""Feed disagreement must block new paper entries."""
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
    earlier = START + timedelta(minutes=20, seconds=30)  # quote at minute 21 is still in the future
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


def test_manual_reference_disagreement_can_persist_paper_entry_lock(tmp_path, monkeypatch):
    """A matched divergence writes BLOCK_ENTRY to the existing local rule ledger."""
    from gym.adapters.store import MarketDB
    from gym.services import research_actions
    from gym.services.rules import RuleService
    from tests.support import market_db, quote

    now = START + timedelta(minutes=22)
    db = market_db(tmp_path, [quote(START, "99", "101")])
    db.c.close()
    monkeypatch.setattr(research_actions, "now_utc", lambda: now)
    local, external = samples(divergent=True)
    report = research_actions.research_action(tmp_path, "feed-divergence-lock", {
        "symbol": "BTCUSDT", "wallex": local, "reference": external,
        "as_of": iso(now), "training_samples": 20, "alert_sigma": 3,
        "duration_seconds": 600}, store="demo")
    assert report["status"] == "PAPER_ENTRY_LOCK_RECORDED"
    assert report["funded_authority"] is False
    db = MarketDB(tmp_path / "market.db", readonly=True)
    try:
        rules = RuleService(db).listing(now, [])["rules"]
        assert any(row["body"]["params"].get("entry_lock")
                   and row["body"]["scope"]["symbols"] == ["BTCUSDT"]
                   for row in rules)
    finally:
        db.c.close()
