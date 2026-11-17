"""T12 holds cash when no rule made money, follows the best one otherwise, and charges every switch."""
import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("rule_selector", SCRIPTS / "rule_selector.py")
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def test_a_steady_fall_keeps_the_selector_in_cash_and_costs_nothing():
    closes = [100 * 0.995 ** i for i in range(700)]
    position, chosen, _ = selector.select(closes, 90)
    picked = [c for c in chosen if c is not None]
    assert set(picked) == {"cash"}
    assert selector.total(selector.earn(closes, position)) == 0.0


def test_a_steady_rise_follows_a_rule_and_pays_one_entry():
    closes = [100 * 1.002 ** i for i in range(700)]
    position, chosen, _ = selector.select(closes, 90)
    assert "cash" not in [c for c in chosen if c is not None]
    returns = selector.earn(closes, position)
    first = next(i for i, c in enumerate(chosen) if c is not None)
    held_move = closes[-1] / closes[first] - 1
    assert 0.9 * held_move < selector.total(returns) < held_move


def test_selection_uses_only_earlier_closes():
    closes = [100 + (i % 37) - (i % 11) for i in range(700)]
    before, chosen_before, _ = selector.select(closes, 90)
    changed = closes[:500] + [c * 3 for c in closes[500:]]
    after, chosen_after, _ = selector.select(changed, 90)
    assert chosen_before[:500] == chosen_after[:500] and before[:500] == after[:500]


def test_block_probability_separates_gains_from_losses():
    assert selector.block_probability([0.01, -0.002] * 100) == 1.0
    assert selector.block_probability([-0.01, 0.002] * 100) == 0.0
