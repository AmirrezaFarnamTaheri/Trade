"""Point-in-time series arithmetic never aligns by row position or backfilled release dates."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.services.research_actions import derived_series
from gym.services.research_protocol import ResearchProtocol
from tests.support import START


def row(series, value, **changes):
    return {"source_id": "supplied", "series": series, "subject": "index", "kind": "MACRO", "unit": "index",
            "value": value, "published_at": START.isoformat(), "revision_at": None,
            "measured_at": START.isoformat(), **changes}


def request(**changes):
    def reference(series):
        return {key: value for key, value in row(series, "1").items() if key in ("source_id", "series", "subject", "kind", "unit")}
    return {"left": reference("credit"), "right": reference("treasury"), "operation": "RATIO",
            "as_of": START.isoformat(), "max_age_seconds": 3600, "max_skew_seconds": 60, **changes}


def test_exact_ratio_and_difference_reference_the_actual_two_vintages(tmp_path):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        ids = ledger.ingest_observations({"observations": [row("credit", "3"), row("treasury", "2")]})["imported_ids"]
        result = derived_series(ledger, request())
        assert Decimal(result["value"]) == Decimal("1.5") and result["unit"] == "dimensionless"
        assert [r["observation_id"] for r in result["inputs"]] == ids
        assert result["status"] == "AVAILABLE" and result["source_authenticity_verified"] is False
        assert derived_series(ledger, request(operation="DIFFERENCE"))["value"] == "1"
        assert result == derived_series(ledger, request())
        assert ledger.conn.in_transaction is False


@pytest.mark.parametrize("change,reason", [
    ({"measured_at": (START - timedelta(seconds=61)).isoformat()}, "MISALIGNED_MEASUREMENTS"),
    ({"measured_at": (START - timedelta(hours=2)).isoformat()}, "STALE_MEASUREMENT"),
    ({"value": "0"}, "ZERO_DENOMINATOR"),
])
def test_unavailable_values_are_not_filled_or_scored(tmp_path, change, reason):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        ledger.ingest_observations({"observations": [row("credit", "3"), {**row("treasury", "2"), **change}]})
        result = derived_series(ledger, request())
        assert result["status"] == "UNAVAILABLE" and result["value"] is None and result["reason"] == reason


def test_future_receipt_and_revision_cannot_rewrite_earlier_derived_values(tmp_path):
    clock = {"at": START}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        ledger.ingest_observations({"observations": [row("credit", "3"), row("treasury", "2")]})
        clock["at"] += timedelta(minutes=10)
        ledger.ingest_observations({"observations": [row("treasury", "1", revision_at=clock["at"].isoformat())]})
        assert derived_series(ledger, request())["value"] == "1.5"
        assert derived_series(ledger, request(as_of=clock["at"].isoformat()))["value"] == "3"
        with pytest.raises(ValueError):
            derived_series(ledger, request(as_of=(clock["at"] + timedelta(seconds=1)).isoformat()))


def test_legacy_observations_need_measurement_clocks_and_units_are_not_guessed(tmp_path):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        legacy = row("credit", "3")
        del legacy["measured_at"]
        ledger.ingest_observations({"observations": [legacy, row("treasury", "2")]})
        assert derived_series(ledger, request())["reason"] == "MEASUREMENT_TIME_UNKNOWN"
        assert derived_series(ledger, request(left={**request()["left"], "source_id": "other"}))["reason"] == "MISSING_INPUT"
        for bad in (request(operation="EXECUTE"), request(max_skew_seconds=True), request(max_age_seconds=0)):
            with pytest.raises(ValueError):
                derived_series(ledger, bad)
        with pytest.raises(ValueError):
            ledger.ingest_observations({"observations": [row("future", "1", measured_at=(START + timedelta(seconds=1)).isoformat())]})


def test_new_measurement_wins_over_late_revision_of_an_older_period_and_units_are_explicit(tmp_path):
    clock = {"at": START}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
        ledger.ingest_observations({"observations": [row("credit", "3"), row("treasury", "2", unit="USD")]})
        clock["at"] += timedelta(minutes=1)
        ledger.ingest_observations({"observations": [row("credit", "4", published_at=clock["at"].isoformat(), measured_at=clock["at"].isoformat())]})
        clock["at"] += timedelta(seconds=1)
        ledger.ingest_observations({"observations": [row("credit", "99", revision_at=clock["at"].isoformat())]})
        query = request(as_of=clock["at"].isoformat(), right={**request()["right"], "unit": "USD"})
        result = derived_series(ledger, query)
        assert result["value"] == "2" and result["unit"] == "index/USD"
        with pytest.raises(ValueError, match="identical explicit units"):
            derived_series(ledger, {**query, "operation": "DIFFERENCE"})


def test_tampered_vintage_is_rejected_and_read_transaction_is_closed(tmp_path):
    with ResearchProtocol(tmp_path, clock=lambda: START) as ledger:
        ledger.ingest_observations({"observations": [row("credit", "3"), row("treasury", "2")]})
        # The append-only triggers prevent ordinary edits; simulate damaged storage.
        triggers = ledger.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='observations'").fetchall()
        for (name,) in triggers:
            ledger.conn.execute('DROP TRIGGER "' + name + '"')
        ledger.conn.execute("UPDATE observations SET body=replace(body, '\"3\"', '\"9\"') WHERE json_extract(body,'$.series')='credit'")
        ledger.conn.commit()
        with pytest.raises(ValueError, match="digest mismatch"):
            derived_series(ledger, request())
        assert ledger.conn.in_transaction is False


def test_cli_uses_the_same_derived_service_and_rejects_ambiguous_input(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    with ResearchProtocol(root, clock=lambda: START) as ledger:
        ledger.ingest_observations({"observations": [row("credit", "3"), row("treasury", "2")]})
    source = tmp_path / "ratio.json"
    source.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["--data", str(tmp_path), "research", "derived", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["value"] == "1.5" and result["order_submitted"] is False
    source.write_text('{"operation":"RATIO","operation":"DIFFERENCE"}', encoding="utf-8")
    assert main(["--data", str(tmp_path), "research", "derived", str(source)]) == 2
