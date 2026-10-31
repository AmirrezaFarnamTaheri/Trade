"""Release guard for the *runtime* token proof (not a Windows acceptance test).

Only an actual Windows process-token query can prove the restricted service SID.
The static checks ensure the source cannot silently revert to account-name-only
checks; behavior is independently expressed in Rust policy tests.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "executor/exec-svc/src/main.rs"
IDENTITY = ROOT / "executor/exec-svc/src/windows_identity.rs"
POLICY = ROOT / "executor/exec-svc/src/lib.rs"
RUST_TEST = ROOT / "executor/exec-svc/tests/restricted_service_identity.rs"


def test_windows_host_requires_restricted_service_token_not_just_account():
    body = HOST.read_text(encoding="utf-8")
    assert "is_restricted_executor_service" in body
    assert "if !exec_svc::windows_identity::is_local_service()" not in body
    assert "ServiceState::Stopped, 5" in body


def test_service_identity_comes_from_os_token_groups_and_restrictions():
    body = IDENTITY.read_text(encoding="utf-8")
    for key in ("OpenProcessToken", "TokenUser", "TokenGroups", "TokenRestrictedSids",
                "LookupAccountNameW", "GetTokenInformation"):
        assert key in body
    assert r'NT SERVICE\\TradingGYMExecutor' in body
    assert "std::env::var" not in body


def test_policy_requires_both_enabled_group_and_restricting_sid():
    policy = POLICY.read_text(encoding="utf-8")
    tests = RUST_TEST.read_text(encoding="utf-8")
    assert "is_restricted_executor_token" in policy
    assert "TokenGroup" in policy
    assert "enabled" in policy
    assert "restricting_sids" in policy
    assert "rejects_missing_disabled_or_wrong_service_group" in tests
    assert "rejects_missing_or_different_restricted_sid" in tests
