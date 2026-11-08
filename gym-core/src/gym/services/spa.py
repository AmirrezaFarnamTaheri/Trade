"""Conservative stationary-bootstrap SPA-style familywise comparison against buy-and-hold."""
import math
from itertools import pairwise
from random import Random
from statistics import fmean

from ..domain.model import parse_ts


def stationary_spa(excess: dict[str, list[float]], *, simulations: int = 199, seed: int = 0) -> dict:
    """Studentized max excess over buy/hold, with block-preserved candidate dependence."""
    if not 2 <= len(excess) <= 8:
        raise ValueError("SPA requires 2..8 candidates")
    arrays = [list(map(float, values)) for values in excess.values()]
    n = len(arrays[0])
    if n < 20 or n > 10000 or any(len(values) != n or any(not math.isfinite(x) for x in values) for values in arrays):
        return {"status": "INSUFFICIENT_DATA", "periods": n}
    if not 100 <= simulations <= 1000 or n * len(arrays) * simulations > 10_000_000:
        raise ValueError("SPA simulation budget exceeded")
    block, rng = max(2, round(n ** (1 / 3))), Random(seed)
    means = [fmean(values) for values in arrays]
    # Identical resampling indices preserve contemporaneous covariance and dependence.
    bootstrap = []
    for _ in range(simulations):
        index, indices = rng.randrange(n), []
        for _ in range(n):
            indices.append(index)
            index = rng.randrange(n) if rng.random() < 1 / block else (index + 1) % n
        bootstrap.append([fmean(values[j] for j in indices) - avg for values, avg in zip(arrays, means)])
    omega = []
    for col in range(len(arrays)):
        avg = fmean(row[col] for row in bootstrap)
        omega.append(math.sqrt(n * math.fsum((row[col] - avg) ** 2 for row in bootstrap) / (simulations - 1)))
    valid = [i for i, value in enumerate(omega) if value > 0]
    if not valid:
        return {"status": "INSUFFICIENT_VARIATION", "periods": n}
    statistic = max(0.0, *(math.sqrt(n) * means[i] / omega[i] for i in valid))
    hits = sum(max(0.0, *(math.sqrt(n) * row[i] / omega[i] for i in valid)) >= statistic
               for row in bootstrap)
    raw = (hits + 1) / (simulations + 1)
    # Upper Wilson confidence bound accounts for simulation uncertainty instead
    # of overstating significance at a small finite bootstrap budget.
    count, z = simulations + 1, 3.090232306167813
    upper = (raw + z * z / (2 * count) +
             z * math.sqrt(raw * (1 - raw) / count + z * z / (4 * count * count))) / (1 + z * z / count)
    return {"status": "EXPLORATORY", "periods": n, "candidates": len(valid),
            "statistic": statistic, "p_value": upper, "raw_bootstrap_p": raw,
            "simulations": simulations, "mean_block_length": block,
            "p_value_basis": "conservative_99.8pct_Wilson_upper_for_centered_stationary_bootstrap",
            "limitation": "SPA-style studentized max; finite-sample upper bound, not a guarantee of an edge or independent final evidence."}


def scorecard_spa(rows: list[dict], verified: dict[str, dict]) -> list[dict]:
    """Estimate a matched buy/hold-relative SPA for each common window/scenario."""
    grouped = {}
    for row in rows:
        grouped.setdefault((row["window"], row["scenario"]), []).append(row)
    reports = []
    for (window, scenario), group in sorted(grouped.items()):
        observed, identity, excess = [], None, {}
        for row in group:
            out = verified.get(row["attempt_id"])
            if out is None:
                continue
            inputs = out["inputs"]
            matched = tuple(inputs.get(k) for k in ("symbol", "from", "to", "resolution", "cash", "cost", "data"))
            # 'cost' contains a dict and is only compared, never used as a grouping key.
            if identity is not None and matched != identity:
                break
            identity = matched
            bids = {decision["t"]: float(decision["bid"]) for decision in out["result"].get("decisions", [])
                    if decision.get("bid") is not None}
            points = [(parse_ts(at), float(equity), bids[at])
                      for at, equity in out["result"].get("curve", []) if at in bids]
            deltas = {(a[0], b[0]): b[1] / a[1] - b[2] / a[2]
                      for a, b in pairwise(points) if a[1] > 0 and a[2] > 0}
            observed.append(set(deltas))
            excess[str(row["trial"])] = deltas
        else:
            common = sorted(set.intersection(*observed)) if len(observed) >= 2 else []
            if len(common) >= 20 and len(excess) >= 2 and all(len(v) == len(common) for v in excess.values()):
                report = stationary_spa({k: [values[t] for t in common] for k, values in excess.items()})
                reports.append({"window": window, "scenario": scenario, **report})
                continue
        reports.append({"window": window, "scenario": scenario, "status": "INSUFFICIENT_COMPARABLE_DATA",
                        "limitation": "Requires >=20 exactly matched recorded return intervals and identical costs."})
    return reports
