import pytest

from gym.domain.multiple_testing import bh_q, sign_test_p
from gym.services.paper_sweep import league


def test_sign_test_is_the_exact_one_sided_binomial_tail():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(3, 3) == pytest.approx(0.125)
    assert sign_test_p(2, 3) == pytest.approx(0.5)
    assert sign_test_p(9, 10) == pytest.approx(11 / 1024)


def test_bh_q_matches_the_step_up_procedure():
    q = bh_q({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert q == pytest.approx({"a": 0.04, "b": 0.0533333, "c": 0.0533333, "d": 0.5})


def row(symbol, net, hold, trades=2, strategy="ema-trend", resolution="1h"):
    return {"symbol": symbol, "strategy": strategy, "resolution": resolution, "net": net, "hold": hold, "trades": trades}


def test_league_scores_against_the_better_of_holding_the_coin_and_holding_cash():
    rows = [
        row("A", 5.0, -10.0),   # beat both: win
        row("B", -5.0, -10.0),  # beat the coin but lost money: cash was better, a loss
        row("C", 20.0, 30.0),   # made money but holding the coin made more: a loss
        row("D", 0.0, -10.0, trades=0),  # never traded: abstained, not a win
        row("E", 0.0, -3.0),    # traded back to exactly cash: a tie, left out of the test
    ]
    cell = league(rows)[0]
    assert (cell["strategy"], cell["resolution"]) == ("ema-trend", "1h")
    assert (cell["traded"], cell["abstained"], cell["wins"], cell["losses"], cell["ties"]) == (4, 1, 1, 2, 1)
    assert cell["p"] == pytest.approx(0.875)
    assert cell["median_excess"] == pytest.approx(-2.5)
    assert cell["q"] == pytest.approx(0.875)


def test_league_ranks_cells_by_adjusted_evidence():
    strong = [row(f"S{i}", 1.0, 0.0, strategy="good") for i in range(10)]
    weak = [row(f"W{i}", -1.0, 0.0, strategy="bad") for i in range(10)]
    cells = league(strong + weak)
    assert [c["strategy"] for c in cells] == ["good", "bad"]
    assert cells[0]["q"] == pytest.approx(2 / 1024)
