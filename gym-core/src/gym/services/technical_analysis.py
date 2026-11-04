"""Read-only indicator diagnostics over observed, closed MID quote bars."""
from datetime import timedelta
import re

from ..domain.bars import BarSpec, Consolidator, qualified
from ..domain.indicators import bar_indicator_values
from ..domain.model import QualityLimits, iso
from ..domain.periods import instant
from ..domain.strategy import digest
from .data_portal import DataPortal

MAX_OBSERVATIONS = 100000


def technical_report(db, symbol, start, end, *, resolution="15min", store="live"):
    return technical_reports(db, symbol, start, end, resolutions=[resolution], store=store)["timeframes"][resolution]


def technical_reports(db, symbol, start, end, *, resolutions, store="live"):
    start, end = instant(start), instant(end)
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid market symbol")
    if store not in ("live", "demo") or not start < end or end - start > timedelta(days=31):
        raise ValueError("need a selected store and a positive range of at most 31 days")
    if (type(resolutions) is not list or not 1 <= len(resolutions) <= 4
            or any(type(value) is not str for value in resolutions) or len(set(resolutions)) != len(resolutions)):
        raise ValueError("need 1..4 distinct fixed resolutions")
    specs = [BarSpec(resolution) for resolution in resolutions]
    if "session" in resolutions or sum((end - start) // spec.step for spec in specs) > 10000:
        raise ValueError("technicals require fixed-duration bars, at most 10000 per request")
    if db.c.in_transaction:
        raise ValueError("technicals require their own read snapshot")
    db.c.execute("BEGIN")
    try:
        count = db.c.execute("SELECT count(*) FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                             ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
        if count > MAX_OBSERVATIONS:
            raise ValueError("too many observations; narrow the technical-analysis range")
        tops = DataPortal(db).tops(symbol, start, end)
    finally:
        db.c.rollback()
    fingerprint = digest([(iso(top.ts_avail), top.bid, top.ask, sorted(top.flags)) for top in tops])
    reports = {spec.resolution: _report_from_quotes(tops, symbol, start, end, spec, store, fingerprint) for spec in specs}
    result = {"schema": "technical-timeframes/1", "symbol": symbol, "from": iso(start), "to_exclusive": iso(end),
              "store": store, "synthetic": store == "demo", "observations": len(tops), "data_digest": fingerprint,
              "funded_authority": False, "order_submitted": False, "timeframes": reports,
              "limitations": ["All timeframes share one bounded observation snapshot and cutoff; each excludes its own forming bars.",
                              "Warmup and gaps are independent per timeframe. No consensus, confidence or trading signal is inferred."]}
    result["report_id"] = digest(result)[:16]
    return result


def closed_quote_bars(tops, symbol, start, end, spec):
    """Shared closed-bar/quality cut for diagnostics and coverage views."""
    consolidator, bars, bad, last_quote = Consolidator(symbol, spec), [], set(), None
    for top in tops:
        bars += consolidator.scan(top.ts_avail)
        if qualified(top):
            bars += consolidator.update_quote(top)
            last_quote = top
        else:
            bad.add(spec.bucket(top.ts_avail))
    bars += consolidator.scan(end)
    complete = [bar for bar in bars if bar.start >= start and bar.start not in bad]
    return complete, bars, bad, last_quote


def _report_from_quotes(tops, symbol, start, end, spec, store, fingerprint):
    complete, bars, bad, last_quote = closed_quote_bars(tops, symbol, start, end, spec)
    segment, gaps, previous = [], 0, None
    for bar in complete:
        if previous is not None and previous.end != bar.start:
            gaps += 1
            segment = []
        segment.append(bar)
        previous = bar
    age = (end - last_quote.ts_avail).total_seconds() if last_quote else None
    status = ("UNAVAILABLE" if not complete else "DEGRADED" if tops and not qualified(tops[-1]) else
              "STALE" if age > QualityLimits().stale_s else "AVAILABLE")
    result = {"schema": "technical-analysis/1", "status": status, "symbol": symbol,
              "from": iso(start), "to_exclusive": iso(end), "resolution": spec.resolution,
              "price_type": "MID", "store": store, "synthetic": store == "demo",
              "authority": "PUBLIC_OBSERVATIONS", "funded_authority": False, "order_submitted": False,
              "observations": len(tops), "qualified_observations": sum(qualified(top) for top in tops),
              "closed_bars": len(complete), "contiguous_bars": len(segment), "gap_count": gaps,
              "excluded_bad_bars": sum(bar.start in bad for bar in bars),
              "disqualified_intervals": len(bad),
              "quote_age_seconds": age, "volume_available": False,
              "last_closed_bar": {"from": iso(previous.start), "to": iso(previous.end),
                                  "available_at": iso(previous.avail), "close": str(previous.close)} if previous else None,
              "indicators": bar_indicator_values(segment),
              "data_digest": fingerprint,
              "limitations": ["Descriptive closed MID quote bars only; no signal, probability or executable price.",
                              "Partial initial/forming bars and intervals with disqualified quotes are excluded. Missing bars reset warmup.",
                              "Contiguous observed bar buckets do not prove continuous coverage within each bar. No gaps or volume are synthesized.",
                              "RSI uses Wilder averages; MACD uses native first-close EMA seeding, not a third-party numerical-parity claim."]}
    result["report_id"] = digest(result)[:16]
    return result
