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
