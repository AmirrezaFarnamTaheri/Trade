"""C3 deterministic shadow-mode-only one-workload engine.

No live Executor, venue credentials, venue order transport or activation API.
Even an apparently valid candidate is simulated and produces no client_id.
All simulated unsettled reservations survive model restart as UNKNOWN.
"""
from __future__ import annotations

import re
from copy import deepcopy

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{5,32}\Z")


class ShadowUnsafe(ValueError):
    """Missing simulation evidence, forbidden mode or invalid cap."""


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ShadowUnsafe(f"{name} must be a positive exact quanta count")
    return value


class ShadowAutopilot:
    """A one-account simulator; shadow arming is NOT funded arming."""

    def __init__(self, *, workload_id: str, account: str, runtime_epoch: int,
                 total_cap_quanta: int, per_order_cap_quanta: int):
        if type(workload_id) is not str or not _NAME.fullmatch(workload_id):
            raise ShadowUnsafe("invalid workload ID")
        if type(account) is not str or (account != "main" and not (
                account.startswith("subaccount:") and _NAME.fullmatch(account))):
            raise ShadowUnsafe("unsupported account scope")
        self.runtime_epoch = _positive(runtime_epoch, "runtime_epoch")
        self.total_cap = _positive(total_cap_quanta, "total cap")
        self.per_order_cap = _positive(per_order_cap_quanta, "per-order cap")
        if self.per_order_cap > self.total_cap:
            raise ShadowUnsafe("per-order cap exceeds session ceiling")
        self.workload_id, self.account = workload_id, account
        self.mode = "DISARMED"
        self.protection_state = "UNAVAILABLE"
        self._spent = 0
        self._pending: dict[str, tuple[str, int]] = {}
        self._used_ids: set[str] = set()

    def _out(self):
        return {"mode": self.mode, "funded_authority": False,
                "executor_authorization": False, "order_posted": False}

    def entry_remaining(self) -> int:
        held = sum(amount for _, amount in self._pending.values())
        remainder = self.total_cap - self._spent - held
        if remainder < 0:
            raise ShadowUnsafe("inconsistent shadow budget")
        return remainder

    def pending_intents(self) -> list[str]:
        return sorted(self._pending)

    def arm_shadow(self, runtime_epoch: int) -> dict:
        if type(runtime_epoch) is not int or runtime_epoch != self.runtime_epoch:
            raise ShadowUnsafe("stale runtime epoch")
        if self.mode != "DISARMED":
            raise ShadowUnsafe("shadow mode cannot override existing stop state")
        if self._pending:
            raise ShadowUnsafe("uncertain entry remains across restart")
        self.mode = "SHADOW"
        return self._out()

    def stage_entry(self, *, intent: str, instrument: str,
                    budget_quanta: int, verified_available_quanta: int,
                    runtime_epoch: int, qualified_quote: bool,
                    venue_open: bool) -> dict:
        if type(intent) is not str or not _NAME.fullmatch(intent):
            raise ShadowUnsafe("invalid synthetic intent ID")
        if type(instrument) is not str or not _SYMBOL.fullmatch(instrument):
            raise ShadowUnsafe("invalid instrument")
        budget = _positive(budget_quanta, "entry budget")
        if type(verified_available_quanta) is not int or verified_available_quanta < 0:
            raise ShadowUnsafe("invalid observed available quanta")
        if type(qualified_quote) is not bool or type(venue_open) is not bool:
            raise ShadowUnsafe("market evidence requires explicit booleans")
        if type(runtime_epoch) is not int:
            raise ShadowUnsafe("invalid runtime epoch")
        blockers = []
        if self.mode != "SHADOW":
            blockers.append("NOT_IN_SHADOW_MODE")
        if runtime_epoch != self.runtime_epoch:
            blockers.append("STALE_RUNTIME_EPOCH")
        if self._pending:
            blockers.append("UNRESOLVED_ENTRY")
        if intent in self._used_ids:
            blockers.append("DUPLICATE_INTENT")
        if not qualified_quote or not venue_open:
            blockers.append("MARKET_NOT_EXECUTABLE")
        if budget > self.per_order_cap:
            blockers.append("PER_ORDER_CAP")
        if budget > self.entry_remaining():
            blockers.append("SESSION_CAP")
        if budget > verified_available_quanta:
            blockers.append("INSUFFICIENT_OBSERVED_BALANCE")
        if not blockers:
            self._pending[intent] = (instrument, budget)
            self._used_ids.add(intent)
        return {
            "state": "BLOCKED" if blockers else "SIMULATED_PENDING",
            "blockers": blockers, "intent": intent, "instrument": instrument,
            "quote_budget_quanta": budget,
            "remaining_cap_quanta": self.entry_remaining(),
            "client_id": None, "order_posted": False, "funded_authority": False,
            "mode": self.mode, "simulation_only": True,
        }

    def observe_fake_terminal(self, intent: str, *, spent_quanta: int, settled: bool) -> dict:
        if intent not in self._pending:
            raise ShadowUnsafe("unknown simulated intent")
        if type(settled) is not bool or not settled:
            raise ShadowUnsafe("fake venue settlement is still missing")
        if type(spent_quanta) is not int or spent_quanta < 0:
            raise ShadowUnsafe("invalid simulated settlement spend")
        instrument, reserved = self._pending[intent]
        if spent_quanta > reserved:
            raise ShadowUnsafe("simulated spend exceeds reserved budget")
        self._spent += spent_quanta
        del self._pending[intent]
        return {
            "state": "SYNTHETIC_CLOSED_UNVERIFIED",
            "intent": intent, "instrument": instrument,
            "spent_quanta": spent_quanta, "funded_authority": False,
            "venue_settled": False, "simulation_only": True,
        }

    def pause(self) -> dict:
        if self.mode == "SHADOW":
            self.mode = "PAUSED"
        return self._out()

    def exit_only(self) -> dict:
        if self.mode != "HALTED":
            self.mode = "EXIT_ONLY"
        return self._out()

    def halt(self) -> dict:
        self.mode = "HALTED"
        return self._out()

    def restart(self, *, new_runtime_epoch: int) -> "ShadowAutopilot":
        new_epoch = _positive(new_runtime_epoch, "new runtime epoch")
        if new_epoch == self.runtime_epoch:
            raise ShadowUnsafe("restart needs a fresh epoch")
        restarted = ShadowAutopilot(
            workload_id=self.workload_id, account=self.account,
            runtime_epoch=new_epoch, total_cap_quanta=self.total_cap,
            per_order_cap_quanta=self.per_order_cap,
        )
        # A crash never frees a pending hold or resumes automation, even
        # after a simulated HALT. No synthetic outcome proves a venue fill.
        restarted._spent = self._spent
        restarted._pending = deepcopy(self._pending)
        restarted._used_ids = self._used_ids.copy()
        return restarted
