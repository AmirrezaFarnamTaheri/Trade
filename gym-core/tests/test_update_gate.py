"""Update outage recommendations never authorize installation or trading."""
import pytest

from gym.services.update_gate import UpdateUnsafe
from gym.services.update_gate import assess_update as assess_service_outage


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
