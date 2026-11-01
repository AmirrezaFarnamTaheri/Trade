"""C2 cost-aware conversion research and deterministic Fake Venue shortfall.

This unit has no live order method. All fills are explicitly synthetic; prices,
fees and balances are never posted to the Executor or treated as settled money.
The caller must retain independent venue/read-only evidence for any real audit.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from .assisted_ticket import _decimal as _exact_decimal
from .assisted_ticket import _zoned

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{5,32}\Z")


class ConversionUnsafe(ValueError):
    """Unsupported order, stale quote, conflicting fill or breached envelope."""


def _d(raw: object, name: str, *, positive: bool = True) -> Decimal:
    try:
        return _exact_decimal(raw, name, positive=positive)
    except (TypeError, ValueError) as exc:
        raise ConversionUnsafe(str(exc)) from None


def _timestamp(raw: str) -> datetime:
    try:
        return _zoned(raw)
    except (TypeError, ValueError) as exc:
        raise ConversionUnsafe(str(exc)) from None


def _fmt(value: Decimal) -> str:
    return format(value, "f")


class ConversionWorkload:
    """One offline, single-asset conversion instruction with arrival benchmark.

    No payload is ever eligible to be sent or assumed executed. No account or
    venue credential exists in this object.
    """

    def __init__(self, *, instruction_id: str, account: str, symbol: str,
                 side: str, requested_base: str, arrival_price: str,
                 fee_rate: str, started_at: str, deadline: str,
                 max_spread_bps: str, quote_budget: str):
        if type(instruction_id) is not str or not _NAME.fullmatch(instruction_id):
            raise ConversionUnsafe("invalid instruction identity")
        if type(account) is not str or (account != "main" and
            not (account.startswith("subaccount:") and _NAME.fullmatch(account))):
            raise ConversionUnsafe("unsupported account scope")
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ConversionUnsafe("unsupported instrument")
        if side not in ("BUY", "SELL"):
            raise ConversionUnsafe("only spot conversion BUY or SELL is modeled")
        started = _timestamp(started_at)
        end = _timestamp(deadline)
        if end <= started or end > started + timedelta(days=31):
            raise ConversionUnsafe("deadline must be after arrival and within 31 days")
        self.id, self.account, self.symbol, self.side = instruction_id, account, symbol, side
        self.started_at, self.deadline = started, end
        self.requested_base = _d(requested_base, "requested_base")
        self.arrival_price = _d(arrival_price, "arrival_price")
        self.fee_rate = _d(fee_rate, "fee_rate", positive=False)
        self.max_spread_bps = _d(max_spread_bps, "max_spread_bps")
        self.quote_budget = _d(quote_budget, "quote_budget")
        if self.fee_rate >= Decimal("0.1") or self.max_spread_bps > Decimal("10000"):
            raise ConversionUnsafe("unsupported fee or spread envelope")
        with localcontext() as ctx:
            ctx.prec = 128
            if side == "BUY" and (
                self.requested_base * self.arrival_price * (1 + self.fee_rate)
                > self.quote_budget
            ):
                raise ConversionUnsafe("budget insufficient for full intended purchase at arrival")
        self._fills: dict[str, tuple[Decimal, Decimal, Decimal, datetime]] = {}

    def opportunity(self, *, observed_at: str, bid: str, ask: str,
                    quote_age_ms: int, venue_open: bool) -> dict:
        observed = _timestamp(observed_at)
        buy = _d(ask, "ask")
        sell = _d(bid, "bid")
        if type(quote_age_ms) is not int or quote_age_ms < 0:
            raise ConversionUnsafe("quote age must be an exact nonnegative integer")
        if type(venue_open) is not bool:
            raise ConversionUnsafe("venue open must be a real boolean")
        with localcontext() as ctx:
            ctx.prec = 128
            spread = (buy - sell) / buy * Decimal(10000) if sell <= buy else Decimal(-1)
            blockers = []
            if not self.started_at <= observed < self.deadline:
                blockers.append("OUTSIDE_INSTRUCTION_WINDOW")
            if not venue_open:
                blockers.append("VENUE_CLOSED")
            if quote_age_ms > 2000 or sell >= buy:
                blockers.append("STALE_OR_CROSSED_QUOTE")
            if spread > self.max_spread_bps:
                blockers.append("SPREAD_ABOVE_ENVELOPE")
            remaining = self._remaining()
            if remaining <= 0:
                blockers.append("INSTRUCTION_ALREADY_SATISFIED")
            # Repeated reads are not authority to execute.
            return {
                "state": "BLOCKED" if blockers else "DRY_RUN_CANDIDATE",
                "blockers": blockers, "instruction_id": self.id,
                "remaining_base": _fmt(remaining),
                "spread_bps": _fmt(spread) if spread >= 0 else None,
                "executable": False, "funded_authority": False,
                "mode": "DRY_RUN", "verified_venue_order": False,
            }

    def _remaining(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 128
            filled = sum((q for q, _, _, _ in self._fills.values()), Decimal(0))
            return self.requested_base - filled

    def observe_fake_fill(self, fill_id: str, *, quantity: str, price: str,
                          quote_fee: str, observed_at: str) -> int:
        if type(fill_id) is not str or not _NAME.fullmatch(fill_id):
            raise ConversionUnsafe("unsafe fake fill identity")
        qty = _d(quantity, "quantity")
        px = _d(price, "price")
        fee = _d(quote_fee, "quote_fee", positive=False)
        stamp = _timestamp(observed_at)
        if not self.started_at <= stamp <= self.deadline:
            raise ConversionUnsafe("fake fill outside instruction validity")
        event = (qty, px, fee, stamp)
        if fill_id in self._fills:
            if self._fills[fill_id] != event:
                raise ConversionUnsafe("conflicting duplicate fake fill ID")
            return len(self._fills)
        if self._fills and stamp < max(row[3] for row in self._fills.values()):
            raise ConversionUnsafe("out-of-order fake fill observation")
        with localcontext() as ctx:
            ctx.prec = 128
            if qty > self._remaining():
                raise ConversionUnsafe("fake fill exceeds requested base")
            # This checks a simulated cap. A funded Executor must perform the
            # authoritative balance and reservation checks separately.
            if self.side == "BUY":
                cumulative = sum(
                    (q * p + f for q, p, f, _ in self._fills.values()),
                    Decimal(0),
                ) + qty * px + fee
                if cumulative > self.quote_budget:
                    raise ConversionUnsafe("simulated buy exceeds budget")
        self._fills[fill_id] = event
        return len(self._fills)

    def shortfall(self, *, mark_price: str, observed_at: str) -> dict:
        observed = _timestamp(observed_at)
        if observed < self.started_at:
            raise ConversionUnsafe("shortfall cannot be measured before arrival")
        mark = _d(mark_price, "mark_price")
        if self._fills and observed < max(row[3] for row in self._fills.values()):
            raise ConversionUnsafe("shortfall observation predates a fake fill")
        with localcontext() as ctx:
            ctx.prec = 128
            remaining = self._remaining()
            filled = self.requested_base - remaining
            sign = Decimal(1) if self.side == "BUY" else Decimal(-1)
            benchmark = self.requested_base * self.arrival_price
            price_effect = sum(
                (sign * q * (p - self.arrival_price)
                 for q, p, fee, _ in self._fills.values()),
                Decimal(0),
            )
            fees = sum((fee for _, _, fee, _ in self._fills.values()), Decimal(0))
            # Unfilled quantity is charged against the arrival bid/ask at the
            # reporting mark, not assumed to have executed at a favorable quote.
            leftover = sign * remaining * (mark - self.arrival_price)
            shortfall = price_effect + fees + leftover
            state = (
                "SYNTHETIC_FILLED_UNVERIFIED" if remaining == 0
                else "SYNTHETIC_DEADLINE_UNFILLED" if observed >= self.deadline
                else "SYNTHETIC_IN_PROGRESS"
            )
            return {
                "instruction_id": self.id, "symbol": self.symbol,
                "side": self.side, "account": self.account, "state": state,
                "benchmark_quote": _fmt(benchmark),
                "filled_base": _fmt(filled), "unfilled_base": _fmt(remaining),
                "fill_slippage_quote": _fmt(price_effect),
                "fees_quote": _fmt(fees),
                "unfilled_opportunity_quote": _fmt(leftover),
                "execution_shortfall_quote": _fmt(shortfall),
                "arrival_price": _fmt(self.arrival_price),
                "report_mark_price": _fmt(mark),
                "report_at": observed_at,
                "shortfall_currency": self.symbol[-4:] if self.symbol.endswith("USDT") else "UNVERIFIED_QUOTE_UNIT",
                "execution_source": "FAKE_VENUE_ONLY",
                "settlement_verified": False, "funded_authority": False,
            }
