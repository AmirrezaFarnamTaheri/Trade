"""M-2 step 1: fits count as trials; artifacts are content-addressed and fail to ABSTAIN."""
from datetime import UTC, datetime, timedelta

import pytest

from gym.services.model_artifacts import ArtifactRegistry
from gym.services.trial_ledger import TrialLedger

NOW = datetime(2026, 11, 10, tzinfo=UTC)
SCHEMA = {"features": ["spread_bps", "ret_1m"], "version": 1}
COST = "a" * 64
MODEL = {"intercept": "-0.1", "coefficients": {"spread_bps": "0.02", "ret_1m": "1.5"}}


def fit(ledger, n):
    return ledger.record(symbol="BTCUSDT", start="2026-10-01T00:00:00+00:00", end="2026-11-01T00:00:00+00:00",
                         hypothesis="meta-label", source="model-fit", config_hash=f"fit-{n}")


def test_each_fit_raises_the_trial_count_and_registration_requires_it(tmp_path):
    with TrialLedger(tmp_path) as ledger, ArtifactRegistry(tmp_path) as registry:
        first, second = fit(ledger, 1), fit(ledger, 2)
        assert (first["trials"], second["trials"]) == (1, 2)
        sha = registry.register(MODEL, kind="logistic", feature_schema=SCHEMA, cost_digest=COST, trial_ledger=ledger,
                                trial_attempt=second["attempt_id"], now=NOW, expires_at=NOW + timedelta(days=30))
        assert registry.identity(sha) == {"model_artifact": sha, "model_feature_schema": registry.identity(sha)[
            "model_feature_schema"], "model_cost_model": COST}
        paper = ledger.record(symbol="BTCUSDT", start=NOW, end=NOW + timedelta(days=1), hypothesis="x",
                              source="paper", config_hash="c")
        with pytest.raises(ValueError, match="trial ledger"):
            registry.register(MODEL, kind="logistic", feature_schema=SCHEMA, cost_digest=COST, trial_ledger=ledger,
                              trial_attempt=paper["attempt_id"], now=NOW, expires_at=NOW + timedelta(days=1))


def test_load_abstains_on_corrupt_expired_or_incompatible(tmp_path):
    with TrialLedger(tmp_path) as ledger, ArtifactRegistry(tmp_path) as registry:
        sha = registry.register(MODEL, kind="logistic", feature_schema=SCHEMA, cost_digest=COST, trial_ledger=ledger,
                                trial_attempt=fit(ledger, 1)["attempt_id"], now=NOW,
                                expires_at=NOW + timedelta(days=30))
        ok = registry.load(sha, feature_schema=SCHEMA, cost_digest=COST, now=NOW)
        assert ok["status"] == "READY" and ok["artifact"] == MODEL
        assert registry.load(sha, feature_schema=SCHEMA, cost_digest=COST, now=NOW + timedelta(days=30))["reason"] == "expired"
        assert registry.load(sha, feature_schema={**SCHEMA, "version": 2}, cost_digest=COST, now=NOW)["reason"] == \
            "incompatible feature schema"
        assert registry.load(sha, feature_schema=SCHEMA, cost_digest="b" * 64, now=NOW)["reason"] == "incompatible cost model"
        assert registry.load("0" * 64, feature_schema=SCHEMA, cost_digest=COST, now=NOW)["reason"] == "unregistered"
        path = tmp_path / "models" / f"{sha}.json"
        path.write_bytes(path.read_bytes().replace(b"1.5", b"9.5"))
        assert registry.load(sha, feature_schema=SCHEMA, cost_digest=COST, now=NOW)["reason"] == "corrupt"
        path.unlink()
        assert registry.load(sha, feature_schema=SCHEMA, cost_digest=COST, now=NOW)["reason"] == "missing"


def test_no_order_or_sizing_module_imports_the_registry():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src/gym"
    for path in [*src.glob("domain/*.py"), src / "services/session.py", src / "services/portfolio.py"]:
        assert "model_artifacts" not in path.read_text(encoding="utf-8"), path
