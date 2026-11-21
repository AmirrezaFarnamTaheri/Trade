"""Paired uplift, Hansen SPA, purged CPCV/PBO, sequential e-process, and causal research prototypes (S006-S023, R001-R004)."""
from __future__ import annotations

import json
import math
from decimal import Decimal
from random import Random

import pytest

from gym.domain.research_prototypes import (
    edge_of_band_target,
    ewmac_forecast,
    factor_ic_analysis,
    vol_target_position,
)
from gym.domain.statistical_inference import (
    hansen_spa,
    paired_baseline_uplift,
    pbo_rank_logit,
    purged_cpcv_splits,
    sequential_e_process,
)


def test_paired_baseline_uplift_distinguishes_positive_underpowered_and_degenerate():
    """S006, S007, S008, S009, S023."""
    rng = Random(11)
    bench = {f"2026-01-{d:02d}": rng.gauss(0.0, 0.01) for d in range(1, 31)}
    strong = {k: v + 0.02 for k, v in bench.items()}
    noisy = {k: v + rng.gauss(0.0, 0.015) for k, v in bench.items()}

    pos = paired_baseline_uplift(strong, bench, min_detectable_effect=0.005, seed=1)
    assert pos["status"] == "POSITIVE_EXPLORATORY" and pos["ci_95"][0] > 0.005 and pos["independent_final_evidence"] is False

    under = paired_baseline_uplift(noisy, bench, min_detectable_effect=0.002, seed=1)
    assert under["status"] in ("UNDERPOWERED_NOT_ESTABLISHED", "NO_EVIDENCE_NOT_ESTABLISHED", "BELOW_THRESHOLD")

    same = paired_baseline_uplift(bench, bench, seed=1)
    assert same["status"] == "DEGENERATE_VARIANCE"


def test_hansen_consistent_spa_ordering_and_null_vs_alternative():
    """S012, S013: p_lower <= p_consistent <= p_upper; detects genuine signal and controls null."""
    rng = Random(2026)
    null_data = {f"s{i}": [rng.gauss(0.0, 0.01) for _ in range(250)] for i in range(10)}
    null_data["bad_model"] = [rng.gauss(-0.02, 0.01) for _ in range(250)]
    null_res = hansen_spa(null_data, simulations=399, seed=7)
    assert null_res["p_lower"] <= null_res["p_consistent"] <= null_res["p_upper"]
    assert null_res["p_consistent"] > 0.05 and null_res["candidates"] == 11

    alt_data = {**null_data, "winner": [rng.gauss(0.015, 0.01) for _ in range(250)]}
    alt_res = hansen_spa(alt_data, simulations=399, seed=7)
    assert alt_res["p_lower"] <= alt_res["p_consistent"] <= alt_res["p_upper"]
    assert alt_res["p_consistent"] < 0.05


def test_purged_cpcv_eliminates_label_overlap_and_computes_pbo():
    """S014, S015: zero overlapping label intervals or embargo violations between train and test splits."""
    # Multi-bar forward labels spanning [i, i+4].
    intervals = [(i, i + 4) for i in range(60)]
    splits = purged_cpcv_splits(intervals, n_groups=6, n_test_groups=2, embargo=2)
    assert len(splits) == 15  # C(6, 2)
    for sp in splits:
        assert sp["purged"] > 0
        test_set = set(sp["test_idx"])
        test_min_max = [(intervals[i][0], intervals[i][1]) for i in sp["test_idx"]]
        for tr in sp["train_idx"]:
            assert tr not in test_set
            s_tr, e_tr = intervals[tr]
            assert not any(s_tr <= te and ts <= e_tr for ts, te in test_min_max)

    rng = Random(99)
    noise_cands = {f"m{i}": [rng.gauss(0.0, 0.01) for _ in range(90)] for i in range(8)}
    pbo = pbo_rank_logit(noise_cands, n_groups=6, n_test_groups=2, embargo=1)
    assert pbo["status"] == "SELECTION_INSTABILITY_DIAGNOSTIC"
    assert 0.0 <= pbo["pbo"] <= 1.0 and pbo["independent_final_evidence"] is False


def test_sequential_e_process_enforces_lower_bound_controls_null_and_detects_signal():
    """S016, S017: anytime-valid e-process refuses violated lower bound and controls optional stopping."""
    with pytest.raises(ValueError, match="lower bound"):
        sequential_e_process([0.01, -0.8], lower_bound=0.5)

    # Monte Carlo optional-stopping false-discovery calibration under zero-mean null (<= alpha).
    false_rejects = 0
    trials = 100
    for seed in range(trials):
        rng = Random(5000 + seed)
        null_r = [max(-0.4, rng.gauss(0.0, 0.02)) for _ in range(120)]
        if sequential_e_process(null_r, lower_bound=0.5, alpha=0.05)["rejected_null"]:
            false_rejects += 1
    assert false_rejects <= 10  # conservative finite-trial envelope around 5%

    # Strong persistent positive drift rejects cleanly over 200 steps (1.02^195 > 20).
    rng = Random(42)
    pos_r = [max(-0.4, rng.gauss(0.02, 0.01)) for _ in range(200)]
    res = sequential_e_process(pos_r, lower_bound=0.5, alpha=0.05)
    assert res["rejected_null"] is True and res["rejected_at_step"] is not None


