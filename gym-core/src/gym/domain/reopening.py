"""C3 post-closure quote replay gate, never an executable Exit Guard.

Venue closure means software protection UNAVAILABLE even if the local stop
would have triggered. At reopening, qualified distinct quotes yield only
an advisory, never an order or tier-2 authorization.
"""
from __future__ import annotations

import re


class ReopeningUnsafe(ValueError):
    """Missing quote sequence, runtime fence or unsupported reopening policy."""


class ReopeningWindow:
    def __init__(self, *, instrument: str, policy: str,
                 quote_count: int, runtime_epoch: int):
        if type(instrument) is not str or not re.fullmatch(r"[A-Z0-9]{5,32}", instrument):
            raise ReopeningUnsafe("invalid venue instrument")
        if policy not in ("SELL_AT_REOPEN", "REEVALUATE_AFTER_N_QUOTES"):
            raise ReopeningUnsafe("unknown reopening policy")
        if type(quote_count) is not int or not 1 <= quote_count <= 1000:
            raise ReopeningUnsafe("invalid count of required qualified quotes")
        if type(runtime_epoch) is not int or runtime_epoch <= 0:
            raise ReopeningUnsafe("invalid runtime epoch")
        self.instrument = instrument
        self.policy = policy
        self.quote_count = quote_count
        self.runtime_epoch = runtime_epoch
        self._last_sequence = 0
        self._consecutive = 0

    def observe(self, *, sequence: int, quote_age_ms: int, venue_open: bool,
                unit_epoch_verified: bool, no_unknown_orders: bool,
                runtime_epoch: int) -> dict:
        if type(sequence) is not int or sequence <= self._last_sequence:
            raise ReopeningUnsafe("quote sequence must increase monotonically")
        if type(quote_age_ms) is not int or quote_age_ms < 0:
            raise ReopeningUnsafe("invalid quote age")
        if (type(venue_open) is not bool or type(unit_epoch_verified) is not bool
                or type(no_unknown_orders) is not bool or type(runtime_epoch) is not int):
            raise ReopeningUnsafe("invalid observation evidence")
        self._last_sequence = sequence
        blockers = []
        if runtime_epoch != self.runtime_epoch:
            blockers.append("STALE_RUNTIME_EPOCH")
        if not venue_open:
            blockers.append("VENUE_CLOSED")
        if quote_age_ms > 2000:
            blockers.append("STALE_QUOTE")
        if not unit_epoch_verified:
            blockers.append("UNIT_EPOCH_UNVERIFIED")
        if not no_unknown_orders:
            blockers.append("UNKNOWN_ORDER")
        if blockers:
            self._consecutive = 0
            advisory = "BLOCKED"
        else:
            self._consecutive = min(self._consecutive + 1, self.quote_count)
            if self._consecutive < self.quote_count:
                advisory = "WAIT_FOR_QUOTES"
            elif self.policy == "SELL_AT_REOPEN":
                advisory = "SELL_AT_REOPEN_CANDIDATE"
            else:
                advisory = "REEVALUATE_EXIT_CANDIDATE"
        # Even a qualified quote is NOT a certified venue-side stop.
        return {
            "instrument": self.instrument,
            "reopening_advisory": advisory,
            "blockers": blockers,
            "qualified_quotes": self._consecutive,
            "protection_state": "UNAVAILABLE" if blockers else "MANUAL_ONLY",
            "funded_authority": False,
            "executable": False,
            "order_submitted": False,
            "authority": "OFFLINE_POLICY_ONLY",
        }

    def restart(self, new_runtime_epoch: int) -> "ReopeningWindow":
        if type(new_runtime_epoch) is not int or new_runtime_epoch <= 0:
            raise ReopeningUnsafe("invalid restart epoch")
        if new_runtime_epoch == self.runtime_epoch:
            raise ReopeningUnsafe("restart must use a fresh epoch")
        fresh = ReopeningWindow(
            instrument=self.instrument, policy=self.policy,
            quote_count=self.quote_count, runtime_epoch=new_runtime_epoch,
        )
        fresh._last_sequence = self._last_sequence
        # Never carry a pre-crash fresh-quote count into a new runtime.
        return fresh
