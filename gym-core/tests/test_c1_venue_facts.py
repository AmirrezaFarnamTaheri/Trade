"""C1 immutable, non-authoritative venue evidence and fail-closed capability registry."""
import hashlib
import json
import sqlite3

import pytest

from gym.services.venue_facts import VenueFactsJournal, VenueFactsUnsafe


def sample(**change):
    record = {
        "evidence_id": "operator-2026-11-01-01",
        "observed_at": "2026-11-01T08:00:00Z",
        "source": "SANITIZED_EXPORT",
        "kind": "BALANCES",
        "endpoint": "ACCOUNT_BALANCES",
        "state": "OBSERVED",
        "account_scope": "main",
        "response_version": "v1",
        "evidence_sha256": hashlib.sha256(b"separate sanitized read-only export").hexdigest(),
    }
    record.update(change)
    return record


def test_c1_evidence_is_durable_and_never_grants_funded_authority(tmp_path):
    db = tmp_path / "venue_facts.db"
    with VenueFactsJournal(db) as journal:
        assert journal.capabilities()["read_only_account"]["state"] == "NOT_CONFIGURED"
        assert journal.record(sample()) == 1
        assert journal.record(sample()) == 1  # duplicate evidence id is idempotent
        assert len(journal.facts()) == 1
        assert journal.facts()[0]["source"] == "SANITIZED_EXPORT"
        assert journal.facts()[0]["trusted_origin"] is False
        state = journal.capabilities()
        assert state["read_only_account"]["state"] == "EVIDENCE_ONLY"
        assert state["assisted_order"]["state"] == "BLOCKED"
        assert state["autopilot"]["state"] == "BLOCKED"
        assert all(not item["funded_authority"] for item in state.values())
    with VenueFactsJournal(db) as reopened:
        assert reopened.facts()[0]["evidence_id"] == "operator-2026-11-01-01"
        assert reopened.capabilities()["read_only_account"]["state"] == "EVIDENCE_ONLY"


def test_c1_probe_reports_never_self_certify_a_write_or_exit_method(tmp_path):
    with VenueFactsJournal(tmp_path / "facts.db") as journal:
        for number, kind in enumerate(("CLIENT_ID_ECHO", "DUPLICATE_ID", "CANCEL_RACE", "VENUE_STOP")):
            journal.record(sample(evidence_id=f"probe-{number}", kind=kind,
                                  endpoint="MANUAL_PROBE",
                                  source="SANITIZED_EXPORT"))
        registry = journal.capabilities()
        assert registry["venue_probe"]["state"] == "NOT_CERTIFIED"
        assert registry["venue_stop"]["state"] == "NOT_CERTIFIED"
        assert registry["assisted_order"]["state"] == "BLOCKED"
        assert registry["autopilot"]["state"] == "BLOCKED"
        assert not any(value["funded_authority"] for value in registry.values())


@pytest.mark.parametrize("change", [
    {"api_key": "VERY-PRIVATE"},
    {"evidence_sha256": "bad"},
    {"evidence_id": "../../unsafe"},
    {"observed_at": "2026-11-01T08:00:00"},
    {"state": "CERTIFIED"},
    {"source": "TRUSTED_T2"},
    {"account_scope": "credit-one"},
    {"endpoint": "https://evil.example?token=secret"},
    {"kind": "EXECUTE_ORDER"},
])
def test_invalid_or_extra_fields_fail_without_persistence(tmp_path, change):
    with VenueFactsJournal(tmp_path / "facts.db") as journal:
        with pytest.raises((VenueFactsUnsafe, TypeError, ValueError)):
            journal.record(sample(**change))
        assert journal.facts() == []


def test_conflicting_duplicate_id_and_future_schema_fail_closed(tmp_path):
    path = tmp_path / "facts.db"
    with VenueFactsJournal(path) as journal:
        journal.record(sample())
        with pytest.raises(VenueFactsUnsafe, match="conflicting"):
            journal.record(sample(state="ERROR"))
        assert len(journal.facts()) == 1
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE venue_facts SET state='ERROR'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM venue_facts")
        conn.execute("PRAGMA user_version=999")
        conn.commit()
    with pytest.raises(VenueFactsUnsafe, match="schema"):
        VenueFactsJournal(path)


def test_chain_rejects_edited_events_even_if_immutability_guard_is_removed(tmp_path):
    path = tmp_path / "facts.db"
    with VenueFactsJournal(path) as journal:
        journal.record(sample())
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER venue_facts_no_update")
        conn.execute("UPDATE venue_facts SET state='ERROR'")
        conn.commit()
    with pytest.raises(VenueFactsUnsafe, match="integrity"):
        VenueFactsJournal(path)


def test_error_and_unknown_are_not_success_or_order_absence(tmp_path):
    with VenueFactsJournal(tmp_path / "facts.db") as journal:
        journal.record(sample(state="UNKNOWN"))
        journal.record(sample(evidence_id="error-01", kind="ORDER_STATUS",
                              endpoint="ORDER_STATUS", state="ERROR"))
        state = journal.capabilities()
        assert state["read_only_account"]["state"] == "UNAVAILABLE"
        assert state["order_reconciliation"]["state"] == "UNAVAILABLE"
        assert state["assisted_order"]["state"] == "BLOCKED"
