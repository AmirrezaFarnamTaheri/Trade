"""Daily allocation paper journal: one decision per market per completed Wallex daily candle.

Decisions use only candles completed and fetched before now; fills use the freshest qualified Wallex
quote and the venue rules in force; nothing is ever sent to the venue. Each run appends to an
append-only JSONL journal, so the forward record cannot be re-decided after the fact.
"""
import json
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from ..domain.allocation import daily_target
from ..domain.bars import qualified
from ..domain.model import UTC, iso
from ..domain.sim import sellable_quantity
from .data_portal import DataPortal
from .rules import RuleService

JOURNAL = "allocation/journal.jsonl"
DAY = timedelta(days=1)


def journal(root):
    path = root / JOURNAL
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def run_day(db, root, symbols, now, *, cash=Decimal(1000), fee_rate=Decimal("0.001"),
            max_quote_age=timedelta(minutes=5), **rule):
    """Decide and paper-fill each market once for its latest completed daily candle; return new entries."""
    daily_target([], 0, **rule)  # validate even when no market has candles
    portal, rules = DataPortal(db), RuleService(db)
    past = journal(root)
    path = root / JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    history_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - 400 * DAY
    for symbol in dict.fromkeys(symbols):
        mine = [e for e in past if e["symbol"] == symbol]
        holdings = mine[-1]["holdings"] if mine else {"base": "0", "quote": str(cash)}
        base, quote_cash = Decimal(holdings["base"]), Decimal(holdings["quote"])
        candles = [k for k in portal.venue_candles(symbol, "1d", history_start, now, as_of=now) if k["t"] + DAY <= now]
        if not candles:
            out.append({"symbol": symbol, "status": "NO_CANDLES", "at": iso(now),
                        "hint": f"run: gymctl history {symbol} --resolution 1d --from 2025-01-01T00:00:00Z"})
            continue
        day = iso(candles[-1]["t"])
        if any(e.get("day") == day for e in mine):
            out.append({"symbol": symbol, "status": "ALREADY_DECIDED", "day": day})
            continue
        tops = [t for t in portal.tops(symbol, now - max_quote_age, now + timedelta(microseconds=1)) if qualified(t)]
        top = tops[-1] if tops else None
        mark = (top.bid + top.ask) / 2 if top else candles[-1]["c"]
        equity = quote_cash + base * mark
        held = float(base * mark / equity) if equity > 0 else 0.0
        decision = daily_target([float(k["c"]) for k in candles], min(max(held, 0.0), 1.0), **rule)
        entry = {"symbol": symbol, "day": day, "at": iso(now), "status": decision["status"], "decision": decision,
                 "quote": top and {"bid": str(top.bid), "ask": str(top.ask), "at": iso(top.ts_avail)}}
        if decision["status"] == "READY" and decision["trade"]:
            change = Decimal(str(round(decision["target"], 6))) * equity - base * mark
            side, intent = ("BUY", "ENTRY") if change > 0 else ("SELL", "EXIT")
            check = rules.check(portal.instrument(symbol), side, intent, now) if top else None
            if top is None:
                entry["status"] = "NO_QUOTE"  # never invent a fill; the collector must be running
            elif not check["allowed"]:
                entry["status"], entry["blockers"] = "BLOCKED", check["blockers"]
            else:
                price = top.ask if side == "BUY" else top.bid
                with localcontext() as ctx:
                    ctx.rounding = ROUND_DOWN
                    qty = min(change, quote_cash / (1 + fee_rate)) / price if side == "BUY" else min(base, -change / price)
                    qty = sellable_quantity(qty, price, portal.spec_at(symbol, now))
                if qty <= 0:
                    entry["status"], entry["blockers"] = "BLOCKED", ["BELOW_MIN_NOTIONAL"]
                else:
                    fee = qty * price * fee_rate
                    sign = 1 if side == "BUY" else -1
                    base, quote_cash = base + sign * qty, quote_cash - sign * qty * price - fee
                    entry["fill"] = {"side": side, "qty": str(qty), "price": str(price), "fee": str(fee)}
        entry["holdings"] = {"base": str(base), "quote": str(quote_cash)}
        entry["equity"] = str(quote_cash + base * mark)
        # shortcut: one writer assumed (a daily scheduled run); two concurrent runs could both append a day.
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        out.append(entry)
    return out
