"""Seeded stationary-block diagnostics of verified saved paper equity returns."""
from decimal import Decimal, localcontext
from random import Random

from ..adapters.run_store import load_verified_run
from ..domain.market_models import decimal, fields, instant
from ..domain.strategy import digest


def return_bootstrap(root, request, *, store):
    fields(request, "run_id seed simulations mean_block_length max_gap_seconds")
    for name, low, high in (("seed", 0, 2**32 - 1), ("simulations", 100, 2000),
                            ("mean_block_length", 1, 1000), ("max_gap_seconds", 1, 604800)):
        if type(request[name]) is not int or not low <= request[name] <= high:
            raise ValueError(f"{name} must be an integer in {low}..{high}")
    out = load_verified_run(root, request["run_id"], store=store)
    curve = out["result"]["curve"]
    if type(curve) is not list or len(curve) > 10000:
        raise ValueError("resampling requires at most 10000 saved marks")
    returns, gaps, following = [], [], []
    with localcontext() as ctx:
        ctx.prec = 80
        previous, retained_end = None, None
        for mark in curve:
            if type(mark) not in (list, tuple) or len(mark) != 2:
                raise ValueError("invalid saved equity mark")
            at, equity = mark
            at, equity = instant(at), decimal(equity, "equity", positive=True)
            if previous:
                seconds = (at - previous[0]).total_seconds()
                if seconds <= 0:
                    raise ValueError("saved equity marks must be strictly chronological")
                if seconds <= request["max_gap_seconds"]:
                    if following and retained_end == previous[0]:
                        following[-1] = len(returns)
                    returns.append(equity / previous[1] - 1)
                    following.append(None)
                    retained_end = at
                else:
                    gaps.append({"from": previous[0].isoformat(), "to": at.isoformat(), "seconds": seconds})
            previous = at, equity
        n, simulations = len(returns), request["simulations"]
        if n < 20:
            raise ValueError("need at least 20 eligible saved return intervals")
        if simulations * n > 1000000 or request["mean_block_length"] > n:
            raise ValueError("resampling budget exceeded or block length exceeds observations")
        observed = sum(returns, Decimal(0)) / n
        centered = [value - observed for value in returns]
        rng, means = Random(request["seed"]), []
        # Restart blocks at real gaps/endpoints instead of inventing adjacency.
        for _ in range(simulations):
            index, total = rng.randrange(n), Decimal(0)
            for step in range(n):
                total += centered[index]
                if step + 1 < n:
                    successor = following[index]
                    index = (rng.randrange(n) if successor is None or rng.randrange(request["mean_block_length"]) == 0 else successor)
            means.append(total / n)
        exceed = sum(value >= observed for value in means)
        ordered = sorted(means)
        result = {"schema": "return-bootstrap/1", "status": "DESCRIPTIVE_ONLY", "store": store,
                  "synthetic": store == "demo", "run_id": out["run_id"], "request": request,
                  "source_outputs_digest": out["outputs_digest"], "observations": n,
                  "excluded_gap_intervals": len(gaps), "gap_examples": gaps[:20],
                  "eligible_segments": sum(index is None for index in following),
                  "observed_mean_simple_return": str(observed),
                  "null_upper_tail_fraction": str(Decimal(exceed + 1) / (simulations + 1)),
                  "null_mean_quantiles": {str(p): str(ordered[(simulations - 1) * p // 100]) for p in (5, 50, 95)},
                  "annualization_applied": False, "trials_accounted_for": False, "funded_authority": False,
                  "limits": ["Returns include saved modeled costs, not authenticated measured execution costs.",
                             "Stationary blocks assume the retained sequence represents local dependence; gaps are excluded.",
                             "Intervals can differ in duration; per-interval means are not annualized.",
                             "No correction for searched strategies or evidence of future profitability; no promotion verdict."]}
    result["report_id"] = digest(result)[:16]
    return result
