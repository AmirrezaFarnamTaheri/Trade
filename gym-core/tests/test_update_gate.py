"""B3 staged update preflight: no direct installer or funded write path."""
import pytest

from gym.services.restore_gate import RestoreUnsafe, assess_migration_staging


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
    decision = assess_migration_staging(valid_state())
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
        assess_migration_staging(valid_state(**change))


def test_update_rejects_missing_or_unknown_flags():
    state = valid_state()
    del state["off_machine_restore_proven"]
    with pytest.raises(RestoreUnsafe):
        assess_migration_staging(state)
    with pytest.raises(RestoreUnsafe):
        assess_migration_staging(valid_state(unresolved_orders=-1))
    with pytest.raises(RestoreUnsafe):
        assess_migration_staging(valid_state(active_funded_authority="false"))


def test_policy_is_only_a_preflight_and_never_an_install_or_permission():
    decision = assess_migration_staging(valid_state())
    assert decision["install_authorized"] is False
    assert decision["funded_arming"] is False


# Separately check the pure operator-outage policy, which is NOT the
# migration staging policy and has no installer or journal side effects.
from gym.services.update_gate import UpdateUnsafe, assess_update as assess_service_outage


def test_service_update_outage_policy_refuses_unknown_orders_even_if_protected():
    with pytest.raises(UpdateUnsafe):
        assess_service_outage(open_positions=1, unknown_orders=1,
                              alternative_protection=True, accepted_outage=True)


def test_service_update_requires_independent_protection_or_operator_outage():
    with pytest.raises(UpdateUnsafe):
        assess_service_outage(open_positions=1, unknown_orders=0,
                              alternative_protection=False, accepted_outage=False)
    with pytest.raises(UpdateUnsafe):
        assess_service_outage(open_positions=0, unknown_orders=0,
                              alternative_protection=False, accepted_outage=False,
                              ledger_integrity_ok=False)


def test_service_update_policy_is_only_a_non_authoritative_recommendation():
    result = assess_service_outage(open_positions=1, unknown_orders=0,
        alternative_protection=False, accepted_outage=True)
    assert result["allowed"] is True
    assert result["mode_after"] == "DISARMED"
    assert result["protection"] == "UNPROTECTED_ACCEPTED"
    assert result["authority"] == "OFFLINE_POLICY_ONLY"


def test_service_update_rejects_nonboolean_and_negative_evidence():
    with pytest.raises(TypeError):
        assess_service_outage(open_positions=-1, unknown_orders=0,
                              alternative_protection=False, accepted_outage=False)
    with pytest.raises(TypeError):
        assess_service_outage(open_positions=1, unknown_orders=0,
                              alternative_protection="true", accepted_outage=False)
