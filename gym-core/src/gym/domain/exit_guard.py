"""C3 fail-closed reopening and protective-exit *advisory* policies.

These are deterministic research/Health models, not an Executor stop, a
certified venue stop order, a funded order, or a permission to arm Autopilot.
Only the restricted money authority can reassess trusted venue evidence and
issue an actual order after independent OS and venue acceptance.
"""
from __future__ import annotations

import re


class ExitPolicyUnsafe(ValueError):
    """Invalid evidence, impossible quantity or missing authority boundary."""


def _boolean(name: str, value: bool) -> None:
    if type(value) is not bool:
        raise ExitPolicyUnsafe(f"{name} must be explicitly true or false")


def _positive(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ExitPolicyUnsafe(f"{name} must be a positive exact integer")


def assess_reopening(*, venue_open: bool, snapshot_fresh: bool,
                     account_reconciled: bool, stop_method_certified: bool,
                     no_unknown_orders: bool, operator_rearmed: bool,
                     runtime_epoch: int, proposal_epoch: int) -> dict:
    """Report whether offline evidence is sufficient to request a fresh T2 check.

    Claims such as `stop_method_certified=True` are asserted by the caller;
    this module CANNOT authenticate those claims or enable trading.
    """
    checks = (
        ("venue_open", venue_open, "VENUE_CLOSED"),
        ("snapshot_fresh", snapshot_fresh, "STALE_MARKET"),
        ("account_reconciled", account_reconciled, "RECONCILIATION_MISSING"),
        ("stop_method_certified", stop_method_certified, "NO_VERIFIED_PROTECTION"),
        ("no_unknown_orders", no_unknown_orders, "UNKNOWN_ORDERS"),
        ("operator_rearmed", operator_rearmed, "NO_OPERATOR_REARM"),
    )
    blockers = []
    for name, value, reason in checks:
        _boolean(name, value)
        if not value:
            blockers.append(reason)
    _positive("runtime_epoch", runtime_epoch)
    _positive("proposal_epoch", proposal_epoch)
    if runtime_epoch != proposal_epoch:
        blockers.append("STALE_RUNTIME_EPOCH")
    return {
        "ready_for_operator_review": not blockers,
        "blockers": blockers,
        "entries_enabled": False,
        "mode_after": "DISARMED",
        "executor_authorization": False,
        "funded_authority": False,
        "authority": "OFFLINE_POLICY_ONLY",
    }


def propose_protective_exit(*, instrument: str, requested_quanta: int,
                            verified_base_quanta: int, venue_executable: bool,
                            same_instrument_inflight: bool,
                            account_entry_inflight: bool, unknown_order: bool,
                            entry_cooldown: bool, mode: str) -> dict:
    """Model a protective reduction that skips *entry-only* cooldown rules.

    A verified base quantity and instrument-specific order slot are still
    required. A competing account entry on another instrument is not a veto.
    The returned candidate is never an executable order.
    """
    if not isinstance(instrument, str) or not re.fullmatch(r"[A-Z0-9]{5,32}", instrument):
        raise ExitPolicyUnsafe("invalid venue-qualified instrument symbol")
    _positive("requested_quanta", requested_quanta)
    if type(verified_base_quanta) is not int or verified_base_quanta < 0:
        raise ExitPolicyUnsafe("verified base must be an exact nonnegative integer")
    for name, value in (
        ("venue_executable", venue_executable),
        ("same_instrument_inflight", same_instrument_inflight),
        ("account_entry_inflight", account_entry_inflight),
        ("unknown_order", unknown_order),
        ("entry_cooldown", entry_cooldown),
    ):
        _boolean(name, value)
    if mode not in {"EXIT_ONLY", "DISARMED", "HALTED"}:
        raise ExitPolicyUnsafe("unknown or armed control mode")
    blockers = []
    if mode == "HALTED":
        blockers.append("HALTED")
    elif mode != "EXIT_ONLY":
        blockers.append("NO_PREAUTHORIZED_EXIT_POLICY")
    if not venue_executable:
        blockers.append("VENUE_UNAVAILABLE")
    if same_instrument_inflight:
        blockers.append("SAME_INSTRUMENT_ORDER")
    if unknown_order:
        blockers.append("UNKNOWN_ORDER")
    if requested_quanta > verified_base_quanta:
        blockers.append("INSUFFICIENT_VERIFIED_BASE")
    return {
        "state": "BLOCKED" if blockers else "ADVISORY_EXIT_CANDIDATE",
        "blockers": blockers,
        "instrument": instrument,
        "candidate_quanta": requested_quanta if not blockers else 0,
        "entry_cooldown_applies": False,
        "account_entry_inflight_ignored": account_entry_inflight,
        "executable": False,
        "funded_authority": False,
        "authority": "OFFLINE_POLICY_ONLY",
    }
