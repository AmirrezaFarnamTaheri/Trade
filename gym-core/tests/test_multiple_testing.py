import itertools
import random

import pytest

from gym.domain.multiple_testing import romano_wolf


def series(rng, n, drift, common, scale=0.01):
    return [drift + c + rng.gauss(0, scale) for c in common]


def test_a_real_edge_survives_and_correlated_nulls_do_not():
    rng = random.Random(7)
    n = 400
    common = [rng.gauss(0, 0.01) for _ in range(n)]
    benchmark = [c * 0.5 for c in common]
    cands = {f"null{i}": series(rng, n, 0.0, common) for i in range(8)}
    cands["edge"] = series(rng, n, 0.004, common)
    p = romano_wolf(cands, [b + c * 0.5 for b, c in zip(benchmark, common)], draws=500, seed=1)
    assert p["edge"] < 0.01
    assert min(v for k, v in p.items() if k != "edge") > 0.05


def test_adjusted_p_values_are_monotone_in_rank_and_deterministic():
    rng = random.Random(3)
    n = 120
    common = [rng.gauss(0, 0.01) for _ in range(n)]
    cands = {f"s{i}": series(rng, n, 0.0005 * i, common) for i in range(5)}
    bench = [0.0] * n
    first = romano_wolf(cands, bench, draws=300, seed=9)
    assert first == romano_wolf(cands, bench, draws=300, seed=9)
    ranked = sorted(first, key=lambda k: -sum(cands[k]))
    assert all(first[a] <= first[b] for a, b in itertools.pairwise(ranked))
    # Adjusting for more candidates can only make a candidate's p-value larger, never smaller.
    alone = romano_wolf({"s4": cands["s4"]}, bench, draws=300, seed=9)
    assert alone["s4"] <= first["s4"] + 1e-12


def test_input_validation():
    with pytest.raises(ValueError):
        romano_wolf({}, [0.0] * 30)
    with pytest.raises(ValueError):
        romano_wolf({"a": [0.0] * 10}, [0.0] * 10)
    with pytest.raises(ValueError):
        romano_wolf({"a": [0.0] * 30}, [0.0] * 31)