def test_rank_ic_uses_average_ranks_and_ignores_constant_rows():
    returns = {day: dict(A=1, B=2, C=3, D=4) for day in ("1", "2", "3")}
    constant = {day: dict(A=1, B=1, C=1, D=1) for day in returns}
    result = factor_ic_analysis(constant, returns)
    assert result["dates_evaluated"] == 0 and result["mean_rank_ic"] is None
    tied = {day: dict(A=1, B=1, C=2, D=2) for day in returns}
    result = factor_ic_analysis(tied, returns)
    assert result["mean_rank_ic"] == result["mean_pearson_ic"] == 0.894427
    assert result["ic_t_stat"] is None
    assert [row["mean_forward_return"] for row in result["calibration_by_rank_quartile"]] == [None, 1.5, None, 3.5]


def test_factor_ic_lab_cli_purges_actual_overlapping_intervals(tmp_path, capsys):
    from gym.cli import main

    def row(start, end):
        return {"at": f"2026-10-{start:02}T00:00:00Z", "label_end": f"2026-10-{end:02}T00:00:00Z",
                "factors": {"A": 1, "B": 1, "C": 2, "D": 2}, "forward_returns": {"A": 1, "B": 2, "C": 3, "D": 4}}

    request = tmp_path / "labels.json"
    request.write_text(json.dumps({"observations": [row(9, 11), row(1, 4), row(2, 3), row(4, 6)], "seed": 17}))
    cmd = ["--data", str(tmp_path / "data"), "research", "factor-ic-lab", str(request)]
    assert main(cmd) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["overlapping_rows_purged"] == 1 and result["dates_evaluated"] == 3
    assert result["mean_rank_ic"] == 0.894427 and not result["registered_trial"]
    assert not (tmp_path / "data").exists()
    future = {**row(9, 11), "label_end": "2099-01-01T00:00:00Z"}
    request.write_text(json.dumps({"observations": [future], "seed": 17}))
    assert main(cmd) != 0
    assert "complete forward labels" in capsys.readouterr().err


def test_causal_ewmac_vol_targeting_edge_of_band_and_factor_ic_prototypes():
    """R001, R002, R003, R004: strictly causal unregistered prototypes with placebo control."""
    closes = [100.0 * math.exp(0.002 * i + 0.03 * math.sin(i * 0.2)) for i in range(320)]
    shocked = closes[:280] + [c * 5.0 for c in closes[280:]]
    f_base = ewmac_forecast(closes)
    f_shock = ewmac_forecast(shocked)
    # Perturbing prices from index 280 onward cannot change any forecast before 280!
    assert f_base[:280] == f_shock[:280]
    assert f_base[270] is not None and -20.0 <= f_base[270] <= 20.0

    # Zero vol abstains; excessive turnover cost blocked by cost-of-speed gate (R002).
    assert vol_target_position(10.0, 0.0)["status"] == "ABSTAIN_ZERO_OR_UNKNOWN_VOL"
    assert vol_target_position(10.0, 0.20, expected_turnover_per_year=50.0)["status"] == "BLOCKED_COST_OF_SPEED"
    ok_pos = vol_target_position(10.0, 0.30, vol_target=0.15, expected_turnover_per_year=4.0)
    assert ok_pos["status"] == "READY" and Decimal(ok_pos["weight"]) == Decimal("0.5") and ok_pos["registered_trial"] is False

    # Edge-of-band rebalancing (R003).
    assert edge_of_band_target(Decimal("0.48"), Decimal("0.50"), Decimal("0.05"))["trade"] is False
    move = edge_of_band_target(Decimal("0.20"), Decimal("0.50"), Decimal("0.05"))
    assert move["trade"] is True and move["new_weight"] == Decimal("0.45")
    assert edge_of_band_target(Decimal("0.20"), Decimal("0"), Decimal("0.05"))["new_weight"] == Decimal("0")

    # Factor Rank-IC detects true cross-sectional predictor while shuffled placebo collapses near 0 (R004).
    rng = Random(33)
    f_by_d, r_by_d = {}, {}
    for d in range(1, 25):
        day = f"2026-01-{d:02d}"
        f_by_d[day] = {f"A{i}": float(i) for i in range(10)}
        r_by_d[day] = {f"A{i}": 0.005 * i + rng.gauss(0.0, 0.002) for i in range(10)}
    ic = factor_ic_analysis(f_by_d, r_by_d, purge_step=2, seed=1)
    assert ic["mean_rank_ic"] > 0.7 and abs(ic["placebo_mean_rank_ic"]) < 0.3 and ic["registered_trial"] is False
