"""Arm-ready preflight: a checklist that is BLOCKED until every item holds, and never arms."""
import json
from datetime import timedelta

from gym.services.arm_preflight import POLICY, preflight, validate_policy
from tests.support import START, market_db, quote_history

GOOD = {"schema": 1, "loss_cap_quote": "50", "quote_asset": "USDT", "venue": "wallex", "symbols": ["BTCUSDT"],
        "kill": {"max_loss_quote": "25", "stale_data_seconds": 30, "max_open_orders": 1}, "expires_days": 7}


def test_policy_validation_requires_a_coherent_loss_cap_and_kill_rules():
    assert validate_policy(GOOD) == []
    assert validate_policy({**GOOD, "loss_cap_quote": "0"})
    assert validate_policy({**GOOD, "kill": {**GOOD["kill"], "max_loss_quote": "60"}})  # above the cap
    assert validate_policy({**GOOD, "symbols": ["BTCTMN"]})  # wrong quote currency
    assert validate_policy({**GOOD, "expires_days": 0})
    assert validate_policy({**GOOD, "extra": 1})


def test_preflight_stays_blocked_and_never_arms(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, quote_history(n=10)).c.close()
    report = preflight(root, START + timedelta(seconds=120))
    assert report["state"] == "BLOCKED" and report["arms"] is False and report["funded_authority"] is False
    assert "owner_policy" in report["blocked_by"] and "stop_gate_responsive" in report["blocked_by"]
    (root / POLICY).write_text(json.dumps(GOOD), "utf-8")
    report = preflight(root, START + timedelta(seconds=120))
    assert "owner_policy" not in report["blocked_by"] and report["policy_sha256"]
    assert report["state"] == "BLOCKED"  # the privileged items cannot be satisfied from the workspace
