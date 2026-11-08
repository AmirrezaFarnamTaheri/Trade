"""Heatmaps keep failed, missing, unready and altered trial artifacts visible."""
import pytest

from gym.services.experiment_registry import ExperimentRegistry
from gym.services.experiment_scorecard import experiment_scorecard
from gym.services.walk_forward import walk_forward
from tests.support import market_db, quote_history
from tests.test_research_workspace import experiment
from tests.test_walk_forward import request as walk_request


@pytest.fixture
def database(tmp_path):
    db = market_db(tmp_path, quote_history(n=240))
    yield db
    db.c.close()


def test_scorecard_keeps_every_trial_and_detects_a_changed_run(tmp_path, database):
    db = database
    with ExperimentRegistry(tmp_path, store="live") as registry:
        record = registry.run(db, experiment())["experiment"]
        request = {"experiment_id": record["id"], "shadow_run_ids": []}
        report = experiment_scorecard(registry, request)
        assert report["registered_attempts"] == 2 and report["registered_trials"] == 1
        assert report["states"] == {"COMPLETED": 1, "INCOMPLETE": 1}
        assert report["rows"][1]["run"] is None and report["rows"][1]["reason"] == "NO_QUALIFIED_DATA"
        card = report["rows"][0]["run"]
        assert card["ready"] and card["fills"] > 0 and card["valuation"]["status"] == "CURRENT"
        assert card["curve"][0][1] == "1000" and "hold USDT" in card["baselines"]
        assert len(card["curve"]) <= 1000 and not report["funded_authority"]
        assert card["curve"][-1][0] == card["period"]["to"]
        # A historical replay cannot masquerade as prospective observation.
        with pytest.raises(ValueError, match="prospective"):
            experiment_scorecard(registry, {**request, "shadow_run_ids": [card["run_id"]]})
        (tmp_path / "runs" / (card["run_id"] + ".json")).write_text("{}", encoding="utf-8")
        changed = experiment_scorecard(registry, request)
        assert changed["rows"][0]["verification"] == "UNAVAILABLE_OR_CHANGED"
        assert changed["rows"][0]["run"] is None and changed["registered_attempts"] == 2


def test_scorecard_pending_attempts_are_not_omitted(tmp_path):
    with ExperimentRegistry(tmp_path, store="live") as registry:
        record = registry.append("EXPERIMENT", None, {"definition": experiment()})
        registry.append("ATTEMPT", record["id"], {"trial": 0, "window": 0, "scenario": 0, "state": "RESULT_PENDING"})
        report = experiment_scorecard(registry, {"experiment_id": record["id"], "shadow_run_ids": []})
        assert report["states"] == {"RESULT_PENDING": 1}
        assert report["rows"][0]["run"] is None


def test_native_walk_forward_receives_explicit_validation_instead_of_crashing(tmp_path):
    db = market_db(tmp_path, quote_history(n=750))
    try:
        with ExperimentRegistry(tmp_path, store="live") as registry:
            report = walk_forward(registry, db, walk_request())
            with pytest.raises(ValueError, match="walk-forward report"):
                experiment_scorecard(registry, {"experiment_id": report["experiment_id"], "shadow_run_ids": []})
    finally:
        db.c.close()


@pytest.mark.parametrize("shadows", [[{}], ["a"] * 2, ["a"] * 5, None])
def test_invalid_shadow_references_are_rejected_at_boundary(tmp_path, shadows):
    with ExperimentRegistry(tmp_path, store="live") as registry:
        with pytest.raises(ValueError):
            experiment_scorecard(registry, {"experiment_id": "unread", "shadow_run_ids": shadows})
