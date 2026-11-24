"""Deterministic multi-trigger precedence and cooldown coordinator (spec §5.2)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .quoting_policy import KillSwitchDecision, KillSwitchEvaluator, KillSwitchState

TRIGGER_PRECEDENCE = ("DISLOCATION", "QUOTE_VOLUME", "FIXED_BAR")


@dataclass(frozen=True)
class TriggerResolution:
    as_of: datetime
    settled_open_orders_first: bool
    kill_switch: KillSwitchDecision
    should_evaluate_decision: bool
    ordered_reasons: tuple[str, ...]
    blocked_reason: str | None = None


class MultiTriggerCoordinator:
    """Enforces §5.2 order: settle open child orders -> KillSwitch -> single coalesced decision per ts_avail."""

    def __init__(
        self,
        kill_switch: KillSwitchEvaluator,
        *,
        non_bar_cooldown_s: float = 30.0,
        dislocation_threshold_bps: Decimal = Decimal("30"),
        quote_volume_threshold: Decimal = Decimal("50000"),
    ) -> None:
        self._kill_switch = kill_switch
        self._cooldown_s = non_bar_cooldown_s
        self._dislocation_bps = dislocation_threshold_bps
        self._quote_volume_threshold = quote_volume_threshold
        self._last_non_bar_at: datetime | None = None
        self._accum_quote_volume = Decimal(0)

    def resolve(
        self,
        *,
        as_of: datetime,
        kill_state: KillSwitchState,
        fixed_bar_closed: bool,
        dislocation_bps: Decimal,
        incremental_quote_volume: Decimal,
        has_working_parent_order: bool,
        settle_open_orders_cb=None,
    ) -> TriggerResolution:
        if settle_open_orders_cb is not None:
            settle_open_orders_cb(as_of)

        ks = self._kill_switch.evaluate(kill_state)
        if ks.halted:
            return TriggerResolution(as_of, True, ks, False, (), blocked_reason="KILL_SWITCH:" + ",".join(ks.reasons))

        self._accum_quote_volume += max(Decimal(0), incremental_quote_volume)
        cooldown_ok = (
            self._last_non_bar_at is None
            or (as_of - self._last_non_bar_at).total_seconds() >= self._cooldown_s
        )
        fired: list[str] = []
        if cooldown_ok and abs(dislocation_bps) >= self._dislocation_bps:
            fired.append("DISLOCATION")
        if cooldown_ok and self._accum_quote_volume >= self._quote_volume_threshold:
            fired.append("QUOTE_VOLUME")
        if fixed_bar_closed:
            fired.append("FIXED_BAR")

        ordered = tuple(r for r in TRIGGER_PRECEDENCE if r in fired)
        if not ordered:
            return TriggerResolution(as_of, True, ks, False, (), None)

        if has_working_parent_order:
            return TriggerResolution(as_of, True, ks, False, ordered, blocked_reason="WORKING_PARENT_ORDER")

        if "DISLOCATION" in ordered or "QUOTE_VOLUME" in ordered:
            self._last_non_bar_at = as_of
        if "QUOTE_VOLUME" in ordered:
            self._accum_quote_volume = Decimal(0)
        return TriggerResolution(as_of, True, ks, True, ordered, None)
