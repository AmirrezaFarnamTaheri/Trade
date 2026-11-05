"""Confirmation and component metadata never invent availability or silently change old vintages."""
from datetime import timedelta
import pytest

from gym.services.research_protocol import ResearchProtocol
from gym.services.research_series import derived_series, convert_series
from tests.support import START
from tests.test_research_series import row, request


def test_confirmation_defers_knowledge_and_component_sum_is_exact(tmp_path):
    clock = {"at": START}
    with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as protocol:
        future = START + timedelta(minutes=1)
        record = row("credit", "3", confirmed_at=future.isoformat(), unit_epoch="v2",
                     components=[{"label": "first", "value": "1.1"}, {"label": "second", "value": "1.9"}])
        protocol.ingest_observations({"observations": [record, row("treasury", "2", unit_epoch="v1")]})
        assert derived_series(protocol, request())["reason"] == "MISSING_INPUT"
        clock["at"] = future
        result = derived_series(protocol, request(as_of=future.isoformat()))
        assert result["reason"] == "UNIT_EPOCH_MISMATCH_REQUIRES_EXPLICIT_CONVERSION"
        assert result["inputs"][0]["confirmed_at"] == future.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        assert derived_series(protocol, request())["reason"] == "MISSING_INPUT"


@pytest.mark.parametrize("changes", [
    {"components": [{"label": "a", "value": "2"}]},
    {"components": [{"label": "a", "value": "1"}, {"label": "a", "value": "2"}]},
    {"unit_epoch": "../old"}, {"confirmed_at": (START - timedelta(seconds=1)).isoformat()},
])
def test_invalid_component_or_clock_batch_is_atomic(tmp_path, changes):
    with ResearchProtocol(tmp_path, clock=lambda: START) as protocol:
        with pytest.raises(ValueError):
            protocol.ingest_observations({"observations": [row("treasury", "2"), row("credit", "3", **changes)]})
        assert protocol.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0


def test_explicit_vintage_factor_converts_epochs_without_mutating_source(tmp_path):
    with ResearchProtocol(tmp_path, clock=lambda: START) as protocol:
        protocol.ingest_observations({"observations": [row("credit", "1000", unit="TMN", unit_epoch="old"),
                                                      row("factor", "0.1", unit="TMN/TMN")]})
        def reference(series, unit):
            return {**request()["left"], "series": series, "unit": unit}
        value = {"value": reference("credit", "TMN"), "factor": reference("factor", "TMN/TMN"), "from_epoch": "old",
                 "to_epoch": "new", "target_unit": "TMN", **{k: request()[k] for k in ("as_of", "max_age_seconds", "max_skew_seconds")}}
        out = convert_series(protocol, value)
        assert out["value"] == "100.0" and out["unit_epoch"] == "new"
        assert protocol.observation(value["value"], START)["value"] == "1000"
        with pytest.raises(ValueError, match="source epoch"):
            convert_series(protocol, {**value, "from_epoch": "unrelated"})
