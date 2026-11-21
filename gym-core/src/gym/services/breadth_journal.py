"""Forward paper record of trial `breadth-trend-forward`: one entry per completed daily candle, filled at the live touch.

Decisions use completed Wallex daily candles of every USDT spot market (domain/breadth.py). Fills are paper only, at
the touch when the scheduled run fires (15:00 Tehran, the cheapest spread hour): sells at the bid first, then buys at
the ask, 0.1% fee per side, exact decimals. A position within 5% of its target is left alone; a zero target always
closes; a coin without a fresh qualified quote is not traded that day and is valued at its last close. Every coin in
the universe or the book gets one recorded decision. The journal is append-only and a day cannot be re-decided.
"""
import json
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from ..domain.bars import qualified
from ..domain.breadth import breadth_targets
from ..domain.model import UTC, iso
from ._journal_lock import append_jsonl, journal_lock
from .data_portal import DataPortal

JOURNAL = "allocation/breadth-journal.jsonl"
DAY, UNITS, HISTORY_DAYS, BAND = timedelta(days=1), Decimal("0.00000001"), 120, Decimal("0.05")


def journal(root):
    path = root / JOURNAL
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def _daily_bars(portal, db, now):
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - HISTORY_DAYS * DAY
    symbols = [r[0] for r in db.c.execute("SELECT symbol FROM instruments WHERE quote='USDT' ORDER BY symbol")]
    bars = {}
    for symbol in symbols:
        candles = [k for k in portal.venue_candles(symbol, "1d", start, now, as_of=now) if k["t"] + DAY <= now]
        if candles and candles[-1]["t"] >= now - 8 * DAY:
            bars[symbol] = candles
    if not bars:
        return None, {}
    # Histories are fetched market by market: decide on the latest day at least half the active markets completed,
    # so one market fetched early cannot set the day; cut every market there and drop the ones that stopped before.
    ends = sorted((c[-1]["t"] for c in bars.values()), reverse=True)
    last_day = ends[(len(ends) - 1) // 2]
    current = {s: [k for k in c if k["t"] <= last_day] for s, c in bars.items()}
    current = {s: c for s, c in current.items() if c and c[-1]["t"] == last_day}
    return last_day, {s: {"close": [float(k["c"]) for k in c], "high": [float(k["h"]) for k in c],
                          "low": [float(k["l"]) for k in c], "volume": [float(k["v"]) for k in c],
                          "last_close": c[-1]["c"]} for s, c in current.items()}


def _last_close(portal, symbol, now):
    candles = portal.venue_candles(symbol, "1d", now - 400 * DAY, now, as_of=now)
    return candles[-1]["c"] if candles else Decimal(0)


def run_breadth_day(db, root, now, *, cash=Decimal(1000), fee_rate=Decimal("0.001"), max_quote_age=timedelta(minutes=5)):
    """Decide, paper-fill and append today's entry; returns it (or why nothing was recorded)."""
    path = root / JOURNAL
    with journal_lock(path):
        return _run_breadth_day_locked(db, root, path, now, cash=cash, fee_rate=fee_rate, max_quote_age=max_quote_age)


def _run_breadth_day_locked(db, root, path, now, *, cash, fee_rate, max_quote_age):
    portal, past = DataPortal(db), journal(root)
    last_day, bars = _daily_bars(portal, db, now)
    if last_day is None:
        return {"status": "NO_CANDLES", "at": iso(now)}
    if any(entry["day"] == iso(last_day) for entry in past):
        return {"status": "ALREADY_DECIDED", "day": iso(last_day)}
    plan = breadth_targets(bars)
    held = {k: Decimal(v) for k, v in past[-1]["units"].items()} if past else {}
    usdt = Decimal(past[-1]["usdt"]) if past else cash
    names = sorted(set(plan["weights"]) | {s for s, q in held.items() if q > 0})
    touches, marks = {}, {}
    for s in names:
        tops = [t for t in portal.tops(s, now - max_quote_age, now + timedelta(microseconds=1)) if qualified(t)]
        touches[s] = tops[-1] if tops else None
        marks[s] = (tops[-1].bid + tops[-1].ask) / 2 if tops else bars[s]["last_close"] if s in bars else _last_close(portal, s, now)
    equity = usdt + sum(held.get(s, Decimal(0)) * marks[s] for s in names)
    decisions, trades = {}, []
    wanted = {s: Decimal(str(round(plan["weights"].get(s, 0.0), 8))) * equity for s in names}
    for s in sorted(names, key=lambda s: wanted[s] - held.get(s, Decimal(0)) * marks[s]):  # sells first
        have = held.get(s, Decimal(0)) * marks[s]
        change, top = wanted[s] - have, touches[s]
        if s not in bars and held.get(s, Decimal(0)) > 0 and top is None:
            decisions[s] = "SKIP_NO_PRICE"  # held, but no current candle or quote: keep it at its last close
        elif wanted[s] > 0 and abs(change) <= BAND * wanted[s] or abs(change) < 1:
            decisions[s] = "HOLD" if have > 0 else "CASH"
        elif top is None:
            decisions[s] = "SKIP_STALE_QUOTE"
        elif change < 0:
            qty = held[s] if wanted[s] == 0 else min(held[s], (-change / top.bid).quantize(UNITS, ROUND_DOWN))
            held[s] -= qty
            usdt += qty * top.bid * (1 - fee_rate)
            decisions[s] = "CLOSE" if held[s] == 0 else "REDUCE"
            trades.append({"symbol": s, "side": "SELL", "qty": str(qty), "price": str(top.bid)})
        else:
            spend = min(change, usdt)
            qty = (spend / top.ask * (1 - fee_rate)).quantize(UNITS, ROUND_DOWN)
            if qty == 0:
                decisions[s] = "SKIP_NO_CASH"
                continue
            decisions[s] = "OPEN" if held.get(s, Decimal(0)) == 0 else "ADD"
            held[s] = held.get(s, Decimal(0)) + qty
            usdt -= spend
            trades.append({"symbol": s, "side": "BUY", "qty": str(qty), "price": str(top.ask)})
    equity = usdt + sum(held.get(s, Decimal(0)) * marks[s] for s in names)
    entry = {"day": iso(last_day), "at": iso(now), "status": "READY", "equity": str(equity), "usdt": str(usdt),
             "units": {s: str(q) for s, q in sorted(held.items()) if q > 0}, "breadth": round(plan["breadth"], 6),
             "gate_open": plan["gate_open"], "universe": plan["universe"], "trend_long": plan["trend_long"],
             "decisions": decisions, "trades": trades}
    append_jsonl(path, json.dumps(entry))
    return entry
