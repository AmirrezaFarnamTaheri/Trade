from datetime import timedelta

import pytest

from gym.services.research_protocol import ResearchProtocol
from tests.support import START


def observation(subject="BTC", value="12", **changes):
    return {"source_id": "supplied-source", "series": "open-interest", "subject": subject, "kind": "OPEN_INTEREST",
            "unit": "USDT", "value": value, "published_at": START.isoformat(), "revision_at": None, **changes}


def query(at, **changes):
    return {"source_id": "supplied-source", "series": "open-interest", "kind": "OPEN_INTEREST", "unit": "USDT",
            "as_of": at.isoformat(), "descending": True, "limit": 10, "max_age_seconds": 86400, **changes}


def test_ingestion_cannot_backdate_knowledge_and_revisions_are_cutoff_bound(tmp_path):
    clock = {"at": START + timedelta(minutes=10)}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        row = observation()
        receipt = ledger.ingest_observations({"observations": [row, observation("ETH", "10")]})
        assert not receipt["funded_authority"]
        assert ledger.screen(query(START))["rows"] == []
        assert [r["subject"] for r in ledger.screen(query(clock["at"]))["rows"]] == ["BTC", "ETH"]
        clock["at"] += timedelta(minutes=10)
        ledger.ingest_observations({"observations": [observation(value="5", revision_at=clock["at"].isoformat())]})
        assert ledger.screen(query(clock["at"]))["rows"][0]["subject"] == "ETH"
        assert ledger.screen(query(START + timedelta(minutes=10)))["rows"][0]["value"] == "12"
        ledger.ingest_observations({"observations": [row]})
        assert ledger.screen(query(clock["at"]))["matching_observations"] == 3
        assert ledger.screen(query(clock["at"], unit="TMN"))["rows"] == []


def test_stale_and_future_publications_are_explicit_and_news_is_not_a_numeric_signal(tmp_path):
    clock = {"at": START + timedelta(hours=1)}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        ledger.ingest_observations({"observations": [observation(), observation("SOL", published_at=(START + timedelta(days=1)).isoformat())]})
        out = ledger.screen(query(clock["at"], max_age_seconds=60))
        assert out["stale_subjects"] == 1 and out["rows"] == []
        ledger.ingest_observations({"observations": [observation(kind="NEWS", unit="text", value="Supplied headline")]})
        news = ledger.screen(query(clock["at"], kind="NEWS", unit="text"))
        assert news["ranking"] == "PUBLICATION_TIME" and not news["rows"][0]["rights_verified"]


@pytest.mark.parametrize("change", [{"value": "NaN"}, {"value": 1.0}, {"source_id": "../secret"},
    {"kind": "APPROVE_ORDER"}, {"rights_verified": True}, {"revision_at": (START - timedelta(seconds=1)).isoformat()}])
def test_unsafe_or_untyped_observations_reject_atomically(tmp_path, change):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        with pytest.raises(ValueError):
            ledger.ingest_observations({"observations": [observation("ETH"), observation(**change)]})
        assert ledger.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
