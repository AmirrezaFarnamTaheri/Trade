"""Small exact tests for judging many tries at once."""
from math import comb


def sign_test_p(wins: int, n: int) -> float:
    """One-sided P(at least `wins` successes in `n` fair coin flips); ties belong outside `n`."""
    if n == 0:
        return 1.0
    return sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def bh_q(pvalues: dict) -> dict:
    """Benjamini-Hochberg q-value for each named p-value (step-up, monotone)."""
    ranked = sorted(pvalues.items(), key=lambda item: item[1])
    m, running, q = len(ranked), 1.0, {}
    for rank in range(m, 0, -1):
        name, value = ranked[rank - 1]
        running = min(running, value * m / rank)
        q[name] = running
    return q
