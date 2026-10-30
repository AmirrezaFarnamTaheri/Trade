"""Venue rules as editable, versioned data (spec §2.8). Pure evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from .model import TEHRAN, InstrumentId, dec, iso, parse_ts

FAMILIES = {"TradingWindow", "PairSuspension", "PriceBand", "VenueQuota", "OpenOrderPolicy",
            "ProductAvailability", "GatewayRestriction", "OrderLimit", "LeverageCap", "FeeSchedule",
            "CurrencyUnit", "Custom"}
# Families that block whenever they are effective and in scope. The order-shaped ones
# (PriceBand, OrderLimit, ...) need an order to judge and stay informational until orders exist.
ALWAYS_ON = {"PairSuspension", "ProductAvailability", "GatewayRestriction", "Custom"}
CLASSES = {"VENUE", "POLICY", "SCENARIO"}
ACTIONS = {"BLOCK_ENTRY", "BLOCK_EXIT", "BLOCK_ALL", "WARN"}
STATUSES = {"VERIFIED", "REPORTED", "INFERRED", "STALE"}
SOURCES = {"announcement", "support_reply", "observed", "operator"}
SIDES = {"BUY", "SELL"}
INTENTS = {"ENTRY", "EXIT"}


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    family: str
    cls: str
    action: str
    scope: dict
    params: dict
    effective_from: datetime
    effective_until: datetime | None
    source: str
    status: str
    last_confirmed_at: datetime | None
    review_hours: float
    exit_confirmed: bool
    disabled: bool
    note: str


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def parse_rule(d: dict) -> Rule:
    """Validate a rule document. Raises ValueError; callers quarantine, never crash."""
    try:
        def pick(k, allowed):
            if d.get(k) not in allowed:
                raise ValueError(f"{k}={d.get(k)!r} not in {sorted(allowed)}")
            return d[k]

        if not isinstance(d.get("id"), str) or not d["id"]:
            raise ValueError("id required")
        scope, params = d.get("scope", {}), d.get("params", {})
        if not isinstance(scope, dict) or not isinstance(params, dict):
            raise ValueError("scope and params must be objects")
        if scope.get("side") not in (None, *SIDES):
            raise ValueError("scope.side must be BUY or SELL")
        if not isinstance(scope.get("symbols", []), list):
            raise ValueError("scope.symbols must be a list")
        r = Rule(
            id=d["id"], name=str(d.get("name", d["id"])), family=pick("family", FAMILIES),
            cls=pick("class", CLASSES), action=pick("action", ACTIONS), scope=scope, params=params,
            effective_from=parse_ts(d["effective_from"]),
            effective_until=parse_ts(d["effective_until"]) if d.get("effective_until") else None,
            source=pick("source", SOURCES), status=pick("status", STATUSES),
            last_confirmed_at=parse_ts(d["last_confirmed_at"]) if d.get("last_confirmed_at") else None,
            review_hours=float(d.get("review_hours", 24)), exit_confirmed=bool(d.get("exit_confirmed", False)),
            disabled=bool(d.get("disabled", False)), note=str(d.get("note", "")),
        )
        if r.effective_until and r.effective_until <= r.effective_from:
            raise ValueError("inverted effective interval")
        if r.family == "TradingWindow":
            closed = params.get("closed")
            if not closed or not isinstance(closed, list):
                raise ValueError("TradingWindow needs params.closed=[{from,to}]")
            for w in closed:
                if _hhmm(w["from"]) == _hhmm(w["to"]):
                    raise ValueError("empty window")
                if not set(w.get("days", [])) <= set(range(7)):
                    raise ValueError("days are weekday numbers 0=Mon..6=Sun")
        if r.family == "VenueQuota":
            if params.get("period") != "tehran_day" or params.get("side") not in SIDES or not params.get("asset"):
                raise ValueError("VenueQuota needs params {asset, side, limit, period: tehran_day}")
            if isinstance(params.get("limit"), float) or not dec(params["limit"]) > 0:
                raise ValueError("VenueQuota limit must be a positive decimal string")
        return r
    except ValueError:
        raise
    except (KeyError, TypeError, InvalidOperation, AttributeError) as e:
        raise ValueError(f"malformed rule: {type(e).__name__}: {e}") from None


def effective_status(r: Rule, now: datetime) -> str:
    if r.status == "INFERRED" and (r.last_confirmed_at or r.effective_from) + timedelta(hours=r.review_hours) < now:
        return "STALE"  # still applied to entries, flagged for review; never void
    return r.status


def may_block_exit(r: Rule, status: str) -> bool:
    if r.cls == "VENUE":
        return status in ("VERIFIED", "REPORTED")
    return r.cls == "POLICY" and r.exit_confirmed


def in_scope(r: Rule, inst: InstrumentId, side: str) -> bool:
    s = r.scope
    return (s.get("venue", inst.venue) == inst.venue
            and (not s.get("symbols") or inst.symbol in s["symbols"])
            and (not s.get("currency") or s["currency"] in (inst.base, inst.quote))
            and s.get("side", side) == side)


def windows(r: Rule, around: datetime, days_back: int = 1, days_fwd: int = 1):
    """Closed intervals [start, end) as aware datetimes, from the Tehran-local spec."""
    d0 = around.astimezone(TEHRAN).date()
    for k in range(-days_back, days_fwd + 1):
        d = d0 + timedelta(days=k)
        for w in r.params["closed"]:
            if w.get("days") and d.weekday() not in w["days"]:
                continue
            f, t = _hhmm(w["from"]), _hhmm(w["to"])
            start = datetime.combine(d, f, TEHRAN)
            end = datetime.combine(d if t > f else d + timedelta(days=1), t, TEHRAN)
            yield start, end


def tehran_day(t: datetime) -> date:
    return t.astimezone(TEHRAN).date()


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    blockers: tuple[dict, ...]
    warnings: tuple[dict, ...]
    quota_remaining: Decimal | None
    ruleset_version: int
    at: datetime


def _ref(r: Rule, status: str, why: str) -> dict:
    return {"rule_id": r.id, "name": r.name, "family": r.family, "class": r.cls, "status": status,
            "source": r.source, "action": r.action, "confirmed": iso(r.last_confirmed_at), "why": why}


def evaluate(rules: list[Rule], inst: InstrumentId, side: str, intent: str, now: datetime, *,
             live: bool = True, used: Decimal = Decimal(0), version: int = 0) -> Verdict:
    """`used` = quota consumed on the Tehran day of `now`, counted across all channels."""
    assert side in SIDES and intent in INTENTS
    blockers, warnings, remaining = [], [], None
    for r in rules:
        if r.disabled or (r.cls == "SCENARIO" and live) or not in_scope(r, inst, side):
            continue
        if now < r.effective_from or (r.effective_until and now >= r.effective_until):
            continue
        status = effective_status(r, now)
        if r.family == "TradingWindow":
            active = any(s <= now < e for s, e in windows(r, now))
            why = "closed window"
        elif r.family == "VenueQuota":
            if not (inst.base == r.params["asset"] and side == r.params["side"]):
                continue
            left = dec(r.params["limit"]) - used
            remaining = left if remaining is None else min(remaining, left)
            active, why = left <= 0, f"quota exhausted ({used}/{r.params['limit']} {r.params['asset']})"
        else:
            active, why = r.family in ALWAYS_ON, r.family.lower()
        if not active:
            continue
        blocks = r.action == "BLOCK_ALL" or r.action == ("BLOCK_ENTRY" if intent == "ENTRY" else "BLOCK_EXIT")
        if r.action == "WARN":
            warnings.append(_ref(r, status, why))
        elif blocks and (intent == "ENTRY" or may_block_exit(r, status)):
            blockers.append(_ref(r, status, why))
        elif blocks:
            warnings.append(_ref(r, status, why + "; cannot block an exit at this class/status"))
    return Verdict(not blockers, tuple(blockers), tuple(warnings), remaining, version, now)


def next_change(rules: list[Rule], inst: InstrumentId, side: str, intent: str, now: datetime, *,
                horizon_days: int = 7, used: Decimal = Decimal(0), **kw) -> datetime | None:
    """First instant after `now` where the verdict flips between allowed and blocked."""
    cur = evaluate(rules, inst, side, intent, now, used=used, **kw).allowed
    limit = now + timedelta(days=horizon_days)
    cand = set()
    for r in rules:
        if not in_scope(r, inst, side):
            continue
        cand.update(t for t in (r.effective_from, r.effective_until) if t)
        if r.family == "TradingWindow":
            for s, e in windows(r, now, 1, horizon_days):
                cand.update((s, e))
        if r.family == "VenueQuota":
            d = tehran_day(now)
            cand.update(datetime.combine(d + timedelta(days=k), time(0), TEHRAN) for k in range(1, horizon_days + 1))
    for t in sorted(c for c in cand if now < c <= limit):
        u = used if tehran_day(t) == tehran_day(now) else Decimal(0)
        if evaluate(rules, inst, side, intent, t, used=u, **kw).allowed != cur:
            return t
    return None


PRESETS: dict[str, list[dict]] = {
    "usdt-irt-october-2026": [
        {"id": "wallex-usdttmn-closure-2100-0900", "name": "USDT/IRT closed 21:00-09:00 Tehran",
         "family": "TradingWindow", "class": "VENUE", "action": "BLOCK_ALL",
         "scope": {"venue": "wallex", "symbols": ["USDTTMN"]}, "params": {"closed": [{"from": "21:00", "to": "09:00"}]},
         "effective_from": "2026-09-30T00:00:00+03:30", "effective_until": "2026-10-18T00:00:00+03:30",
         "source": "announcement", "status": "REPORTED", "last_confirmed_at": "2026-09-30T12:00:00+03:30",
         "note": "Central bank directive via Wallex; open orders kept through closure, liquidation paused. Proof X19, X21."},
        {"id": "wallex-usdttmn-closure-2330-1130", "name": "USDT/IRT closed 23:30-11:30 Tehran",
         "family": "TradingWindow", "class": "VENUE", "action": "BLOCK_ALL",
         "scope": {"venue": "wallex", "symbols": ["USDTTMN"]}, "params": {"closed": [{"from": "23:30", "to": "11:30"}]},
         "effective_from": "2026-10-18T00:00:00+03:30", "source": "announcement", "status": "REPORTED",
         "last_confirmed_at": "2026-10-18T12:00:00+03:30",
         "note": "From 18 Oct 2026 (26 Mehr 1405) until further notice; liquidation paused during closure. Proof X20."},
        {"id": "wallex-usdt-daily-buy-cap", "name": "2,000 USDT bought per user per Tehran day",
         "family": "VenueQuota", "class": "VENUE", "action": "BLOCK_ALL", "scope": {"venue": "wallex"},
         "params": {"asset": "USDT", "side": "BUY", "limit": "2000", "period": "tehran_day"},
         "effective_from": "2026-09-30T00:00:00+03:30", "source": "announcement", "status": "REPORTED",
         "last_confirmed_at": "2026-10-18T12:00:00+03:30",
         "note": "Counts purchases from every channel, including manual app trades. Proof X19, X20."},
    ],
}
