"""Successive paper windows retain separate selection, warmup and failure states."""
import json
from datetime import timedelta

import pytest

from gym.cli import main
from gym.domain.model import iso
from gym.services import temporal_validation
from tests.support import START, market_db, quote, quote_history

CANDIDATES = [{"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
              {"strategy": "sma-reversion", "params": {"lookback": 3, "entry_bps": 0}}]


@pytest.mark.parametrize("folds", [True, 0, 6, "2", 2.5])
def test_invalid_window_count_is_rejected_before_transaction(tmp_path, folds):
    db = market_db(tmp_path, [])
    try:
        with pytest.raises(ValueError, match="folds"):
            temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(hours=4),
                                         CANDIDATES, folds=folds)
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_windows_share_snapshot_but_not_cash_or_strategy_state(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=1500))
    end = START + timedelta(minutes=240)
    try:
        original = temporal_validation.validate(db, "BTCUSDT", START, end, CANDIDATES,
                                                resolution="1min", folds=3)
        assert original["mode"] == "MULTI_WINDOW_VALIDATION"
        assert original["funded_authority"] is False and original["independent_final_evidence"] is False
        assert len(original["folds"]) == 3
        for first, second in zip(original["folds"], original["folds"][1:]):
            assert first["windows"]["holdout"]["to"] == second["windows"]["selection"]["from"]
        assert original["trial_count"] == len(original["runs"])
        assert all(run["result"]["start_cash"] == "1000" for run in original["runs"])
        assert all(fold["windows"]["purge_seconds"] == 60 for fold in original["folds"])
        compare = temporal_validation._compare_in_snapshot
        calls = []

        def mutate_between_windows(*args, **kwargs):
            result = compare(*args, **kwargs)
            if not calls:
                from gym.adapters.store import MarketDB
                writer = MarketDB(tmp_path / "market.db")
                try:
                    writer.c.execute("update book_top set bid='50000',ask='50001' where ts_avail>=?",
                                     (original["folds"][-1]["windows"]["holdout"]["from"],))
                finally:
                    writer.c.close()
            calls.append(1)
            return result

        monkeypatch.setattr(temporal_validation, "_compare_in_snapshot", mutate_between_windows)
        pinned = temporal_validation.validate(db, "BTCUSDT", START, end, CANDIDATES, resolution="1min", folds=3)
        assert len(calls) == 3 and pinned == original
        monkeypatch.setattr(temporal_validation, "_compare_in_snapshot", compare)
        changed = temporal_validation.validate(db, "BTCUSDT", START, end, CANDIDATES, resolution="1min", folds=3)
        assert changed["validation_id"] != original["validation_id"]
        assert changed["folds"][:-1] == original["folds"][:-1]
        assert changed["folds"][-1]["selection"] == original["folds"][-1]["selection"]
        assert changed["folds"][-1]["selected"] == original["folds"][-1]["selected"]
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_inactive_windows_remain_incomplete_without_fabricated_returns(tmp_path):
    db = market_db(tmp_path, quote_history(n=80))
    try:
        for minutes in (80, 160):
            db.add_book_top(quote(START + timedelta(minutes=minutes), "70000", "70010"), None)
        report = temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(hours=4),
                                              CANDIDATES, resolution="1min", folds=3)
        assert report["status"] == "INCOMPLETE" and report["evaluated_windows"] == 0
        assert all(fold["status"] == "ABSTAIN" and fold["holdout_run_id"] is None for fold in report["folds"])
        assert report["trial_count"] == 6
        assert "aggregate_return" not in report
    finally:
        db.c.close()


def test_missing_selection_data_rejects_the_request_without_zero_substitution(tmp_path):
    db = market_db(tmp_path, quote_history(n=80))
    try:
        with pytest.raises(ValueError, match="no qualified"):
            temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(hours=4),
                                         CANDIDATES, resolution="1min", folds=3)
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_short_windows_rollback_and_single_window_identity_is_unchanged(tmp_path):
    db = market_db(tmp_path, quote_history(n=240))
    try:
        with pytest.raises(ValueError, match="three decision periods"):
            temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(minutes=10),
                                         CANDIDATES, resolution="1min", folds=3)
        assert not db.c.in_transaction
        options = {"resolution": "1min"}
        assert temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(minutes=35), CANDIDATES, **options) == (
            temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(minutes=35), CANDIDATES, folds=1, **options))
    finally:
        db.c.close()


def test_cli_publishes_every_window_reference(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, quote_history(n=240)).c.close()
    args = ["--data", str(tmp_path), "validate", "BTCUSDT", "--res", "1min", "--folds", "2",
            "--from", iso(START), "--to", iso(START + timedelta(minutes=35)),
            *[item for candidate in CANDIDATES for item in ("--candidate", json.dumps(candidate))]]
    assert main(args) == 0
    manifests = list((root / "runs" / "validations").glob("*.json"))
    assert len(manifests) == 1
    report = json.loads(manifests[0].read_text("utf-8"))
    assert len(report["folds"]) == 2
    ids = [run_id for fold in report["folds"] for run_id in
           [*fold["selection"]["run_ids"], *([fold["holdout_run_id"]] if fold["holdout_run_id"] else [])]]
    assert len(ids) == report["trial_count"]
    assert all((root / "runs" / (run_id + ".json")).is_file() for run_id in ids)
    assert "validation record:" in capsys.readouterr().out


def test_unexpected_holdout_errors_are_not_masked_as_missing_data(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=240))
    try:
        def invalid_holdout(*args, **kwargs):
            raise ValueError("invalid recorded equity path")

        monkeypatch.setattr(temporal_validation, "paper", invalid_holdout)
        with pytest.raises(ValueError, match="invalid recorded equity"):
            temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(minutes=35),
                                         CANDIDATES, resolution="1min")
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_missing_holdout_remains_unavailable(tmp_path):
    db = market_db(tmp_path, quote_history(n=128))
    try:
        report = temporal_validation.validate(db, "BTCUSDT", START, START + timedelta(minutes=31),
                                              CANDIDATES, resolution="1min")
        assert report["selected"] is not None
        assert report["status"] == "UNAVAILABLE" and report["holdout_run_id"] is None
    finally:
        db.c.close()
