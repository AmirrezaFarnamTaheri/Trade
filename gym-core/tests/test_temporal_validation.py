"""Later outcomes cannot choose the strategy evaluated on those outcomes."""
from datetime import timedelta
import json

import pytest

from gym.domain.model import iso
from gym.services.temporal_validation import validate
from tests.support import START, market_db, quote_history

CANDIDATES = [{"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
              {"strategy": "sma-reversion", "params": {"lookback": 3, "entry_bps": 0}}]


def test_cli_publishes_a_real_validation_artifact(tmp_path, capsys):
    from gym.cli import main
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, quote_history(n=240))
    db.c.close()
    assert main(["--data", str(tmp_path), "validate", "BTCUSDT", "--res", "1min",
                 "--from", iso(START), "--to", iso(START + timedelta(minutes=35)),
                 *[argument for candidate in CANDIDATES for argument in ("--candidate", json.dumps(candidate))]]) == 0
    manifests = list((root / "runs" / "validations").glob("*.json"))
    assert len(manifests) == 1
    report = json.loads(manifests[0].read_text("utf-8"))
    for run_id in report["selection"]["run_ids"]:
        assert (root / "runs" / (run_id + ".json")).is_file()
    assert report["independent_final_evidence"] is False and report["order_submitted"] is False
    assert "validation record:" in capsys.readouterr().out


def test_holdout_changes_cannot_change_selection_or_its_evidence(tmp_path):
    db = market_db(tmp_path, quote_history(n=1500))
    end = START + timedelta(minutes=240)
    try:
        first = validate(db, "BTCUSDT", START, end, CANDIDATES, resolution="1min")
        assert first["authority"] == "PAPER_ONLY" and first["funded_authority"] is False
        assert first["independent_final_evidence"] is False
        assert first["selected"] is not None
        cutoff = first["windows"]["holdout"]["from"]
        db.c.execute("UPDATE book_top SET bid='50000',ask='50001' WHERE ts_avail>=?", (cutoff,))
        db.c.commit()
        changed = validate(db, "BTCUSDT", START, end, CANDIDATES, resolution="1min")
        assert first["selection"] == changed["selection"]
        assert first["selected"] == changed["selected"]
        assert first["holdout_run_id"] != changed["holdout_run_id"]
        assert first["validation_id"] != changed["validation_id"]
        selection_end = first["windows"]["selection"]["to"]
        assert selection_end < cutoff < iso(end)
        assert first["windows"]["purge_seconds"] == 60
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_stale_selection_abstains_without_inspecting_holdout(tmp_path):
    db = market_db(tmp_path, quote_history(n=80))
    try:
        report = validate(db, "BTCUSDT", START, START + timedelta(hours=4), CANDIDATES, resolution="1min")
        assert report["status"] == "ABSTAIN"
        assert report["selected"] is None and report["holdout_run_id"] is None
        assert len(report["runs"]) == 2
        assert report["reason"] == "NO_CURRENT_ACTIVE_SELECTION_RESULT"
    finally:
        db.c.close()


@pytest.mark.parametrize("resolution", ["session", "bogus"])
def test_variable_or_invalid_periods_are_not_given_a_fake_purge(tmp_path, resolution):
    db = market_db(tmp_path, quote_history(n=30))
    try:
        with pytest.raises(ValueError):
            validate(db, "BTCUSDT", START, START + timedelta(hours=1), CANDIDATES, resolution=resolution)
        assert not db.c.in_transaction
    finally:
        db.c.close()
