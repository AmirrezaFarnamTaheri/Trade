"""Persisted policy entry locks expire and never suppress exits."""
from datetime import timedelta

from gym.adapters.run_store import save_run
from gym.domain.model import InstrumentId
from gym.services import entry_locks
from gym.services.paper import paper
from gym.services.research_actions import research_action
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def test_evidence_linked_lock_survives_restart_expires_and_preserves_exit(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
        now = START + timedelta(hours=1)
        monkeypatch.setattr(entry_locks, "now_utc", lambda: now)
        request = {"run_id": out["run_id"], "scope": "PAIR", "reason": "COOLDOWN", "duration_seconds": 3600, "threshold_percent": None}
        first = research_action(tmp_path, "entry-lock-add", request)
        assert research_action(tmp_path, "entry-lock-add", request) == first
        rules = RuleService(db)
        inst = InstrumentId.wallex("BTCUSDT")
        assert not rules.check(inst, "BUY", "ENTRY", now)["allowed"]
        assert rules.check(inst, "SELL", "EXIT", now)["allowed"]
        assert rules.check(inst, "BUY", "ENTRY", now + timedelta(hours=1))["allowed"]
        assert rules.check(InstrumentId.wallex("ETHUSDT"), "BUY", "ENTRY", now)["allowed"]
        assert len(research_action(tmp_path, "entry-locks")["rules"]) == 1
        assert not first["funded_authority"] and not first["exit_blocked"]
        request = {**request, "scope": "GLOBAL", "reason": "DRAWDOWN", "threshold_percent": "100"}
        assert research_action(tmp_path, "entry-lock-add", request)["status"] == "NOT_TRIGGERED"
        assert len(research_action(tmp_path, "entry-locks")["rules"]) == 1
    finally:
        db.c.close()
