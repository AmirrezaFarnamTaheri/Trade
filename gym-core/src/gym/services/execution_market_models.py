"""Read-only, bounded point-in-time market-cost calibration from archived receipts."""
import json
import re
import sqlite3
from collections import deque
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from ..domain.bars import qualified
from ..domain.execution_costs import fit_square_root_impact
from ..domain.market_models import fields, instant
from ..domain.model import TEHRAN, iso, parse_ts
from ..domain.strategy import digest
from ..domain.volatility import ParkinsonEWMA
from .collector import now_utc
from .data_portal import DataPortal
from .market_statistics import spread_report


def _hourly_fees(root: Path, symbol, start, end):
    """Use authenticated, immutable local GET receipts, never a default as evidence."""
    path = root / "external_journal.db"
    if path.is_symlink() or not path.is_file():
        return {}
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        raw = conn.execute(
            "SELECT observed_at,snapshot_json FROM external_account_snapshots "
            "WHERE account_id='main' ORDER BY sequence DESC LIMIT 10000").fetchall()
    except (sqlite3.Error, OSError):
        return {}
    finally:
        if conn is not None:
            conn.close()
    fees = {}
    for stamp, encoded in raw:
        try:
            at = parse_ts(stamp)
            if not start <= at < end:
                continue
            snapshot = json.loads(encoded)
            if snapshot.get("transport") not in ("INTERACTIVE_USER_GET", "EXECUTOR_SERVICE_WINHTTP"):
                continue
            rates = (snapshot.get("fee_rates") or {}).get(symbol)
            if type(rates) is not dict:
                continue
            maker, taker = Decimal(rates["maker"]), Decimal(rates["taker"])
            if any(not r.is_finite() or not 0 <= r < 1 for r in (maker, taker)):
                continue
            hour = str(at.astimezone(TEHRAN).hour)
            if hour not in fees or at > fees[hour][0]:
                fees[hour] = (at, maker, taker)
        except (ValueError, TypeError, KeyError, ArithmeticError, json.JSONDecodeError):
            continue
    return fees


def _public_trade_samples(db, symbol, start, end):
    """Join earlier public quotes to later trade receipts using the availability clock."""
    from ..domain.model import BookTop

    boot = start - timedelta(hours=2)
    instrument_id = "wallex:" + symbol
    rows = db.c.execute(
        "SELECT ts_avail,ts_event,price,qty,aggressor FROM trades "
        "WHERE instrument_id=? AND ts_avail>=? AND ts_avail<? "
        "ORDER BY ts_avail,rowid LIMIT 100001",
        (instrument_id, iso(boot), iso(end))).fetchall()
    if len(rows) > 100000:
        raise ValueError("impact print scan exceeds 100000 receipts; narrow the window")
    top_count = db.c.execute(
        "SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
        "AND ts_avail>=? AND ts_avail<? LIMIT 100001)",
        (instrument_id, iso(boot), iso(end))).fetchone()[0]
    if top_count > 100000:
        raise ValueError("impact quote scan exceeds 100000 receipts; narrow the window")
    quotes = DataPortal(db).tops(symbol, boot, end)
    qindex, last = 0, None
    bucket = high = low = last_closed_bucket = None
    estimator = ParkinsonEWMA()
    volume_queue = deque()
    volume = Decimal(0)
    observations, excluded = [], 0

    def close_bucket():
        """Finalize the active closed quote-minute once, retaining its start."""
        nonlocal bucket, high, low, last_closed_bucket
        if bucket is None:
            return
        estimator.update(high, low)
        last_closed_bucket = bucket
        bucket = high = low = None

    def observe(quote):
        """Consume a qualified available quote, resetting on discontinuous minutes."""
        nonlocal last, bucket, high, low, estimator, last_closed_bucket
        if not isinstance(quote, BookTop) or not qualified(quote):
            return
        at = quote.ts_avail.replace(second=0, microsecond=0)
        mid = (quote.bid + quote.ask) / 2
        if bucket is not None and at != bucket:
            close_bucket()
        if bucket is None:
            # A trade may have already closed the previous minute. Track that
            # close independently so a later quote cannot carry EWMA over a gap.
            if last_closed_bucket is not None and at - last_closed_bucket != timedelta(minutes=1):
                estimator = ParkinsonEWMA()
                last_closed_bucket = None
            bucket, high, low = at, mid, mid
        else:
            high, low = max(high, mid), min(low, mid)
        last = quote

    for avail, event, raw_price, raw_qty, side in rows:
        try:
            at = parse_ts(avail)
            if parse_ts(event) > at:
                raise ValueError("event is unavailable at receipt")
            price, qty = Decimal(raw_price), Decimal(raw_qty)
            if (not price.is_finite() or not qty.is_finite() or price <= 0 or qty <= 0
                    or side not in ("BUY", "SELL")):
                raise ValueError("invalid public trade print")
        except (ValueError, TypeError, ArithmeticError):
            excluded += 1
            continue
        while qindex < len(quotes) and quotes[qindex].ts_avail < at:
            observe(quotes[qindex])
            qindex += 1
        if bucket is not None and at >= bucket + timedelta(minutes=1):
            close_bucket()
        while volume_queue and volume_queue[0][0] <= at - timedelta(hours=1):
            _, old_qty = volume_queue.popleft()
            volume -= old_qty
        if (start <= at < end and last is not None and at - last.ts_avail <= timedelta(seconds=120)
                and estimator.count >= 10 and estimator.variance > 0 and 0 < qty <= volume):
            mid = (last.bid + last.ask) / 2
            observed_cost = ((price - mid) if side == "BUY" else (mid - price)) / mid * 10000
            if Decimal(-200) <= observed_cost <= Decimal(2000):
                observations.append({"spread_bps": str((last.ask - last.bid) / mid * 10000),
                                     "volatility_bps": str(estimator.variance.sqrt() * 10000),
                                     "quantity": str(qty), "volume_base": str(volume),
                                     "observed_cost_bps": str(observed_cost)})
            else:
                excluded += 1
        elif start <= at < end:
            excluded += 1
        volume_queue.append((at, qty))
        volume += qty
        if len(observations) > 10000:
            raise ValueError("impact model exceeds 10000 samples; narrow the window")
    return observations, excluded


