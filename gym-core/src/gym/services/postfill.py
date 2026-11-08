"""Retrospective public-quote markouts for simulated fills; never order authority."""
import re
from bisect import bisect_left, bisect_right
from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise

from ..domain.bars import qualified
from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

HORIZONS_SECONDS = (60, 300, 1800)
MAX_ROWS = 5000
MAX_QUOTES = 100000


def post_fill_checks(orders, tops, *, symbol, strategy, order_type, cutoff,
                     max_delay_seconds=120):
    """Measure signed 1/5/30-minute paper markouts without invented missing marks.

    The result is retrospective analysis. A fitted cost profile is descriptive
    until applied only to a later disjoint replay, never the same input window.
    """
    if (type(orders) is not list or len(orders) > MAX_ROWS
            or type(tops) is not list or len(tops) > MAX_QUOTES
            or type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
            or type(strategy) is not str or not 1 <= len(strategy) <= 80
            or order_type not in ("market", "limit")
            or cutoff.tzinfo is None
            or type(max_delay_seconds) is not int or not 0 <= max_delay_seconds <= 120):
        raise ValueError("invalid postfill paper markout request")
    if any(top.symbol != symbol or top.ts_avail > cutoff for top in tops):
        raise ValueError("postfill quotes must be known by the report cutoff")
    if any(a.ts_avail > b.ts_avail for a, b in pairwise(tops)):
        raise ValueError("postfill quotes must be chronological")
    rows, marks, midpoint_marks = [], {str(k): [] for k in HORIZONS_SECONDS}, {str(k): [] for k in HORIZONS_SECONDS}
    times = [top.ts_avail for top in tops]
    latest_mark = None
    with localcontext() as context:
        context.prec = 70
        for order in orders:
            if type(order) is not dict:
                raise ValueError("invalid postfill order")
            if order.get("status") != "FILLED":
                continue
            if order.get("side") not in ("BUY", "SELL") or type(order.get("ref")) is not str:
                raise ValueError("invalid filled paper order")
            qty, price = Decimal(order["qty"]), Decimal(order["price"])
            if not qty.is_finite() or qty <= 0 or not price.is_finite() or price <= 0:
                raise ValueError("invalid paper fill economics")
            at = parse_ts(order["fill_time"])
            if at > cutoff:
                raise ValueError("postfill order is beyond the report cutoff")
            # A fill-time spread is already present in the simulated price.
            # Train an additional adverse-move cost only against a qualified
            # midpoint observed no later than that fill.
            prior_index = bisect_right(times, at) - 1
            prior = tops[prior_index] if prior_index >= 0 else None
            if (prior is None or not qualified(prior) or "CLOSED" in prior.flags
                    or at - prior.ts_avail > timedelta(seconds=max_delay_seconds)):
                prior = None
            fill_midpoint = (prior.bid + prior.ask) / 2 if prior is not None else None
            out = {"ref": order["ref"], "side": order["side"], "fill_time": iso(at),
                   "fill_price": str(price), "quantity": str(qty),
                   "fill_midpoint_at": iso(prior.ts_avail) if prior is not None else None,
                   "markouts_bps": {}, "midpoint_markouts_bps": {},
                   "mark_available_at": {}}
            for h in HORIZONS_SECONDS:
                target = at + timedelta(seconds=h)
                index = bisect_left(times, target)
                quote = tops[index] if target <= cutoff and index < len(tops) else None
                if (quote is None or not qualified(quote) or "CLOSED" in quote.flags
                        or quote.ts_avail - target > timedelta(seconds=max_delay_seconds)):
                    out["markouts_bps"][str(h)] = None
                    out["midpoint_markouts_bps"][str(h)] = None
                    out["mark_available_at"][str(h)] = None
                    continue
                mid = (quote.bid + quote.ask) / 2
                markout = ((mid - price) / price if order["side"] == "BUY"
                           else (price - mid) / price) * 10000
                out["markouts_bps"][str(h)] = str(+markout)
                out["mark_available_at"][str(h)] = iso(quote.ts_avail)
                marks[str(h)].append(markout)
                if fill_midpoint is not None:
                    midpoint_markout = ((mid - fill_midpoint) / fill_midpoint
                                       if order["side"] == "BUY" else
                                       (fill_midpoint - mid) / fill_midpoint) * 10000
                    out["midpoint_markouts_bps"][str(h)] = str(+midpoint_markout)
                    midpoint_marks[str(h)].append(midpoint_markout)
                else:
                    out["midpoint_markouts_bps"][str(h)] = None
                if latest_mark is None or latest_mark < quote.ts_avail:
                    latest_mark = quote.ts_avail
            rows.append(out)
        horizons = {}
        for h in HORIZONS_SECONDS:
            sample = marks[str(h)]
            average = sum(sample, Decimal(0)) / len(sample) if sample else None
            adverse = (sum((max(Decimal(0), -x) for x in sample), Decimal(0)) / len(sample)
                       if sample else None)
            midpoint_sample = midpoint_marks[str(h)]
            midpoint_adverse = (sum((max(Decimal(0), -x) for x in midpoint_sample), Decimal(0))
                                / len(midpoint_sample) if midpoint_sample else None)
            horizons[str(h)] = {
                "available": len(sample), "missing": len(rows) - len(sample),
                "mean_signed_bps": str(+average) if average is not None else None,
                "mean_adverse_bps": str(+adverse) if adverse is not None else None,
                "midpoint_baseline_available": len(midpoint_sample),
                "midpoint_baseline_missing": len(rows) - len(midpoint_sample),
                "mean_adverse_ex_spread_bps": (str(+midpoint_adverse)
                                              if midpoint_adverse is not None else None)}
        profile = None
        if latest_mark is not None and len(midpoint_marks["300"]) >= 30:
            penalty = min(Decimal(200), Decimal(horizons["300"]["mean_adverse_ex_spread_bps"]))
            profile = {symbol: {"schema": "postfill-adverse/1", "symbol": symbol,
                                "trained_until": iso(latest_mark),
                                "penalty_bps": str(+penalty),
                                "sample_count": len(midpoint_marks["300"]),
                                "source": "PAPER_MARKOUT_DIAGNOSTIC"}}
        result = {
            "schema": "paper-postfill-markouts/1", "symbol": symbol, "strategy": strategy,
            "order_type": order_type, "cutoff": iso(cutoff), "filled_orders": len(rows),
            "rows": rows, "groups": [{"strategy": strategy, "order_type": order_type,
                                     "horizons": horizons}], "postfill_cost_profile": profile,
            "funded_authority": False, "order_submitted": False,
            "limitations": [
                "These fills are simulated, not authenticated venue order executions.",
                "A future quote is used only for retrospective post-fill diagnosis, never to change an earlier decision.",
                "Unavailable or unqualified future quotes stay missing; no price interpolation.",
                "A 5-minute adverse cost profile needs 30 qualified fill-time midpoints and enters only later paper replays.",
                "Markouts omit custody, cross-venue transport, real settlement and other unobserved costs.",
            ],
        }
        result["report_id"] = digest(result)[:16]
        return result
