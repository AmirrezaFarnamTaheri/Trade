"""Phase A trial accounting must include one-off exploratory paper runs."""

import json
import sqlite3
from datetime import timedelta

import pytest

from gym.cli import main
from gym.services.trial_ledger import TrialLedger
from tests.support import START, market_db, quote_history


def test_trial_attempts_are_append_only_and_scoped_to_exact_research_question(tmp_path):
    """Attempts are counted by symbol, historical window and hypothesis."""
    end = START + timedelta(minutes=20)
    with TrialLedger(tmp_path) as ledger:
        first = ledger.record(symbol="BTCUSDT", start=START, end=end, hypothesis="alpha",
                              source="paper", config_hash="candidate-1", attempt_id="trial-1")
        duplicate = ledger.record(symbol="BTCUSDT", start=START, end=end, hypothesis="alpha",
                                  source="paper", config_hash="candidate-1", attempt_id="trial-1")
        ledger.record(symbol="BTCUSDT", start=START, end=end, hypothesis="alpha",
                      source="paper", config_hash="candidate-2", attempt_id="trial-2")
        ledger.record(symbol="ETHUSDT", start=START, end=end, hypothesis="alpha",
                      source="paper", config_hash="candidate-1")
        ledger.record(symbol="BTCUSDT", start=START, end=end, hypothesis="different",
                      source="paper", config_hash="candidate-1")
        assert first == duplicate
        assert ledger.count(symbol="BTCUSDT", start=START, end=end, hypothesis="alpha") == 2
        assert ledger.count(symbol="ETHUSDT", start=START, end=end, hypothesis="alpha") == 1
        assert ledger.count(symbol="BTCUSDT", start=START, end=end, hypothesis="different") == 1
        with pytest.raises(ValueError, match="different"):
            ledger.record(symbol="ETHUSDT", start=START, end=end, hypothesis="alpha",
                          source="paper", config_hash="candidate-1", attempt_id="trial-1")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.conn.execute("DELETE FROM trial_attempts WHERE attempt_id='trial-1'")
    with TrialLedger(tmp_path) as reopened:
        assert reopened.count(symbol="BTCUSDT", start=START, end=end, hypothesis="alpha") == 2


def test_five_individual_cli_replays_count_as_five_exploratory_trials(tmp_path, capsys):
    """Single runs across parameter choices must appear in the global question count."""
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, quote_history(n=180))
    db.c.close()
    end = START + timedelta(minutes=20)
    for fast in range(2, 7):
        assert main(["--data", str(tmp_path), "paper", "BTCUSDT", "--from", START.isoformat(),
                     "--to", end.isoformat(), "--res", "1min",
                     "--params", json.dumps({"fast": fast, "slow": 10})]) == 0
        capsys.readouterr()
    with TrialLedger(root) as ledger:
        assert ledger.count(symbol="BTCUSDT", start=START, end=end, hypothesis="ad-hoc") == 5
