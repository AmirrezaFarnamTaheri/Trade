"""Bounded recorded-data coverage and cross-market diagnostics, never entry authority."""
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, localcontext
import re

from ..domain.bars import BarSpec, qualified
from ..domain.market_models import fields
from ..domain.model import QualityLimits, iso, parse_ts
from ..domain.strategy import digest
from ..domain.technical_features import TechnicalFeatures
from .data_portal import DataPortal
from .collector import now_utc
from .technical_analysis import _report_from_quotes, closed_quote_bars


def _window(value):
    if any(type(value[k]) is not str for k in ("from", "to", "resolution")):
        raise ValueError("window and resolution must be strings")
    start, end, spec = parse_ts(value["from"]), parse_ts(value["to"]), BarSpec(value["resolution"])
    if not start < end <= now_utc() or end - start > timedelta(days=31) or spec.resolution == "session":
        raise ValueError("need a positive fixed-bar window of at most 31 days")
    if (end - spec.bucket(start)) // spec.step > 1440:
        raise ValueError("choose a coarser resolution: at most 1440 coverage buckets")
    return start, end, spec


def _symbol(value):
    if type(value) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", value):
        raise ValueError("invalid market symbol")
    return value


@contextmanager
def _read_quotes(db, symbols, start, end):
    if db.c.in_transaction:
        raise ValueError("market diagnostics require their own read snapshot")
    db.c.execute("BEGIN")
    try:
        count = 0
        quotes = {}
        for symbol in symbols:
            count += db.c.execute("SELECT count(*) FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                                  ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
            if count > 100000:
                raise ValueError("too many observations; narrow the window or universe")
            quotes[symbol] = DataPortal(db).tops(symbol, start, end)
        yield quotes
    finally:
        db.c.rollback()


def coverage_timeline(db, request, *, store):
    fields(request, "symbol from to resolution")
    symbol = _symbol(request["symbol"])
    start, end, spec = _window(request)
    # Keep trade-receipt and quote reads in the same snapshot.
    with _read_quotes(db, [symbol], start, end) as quotes:
        tops = quotes[symbol]
        count = db.c.execute("SELECT count(*) FROM trades WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                             ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
        if count > 100000:
            raise ValueError("too many trade receipts; narrow the window")
        receipts = db.c.execute("SELECT ts_event,ts_avail FROM trades WHERE instrument_id=? AND ts_avail>=? AND ts_avail<? ORDER BY ts_avail,rowid",
                               ("wallex:" + symbol, iso(start), iso(end))).fetchall()
    groups = {}
    at = spec.bucket(start)
    while at < end:
        groups[at] = {"from": iso(max(at, start)), "to_exclusive": iso(min(at + spec.step, end)),
                      "quotes": 0, "disqualified_quotes": 0, "trade_receipts": 0, "late_trade_receipts": 0,
                      "maximum_trade_delay_seconds": None, "future_event_receipts": 0, "indicator_readiness": None}
        at += spec.step
    last_by_bucket, qualified_by_bucket = {}, {}
    for top in tops:
        key = spec.bucket(top.ts_avail)
        groups[key]["quotes"] += 1
        groups[key]["disqualified_quotes"] += int(not qualified(top))
        last_by_bucket[key] = top
        if qualified(top):
            qualified_by_bucket[key] = top
    for event, available in receipts:
        receipt, event = parse_ts(available), parse_ts(event)
        bucket = groups[spec.bucket(receipt)]
        delay = (receipt - event).total_seconds()
        bucket["trade_receipts"] += 1
        bucket["late_trade_receipts"] += int(delay > QualityLimits().stale_s)
        bucket["future_event_receipts"] += int(delay < 0)
        bucket["maximum_trade_delay_seconds"] = max(delay, bucket["maximum_trade_delay_seconds"] or delay)
    complete, _, _, _ = closed_quote_bars(tops, symbol, start, end, spec)
    bars, state, previous = {bar.start: bar for bar in complete}, TechnicalFeatures(), None
    last_qualified = None
    for key, bucket in groups.items():
        last_qualified = qualified_by_bucket.get(key, last_qualified)
        known_age = (parse_ts(bucket["to_exclusive"]) - last_qualified.ts_avail).total_seconds() if last_qualified else None
        bucket["last_known_qualified_quote_age_seconds"] = known_age
        bucket["quote_stale"] = known_age > QualityLimits().stale_s if known_age is not None else None
        top = last_by_bucket.get(key)
        age = (parse_ts(bucket["to_exclusive"]) - top.ts_avail).total_seconds() if top else None
        bucket["last_quote_age_seconds"] = age
        bucket["status"] = ("MISSING" if top is None else "DEGRADED" if bucket["disqualified_quotes"]
                            else "STALE" if age > QualityLimits().stale_s else "OBSERVED")
        bar = bars.get(key)
        if bar is None:
            state, previous = TechnicalFeatures(), None
            continue
        if previous is not None and previous.end != bar.start:
            state = TechnicalFeatures()
        values = state.update(bar.close, high=bar.high, low=bar.low)
        bucket["indicator_readiness"] = {name: value["status"] for name, value in values.items()}
        previous = bar
    result = {"symbol": symbol, "from": iso(start), "to_exclusive": iso(end), "resolution": spec.resolution,
              "store": store, "synthetic": store == "demo", "funded_authority": False,
              "observations": len(tops), "trade_receipts": len(receipts), "buckets": list(groups.values()),
              "counts": dict(Counter(row["status"] for row in groups.values())),
              "data_digest": digest([(iso(t.ts_avail), t.bid, t.ask, sorted(t.flags)) for t in tops]),
              "limitation": "Bucket observations do not prove continuous coverage within a bucket. Missing buckets reset readiness. "
                            "Trade delay is receipt minus supplied event time; late means greater than the quote-staleness threshold. "
                            "Only receipts before the exclusive end are read; no historical rows are repaired or synthesized."}
    result["report_id"] = digest(result)[:16]
    return result


def screen_markets(db, request, *, store):
    fields(request, "symbols reference quote_currency from to resolution metric")
    start, end, spec = _window(request)
    symbols = request["symbols"]
    metrics = ("momentum_percent", "relative_momentum_percent", "sma_distance_20_percent", "spread_bps", "liquidity_quote", "volatility_percent")
    if type(symbols) is not list or not 1 <= len(symbols) <= 20 or any(type(s) is not str for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("need 1..20 distinct explicit market symbols")
    for symbol in symbols:
        _symbol(symbol)
    if request["reference"] not in symbols or request["quote_currency"] not in ("USDT", "TMN") or request["metric"] not in metrics:
        raise ValueError("need a reference in the universe, one quote currency and a supported metric")
    with _read_quotes(db, symbols, start, end) as quotes:
        if any(DataPortal(db).instrument(symbol).quote != request["quote_currency"] for symbol in symbols):
            raise ValueError("all instruments must share the declared quote currency")
    rows = []
    with localcontext() as context:
        context.prec = 160
        for symbol in symbols:
            tops = quotes[symbol]
            fingerprint = digest([(iso(t.ts_avail), t.bid, t.ask, t.bid_qty, t.ask_qty, sorted(t.flags)) for t in tops])
            report = _report_from_quotes(tops, symbol, start, end, spec, store, fingerprint)
            bars, _, _, _ = closed_quote_bars(tops, symbol, start, end, spec)
            row = {"symbol": symbol, "status": report["status"], "excluded_reason": None,
                   "contiguous_bars": report["contiguous_bars"], "data_digest": fingerprint,
                   **dict.fromkeys(metrics), "last_closed_at": report["last_closed_bar"]["to"] if report["last_closed_bar"] else None}
            if report["status"] != "AVAILABLE" or report["gap_count"] or report["disqualified_intervals"]:
                row["excluded_reason"] = "GAPPED_OR_DISQUALIFIED_HISTORY" if report["gap_count"] or report["disqualified_intervals"] else report["status"]
            elif len(bars) < 2 or bars[0].start != start or bars[-1].end != end:
                row["excluded_reason"] = "INCOMPLETE_COMPARISON_WINDOW"
            else:
                closes = [bar.close for bar in bars]
                row["momentum_percent"] = str(100 * (closes[-1] / closes[0] - 1))
                row["sma_distance_20_percent"] = report["indicators"]["sma_distance_20_percent"]["value"]
                row["spread_bps"] = str(tops[-1].spread_bps)
                top = tops[-1]
                if top.bid_qty is not None and top.ask_qty is not None and top.bid_qty >= 0 and top.ask_qty >= 0:
                    row["liquidity_quote"] = str(min(top.bid * top.bid_qty, top.ask * top.ask_qty))
                returns = [b / a - 1 for a, b in zip(closes, closes[1:])]
                if len(returns) >= 2:
                    mean = sum(returns) / len(returns)
                    row["volatility_percent"] = str(100 * (sum((r - mean)**2 for r in returns) / (len(returns) - 1)).sqrt())
            rows.append(row)
        reference = next(row for row in rows if row["symbol"] == request["reference"])
        for row in rows:
            if row["momentum_percent"] is not None and reference["momentum_percent"] is not None:
                row["relative_momentum_percent"] = str(Decimal(row["momentum_percent"]) - Decimal(reference["momentum_percent"]))
            if row["excluded_reason"] is None and row[request["metric"]] is None:
                row["excluded_reason"] = "METRIC_UNAVAILABLE_OR_WARMUP"
    eligible = sorted((r for r in rows if r["excluded_reason"] is None), key=lambda r: (Decimal(r[request["metric"]]), r["symbol"]),
                      reverse=request["metric"] != "spread_bps")
    result = {"store": store, "from": iso(start), "to_exclusive": iso(end), "quote_currency": request["quote_currency"],
            "reference": request["reference"], "metric": request["metric"], "ranked": eligible,
            "excluded": [r for r in rows if r["excluded_reason"] is not None], "funded_authority": False,
            "limitation": "Explicit supplied universe, not a historical listing census. Momentum compares first/last closed MID prices. "
                          "Volatility is sample standard deviation of bar returns, unannualized. Liquidity is the smaller received top-level "
                          "quote notional, not full book depth or fill capacity. No confidence, intrinsic value or order recommendation."}
    result["report_id"] = digest(result)[:16]
    return result
