"""C2 *offline only* exact-decimal assisted-ticket preview and review queue.

This models a quote-fee, marketable-limit BUY entry or SELL protective exit.
It does NOT construct a funded order, client_id, T1 approval, request body or
venue transport. Only the independently isolated Executor may implement those.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_UP, localcontext

_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{5,32}\Z")
_ISO = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class TicketUnsafe(ValueError):
    """The offline preview is stale, invalid or exceeds a declared envelope."""


def _decimal(raw: object, label: str, *, positive: bool = True) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, str) or not _AMOUNT.fullmatch(raw):
        raise TicketUnsafe(f"{label} requires a non-scientific exact decimal string")
    value = Decimal(raw)
    if value <= 0 if positive else value < 0:
        raise TicketUnsafe(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return value


def _zoned(raw: str) -> datetime:
    if not isinstance(raw, str) or not _ISO.fullmatch(raw):
        raise TicketUnsafe("timestamp must be a complete zoned ISO second")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise TicketUnsafe("invalid ticket timestamp") from None


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _fingerprint(ticket: dict) -> str:
    body = {key: value for key, value in ticket.items() if key != "preview_sha256"}
    raw = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def prepare_preview(*, symbol: str, side: str, intent: str,
                    quantity: str, bid: str, ask: str, worst_price: str,
                    fee_rate: str, operator_quote_cap: str,
                    available_quote: str, available_base: str, minimum_quote: str,
                    observed_at: str, expires_at: str,
                    snapshot_seq: int, quote_age_ms: int) -> dict:
    """Return an immutable-by-hash UI preview with NO permission to trade.

    Quote-fee only: this model must not be treated as valid for fee-in-base
    methods or other venue order types. A real Executor must recompute
    quantities, rules, fills and money from authenticated current evidence.
    """
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise TicketUnsafe("invalid instrument")
    if (side, intent) not in {("BUY", "ENTRY"), ("SELL", "EXIT")}:
        raise TicketUnsafe("unsupported order side or intent")
    if type(snapshot_seq) is not int or snapshot_seq <= 0:
        raise TicketUnsafe("snapshot sequence must be positive")
    if type(quote_age_ms) is not int or not 0 <= quote_age_ms <= 2000:
        raise TicketUnsafe("quotes are stale or have an invalid age")
    stamp, expiry = _zoned(observed_at), _zoned(expires_at)
    if not stamp < expiry <= stamp + timedelta(seconds=60):
        raise TicketUnsafe("preview expiry must be within sixty seconds")
    qty = _decimal(quantity, "quantity")
    best_bid, best_ask = _decimal(bid, "bid"), _decimal(ask, "ask")
    worst = _decimal(worst_price, "worst_price")
    fee = _decimal(fee_rate, "fee_rate", positive=False)
    cap = _decimal(operator_quote_cap, "operator_quote_cap")
    quote = _decimal(available_quote, "available_quote", positive=False)
    base = _decimal(available_base, "available_base", positive=False)
    min_notional = _decimal(minimum_quote, "minimum_quote")
    if best_bid >= best_ask or fee >= Decimal("0.1"):
        raise TicketUnsafe("invalid quote book or fee rate")
    # The project accepts up to 38-digit source decimals; the default
    # 28-digit context would silently round qty*price*fee. Keep enough
    # significant digits for every bounded factor and conservative ceiling.
    with localcontext() as exact:
        exact.prec = 128
        if qty * (best_ask if side == "BUY" else best_bid) < min_notional:
            raise TicketUnsafe("order below venue minimum notional")
        if side == "BUY" and worst < best_ask:
            raise TicketUnsafe("buy worst price must include current ask")
        if side == "SELL" and worst > best_bid:
            raise TicketUnsafe("sell worst price must not exceed current bid")

        expected = qty * (best_ask if side == "BUY" else best_bid)
        gross = qty * worst
        worst_fee = gross * fee
        # BUY total is the maximum possible quote spend; SELL total is minimum
        # modeled quote proceeds. It is NOT an executable price promise.
        worst_total = gross + worst_fee if side == "BUY" else gross - worst_fee
        if side == "BUY" and (worst_total > cap or worst_total > quote):
            raise TicketUnsafe("buy worst-case quote spend exceeds cap or available quote")
        if side == "SELL" and qty > base:
            raise TicketUnsafe("protective exit exceeds observed base availability")
        # Quote-fee break-even ask-side cost, rounded conservatively up to 6dp.
        breakeven = (
            (worst_total / qty / (Decimal(1) - fee)).quantize(
                Decimal("0.000001"), rounding=ROUND_UP,
            ) if side == "BUY" else None
        )
        preview = {
            "symbol": symbol, "side": side, "intent": intent,
            "quantity": _fmt(qty), "bid": _fmt(best_bid), "ask": _fmt(best_ask),
            "worst_price": _fmt(worst), "fee_rate": _fmt(fee),
            "operator_quote_cap": _fmt(cap), "available_quote": _fmt(quote),
            "available_base": _fmt(base), "minimum_quote": _fmt(min_notional),
            "observed_at": observed_at, "expires_at": expires_at,
            "snapshot_seq": snapshot_seq, "quote_age_ms": quote_age_ms,
            "estimated_gross_quote": _fmt(expected),
            "worst_gross_quote": _fmt(gross), "worst_fee_quote": _fmt(worst_fee),
            "worst_total_quote": _fmt(worst_total),
            "break_even_bid": None if breakeven is None else _fmt(breakeven),
            "mode": "DRY_RUN", "source": "OFFLINE_PREVIEW",
            "fee_assumption": "QUOTE_ONLY_UNVERIFIED",
            "client_id": None, "funded_authority": False,
            "order_submitted": False,
        }
        return {**preview, "preview_sha256": _fingerprint(preview)}


class OfflineTicketQueue:
    """In-memory review only. ACKNOWLEDGE != Tier-1 permission or order POST."""

    def __init__(self):
        self._tickets: dict[str, dict] = {}

    def add(self, ticket: dict) -> str:
        if (not isinstance(ticket, dict) or ticket.get("preview_sha256") != _fingerprint(ticket)
                or ticket.get("mode") != "DRY_RUN" or ticket.get("client_id") is not None
                or ticket.get("funded_authority") is not False
                or ticket.get("order_submitted") is not False):
            raise TicketUnsafe("offline ticket integrity or authority is invalid")
        key = ticket["preview_sha256"]
        if key in self._tickets:
            raise TicketUnsafe("duplicate preview")
        self._tickets[key] = {"preview": copy.deepcopy(ticket), "state": "PREVIEWED"}
        return key

    def review(self, preview_hash: str, decision: str, *, at: str) -> dict:
        if preview_hash not in self._tickets:
            raise TicketUnsafe("unknown ticket")
        row = self._tickets[preview_hash]
        if row["state"] != "PREVIEWED":
            raise TicketUnsafe("ticket already reviewed")
        now = _zoned(at)
        original = row["preview"]
        if now < _zoned(original["observed_at"]) or now >= _zoned(original["expires_at"]):
            raise TicketUnsafe("ticket expired or not yet valid")
        if decision not in {"ACKNOWLEDGE", "REJECT"}:
            raise TicketUnsafe("only offline acknowledgment or rejection is supported")
        row["state"] = "ACKNOWLEDGED" if decision == "ACKNOWLEDGE" else "REJECTED"
        return {"state": row["state"], "preview_sha256": preview_hash,
                "mode": "DRY_RUN", "funded_authority": False,
                "order_submitted": False, "tier1_approval": False}
