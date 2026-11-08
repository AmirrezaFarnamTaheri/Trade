"""Causal, bounded quote diagnostics for TMN premium and lead-lag hypotheses.

This is descriptive paper research, not a transferable arbitrage or execution signal.
"""
from bisect import bisect_left
from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise

from ..domain.bars import BarSpec, qualified
from ..domain.market_models import rate
from ..domain.model import iso
from ..domain.strategy import digest

MAX_QUOTES = 100000
MAX_SAMPLES = 1440


def analyze_quotes(base, books, start, end, *, resolution, max_age_seconds,
                   max_skew_seconds, fee_rate, store):
    if store not in ("live", "demo"):
        raise ValueError("invalid store")
    if type(base) is not str or not base.isalnum() or not base.isupper() or not 2 <= len(base) <= 16 or base == "USDT":
        raise ValueError("premium needs an explicit non-USDT uppercase base")
    fee = rate(str(fee_rate))
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
        raise ValueError("invalid maximum quote age")
    if type(max_skew_seconds) is not int or not 0 <= max_skew_seconds <= max_age_seconds:
        raise ValueError("invalid quote skew")
    spec = BarSpec(resolution)
    if resolution == "session" or not start < end or end - start > timedelta(days=31):
        raise ValueError("premium requires a bounded fixed-bar window")
    stamps = []
    stamp = spec.bucket(start) + spec.step
    while stamp <= end:
        stamps.append(stamp)
        if len(stamps) > MAX_SAMPLES:
            raise ValueError("too many evaluation closes")
        stamp += spec.step
    if not stamps:
        raise ValueError("no complete evaluation closes")
    symbols = (base + "TMN", base + "USDT", "USDTTMN")
    histories, times = {}, {}
    for symbol in symbols:
        rows = books.get(symbol, ())
        if len(rows) > MAX_QUOTES:
            raise ValueError("too many quote observations")
        if any(top.symbol != symbol or not start <= top.ts_avail < end for top in rows):
            raise ValueError("quote symbol or window mismatch")
        if any(a.ts_avail > b.ts_avail for a, b in pairwise(rows)):
            raise ValueError("quotes must follow availability order")
        histories[symbol] = rows
        times[symbol] = [top.ts_avail for top in rows]
    samples, reasons = [], {}
    with localcontext() as context:
        context.prec = 80
        for close in stamps:
            observed = [histories[s][bisect_left(times[s], close) - 1]
                        if bisect_left(times[s], close) else None for s in symbols]
            reason = None
            if any(top is None or not qualified(top) or "CLOSED" in top.flags for top in observed):
                reason = "UNQUALIFIED_OR_MISSING"
            elif any((close - top.ts_avail).total_seconds() > max_age_seconds for top in observed):
                reason = "STALE_QUOTE"
            elif (max(top.ts_avail for top in observed) - min(top.ts_avail for top in observed)).total_seconds() > max_skew_seconds:
                reason = "SKEWED_QUOTE"
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            primary, asset_usdt, usdt_tmn = observed
            cross_bid = asset_usdt.bid * usdt_tmn.bid
            cross_ask = asset_usdt.ask * usdt_tmn.ask
            if cross_bid <= 0 or cross_ask <= 0:
                reasons["INVALID_CONVERSION"] = reasons.get("INVALID_CONVERSION", 0) + 1
                continue
            # Buying at the primary ask and selling through two observed conversion bids.
            net_bid = cross_bid * (1 - fee) ** 3
            # Reversing direction pays the two conversion asks and three modeled fees.
            reverse_cost = cross_ask / (1 - fee) ** 3
            samples.append({"at": iso(close), "primary_observed_at": iso(primary.ts_avail),
                            "asset_usdt_observed_at": iso(asset_usdt.ts_avail),
                            "usdt_tmn_observed_at": iso(usdt_tmn.ts_avail),
                            "primary_bid": str(primary.bid), "primary_ask": str(primary.ask),
                            "converted_bid": str(cross_bid), "converted_ask": str(cross_ask),
                            "premium_bps": str((primary.bid / cross_ask - 1) * 10000),
                            "cross_sale_net_bps": str((net_bid / primary.ask - 1) * 10000),
                            "reverse_net_bps": str((primary.bid / reverse_cost - 1) * 10000)})
    result = {"schema": "premium-quotes/1", "base": base, "store": store, "synthetic": store == "demo",
              "resolution": resolution, "from": iso(start), "to_exclusive": iso(end),
              "fee_rate": str(fee), "max_quote_age_seconds": max_age_seconds,
              "max_quote_skew_seconds": max_skew_seconds, "samples": samples,
              "coverage": {"closes": len(stamps), "eligible": len(samples),
                           "excluded": len(stamps) - len(samples), "reasons": reasons},
              "data_digests": {symbol: digest([(iso(q.ts_avail), q.bid, q.ask, sorted(q.flags))
                                               for q in histories[symbol]]) for symbol in symbols},
              "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
              "held_out": False, "established_edge": False,
              "limitations": ["Availability-time aligned quotes strictly before each fixed-bar close, never backfilled.",
                              "Best displayed quotes, not guaranteed cross-market fillable depth, venue access or transfer settlement.",
                              "Three modeled fee legs; excludes transfer, funding, withdrawal and market-closure costs.",
                              "Exploratory diagnostic; independent future evaluation and measured executable economics remain required."]}
    result["report_id"] = digest(result)[:16]
    return result


