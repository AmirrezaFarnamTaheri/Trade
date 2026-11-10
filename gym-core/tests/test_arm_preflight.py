"""Arm-ready preflight: a checklist that is BLOCKED until every item holds, and never arms."""
import json
from datetime import timedelta

from gym.services.arm_preflight import POLICY, preflight, validate_policy
from tests.support import START, market_db, quote_history

GOOD = {"schema": 1, "loss_cap_quote": "50", "max_order_quote": "20", "max_orders_per_day": 20, "quote_asset": "USDT",
        "venue": "wallex", "symbols": ["BTCUSDT"],
        "kill": {"max_loss_quote": "25", "stale_data_seconds": 30, "max_open_orders": 1}, "expires_days": 7}


def test_policy_validation_requires_a_coherent_loss_cap_and_kill_rules():
    assert validate_policy(GOOD) == []
    assert validate_policy({**GOOD, "loss_cap_quote": "0"})
    assert validate_policy({**GOOD, "kill": {**GOOD["kill"], "max_loss_quote": "60"}})  # above the cap
    assert validate_policy({**GOOD, "symbols": ["BTCTMN"]})  # wrong quote currency
    assert validate_policy({**GOOD, "expires_days": 0})
    assert validate_policy({**GOOD, "extra": 1})
    assert validate_policy({**GOOD, "max_order_quote": "60"})  # an order above the whole loss cap
    assert validate_policy({**GOOD, "max_orders_per_day": 0})


def test_every_shipped_option_is_valid_and_tiers_increase():
    from pathlib import Path
    options = Path(__file__).resolve().parents[2] / "contracts" / "arm-policy"
    tiers = [json.loads((options / f"{name}.json").read_text("utf-8")) for name in ("cost-probe", "pilot", "extended")]
    assert all(validate_policy(t) == [] for t in tiers)
    caps = [float(t["loss_cap_quote"]) for t in tiers]
    assert caps == sorted(caps) and tiers[0]["kill"]["max_open_orders"] == 1


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


def test_arm_record_digest_matches_the_rust_fixture():
    import hashlib
    from pathlib import Path

    from gym.services.arm_preflight import arm_record
    root = Path(__file__).resolve().parents[2]
    fx = json.loads((root / "contracts/v1/fixtures/arm-record.json").read_text(encoding="utf-8"))
    policy = (root / fx["policy_file"]).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(policy).hexdigest() == fx["policy_sha256"]
    record = arm_record(policy, fx["approver"], fx["runtime_epoch"], fx["armed_at_ms"], fx["expires_days"])
    assert record == {"canonical": fx["canonical"], "digest": fx["digest"], "expires_at_ms": fx["expires_at_ms"]}
    raised = policy.replace(b'"loss_cap_quote": "10"', b'"loss_cap_quote": "11"')
    assert arm_record(raised, "owner", 3, fx["armed_at_ms"], 7)["digest"] != fx["digest"]
