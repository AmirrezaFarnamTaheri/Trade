"""B3 staged update preflight: no direct installer or funded write path."""
import pytest

from gym.services.restore_gate import RestoreUnsafe, assess_update


def valid_state(**changes):
    state = {
        "active_funded_authority": False,
        "unresolved_orders": 0,
        "ledger_integrity_verified": True,
        "off_machine_restore_proven": True,
        "migration_rehearsed": True,
        "current_schema": 1,
        "target_schema": 2,
    }
    state.update(changes)
    return state


def test_update_preflight_only_allows_safe_forward_staging():
    decision = assess_update(valid_state())
    assert decision == {"allow_staged_update": True, "install_authorized": False,
                        "funded_arming": False}


@pytest.mark.parametrize("change", [
    {"active_funded_authority": True},
    {"unresolved_orders": 1},
    {"ledger_integrity_verified": False},
    {"off_machine_restore_proven": False},
    {"migration_rehearsed": False},
    {"target_schema": 1},
    {"target_schema": 3},
    {"target_schema": 0},
])
def test_update_refuses_unverified_or_funded_conditions(change):
    with pytest.raises(RestoreUnsafe):
        assess_update(valid_state(**change))


def test_update_rejects_missing_or_unknown_flags():
    state = valid_state()
    del state["off_machine_restore_proven"]
    with pytest.raises(RestoreUnsafe):
        assess_update(state)
    with pytest.raises(RestoreUnsafe):
        assess_update(valid_state(unresolved_orders=-1))
    with pytest.raises(RestoreUnsafe):
        assess_update(valid_state(active_funded_authority="false"))


def test_policy_is_only_a_preflight_and_never_an_install_or_permission():
    decision = assess_update(valid_state())
    assert decision["install_authorized"] is False
    assert decision["funded_arming"] is False
