"""Exploratory 200-seed timing comparison against equal-duration random entries.

Reuses saved paper fills/closed-bar bids, does not create trades or change run IDs.
"""
from bisect import bisect_right
from math import isfinite
from random import Random
from statistics import fmean

from ..domain.model import parse_ts
from ..domain.performance import trade_ledger


def random_entry_percentile(marks, trades, *, seeds=200, seed=0):
    """Replay the same number of holding intervals at random recorded entry times."""
    if seeds != 200:
        raise ValueError("random-entry comparison requires exactly 200 seeds")
    if not trades or len(marks) < 3:
        return {"status": "INSUFFICIENT_DATA", "trades": len(trades), "seeds": seeds}
    points = sorted((float(t), float(bid)) for t, bid in marks)
    if any(not isfinite(v) or v <= 0 for _, v in points):
        raise ValueError("invalid baseline prices")
    prices = dict(points)
    possible = []
    for trade in trades:
        hold, net, drag = (float(trade[k]) for k in ("holding_seconds", "net_return", "cost_drag"))
        if hold <= 0 or not isfinite(net) or not 0 <= drag < 1:
            return {"status": "INSUFFICIENT_DATA", "reason": "UNSUPPORTED_TRADE_DURATION_OR_COST"}
        eligible = [(bid, prices[t + hold]) for t, bid in points if t + hold in prices]
        if not eligible:
            return {"status": "INSUFFICIENT_DATA", "reason": "NO_EXACT_HOLDING_WINDOW", "trades": len(trades)}
        possible.append((eligible, drag))
    observed = fmean(float(t["net_return"]) for t in trades)
    simulated = []
    for trial in range(seeds):
        rng = Random(seed + trial)
        simulated.append(fmean(exit_price / entry - 1 - drag
                               for candidates, drag in possible
                               for entry, exit_price in (rng.choice(candidates),)))
    rank = sum(value < observed for value in simulated) + 0.5 * sum(value == observed for value in simulated)
    return {"status": "EXPLORATORY", "trades": len(trades), "seeds": seeds,
            "observed_mean_net_return": observed, "random_mean_net_return": fmean(simulated),
            "percentile": round(100 * rank / seeds, 2),
            "basis": "Exact observed holding durations, same trade count, empirical modeled fill friction per trade.",
            "authority": "PAPER_ONLY"}


def random_entry_report(out):
    """Estimate fee/spread/latency friction against closed-bar marks before shuffling."""
    result = out["result"]
    if out.get("mode") != "PAPER":
        return {"status": "INSUFFICIENT_DATA", "reason": "NATIVE_PAPER_ONLY"}
    ledger = trade_ledger(result.get("orders", []), result.get("base") or "")
    marks = sorted((parse_ts(row["t"]).timestamp(), float(row["bid"]))
                   for row in result.get("decisions", []) if row.get("bid"))
    times = [t for t, _ in marks]
    trades = []
    for trade in ledger["trades"]:
        if trade["return"] is None or not times:
            continue
        open_at, close_at = (parse_ts(trade[k]).timestamp() for k in ("opened_at", "closed_at"))
        start, finish = bisect_right(times, open_at) - 1, bisect_right(times, close_at) - 1
        if start < 0 or finish < 0 or marks[start][1] <= 0:
            continue
        net = float(trade["return"])
        gross = marks[finish][1] / marks[start][1] - 1
        trades.append({"holding_seconds": trade["holding_seconds"], "net_return": net,
                       "cost_drag": max(0.0, gross - net)})
    report = random_entry_percentile(marks, trades)
    report["limitation"] = ("Random entry at observed closed-bar bids, exact recorded durations when available; "
                            "friction inferred from simulated fill/mark differences, not independent venue costs. "
                            "No portfolio path, inventory constraint or independent test set.")
    return report
