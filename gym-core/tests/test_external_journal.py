"""B1 external Journal: durable, monotone, never authoritative money fills."""
import sqlite3
import pytest

from gym.domain.account_observations import project_account
from gym.services.external_journal import ExternalJournal


def observation(at, status="open", filled="0"):
    orders = [] if status is None else [{"client_id": "manual-1", "symbol": "BTCUSDT",
                                         "status": status, "filled": filled}]
    return project_account("main", at, orders=orders)


def test_manual_observation_is_append_only_and_survives_restart(tmp_path):
    path = tmp_path / "external_journal.db"
    first = observation("2026-10-31T15:00:00Z")
    with ExternalJournal(path) as j:
        assert j.record(first) == 1
        assert j.record(first) == 0
        assert len(j.events()) == 1
    with ExternalJournal(path) as j:
        assert len(j.events()) == 1
        assert j.record(observation("2026-10-31T15:01:00Z", "canceled", "0.25")) == 1
        rows = j.events()
        assert rows[-1]["raw_status"] == "canceled"
        assert rows[-1]["filled_observed"] == "0.25"
        assert rows[-1]["settlement"] == "UNKNOWN"
        assert rows[-1]["economic_effect"] == "UNVERIFIED"
        assert rows[-1]["authority"] == "READ_ONLY"


def test_missing_venue_list_row_cannot_erase_an_external_order(tmp_path):
    with ExternalJournal(tmp_path / "external.db") as j:
        j.record(observation("2026-10-31T15:00:00Z", "open"))
        assert j.record(observation("2026-10-31T15:01:00Z", None)) == 0
        assert len(j.events()) == 1


def test_stale_snapshot_or_decreasing_cumulative_fill_fails_closed(tmp_path):
    with ExternalJournal(tmp_path / "external.db") as j:
        j.record(observation("2026-10-31T15:02:00Z", "partial", "0.25"))
        with pytest.raises(ValueError, match="stale"):
            j.record(observation("2026-10-31T15:01:00Z", "open", "0"))
        with pytest.raises(ValueError, match="regressed"):
            j.record(observation("2026-10-31T15:03:00Z", "canceled", "0.20"))
        assert len(j.events()) == 1


def test_different_accounts_are_separate_and_forged_authority_is_rejected(tmp_path):
    main = observation("2026-10-31T15:00:00Z")
    credit = project_account("subaccount:credit-1", "2026-10-31T15:00:00Z",
              orders=[{"client_id": "manual-1", "status": "open", "filled": "0"}])
    with ExternalJournal(tmp_path / "external.db") as j:
        assert j.record(main) == 1
        assert j.record(credit) == 1
        forged = dict(main, authority="FUNDED")
        with pytest.raises(ValueError, match="read-only"):
            j.record(forged)
        assert len(j.events()) == 2
        assert {r["account_id"] for r in j.events()} == {"main", "subaccount:credit-1"}


def test_sqlite_event_rows_are_immutable(tmp_path):
    path = tmp_path / "external.db"
    with ExternalJournal(path) as j:
        j.record(observation("2026-10-31T15:00:00Z"))
    db = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE external_order_events SET raw_status='fake'")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM external_order_events")
    db.close()
