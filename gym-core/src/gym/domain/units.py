"""IRT unit discontinuity (spec §2.6): a redenomination rescales every IRT price by 10^k at once,
while prices against USDT stay continuous. Pure detection; the collector records and acts on it."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .model import iso

TOLERANCE = Decimal("0.15")
MAX_EXPONENT = 4


def rescale_exponent(ratio: Decimal) -> int | None:
    """k when `ratio` is within 15% of 10**k for 1 <= |k| <= 4, else None."""
    for k in range(-MAX_EXPONENT, MAX_EXPONENT + 1):
        if k and abs(ratio / Decimal(10) ** k - 1) <= TOLERANCE:
            return k
    return None


class UnitWatch:
    """Tracks the IRT-per-USDT rate implied by each asset: mid(ASSET/IRT) / mid(ASSET/USDT); USDT/IRT itself
    counts as one asset. A market move cancels in that ratio; a unit change does not. A discontinuity needs
    the same exponent on `min_assets` assets (or on every tracked asset when fewer are tracked)."""

    def __init__(self, quote: str = "TMN", reference: str = "USDT", min_assets: int = 2):
        self.quote, self.reference, self.min_assets = quote, reference, min_assets
        self.rates: dict[str, Decimal] = {}  # last accepted implied rate per asset

    def implied(self, mids: dict[tuple[str, str], Decimal]) -> dict[str, Decimal]:
        out = {}
        for (base, quote), mid in mids.items():
            if quote != self.quote:
                continue
            if base == self.reference:
                out[base] = mid
            elif (base, self.reference) in mids:
                out[base] = mid / mids[base, self.reference]
        return out

    def observe(self, mids: dict[tuple[str, str], Decimal]) -> dict | None:
        """Feed current qualified mids keyed (base, quote). Returns the event once per discontinuity."""
        rates = self.implied(mids)
        jumps = {a: rescale_exponent(r / self.rates[a]) for a, r in rates.items() if a in self.rates}
        for a, r in rates.items():
            if jumps.get(a) is None:
                self.rates[a] = r  # continuous: follow the market; a lone jump keeps its old reference
        moved = {a: k for a, k in jumps.items() if k is not None}
        if not moved:
            return None
        exponent = max(set(moved.values()), key=list(moved.values()).count)
        agreeing = sorted(a for a, k in moved.items() if k == exponent)
        if len(agreeing) < min(self.min_assets, len(self.rates)):
            return None
        event = {"currency": self.quote, "exponent": exponent, "assets": agreeing,
                 "ratios": {a: str(rates[a] / self.rates[a]) for a in agreeing}}
        for a in agreeing:
            self.rates[a] = rates[a]
        return event


def unit_freeze_rule(event: dict, now: datetime) -> dict:
    """An INFERRED venue rule: blocks new entries in the currency, never an exit, until the operator reviews it."""
    stamp = iso(now).replace(":", "").replace("-", "").replace(".", "")
    return {
        "id": f"unit-discontinuity-{event['currency'].lower()}-{stamp}", "name": f"{event['currency']} unit discontinuity x10^{event['exponent']}",
        "family": "CurrencyUnit", "class": "VENUE", "action": "BLOCK_ENTRY",
        "scope": {"venue": "wallex", "currency": event["currency"]}, "params": {"unit_discontinuity": event},
        "effective_from": iso(now), "source": "observed", "status": "INFERRED", "last_confirmed_at": iso(now),
        "note": "Detected automatically: every IRT price jumped by a power of ten while USDT prices stayed continuous. "
                "Confirm the redenomination, open a new CurrencyUnit epoch, then disable this rule.",
    }
