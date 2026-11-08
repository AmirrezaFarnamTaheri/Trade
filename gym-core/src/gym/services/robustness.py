"""Exploratory selection, recorded-regime and realized-trade-path diagnostics."""
from decimal import Decimal, localcontext
from itertools import combinations, pairwise
from math import comb, log
from random import Random

from ..adapters.run_store import load_verified_run
from ..domain.market_models import decimal, fields, instant
from ..domain.model import iso
from ..domain.performance import trade_ledger
from ..domain.strategy import digest
from .return_bootstrap import return_bootstrap


def cscv(rows, partitions):
    """Contiguous equal blocks; selection metric is mean per-interval simple return."""
    if type(partitions) is not int or partitions not in (4, 6, 8, 10):
        raise ValueError("CSCV partitions must be 4, 6, 8 or 10")
    if len(rows) < partitions * 10:
        return {"status": "INSUFFICIENT_DATA", "required_intervals": partitions * 10, "observations": len(rows)}
    n, size = len(rows[0]), len(rows) // partitions
    if not 2 <= n <= 8 or len(rows) > 10000 or any(len(row) != n or any(not x.is_finite() for x in row) for row in rows):
        raise ValueError("invalid or unbounded CSCV return matrix")
    if len(rows) * n * comb(partitions, partitions // 2) > 2000000:
        raise ValueError("CSCV budget exceeded; reduce partitions or the window")
    if not any(len(set(row)) > 1 for row in rows):
        return {"status": "INSUFFICIENT_VARIATION", "observations": len(rows)}
    blocks = [[sum((row[i] for row in rows[b * size:(b + 1) * size]), Decimal(0)) / size
               for i in range(n)] for b in range(partitions)]
    outcomes, selection_ties, median_ties, below = [], 0, 0, 0
    for training in combinations(range(partitions), partitions // 2):
        test = [b for b in range(partitions) if b not in training]
        score = lambda indices: [sum((blocks[b][i] for b in indices), Decimal(0)) / len(indices) for i in range(n)]
        inside, outside = score(training), score(test)
        selected = max(range(n), key=lambda i: (inside[i], -i))
        selection_ties += sum(x == inside[selected] for x in inside) > 1
        lower = sum(x < outside[selected] for x in outside)
        equal = sum(x == outside[selected] for x in outside)
        relative = (Decimal(lower) + (Decimal(equal) + 1) / 2) / (n + 1)
        below += relative < Decimal("0.5")
        median_ties += relative == Decimal("0.5")
        outcomes.append({"training_blocks": list(training), "selected_candidate": selected,
                         "test_mean_return": str(outside[selected]), "relative_rank": str(relative),
                         "rank_logit": log(float(relative / (1 - relative)))})
    return {"status": "EXPLORATORY", "metric": "mean_simple_return_per_recorded_interval",
            "partitions": partitions, "intervals_per_block": size, "discarded_tail_intervals": len(rows) % partitions,
            "combinations": len(outcomes), "selection_ties": selection_ties, "median_ties": median_ties,
            "below_median_fraction": str(Decimal(below) / len(outcomes)),
            "at_or_below_median_fraction": str(Decimal(below + median_ties) / len(outcomes)),
            "independent_test": False, "outcomes": outcomes}


def trade_reshuffle(pnls, cash, *, seed, simulations):
    if len(pnls) < 10:
        return {"status": "INSUFFICIENT_DATA", "closed_trade_count": len(pnls), "required_trades": 10}
    if simulations * len(pnls) > 1000000:
        raise ValueError("trade-path resampling budget exceeded")
    rng, losses = Random(seed), []
    with localcontext() as context:
        context.prec = 80
        for _ in range(simulations):
            path = list(pnls)
            rng.shuffle(path)
            equity, peak, worst = cash, cash, Decimal(0)
            for pnl in path:
                equity += pnl
                peak = max(peak, equity)
                worst = max(worst, (peak - equity) / peak)
            losses.append(worst)
        losses.sort()
        return {"status": "DESCRIPTIVE_ONLY", "closed_trade_count": len(pnls),
                "final_realized_equity": str(cash + sum(pnls, Decimal(0))),
                "drawdown_fraction_quantiles": {str(p): str(losses[(simulations - 1) * p // 100]) for p in (5, 50, 95)},
                "new_market_samples": False,
                "basis": "Additive permutation of fixed FIFO realized P/L; no compounding, open marks, timing, inventory or executable capital path."}


def robustness(root, request, *, store):
    fields(request, "run_ids partitions seed simulations mean_block_length max_gap_seconds")
    ids = request["run_ids"]
    if type(ids) is not list or not 2 <= len(ids) <= 8 or any(type(key) is not str for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("need 2..8 distinct saved run IDs")
    for key, low, high in (("seed", 0, 2**32 - 1), ("simulations", 100, 2000),
                            ("mean_block_length", 1, 1000), ("max_gap_seconds", 1, 604800)):
        if type(request[key]) is not int or not low <= request[key] <= high:
            raise ValueError(f"{key} must be an integer in {low}..{high}")
    if type(request["partitions"]) is not int or request["partitions"] not in (4, 6, 8, 10):
        raise ValueError("CSCV partitions must be 4, 6, 8 or 10")
    records = [load_verified_run(root, key, store=store) for key in ids]
    match = ("engine", "symbol", "from", "to", "resolution", "cash", "cost", "rules_mode", "store", "data", "snapshots", "subscriptions", "reference_symbol")
    if any(r["inputs"].get("kind") in ("portfolio", "live-session") or r.get("mode") != "PAPER" for r in records):
        raise ValueError("robustness requires comparable historical single-market runs")
    if any(any(r["inputs"].get(k) != records[0]["inputs"].get(k) for k in match) for r in records[1:]):
        raise ValueError("robustness requires identical market, window, cash, costs, clocks and observed inputs")
    if len({r["inputs"]["config_hash"] for r in records}) != len(records):
        raise ValueError("robustness requires distinct strategy configurations")
    intervals, reports = [], []
    for out in records:
        curve = out["result"]["curve"]
        if (type(curve) is not list or len(curve) > 10000
                or any(type(mark) not in (list, tuple) or len(mark) != 2 for mark in curve)):
            raise ValueError("robustness requires at most 10000 saved marks per run")
        points = [(instant(t), decimal(value, "equity", positive=True)) for t, value in curve]
        mapping, excluded = {}, 0
        regimes = {d["t"]: d.get("feature_values", {}).get("entry_regime", d.get("feature_values", {}).get("regime", "NOT_RECORDED")) for d in out["result"]["decisions"]}
        groups = {}
        for (a, first), (b, last) in pairwise(points):
            gap = (b - a).total_seconds()
            if gap <= 0:
                raise ValueError("saved equity marks must be strictly chronological")
            if gap > request["max_gap_seconds"]:
                excluded += 1
                continue
            change = last / first - 1
            mapping[(a, b)] = change
            state = regimes.get(iso(a), "NOT_RECORDED")
            groups.setdefault(state, []).append(change)
        intervals.append(mapping)
        try:
            blocks = return_bootstrap(root, {k: v for k, v in {**request, "run_id": out["run_id"]}.items()
                                              if k not in ("run_ids", "partitions")}, store=store)
        except ValueError as error:
            blocks = {"status": "UNAVAILABLE", "reason": str(error)}
        trades = trade_ledger(out["result"]["orders"], out["result"]["base"])["trades"]
        reports.append({"run_id": out["run_id"], "outputs_digest": out["outputs_digest"], "excluded_gap_intervals": excluded,
            "return_blocks": blocks, "regimes": {"status": "RECORDED" if any(k != "NOT_RECORDED" for k in groups) else "NOT_RECORDED",
                "groups": {k: {"intervals": len(v), "mean_simple_return": str(sum(v, Decimal(0)) / len(v))} for k, v in sorted(groups.items())}},
            "trade_paths": trade_reshuffle([Decimal(t["pnl"]) for t in trades], Decimal(out["result"]["start_cash"]),
                                          seed=request["seed"], simulations=request["simulations"])})
    common = sorted(set.intersection(*(set(values) for values in intervals)))
    uniform = len({(b - a).total_seconds() for a, b in common}) <= 1
    complete = all(len(values) == len(common) for values in intervals) and all(not r["excluded_gap_intervals"] for r in reports)
    selected = (cscv([[values[at] for values in intervals] for at in common], request["partitions"])
                if uniform and complete else {"status": "INSUFFICIENT_CONTIGUOUS_DATA"})
    result = {"schema": "robustness/1", "store": store, "request": request, "common_intervals": len(common),
        "cscv": selected, "runs": reports, "all_trials_accounted_for": False, "funded_authority": False,
        "source": "https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf",
        "limits": ["CSCV recombines contiguous blocks symmetrically; its test sets are not chronological future evaluations.",
                   "Only supplied verified configurations are included. Unreported searches, limited candidates and regime coverage limit interpretation.",
                   "Mean interval return selects candidates; rank ties are explicit. No calibrated confidence or promotion threshold is supplied.",
                   "Return blocks assume local dependence; reshuffled realized P/L preserves trades and costs but creates no new market sample.",
                   "Recorded decision regimes describe subsequent intervals and are not independently estimated forecasts."]}
    result["report_id"] = digest(result)[:16]
    return result
