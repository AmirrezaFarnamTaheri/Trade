"""Calibrated statistical oracles, dependence/power gates, SPA calibration, and negative controls (S001-S011, S018-S023)."""
from __future__ import annotations

import math
from datetime import timedelta
from random import Random

import pytest

from gym.domain.model import iso
from gym.domain.performance import (
    deflated_sharpe,
    lo_annualized_sharpe,
    performance,
    probabilistic_sharpe,
)
from gym.services.spa import stationary_spa
from tests.support import START


def test_lo_annualized_sharpe_matches_positive_and_negative_serial_dependence_oracles():
    """S003, S004: positive autocorrelation shrinks annualized Sharpe; negative autocorrelation raises it; zero variance is None."""
    rng = Random(42)
    # Construct AR(1) series with positive autocorrelation phi=+0.6 vs IID vs negative phi=-0.6.
    def ar1(phi: float, n: int = 400):
        x, out = 0.0, []
        for _ in range(n):
            x = phi * x + rng.gauss(0.002, 0.01)
            out.append(x)
        return out

    pos = ar1(0.6)
    neg = ar1(-0.6)
    naive_pos = (sum(pos) / len(pos)) / math.sqrt(sum((v - sum(pos) / len(pos)) ** 2 for v in pos) / (len(pos) - 1)) * math.sqrt(365)
    lo_pos = lo_annualized_sharpe(pos, 365, max_lags=10)
    naive_neg = (sum(neg) / len(neg)) / math.sqrt(sum((v - sum(neg) / len(neg)) ** 2 for v in neg) / (len(neg) - 1)) * math.sqrt(365)
    lo_neg = lo_annualized_sharpe(neg, 365, max_lags=10)

    assert lo_pos is not None and lo_pos < naive_pos
    assert lo_neg is not None and lo_neg > naive_neg
    # Degenerate zero-variance series must return None (S022).
    assert lo_annualized_sharpe([0.0] * 50, 365) is None


def test_psr_and_dsr_monotonicity_in_trials_and_small_sample_refusal():
    """S005, S018, S022: more searched trials strictly reduce DSR; small samples refuse."""
    p_low = probabilistic_sharpe(0.2, 100, 0.0, 3.0, benchmark=0.0)
    p_high = probabilistic_sharpe(0.5, 100, 0.0, 3.0, benchmark=0.0)
    assert 0.5 < p_low < p_high < 1.0

    # Increasing the selection family count monotonically reduces deflated Sharpe probability.
    d1 = deflated_sharpe(0.3, 200, 0.0, 3.0, 1, 0.04)
    d10 = deflated_sharpe(0.3, 200, 0.0, 3.0, 10, 0.04)
    d100 = deflated_sharpe(0.3, 200, 0.0, 3.0, 100, 0.04)
    assert d1 > d10 > d100

    # Small sample (n <= 2) must return None rather than a bogus significance score.
    assert probabilistic_sharpe(1.0, 2, 0.0, 3.0, benchmark=0.0) is None


def test_irregular_and_nonpositive_mark_intervals_are_explicitly_counted():
    """S001, S004: duplicate/nonpositive timestamps are surfaced in mark_spacing."""
    t1 = START + timedelta(minutes=1)
    t2 = START + timedelta(minutes=1)  # duplicate timestamp!
    t3 = START + timedelta(minutes=11)
    record = {
        "inputs": {"from": iso(START), "to": iso(t3)},
        "result": {"quote": "USDT", "start_cash": "100",
                   "curve": [(iso(t1), "101"), (iso(t2), "101"), (iso(t3), "102")]},
    }
    spacing = performance(record, enhanced=True)["mark_spacing"]
    assert spacing["nonpositive_intervals"] == 1
    assert spacing["positive_intervals"] == 2
    assert spacing["max_seconds"] == 600.0


def test_spa_style_scope_null_control_and_positive_control_calibration():
    """S010, S011, S020: SPA enforces 2..8 candidates, controls false positives under null, detects strong signal, and loses skill when shuffled."""
    with pytest.raises(ValueError, match="2..8"):
        stationary_spa({"only_one": [0.01] * 50})
    with pytest.raises(ValueError, match="2..8"):
        stationary_spa({f"c{i}": [0.01] * 50 for i in range(9)})

    # Unbalanced or short arrays refuse cleanly (S011, S022).
    assert stationary_spa({"a": [0.01] * 10, "b": [0.01] * 10})["status"] == "INSUFFICIENT_DATA"
    assert stationary_spa({"a": [0.0] * 40, "b": [0.0] * 40})["status"] == "INSUFFICIENT_VARIATION"

    # True null across correlated candidates: p_value stays well above 0.05.
    rng = Random(777)
    common = [rng.gauss(0.0, 0.01) for _ in range(300)]
    null_excess = {f"c{i}": [c + rng.gauss(0.0, 0.005) for c in common] for i in range(4)}
    null_res = stationary_spa(null_excess, simulations=499, seed=1)
    assert null_res["status"] == "EXPLORATORY"
    assert "SPA-style" in null_res["limitation"]
    assert null_res["p_value"] > 0.05

    # Positive control: genuine strong signal beats null cleanly.
    pos_excess = {**null_excess, "winner": [0.015 + rng.gauss(0.0, 0.01) for _ in range(300)]}
    pos_res = stationary_spa(pos_excess, simulations=499, seed=1)
    assert pos_res["p_value"] < 0.05

    # Negative control (S020): random-sign placebo destroys the positive control's mean signal.
    placebo = [v * (1 if rng.random() < 0.5 else -1) for v in pos_excess["winner"]]
    placebo_res = stationary_spa({**null_excess, "placebo": placebo}, simulations=499, seed=1)
    assert placebo_res["p_value"] > pos_res["p_value"]
