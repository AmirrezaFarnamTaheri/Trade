"""C3 one-workload shadow Autopilot: cap, runtime fence, no money authority."""
import pytest

from gym.domain.shadow_autopilot import ShadowAutopilot, ShadowUnsafe


def new():
    return ShadowAutopilot(
        workload_id="one-conversion", account="main",
        runtime_epoch=3, total_cap_quanta=1000, per_order_cap_quanta=400,
    )


def test_shadow_requires_disarmed_start_fresh_epoch_and_exact_budget():
    bot = new()
    assert bot.mode == "DISARMED"
    assert bot.entry_remaining() == 1000
    assert bot.stage_entry(intent="paper-1", instrument="BTCUSDT",
            budget_quanta=300, verified_available_quanta=1000,
            runtime_epoch=3, qualified_quote=True, venue_open=True)["state"] == "BLOCKED"
    assert bot.arm_shadow(3)["mode"] == "SHADOW"
    first = bot.stage_entry(intent="paper-1", instrument="BTCUSDT",
        budget_quanta=300, verified_available_quanta=1000,
        runtime_epoch=3, qualified_quote=True, venue_open=True)
    assert first["state"] == "SIMULATED_PENDING"
    assert first["client_id"] is None
    assert first["order_posted"] is False
    assert first["funded_authority"] is False
    assert bot.entry_remaining() == 700
    competing = bot.stage_entry(intent="paper-2", instrument="ETHUSDT",
        budget_quanta=100, verified_available_quanta=700,
        runtime_epoch=3, qualified_quote=True, venue_open=True)
    assert competing["state"] == "BLOCKED"
    assert "UNRESOLVED_ENTRY" in competing["blockers"]
    bot.observe_fake_terminal("paper-1", spent_quanta=250, settled=True)
    assert bot.entry_remaining() == 750
    second = bot.stage_entry(intent="paper-2", instrument="ETHUSDT",
        budget_quanta=400, verified_available_quanta=750,
        runtime_epoch=3, qualified_quote=True, venue_open=True)
    assert second["state"] == "SIMULATED_PENDING"
    assert bot.entry_remaining() == 350


def test_shadow_rejects_unsafe_cap_and_ambiguous_fills():
    bot = new()
    bot.arm_shadow(3)
    for n, amount in enumerate([401, 1001]):
        r = bot.stage_entry(intent=f"over-{n}", instrument="BTCUSDT",
            budget_quanta=amount, verified_available_quanta=1000,
            runtime_epoch=3, qualified_quote=True, venue_open=True)
        assert r["state"] == "BLOCKED"
    assert bot.stage_entry(intent="stale", instrument="BTCUSDT",
            budget_quanta=100, verified_available_quanta=1000,
            runtime_epoch=2, qualified_quote=True, venue_open=True)["state"] == "BLOCKED"
    assert bot.stage_entry(intent="closed", instrument="BTCUSDT",
            budget_quanta=100, verified_available_quanta=1000,
            runtime_epoch=3, qualified_quote=True, venue_open=False)["state"] == "BLOCKED"
    bot.stage_entry(intent="paper", instrument="BTCUSDT", budget_quanta=300,
        verified_available_quanta=1000, runtime_epoch=3,
        qualified_quote=True, venue_open=True)
    with pytest.raises(ShadowUnsafe, match="settlement"):
        bot.observe_fake_terminal("paper", spent_quanta=100, settled=False)
    with pytest.raises(ShadowUnsafe, match="reserved"):
        bot.observe_fake_terminal("paper", spent_quanta=301, settled=True)
    assert bot.entry_remaining() == 700


def test_restart_disarms_and_preserves_ambiguous_reservation():
    bot = new()
    bot.arm_shadow(3)
    bot.stage_entry(intent="paper", instrument="BTCUSDT",
        budget_quanta=300, verified_available_quanta=1000,
        runtime_epoch=3, qualified_quote=True, venue_open=True)
    restarted = bot.restart(new_runtime_epoch=4)
    assert restarted.mode == "DISARMED"
    assert restarted.entry_remaining() == 700
    assert restarted.pending_intents() == ["paper"]
    with pytest.raises(ShadowUnsafe, match="uncertain"):
        restarted.arm_shadow(4)
    assert restarted.stage_entry(intent="new", instrument="BTCUSDT",
        budget_quanta=100, verified_available_quanta=1000,
        runtime_epoch=3, qualified_quote=True, venue_open=True)["state"] == "BLOCKED"
    assert restarted.protection_state == "UNAVAILABLE"


def test_pause_exit_only_halt_veto_entry_and_cannot_claim_venue_protection():
    bot = new()
    bot.arm_shadow(3)
    assert bot.pause()["mode"] == "PAUSED"
    assert bot.stage_entry(intent="late", instrument="BTCUSDT",
        budget_quanta=100, verified_available_quanta=1000,
        runtime_epoch=3, qualified_quote=True, venue_open=True)["state"] == "BLOCKED"
    assert bot.exit_only()["mode"] == "EXIT_ONLY"
    assert bot.protection_state == "UNAVAILABLE"
    assert bot.halt()["mode"] == "HALTED"
    with pytest.raises(ShadowUnsafe):
        bot.arm_shadow(3)
    assert bot.restart(new_runtime_epoch=4).mode == "DISARMED"


@pytest.mark.parametrize("change", [
    {"runtime_epoch": 0},
    {"runtime_epoch": True},
    {"total_cap_quanta": 0},
    {"per_order_cap_quanta": 1001},
    {"workload_id": "has space"},
])
def test_bad_shadow_envelope_is_rejected(change):
    params = dict(workload_id="one-conversion", account="main", runtime_epoch=3,
                  total_cap_quanta=1000, per_order_cap_quanta=400)
    params.update(change)
    with pytest.raises((ShadowUnsafe, ValueError, TypeError)):
        ShadowAutopilot(**params)