def market_execution_model_report(root, db, request, *, store):
    """Research a dated, opt-in profile; no fee/fill/impact assumptions apply automatically."""
    fields(request, "symbol from to")
    symbol = request["symbol"]
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid execution-model symbol")
    start, end = instant(request["from"]), instant(request["to"])
    if not start < end <= now_utc() or end - start > timedelta(days=31):
        raise ValueError("execution-model window must be historical and at most 31 days")
    # A long-lived read snapshot prevents quote/trade feeds from changing mid-fit.
    db.c.execute("BEGIN")
    try:
        samples, excluded = _public_trade_samples(db, symbol, start, end)
        spread = spread_report(db, start, end, symbol=symbol, store=store)
    finally:
        db.c.rollback()
    fee_hours = _hourly_fees(Path(root), symbol, start, end) if store == "live" else {}
    hours = {}
    for group in spread["groups"]:
        if group["samples"] < 20:
            continue
        hour = str(group["tehran_hour"])
        fee = fee_hours.get(hour)
        hours[hour] = {"spread_bps": group["spread_bps"]["p95"],
                       "observed_median_spread_bps": group["spread_bps"]["median"],
                       "quote_samples": group["samples"],
                       "taker_fee_rate": str(fee[2]) if fee else None,
                       "maker_fee_rate": str(fee[1]) if fee else None,
                       "fee_observed_at": iso(fee[0]) if fee else None}
    hourly = {"schema": "hourly-costs/1", "symbol": symbol,
              "trained_until": iso(end), "timezone": "Asia/Tehran",
              "spread_source": "PUBLIC_QUOTE_P95_BY_TEHRAN_HOUR",
              "fee_source": "READ_ONLY_ACCOUNT_GET_WHEN_OBSERVED",
              "data_digest": spread["data_digest"], "hours": hours}
    impact = fit_square_root_impact(symbol, samples, trained_until=end)
    # Synthetic demonstration data is useful for model tests, never for live calibration.
    profiles = {}
    if store == "live":
        if impact["status"] == "AVAILABLE":
            profiles["impact_models"] = {symbol: impact}
        if hours:
            profiles["hourly_costs"] = {symbol: hourly}
    out = {"schema": "execution-market-model/1", "symbol": symbol, "store": store,
           "synthetic": store == "demo", "from": iso(start), "to_exclusive": iso(end),
           "impact": impact, "hourly": hourly, "excluded_prints": excluded,
           "sample_count": len(samples), "cost_models": profiles,
           "automatic_application": False, "funded_authority": False,
           "limits": ["Public prints are proxies and must not be mislabelled independent funded-order fills.",
                      "Spread estimates are observation weighted. Blank hourly fees are unknown, never zero.",
                      "Only source receipts strictly before the declared window end are eligible.",
                      "Model fits use chronological 80/20 split; holdout is not used to select coefficients.",
                      "Operator must opt in explicitly and cannot use a profile before its training cutoff."]}
    out["report_id"] = digest(out)[:16]
    return out
