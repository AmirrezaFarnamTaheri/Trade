"""The workspace can read and save the owner arm policy; saving grants nothing and bad policies never land."""
import json

import pytest

from gym.services.arm_preflight import DEFAULT_POLICY, validate_policy
from gym.services.research_actions import research_action


def test_defaults_are_a_valid_policy_and_read_shows_them_with_the_preflight(tmp_path):
    assert validate_policy(DEFAULT_POLICY) == []
    out = research_action(tmp_path, "arm-policy-read")
    assert out["policy"] is None and out["default"] == DEFAULT_POLICY
    assert out["preflight"]["state"] == "BLOCKED"  # nothing is set up in an empty workspace
    assert "owner_policy" in out["preflight"]["blocked_by"]


def test_save_roundtrips_is_hash_stable_and_rejects_an_incoherent_policy(tmp_path):
    saved = research_action(tmp_path, "arm-policy-save", dict(DEFAULT_POLICY))
    assert saved["saved"] is True and len(saved["policy_sha256"]) == 64
    again = research_action(tmp_path, "arm-policy-save", dict(DEFAULT_POLICY))
    assert again["policy_sha256"] == saved["policy_sha256"]  # canonical write: same policy, same digest
    out = research_action(tmp_path, "arm-policy-read")
    assert out["policy"] == DEFAULT_POLICY
    assert json.loads((tmp_path / "arm-policy.json").read_text()) == DEFAULT_POLICY
    for breakage in ({"loss_cap_quote": "0"}, {"max_order_quote": "60"}, {"expires_days": 31},
                     {"kill": {**DEFAULT_POLICY["kill"], "max_loss_quote": "500"}},
                     {"symbols": ["BTCTMN"]}):
        with pytest.raises(ValueError):
            research_action(tmp_path, "arm-policy-save", {**DEFAULT_POLICY, **breakage})
    assert research_action(tmp_path, "arm-policy-read")["policy"] == DEFAULT_POLICY  # failures changed nothing


def test_the_policy_belongs_to_the_live_workspace_and_read_takes_no_value(tmp_path):
    with pytest.raises(ValueError, match="live workspace"):
        research_action(tmp_path, "arm-policy-save", dict(DEFAULT_POLICY), store="demo")
    with pytest.raises(ValueError, match="takes no value"):
        research_action(tmp_path, "arm-policy-read", {"x": 1})
