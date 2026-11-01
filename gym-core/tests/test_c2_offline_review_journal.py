"""C2 persistent *offline* review queue: not Executor T1 and never a POST."""
import sqlite3

import pytest

from gym.domain.assisted_ticket import prepare_preview
from gym.services.offline_review_journal import OfflineReviewJournal, ReviewUnsafe


def preview():
    return prepare_preview(
        symbol="BTCUSDT", side="BUY", intent="ENTRY", quantity="0.01",
        bid="100", ask="101", worst_price="103", fee_rate="0.002",
        operator_quote_cap="2", available_quote="2", available_base="0",
        minimum_quote="1", observed_at="2026-11-01T08:00:00Z",
        expires_at="2026-11-01T08:00:30Z",
        snapshot_seq=5, quote_age_ms=10,
    )


def test_offline_review_is_durable_and_never_grants_t1_or_money(tmp_path):
    path = tmp_path/"reviews.db"
    with OfflineReviewJournal(path) as journal:
        h = journal.record(preview())
        assert h == preview()["preview_sha256"]
        assert journal.record(preview()) == h
        assert journal.tickets()[0]["state"] == "PREVIEWED"
        result = journal.review(h, "ACKNOWLEDGE", at="2026-11-01T08:00:10Z")
        assert result["state"] == "ACKNOWLEDGED_OFFLINE"
        assert result["funded_authority"] is False
        assert result["tier1_approval"] is False
        assert result["order_submitted"] is False
        assert journal.tickets()[0]["state"] == "ACKNOWLEDGED_OFFLINE"
        assert len(journal.review_events()) == 1
    with OfflineReviewJournal(path) as recovered:
        assert recovered.tickets()[0]["state"] == "ACKNOWLEDGED_OFFLINE"
        assert recovered.review_events()[0]["decision"] == "ACKNOWLEDGE"
        with pytest.raises(ReviewUnsafe, match="reviewed"):
            recovered.review(h, "REJECT", at="2026-11-01T08:00:12Z")


def test_forged_preview_and_secrets_rejected_before_persistence(tmp_path):
    with OfflineReviewJournal(tmp_path/"reviews.db") as journal:
        ticket = preview()
        ticket["worst_total_quote"] = "0"
        with pytest.raises(ReviewUnsafe, match="integrity"):
            journal.record(ticket)
        ticket = preview()
        ticket["api_key"] = "SECRET"
        with pytest.raises(ReviewUnsafe, match="fields"):
            journal.record(ticket)
        assert journal.tickets() == []


def test_expired_and_invalid_offline_decisions_never_emit_review_events(tmp_path):
    with OfflineReviewJournal(tmp_path/"reviews.db") as journal:
        h = journal.record(preview())
        with pytest.raises(ReviewUnsafe, match="expires"):
            journal.review(h, "ACKNOWLEDGE", at="2026-11-01T08:00:30Z")
        with pytest.raises(ReviewUnsafe):
            journal.review(h, "APPROVE_LIVE", at="2026-11-01T08:00:15Z")
        assert journal.review_events() == []
        r = journal.review(h, "REJECT", at="2026-11-01T08:00:11Z")
        assert r["state"] == "REJECTED_OFFLINE"


def test_modified_persisted_preview_fails_closed(tmp_path):
    path = tmp_path/"reviews.db"
    with OfflineReviewJournal(path) as journal:
        journal.record(preview())
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER ticket_previews_no_update")
        db.execute("UPDATE ticket_previews SET canonical_json='{}'")
        db.commit()
    with pytest.raises(ReviewUnsafe, match="integrity"):
        OfflineReviewJournal(path)
