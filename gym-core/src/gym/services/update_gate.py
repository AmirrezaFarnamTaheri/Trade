"""B3 pure update admission policy. It executes NO service update.

Only an independently verified protection plan or a separately recorded
operator outage acceptance allows an update with open positions. Neither
means an already active software stop will remain active during the update.
"""
from __future__ import annotations


class UpdateUnsafe(ValueError):
    pass


def assess_update(*, open_positions: int, unknown_orders: int,
                  alternative_protection: bool, accepted_outage: bool,
                  ledger_integrity_ok: bool = True) -> dict:
    for name, value in (("open_positions", open_positions), ("unknown_orders", unknown_orders)):
        if type(value) is not int or value < 0:
            raise TypeError(f"{name} must be a nonnegative integer")
    for name, value in (("alternative_protection", alternative_protection),
                        ("accepted_outage", accepted_outage),
                        ("ledger_integrity_ok", ledger_integrity_ok)):
        if type(value) is not bool:
            raise TypeError(f"{name} requires explicit boolean evidence")
    if not ledger_integrity_ok:
        raise UpdateUnsafe("unsafe update: authoritative ledger integrity not verified")
    if unknown_orders != 0:
        raise UpdateUnsafe("unsafe update: unresolved order or reservation")
    if open_positions and not (alternative_protection or accepted_outage):
        raise UpdateUnsafe("unsafe update: open positions lack alternative protection or accepted outage")
    protection = (
        "NONE" if open_positions == 0 else
        "INDEPENDENT_VERIFIED" if alternative_protection else
        "UNPROTECTED_ACCEPTED"
    )
    # This is an *admission recommendation*. The actual service updater must
    # re-read authoritative state under its own lock, journal the T2 consent,
    # refuse later activity, then restart DISARMED and reconcile.
    return {
        "allowed": True, "mode_after": "DISARMED",
        "protection": protection, "authority": "OFFLINE_POLICY_ONLY",
    }
