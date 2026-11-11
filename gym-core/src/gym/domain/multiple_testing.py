"""Romano-Wolf stepdown for several candidate strategies against one benchmark (report 4.10, 37a5f6dc 4.5).

The deflated Sharpe guards the single best pick; when several candidates are reported together, this controls the
family-wise error rate across all of them while keeping their dependence (they trade the same markets). Each
candidate's excess return over the benchmark is studentised; a circular block bootstrap, shared across candidates
so their correlation survives, gives the null distribution of the maximum statistic, and the stepdown removes
rejected candidates before testing the rest (Romano and Wolf, 2005; adjusted p-values as in their 2016 note).
Statistics only; floats are fine here because nothing is priced or settled from them.
"""
from __future__ import annotations

import math
import random


def _studentised(diff: list[float]) -> tuple[float, float]:
    n = len(diff)
    mean = sum(diff) / n
    var = sum((x - mean) ** 2 for x in diff) / (n - 1)
    return mean, math.sqrt(var) if var > 0 else 0.0


def romano_wolf(candidates: dict[str, list[float]], benchmark: list[float], *, draws: int = 2000,
                block: int = 10, seed: int = 0) -> dict[str, float]:
    """Stepdown-adjusted p-values for "mean excess return over the benchmark is positive", per candidate."""
    if not candidates:
        raise ValueError("no candidates")
    n = len(benchmark)
    if n < 20 or any(len(r) != n for r in candidates.values()):
        raise ValueError("every series needs the benchmark's length, at least 20 periods")
    if not 1 <= block <= n // 2 or not 100 <= draws <= 100_000:
        raise ValueError("block must be 1..n/2 and draws 100..100000")
    names = sorted(candidates)
    diffs = [[a - b for a, b in zip(candidates[k], benchmark)] for k in names]
    stats, centres = [], []
    for diff in diffs:
        mean, sd = _studentised(diff)
        centres.append(mean)
        stats.append(math.sqrt(n) * mean / sd if sd else (math.inf if mean > 0 else -math.inf))
    order = sorted(range(len(names)), key=lambda i: stats[i], reverse=True)
    rng = random.Random(seed)
    exceed = [0] * len(names)
    for _ in range(draws):
        index = []
        while len(index) < n:
            start = rng.randrange(n)
            index.extend((start + j) % n for j in range(block))
        index = index[:n]
        boot = []
        for diff, centre in zip(diffs, centres):
            sample = [diff[i] for i in index]
            mean, sd = _studentised(sample)
            boot.append(math.sqrt(n) * (mean - centre) / sd if sd else 0.0)
        # Stepdown: the null for the i-th ranked candidate is the max over it and every lower-ranked one.
        running = -math.inf
        for rank in range(len(order) - 1, -1, -1):
            running = max(running, boot[order[rank]])
            if running >= stats[order[rank]]:
                exceed[rank] += 1
    adjusted, worst = {}, 0.0
    for rank, i in enumerate(order):
        worst = max(worst, (exceed[rank] + 1) / (draws + 1))  # monotone in rank; +1 keeps p away from zero
        adjusted[names[i]] = worst
    return adjusted
