"""C3 no-effect Exit Guard and venue reopening policy, before funded certification."""
import pytest
from gym.domain.exit_guard import assess_reopening, propose_protective_exit, ExitPolicyUnsafe


def safe_reopen(**changes):
    args = {
        "venue_open": True, "snapshot_fresh": True,
        "account_reconciled": True, "stop_method_certified": True,
        "no_unknown_orders": True, "operator_rearmed": True,
        "runtime_epoch": 9, "proposal_epoch": 9,
    }
    args.update(changes)
    return assess_reopening(**args)


def test_even_all_reopening_checks_cannot_arm_a_python_or_ui_process():
    result = safe_reopen()
    assert result["ready_for_operator_review"] is True
    assert result["entries_enabled"] is False
    assert result["mode_after"] == "DISARMED"
    assert result["funded_authority"] is False
    assert result["executor_authorization"] is False


@pytest.mark.parametrize("change,expected", [
    ({"venue_open": False}, "VENUE_CLOSED"),
    ({"snapshot_fresh": False}, "STALE_MARKET"),
    ({"account_reconciled": False}, "RECONCILIATION_MISSING"),
    ({"stop_method_certified": False}, "NO_VERIFIED_PROTECTION"),
    ({"no_unknown_orders": False}, "UNKNOWN_ORDERS"),
    ({"operator_rearmed": False}, "NO_OPERATOR_REARM"),
    ({"proposal_epoch": 8}, "STALE_RUNTIME_EPOCH"),
])
def test_reopening_never_resumes_entries_without_necessary_evidence(change, expected):
    result = safe_reopen(**change)
    assert result["ready_for_operator_review"] is False
    assert expected in result["blockers"]
    assert result["entries_enabled"] is False


@pytest.mark.parametrize("change", [
    {"venue_open": "true"},
    {"runtime_epoch": 0},
    {"proposal_epoch": True},
])
def test_reopening_rejects_malformed_claimed_evidence(change):
    with pytest.raises((ExitPolicyUnsafe, TypeError)):
        safe_reopen(**change)


def test_verified_cross_instrument_exit_candidate_can_bypass_entry_cooldown():
    result = propose_protective_exit(
        instrument="ETHUSDT", requested_quanta=5, verified_base_quanta=6,
        venue_executable=True, same_instrument_inflight=False,
        account_entry_inflight=True, unknown_order=False,
        entry_cooldown=True, mode="EXIT_ONLY",
    )
    assert result["state"] == "ADVISORY_EXIT_CANDIDATE"
    assert result["entry_cooldown_applies"] is False
    assert result["executable"] is False
    assert result["funded_authority"] is False


@pytest.mark.parametrize("change,expected", [
    ({"requested_quanta": 8}, "INSUFFICIENT_VERIFIED_BASE"),
    ({"same_instrument_inflight": True}, "SAME_INSTRUMENT_ORDER"),
    ({"unknown_order": True}, "UNKNOWN_ORDER"),
    ({"venue_executable": False}, "VENUE_UNAVAILABLE"),
    ({"mode": "HALTED"}, "HALTED"),
])
def test_exit_never_ignores_position_or_order_integrity(change, expected):
    params = {
        "instrument": "BTCUSDT", "requested_quanta": 5,
        "verified_base_quanta": 6, "venue_executable": True,
        "same_instrument_inflight": False, "account_entry_inflight": False,
        "unknown_order": False, "entry_cooldown": True, "mode": "EXIT_ONLY",
    }
    params.update(change)
    result = propose_protective_exit(**params)
    assert result["state"] == "BLOCKED"
    assert expected in result["blockers"]
    assert result["executable"] is False
    assert result["funded_authority"] is False
