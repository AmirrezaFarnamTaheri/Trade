"""B3 update admission must never imply a funded position is protected."""
import pytest
from gym.services.update_gate import UpdateUnsafe, assess_update


def test_update_without_open_money_starts_disarmed():
    result = assess_update(open_positions=0, unknown_orders=0,
                           alternative_protection=False, accepted_outage=False)
    assert result["allowed"] is True
    assert result["mode_after"] == "DISARMED"
    assert result["protection"] == "NONE"


def test_open_positions_require_verified_alternative_or_explicit_outage_consent():
    with pytest.raises(UpdateUnsafe, match="protection"):
        assess_update(open_positions=1, unknown_orders=0,
                      alternative_protection=False, accepted_outage=False)
    proved = assess_update(open_positions=1, unknown_orders=0,
                           alternative_protection=True, accepted_outage=False)
    assert proved["protection"] == "INDEPENDENT_VERIFIED"
    acknowledged = assess_update(open_positions=1, unknown_orders=0,
                                 alternative_protection=False, accepted_outage=True)
    assert acknowledged["protection"] == "UNPROTECTED_ACCEPTED"
    assert acknowledged["mode_after"] == "DISARMED"


def test_unknown_order_and_corrupt_ledger_refuse_update_even_with_outage_consent():
    with pytest.raises(UpdateUnsafe, match="unresolved"):
        assess_update(open_positions=0, unknown_orders=1,
                      alternative_protection=True, accepted_outage=True)
    with pytest.raises(UpdateUnsafe, match="ledger"):
        assess_update(open_positions=0, unknown_orders=0,
                      alternative_protection=True, accepted_outage=True,
                      ledger_integrity_ok=False)


def test_boolean_not_accepted_as_counts_or_evidence():
    with pytest.raises((TypeError, ValueError)):
        assess_update(open_positions=True, unknown_orders=0,
                      alternative_protection=False, accepted_outage=False)
    with pytest.raises((TypeError, ValueError)):
        assess_update(open_positions=0, unknown_orders=-1,
                      alternative_protection=False, accepted_outage=False)
    with pytest.raises((TypeError, ValueError)):
        assess_update(open_positions=0, unknown_orders=0,
                      alternative_protection="yes", accepted_outage=False)
