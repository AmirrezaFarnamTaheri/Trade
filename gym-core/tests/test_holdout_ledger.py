from contextlib import closing

import pytest

from gym.services.holdout_ledger import HoldoutLedger, HoldoutRefused


def test_holdout_checks_market_and_time_and_counts_legacy_evidence(tmp_path):
    with closing(HoldoutLedger(tmp_path / "holdout.sqlite3")) as ledger:
        first = {"coverage": {"BTC": ["2024-01-01", "2024-02-01"]}}
        later = {"coverage": {"BTC": ["2024-02-02", "2024-03-01"]}}
        other = {"coverage": {"ETH": ["2024-01-01", "2024-02-01"]}}
        assert ledger.look("first", first, 2, rescore=False)["look"] == 1
        assert ledger.look("later", later, 3, rescore=False)["look"] == 1
        assert ledger.look("other", other, 5, rescore=False)["look"] == 1
        overlap = {"coverage": {"BTC": ["2024-02-01", "2024-02-02"]}}
        with pytest.raises(HoldoutRefused, match="already scored 2"):
            ledger.look("overlap", overlap, 7, rescore=False)
        assert ledger.look("overlap", overlap, 7, rescore=True)["configurations_all_looks"] == 12

    with closing(HoldoutLedger(tmp_path / "legacy.sqlite3")) as ledger:
        ledger.look("legacy", {}, 6, rescore=False)
        with pytest.raises(HoldoutRefused, match="unscoped"):
            ledger.look("first", first, 2, rescore=False)
        assert ledger.look("first", first, 2, rescore=True)["configurations_all_looks"] == 8