def analyze_lead_lag(primary, leader, start, end, *, resolution, max_age_seconds,
                     max_skew_seconds, min_overlap, store, max_delay_bars=1):
    """Previous closed interval's leader return versus the next follower return."""
    if (store not in ("live", "demo") or primary is leader or
            (primary and leader and primary[0].symbol == leader[0].symbol)):
        raise ValueError("need distinct selected market observations")
    if type(min_overlap) is not int or not 2 <= min_overlap <= MAX_SAMPLES:
        raise ValueError("invalid minimum overlap")
    if type(max_delay_bars) is not int or not 1 <= max_delay_bars <= 12:
        raise ValueError("lead-lag scan needs 1..12 prior delays")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
        raise ValueError("invalid quote age")
    if type(max_skew_seconds) is not int or not 0 <= max_skew_seconds <= max_age_seconds:
        raise ValueError("invalid quote skew")
    spec = BarSpec(resolution)
    if resolution == "session" or not start < end or end - start > timedelta(days=31):
        raise ValueError("need bounded fixed-bar closes")
    if len(primary) > MAX_QUOTES or len(leader) > MAX_QUOTES:
        raise ValueError("too many observations")
    for rows in (primary, leader):
        if any(a.ts_avail > b.ts_avail for a, b in pairwise(rows)):
            raise ValueError("noncausal observation order")
    primary_times = [x.ts_avail for x in primary]
    leader_times = [x.ts_avail for x in leader]

    def aligned(rows, times, close):
        """Select the latest qualified quote strictly available before close."""
        idx = bisect_left(times, close) - 1
        if idx < 0:
            return None
        top = rows[idx]
        if (not qualified(top) or "CLOSED" in top.flags or
                (close - top.ts_avail).total_seconds() > max_age_seconds):
            return None
        return top
    closes = []
    stamp = spec.bucket(start) + spec.step
    while stamp <= end:
        if len(closes) >= MAX_SAMPLES:
            raise ValueError("too many evaluation closes")
        a, b = aligned(primary, primary_times, stamp), aligned(leader, leader_times, stamp)
        if a is not None and b is not None and abs((a.ts_avail - b.ts_avail).total_seconds()) <= max_skew_seconds:
            closes.append((stamp, (a.bid + a.ask) / 2, (b.bid + b.ask) / 2))
        else:
            closes.append((stamp, None, None))
        stamp += spec.step
    returns = []
    for prev, cur in pairwise(closes):
        if cur[0] - prev[0] != spec.step or any(x is None for x in (prev[1], prev[2], cur[1], cur[2])):
            returns.append(None)
        else:
            returns.append((cur[1] / prev[1] - 1, cur[2] / prev[2] - 1))
    pairs = [(a[1], b[0]) for a, b in pairwise(returns) if a is not None and b is not None]
    result = {"schema": "lead-lag/1", "store": store, "synthetic": store == "demo",
              "overlap": len(pairs), "min_overlap": min_overlap, "leader_precedes_follower": True,
              "correlation": None, "status": "INSUFFICIENT_OVERLAP", "held_out": False,
              "established_edge": False, "funded_authority": False, "order_submitted": False}
    if len(pairs) >= min_overlap:
        with localcontext() as context:
            context.prec = 80
            x, y = zip(*pairs)
            mx, my = sum(x) / len(x), sum(y) / len(y)
            vx = sum((v - mx)**2 for v in x)
            vy = sum((v - my)**2 for v in y)
            if vx and vy:
                result["correlation"] = str(sum((a - mx)*(b - my) for a, b in pairs) / (vx * vy).sqrt())
                result["status"] = "DESCRIPTIVE_ONLY"
            else:
                result["status"] = "ZERO_VARIANCE"
    if max_delay_bars > 1:
        # A lag-d pair is the leader return at t vs follower return at t+d.
        # Require every intervening interval: missing market data must not
        # bridge an apparent long-range predictive relationship.
        def correlation(pairs):
            """Pearson correlation of a historical, chronological return subset."""
            if len(pairs) < 2:
                return None
            x, y = zip(*pairs)
            mx, my = sum(x) / len(x), sum(y) / len(y)
            vx = sum((value - mx) ** 2 for value in x)
            vy = sum((value - my) ** 2 for value in y)
            return (sum((a - mx) * (b - my) for a, b in pairs) / (vx * vy).sqrt()
                    if vx > 0 and vy > 0 else None)

        scan = []
        with localcontext() as context:
            context.prec = 80
            for delay in range(1, max_delay_bars + 1):
                matched = [(returns[i][1], returns[i + delay][0])
                           for i in range(len(returns) - delay)
                           if all(row is not None for row in returns[i:i + delay + 1])]
                training = len(matched) * 7 // 10
                train, holdout = matched[:training], matched[training:]
                train_corr = correlation(train) if len(train) >= min_overlap else None
                holdout_corr = correlation(holdout) if len(holdout) >= max(3, min_overlap // 4) else None
                scan.append({"delay_bars": delay, "matched": len(matched),
                             "training_samples": len(train), "holdout_samples": len(holdout),
                             "training_correlation": str(train_corr) if train_corr is not None else None,
                             "holdout_correlation": str(holdout_corr) if holdout_corr is not None else None,
                             "same_sign_oos": (train_corr * holdout_corr > 0
                                               if train_corr is not None and holdout_corr is not None else None)})
        eligible = [row for row in scan if row["training_correlation"] is not None
                    and Decimal(row["training_correlation"]) > 0]
        best = max(eligible, key=lambda row: (Decimal(row["training_correlation"]),
                                              -row["delay_bars"])) if eligible else None
        result.update(schema="lead-lag/2", max_delay_bars=max_delay_bars,
                      delay_scan=scan,
                      best_training_delay=best["delay_bars"] if best else None,
                      selection_basis="CHRONOLOGICAL_TRAIN_ONLY",
                      internal_holdout_only=True)
    result["limitations"] = ["Consecutive causally aligned closed-window mid returns only; no interpolation.",
                             "Lagged correlation does not establish prediction, profitability or funded authority."]
    result["report_id"] = digest(result)[:16]
    return result
