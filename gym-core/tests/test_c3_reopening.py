"""C3 venue reopening requires fresh, ordered observations, never arms trading."""
import pytest

from gym.domain.reopening import ReopeningWindow, ReopeningUnsafe


def make(policy="SELL_AT_REOPEN", quotes=1):
    return ReopeningWindow(
        instrument="BTCUSDT", policy=policy, quote_count=quotes,
        runtime_epoch=9,
    )


def test_venue_closed_means_unavailable_exit_even_when_triggered():
    gate = make()
    closed = gate.observe(
        sequence=1, quote_age_ms=10, venue_open=False,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9,
    )
    assert closed["protection_state"] == "UNAVAILABLE"
    assert closed["reopening_advisory"] == "BLOCKED"
    assert closed["funded_authority"] is False
    live = gate.observe(sequence=2, quote_age_ms=15, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    assert live["reopening_advisory"] == "SELL_AT_REOPEN_CANDIDATE"
    assert live["order_submitted"] is False
    assert live["executable"] is False


def test_soft_exit_requires_n_distinct_consecutive_qualified_quotes():
    gate = make("REEVALUATE_AFTER_N_QUOTES", 3)
    for sequence in (1, 2):
        result = gate.observe(sequence=sequence, quote_age_ms=10, venue_open=True,
            unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
        assert result["reopening_advisory"] == "WAIT_FOR_QUOTES"
        assert result["qualified_quotes"] == sequence
    stale = gate.observe(sequence=3, quote_age_ms=2001, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    assert stale["reopening_advisory"] == "BLOCKED"
    assert stale["qualified_quotes"] == 0
    for sequence in (4, 5):
        result = gate.observe(sequence=sequence, quote_age_ms=10, venue_open=True,
            unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
        assert result["reopening_advisory"] == "WAIT_FOR_QUOTES"
    final = gate.observe(sequence=6, quote_age_ms=10, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    assert final["reopening_advisory"] == "REEVALUATE_EXIT_CANDIDATE"
    assert final["executable"] is False


def test_reopen_cannot_use_stale_epoch_ambiguous_orders_or_new_unit():
    gate = make()
    for seq, change in enumerate([
        {"runtime_epoch": 8},
        {"no_unknown_orders": False},
        {"unit_epoch_verified": False},
    ], 1):
        kwargs = dict(sequence=seq, quote_age_ms=10, venue_open=True,
            unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
        kwargs.update(change)
        result = gate.observe(**kwargs)
        assert result["reopening_advisory"] == "BLOCKED"
        assert result["qualified_quotes"] == 0
    good = gate.observe(sequence=4, quote_age_ms=10, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    assert good["reopening_advisory"] == "SELL_AT_REOPEN_CANDIDATE"


def test_replay_and_reordered_quotes_cannot_fabricate_qualification():
    gate = make("REEVALUATE_AFTER_N_QUOTES", 2)
    gate.observe(sequence=1, quote_age_ms=10, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    with pytest.raises(ReopeningUnsafe, match="sequence"):
        gate.observe(sequence=1, quote_age_ms=10, venue_open=True,
            unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=9)
    # A reboot forgets qualified quotes and requires new process epoch.
    rebooted = gate.restart(10)
    assert rebooted.observe(sequence=2, quote_age_ms=10, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=True, runtime_epoch=10
        )["reopening_advisory"] == "WAIT_FOR_QUOTES"


@pytest.mark.parametrize("policy,n", [
    ("AUTO_SELL", 1), ("SELL_AT_REOPEN", 0),
    ("REEVALUATE_AFTER_N_QUOTES", 1001),
])
def test_unsupported_reopening_policy_is_rejected(policy, n):
    with pytest.raises(ReopeningUnsafe):
        make(policy, n)
