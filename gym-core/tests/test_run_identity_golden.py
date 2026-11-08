"""Run IDs and output digests are stable across releases; a change here invalidates every saved comparison."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.sim import CostModel
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


def test_paper_run_identity_is_frozen(tmp_path):
    db = market_db(tmp_path, quote_history(n=500))
    window = {"resolution": "1min", "fast": 2, "slow": 3}
    plain = paper(db, "BTCUSDT", START, START + timedelta(hours=1), **window)
    # Pinned from the release before the participation cap existed: default runs must keep their identity.
    assert (plain["run_id"], plain["outputs_digest"]) == ("4a2e0fb22a1f52eb", "85bc4a119e7a2a9d")
    capped = paper(db, "BTCUSDT", START, START + timedelta(hours=1), cost=CostModel(max_participation=Decimal("0.5")), **window)
    assert capped["run_id"] == "136d3ca115f1cf8c"

def test_price_band_display_does_not_mutate_existing_market_run_artifact(tmp_path):
    """A display-only safety notice must not corrupt a frozen saved run ID."""
    from copy import deepcopy

    from gym.adapters.run_store import save_run
    from gym.services.reports import text_report

    db = market_db(tmp_path, quote_history(n=180))
    try:
        args = ("BTCUSDT", START, START + timedelta(minutes=30))
        previous = paper(db, *args, resolution="1min", fast=2, slow=3)
        old_record = deepcopy(previous)
        old_record["warnings"] = [w for w in old_record["warnings"] if not w.startswith("Price-band reference ESTIMATED")]
        saved_path = save_run(old_record, tmp_path / "runs")
        repeat = paper(db, *args, resolution="1min", fast=2, slow=3)
        assert save_run(repeat, tmp_path / "runs") == saved_path
        assert repeat == old_record
        assert "Price-band reference ESTIMATED" in text_report(repeat)
    finally:
        db.c.close()
