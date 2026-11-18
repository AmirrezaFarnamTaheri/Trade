"""A planted edge is found when it is large and missed when it is zero; the search reports the first edge found."""
import importlib.util
import sys
from pathlib import Path
from random import Random

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("detectable_edge", SCRIPTS / "detectable_edge.py")
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)

_RNG = Random(3)
NOISE = [_RNG.gauss(0, 0.02) for _ in range(800)]


def test_a_large_edge_is_detected_and_no_edge_is_not():
    passes = edge.bootstrap_test(block=1, draws=100)
    assert edge.detection(NOISE, 0.01, passes, block=1) >= 0.95
    assert edge.detection(NOISE, 0.0, passes, block=1) <= 0.20


def test_the_smallest_detectable_edge_lies_between_noise_and_a_huge_edge():
    found, curve = edge.smallest(NOISE, edge.deflated_test(trials=3, sharpe_variance=0.0001), block=1)
    assert found is not None and 1 <= found <= 50
    assert curve[-1] == (found, curve[-1][1]) and curve[-1][1] >= edge.TARGET
