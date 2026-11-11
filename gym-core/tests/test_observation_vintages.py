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


def test_numeric_screen_keeps_latest_measurement_when_older_period_is_published_later(tmp_path):
    measured = START + timedelta(hours=1)
    published = START + timedelta(hours=2)
    clock = {"at": START + timedelta(hours=3)}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        ledger.ingest_observations({"observations": [
            observation(value="20", measured_at=measured.isoformat(), published_at=measured.isoformat()),
            observation(value="999", measured_at=START.isoformat(), published_at=published.isoformat(),
                        revision_at=clock["at"].isoformat()),
        ]})
        reference = {key: observation()[key] for key in ("source_id", "series", "subject", "kind", "unit")}
        first_cutoff = clock["at"]
        selected = ledger.screen(query(first_cutoff))["rows"][0]
        assert selected == ledger.observation(reference, first_cutoff)
        assert selected["value"] == "20"

        clock["at"] += timedelta(seconds=1)
        ledger.ingest_observations({"observations": [
            observation(value="25", measured_at=measured.isoformat(), published_at=measured.isoformat(),
                        revision_at=clock["at"].isoformat()),
        ]})
        assert ledger.screen(query(clock["at"]))["rows"][0]["value"] == "25"
        assert ledger.screen(query(first_cutoff))["rows"][0]["value"] == "20"


@pytest.mark.parametrize("kind,unit,value,measured", [
    ("OPEN_INTEREST", "USDT", "12", True),
    ("OPEN_INTEREST", "USDT", "12", False),
    ("NEWS", "text", "Supplied headline", False),
])
def test_screen_freshness_uses_measurement_when_known_and_publication_otherwise(tmp_path, kind, unit, value, measured):
    published = START + timedelta(hours=1)
    clock = {"at": published}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        ledger.ingest_observations({"observations": [
            observation(kind=kind, unit=unit, value=value, published_at=published.isoformat(),
                        **({"measured_at": START.isoformat()} if measured else {})),
        ]})
        assert len(ledger.screen(query(clock["at"], kind=kind, unit=unit, max_age_seconds=3600))["rows"]) == 1
        clock["at"] += timedelta(seconds=1)
        result = ledger.screen(query(clock["at"], kind=kind, unit=unit, max_age_seconds=3600))
        assert result["stale_subjects"] == int(measured)
        assert len(result["rows"]) == int(not measured)


@pytest.mark.parametrize("change", [{"value": "NaN"}, {"value": 1.0}, {"source_id": "../secret"},
    {"kind": "APPROVE_ORDER"}, {"rights_verified": True}, {"revision_at": (START - timedelta(seconds=1)).isoformat()}])
def test_unsafe_or_untyped_observations_reject_atomically(tmp_path, change):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        with pytest.raises(ValueError):
            ledger.ingest_observations({"observations": [observation("ETH"), observation(**change)]})
        assert ledger.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
