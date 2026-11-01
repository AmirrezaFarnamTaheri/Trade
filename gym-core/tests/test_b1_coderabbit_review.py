"""Regression contracts for six concrete PR #10 review findings.

OS/CI source guards supplement, but never replace, hosted Windows execution.
"""
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest
import gym.services.external_journal as journal_mod
from gym.services.external_journal import ExternalJournal
from gym.domain.account_observations import project_account
from gym.adapters.wallex_account_read import WallexAccountReader

ROOT = Path(__file__).resolve().parents[2]


def test_tiny_crypto_decimals_are_plain_and_lossless():
    account = project_account("main", "2026-10-31T15:00:00Z",
        balances={"BTC": {"value": "1.2E-7", "locked": "0.00000000"}},
        orders=[{"client_id": "manual1", "status": "open", "filled": "1.2E-7"}])
    assert account["balances"][0]["venue_value"] == "0.00000012"
    assert account["orders"][0]["filled_observed"] == "0.00000012"


def test_invalid_obligation_asset_is_rejected_even_when_obligation_missing():
    for asset in (123, ["USDT"], "usdt!", " "):
        with pytest.raises(ValueError):
            project_account("main", "2026-10-31T15:00:00Z",
                exposure=[{"account_id": "subaccount:1", "product": "MARGIN",
                           "obligation_asset": asset}])
    result = project_account("main", "2026-10-31T15:00:00Z",
        exposure=[{"account_id": "subaccount:1", "product": "MARGIN",
                   "obligation_asset": "usdt"}])
    assert result["exposure"][0]["obligation_asset"] == "USDT"


def test_journal_deduplicates_equal_numbers_with_different_scales(tmp_path):
    def snapshot(filled):
        return project_account("main", "2026-10-31T15:00:00Z",
            orders=[{"client_id": "m1", "status": "partial", "filled": filled}])
    with ExternalJournal(tmp_path / "journal.db") as journal:
        assert journal.record(snapshot("0.250")) == 1
        assert journal.record(snapshot("0.25")) == 0
        assert len(journal.events()) == 1


def test_journal_stores_tiny_quantities_as_plain_decimals(tmp_path):
    snap = project_account("main", "2026-10-31T15:00:00Z",
        orders=[{"client_id": "m1", "status": "partial", "filled": "1.2E-7"}])
    with ExternalJournal(tmp_path / "journal.db") as journal:
        journal.record(snap)
        assert journal.events()[0]["filled_observed"] == "0.00000012"


def test_failed_schema_creation_leaves_no_partial_table(tmp_path, monkeypatch):
    broken = journal_mod.SCHEMA.replace(
        "CREATE INDEX external_order_lookup",
        "THIS IS INVALID SQLITE; CREATE INDEX external_order_lookup",
    )
    monkeypatch.setattr(journal_mod, "SCHEMA", broken)
    path = tmp_path / "journal.db"
    with pytest.raises(sqlite3.DatabaseError):
        ExternalJournal(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='external_order_events'"
        ).fetchone()[0] == 0


def test_ci_checkout_tokens_are_nonpersistent_and_read_only():
    ci = (ROOT / ".github/workflows/validate.yml").read_text("utf-8")
    assert "permissions:\n  contents: read" in ci
    # CI may add safe no-secret runner jobs. Every checkout must opt out
    # of persisting credentials; do not hardcode the number of jobs.
    assert ci.count("actions/checkout@v4") >= 3
    assert ci.count("actions/checkout@v4") == ci.count("persist-credentials: false")


def test_windows_negative_probe_rejects_uac_filtered_admin_tokens():
    code = (ROOT / "scripts/windows/Test-UnprivilegedExecutorAccess.ps1").read_text("utf-8")
    assert "S-1-5-32-544" in code
    assert "$identity.Groups" in code
    assert "IsInRole" in code


def test_stop_listener_recovers_from_client_abort_and_pipe_recreate_errors():
    code = (ROOT / "executor/exec-svc/src/windows_pipe.rs").read_text("utf-8")
    assert "let connect_result = listening.connect().await" in code
    assert "if connect_result.is_err()" in code
    assert "tokio::time::sleep(Duration::from_millis(50)).await" in code
    assert "create_pipe(service_sid, logon_sid, false)" in code
