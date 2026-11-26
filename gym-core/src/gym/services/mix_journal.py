"""Forward paper record of the passive multi-asset mix on Wallex prices; one entry per completed daily candle.

The `passive-multi-asset-mix` trial passed on stand-in prices; this records what the same weights do on Wallex's own
tokens, with fills at the live touch. Decisions use only completed daily candles; nothing is sent to the venue, and the
append-only journal cannot be re-decided afterwards. A token without a fresh quote is valued at its last close and not
traded that day; a token whose daily candles stopped more than three days ago gets no weight.
"""
import json
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from ..domain.bars import qualified
from ..domain.mix import LOOKBACK, inverse_vol_targets, needs_rebalance
from ..domain.model import UTC, iso
from ._journal_lock import append_jsonl, journal_lock
from .data_portal import DataPortal

JOURNAL = "allocation/mix-journal.jsonl"
TOKENS = {"gold": "XAUTUSDT", "silver": "SLVONUSDT", "oil": "USOONUSDT", "copper": "COPXONUSDT", "apple": "AAPLXUSDT", "btc": "BTCUSDT"}
DAY, UNITS = timedelta(days=1), Decimal("0.00000001")


def journal(root):
    path = root / JOURNAL
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def daily_returns(closes_by_token, last_day):
    """Calendar-day returns per token up to `last_day`, each token's last close carried over days without a candle."""
    first = max(min(closes) for closes in closes_by_token.values())
    days, day = [], first
    while day <= last_day:
        days.append(day)
        day += DAY
    out, prices = {}, {}
    for name, closes in closes_by_token.items():
        last, series = closes[max(d for d in closes if d <= first)], []
        for d in days:
            last = closes.get(d, last)
            series.append(last)
        prices[name] = series
        out[name] = [0.0] + [float(series[k] / series[k - 1] - 1) for k in range(1, len(series))]
    return days, out, {name: series[-1] for name, series in prices.items()}


def run_mix_day(db, root, now, *, cash=Decimal(1000), fee_rate=Decimal("0.001"), max_quote_age=timedelta(minutes=5),
                required_day=None):
    """Decide, paper-fill and append today's entry; returns it (or why nothing was recorded)."""
    path = root / JOURNAL
    with journal_lock(path):
        return _run_mix_day_locked(db, root, path, now, cash=cash, fee_rate=fee_rate, max_quote_age=max_quote_age,
                                   required_day=required_day)


def _run_mix_day_locked(db, root, path, now, *, cash, fee_rate, max_quote_age, required_day):
    portal, past = DataPortal(db), journal(root)
    if required_day is not None and any(entry["day"] == iso(required_day) for entry in past):
        return {"status": "ALREADY_DECIDED", "day": iso(required_day)}
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - 400 * DAY
    closes = {}
    for name, symbol in TOKENS.items():
        candles = [k for k in portal.venue_candles(symbol, "1d", start, now, as_of=now) if k["t"] + DAY <= now]
        if not candles:
            return {"status": "NO_CANDLES", "symbol": symbol, "at": iso(now)}
        closes[name] = {k["t"]: k["c"] for k in candles}
    last_day = max(max(c) for c in closes.values())
    if required_day is not None and last_day != required_day:
        return {"status": "MISSING_COMPLETED_DAY", "required_day": iso(required_day), "last_completed_day": iso(last_day)}
    if any(entry["day"] == iso(last_day) for entry in past):
        return {"status": "ALREADY_DECIDED", "day": iso(last_day)}
    days, returns, last_close = daily_returns(closes, last_day)
    if len(days) <= LOOKBACK:
        return {"status": "WARMING_UP", "day": iso(last_day), "days": len(days)}

    held = {k: Decimal(v) for k, v in past[-1]["units"].items()} if past else {name: Decimal(0) for name in TOKENS}
    usdt = Decimal(past[-1]["usdt"]) if past else cash
    touches, marks = {}, {}
    for name, symbol in TOKENS.items():
        tops = [t for t in portal.tops(symbol, now - max_quote_age, now + timedelta(microseconds=1)) if qualified(t)]
        touches[name] = tops[-1] if tops else None
        marks[name] = (tops[-1].bid + tops[-1].ask) / 2 if tops else last_close[name]
    equity = usdt + sum(held[n] * marks[n] for n in TOKENS)
    weights = {n: float(held[n] * marks[n] / equity) if equity > 0 else 0.0 for n in TOKENS}
    # A token whose candles stopped would show zero volatility and take most of the weight; leave it out instead.
    current = {n for n in TOKENS if max(closes[n]) >= last_day - 3 * DAY}
    wanted = {n: 0.0 for n in TOKENS} | inverse_vol_targets({n: returns[n] for n in current}, len(days))
    month_start = (last_day + DAY).day == 1
    trades = []
    if (not past or month_start) and needs_rebalance(wanted, weights):
        order = sorted(TOKENS, key=lambda n: Decimal(str(wanted[n])) * equity - held[n] * marks[n])  # sells first
        for name in order:
            top = touches[name]
            change = Decimal(str(round(wanted[name], 6))) * equity - held[name] * marks[name]
            if top is None or abs(change) < 1:  # stale quote, or under one USDT: not worth a fill
                continue
            if change < 0:
                qty = min(held[name], -change / top.bid).quantize(UNITS, ROUND_DOWN)
                held[name] -= qty
                usdt += qty * top.bid * (1 - fee_rate)
                trades.append({"token": name, "side": "SELL", "qty": str(qty), "price": str(top.bid)})
            else:
                spend = min(change, usdt)
                qty = (spend / top.ask * (1 - fee_rate)).quantize(UNITS, ROUND_DOWN)
                held[name] += qty
                usdt -= spend
                trades.append({"token": name, "side": "BUY", "qty": str(qty), "price": str(top.ask)})
    equity = usdt + sum(held[n] * marks[n] for n in TOKENS)
    entry = {"day": iso(last_day), "at": iso(now), "status": "READY", "equity": str(equity), "usdt": str(usdt),
             "units": {n: str(held[n]) for n in TOKENS}, "target_weights": {n: round(w, 6) for n, w in wanted.items()},
             "trades": trades, "stale_quotes": [TOKENS[n] for n in TOKENS if touches[n] is None],
             "stale_candles": [TOKENS[n] for n in TOKENS if n not in current]}
    append_jsonl(path, json.dumps(entry))
    return entry
