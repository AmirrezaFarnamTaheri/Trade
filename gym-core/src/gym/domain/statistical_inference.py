"""Calibrated statistical inference diagnostics: paired uplift, Hansen SPA, purged CPCV/PBO, sequential e-process (S006-S023)."""
from __future__ import annotations

import itertools
import math
from operator import itemgetter
from random import Random
from statistics import fmean

from .strategy import digest


def paired_baseline_uplift(
    strategy_by_date: dict[str, float],
    benchmark_by_date: dict[str, float],
    *,
    min_detectable_effect: float = 0.0,
    simulations: int = 499,
    seed: int = 0,
    block_length: int | None = None,
) -> dict:
    """Date-clustered stationary-block bootstrap of strategy minus investable benchmark (S006, S007, S008, S009, S023)."""
    common = sorted(set(strategy_by_date) & set(benchmark_by_date))
    n = len(common)
    lineage = {"formula": "paired-date-stationary-bootstrap/1", "seed": seed, "simulations": simulations, "denominator_dates": n}
    if n < 20:
        return {"status": "INSUFFICIENT_DATA", "lineage": lineage, "independent_final_evidence": False}
    diffs = [float(strategy_by_date[d]) - float(benchmark_by_date[d]) for d in common]
    if any(not math.isfinite(x) for x in diffs):
        return {"status": "INVALID_DATA", "lineage": lineage, "independent_final_evidence": False}
    mean_diff = fmean(diffs)
    var = math.fsum((x - mean_diff) ** 2 for x in diffs) / (n - 1)
    if var <= 0:
        return {"status": "DEGENERATE_VARIANCE", "mean_uplift": mean_diff, "lineage": lineage, "independent_final_evidence": False}
    block = block_length or max(2, round(n ** (1 / 3)))
    rng = Random(seed)
    boot_means = []
    for _ in range(simulations):
        idx, total = rng.randrange(n), 0.0
        for _ in range(n):
            total += diffs[idx]
            idx = rng.randrange(n) if rng.random() < 1 / block else (idx + 1) % n
        boot_means.append(total / n)
    boot_means.sort()
    lo_95 = boot_means[int(0.025 * (simulations - 1))]
    hi_95 = boot_means[int(0.975 * (simulations - 1))]
    boot_mean = fmean(boot_means)
    se = math.sqrt(math.fsum((m - boot_mean) ** 2 for m in boot_means) / (simulations - 1))
    # Distinguish underpowered vs positive vs no-edge (S009).
    if lo_95 > min_detectable_effect:
        status = "POSITIVE_EXPLORATORY"
    elif hi_95 < min_detectable_effect:
        status = "BELOW_THRESHOLD"
    elif se > 0 and 2.8 * se > max(min_detectable_effect, 1e-9) and min_detectable_effect > 0:
        status = "UNDERPOWERED_NOT_ESTABLISHED"
    else:
        status = "NO_EVIDENCE_NOT_ESTABLISHED"
    return {
        "status": status,
        "mean_uplift": mean_diff,
        "ci_95": [lo_95, hi_95],
        "bootstrap_se": se,
        "mean_block_length": block,
        "min_detectable_effect": min_detectable_effect,
        "lineage": {**lineage, "block_length": block, "digest": digest({"diffs_n": n, "seed": seed, "block": block})[:16]},
        "independent_final_evidence": False,
    }


def hansen_spa(
    excess: dict[str, list[float]],
    *,
    simulations: int = 499,
    seed: int = 0,
    block_length: int | None = None,
) -> dict:
    """Hansen (2005) consistent, liberal, and conservative studentized SPA p-values (S012, S013)."""
    if len(excess) < 2:
        raise ValueError("Hansen SPA requires at least 2 candidates")
    arrays = [list(map(float, vals)) for vals in excess.values()]
    n = len(arrays[0])
    if n < 20 or any(len(a) != n or any(not math.isfinite(x) for x in a) for a in arrays):
        return {"status": "INSUFFICIENT_DATA", "periods": n}
    block = block_length or max(2, round(n ** (1 / 3)))
    means = [fmean(a) for a in arrays]
    rng = Random(seed)
    boot_means = []
    for _ in range(simulations):
        idx, indices = rng.randrange(n), []
        for _ in range(n):
            indices.append(idx)
            idx = rng.randrange(n) if rng.random() < 1 / block else (idx + 1) % n
        gather = itemgetter(*indices)
        boot_means.append([fmean(gather(a)) for a in arrays])
    omega = []
    for k in range(len(arrays)):
        avg = fmean(row[k] for row in boot_means)
        omega.append(math.sqrt(n * math.fsum((row[k] - avg) ** 2 for row in boot_means) / (simulations - 1)))
    valid = [k for k, w in enumerate(omega) if w > 0]
    if not valid:
        return {"status": "INSUFFICIENT_VARIATION", "periods": n}
    t_obs = max(0.0, *(math.sqrt(n) * means[k] / omega[k] for k in valid))
    # Hansen consistent recentering threshold: sqrt(2 * ln(ln(n))).
    thresh = -math.sqrt(2.0 * math.log(max(math.log(n), 1.0001)))
    hits = {"lower": 0, "consistent": 0, "upper": 0}
    for row in boot_means:
        centered = [row[k] - means[k] for k in range(len(arrays))]
        vals_l, vals_c, vals_u = [0.0], [0.0], [0.0]
        for k in valid:
            mu_u = 0.0
            mu_l = min(0.0, means[k])
            mu_c = means[k] if (math.sqrt(n) * means[k] / omega[k]) <= thresh else 0.0
            vals_u.append(math.sqrt(n) * (centered[k] + mu_u) / omega[k])
            vals_c.append(math.sqrt(n) * (centered[k] + mu_c) / omega[k])
            vals_l.append(math.sqrt(n) * (centered[k] + mu_l) / omega[k])
        if max(vals_l) >= t_obs:
            hits["lower"] += 1
        if max(vals_c) >= t_obs:
            hits["consistent"] += 1
        if max(vals_u) >= t_obs:
            hits["upper"] += 1
    return {
        "schema": "hansen-spa/1",
        "status": "DIAGNOSTIC_ONLY",
        "periods": n,
        "candidates": len(valid),
        "simulations": simulations,
        "mean_block_length": block,
        "statistic": t_obs,
        "p_lower": (hits["lower"] + 1) / (simulations + 1),
        "p_consistent": (hits["consistent"] + 1) / (simulations + 1),
        "p_upper": (hits["upper"] + 1) / (simulations + 1),
        "independent_final_evidence": False,
    }


def purged_cpcv_splits(
    label_intervals: list[tuple[int, int]],
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int = 1,
) -> list[dict]:
    """Generate combinatorial purged & embargoed CV folds preventing label overlap leakage (S014)."""
    n = len(label_intervals)
    if n_groups < 3 or not 1 <= n_test_groups < n_groups or n < n_groups or embargo < 0:
        raise ValueError("invalid CPCV split parameters")
    # Partition indices into n_groups contiguous blocks.
    edges = [round(i * n / n_groups) for i in range(n_groups + 1)]
    blocks = [list(range(edges[i], edges[i + 1])) for i in range(n_groups)]
    splits = []
    for test_groups in itertools.combinations(range(n_groups), n_test_groups):
        test_idx = sorted(i for g in test_groups for i in blocks[g])
        test_idx_set = set(test_idx)
        test_spans = [(label_intervals[blocks[g][0]][0], max(label_intervals[i][1] for i in blocks[g])) for g in test_groups]
        embargo_ends = [max(label_intervals[i][1] for i in blocks[g]) + embargo for g in test_groups]
        train_idx, purged_count = [], 0
        for i in range(n):
            if i in test_idx_set:
                continue
            s_i, e_i = label_intervals[i]
            overlaps = any(s_i <= t_end and t_start <= e_i for t_start, t_end in test_spans)
            in_embargo = any(t_end < s_i <= emb_end for (_, t_end), emb_end in zip(test_spans, embargo_ends))
            if overlaps or in_embargo:
                purged_count += 1
            else:
                train_idx.append(i)
        splits.append({"test_groups": test_groups, "train_idx": train_idx, "test_idx": test_idx, "purged": purged_count})
    return splits


def pbo_rank_logit(candidate_returns: dict[str, list[float]], *, n_groups: int = 6, n_test_groups: int = 2, embargo: int = 1) -> dict:
    """Probability of Backtest Overfitting (Bailey et al.) via purged CPCV winner OOS rank logits (S015)."""
    names = sorted(candidate_returns)
    if len(names) < 2:
        raise ValueError("PBO requires at least 2 candidates")
    n = len(candidate_returns[names[0]])
    if any(len(candidate_returns[k]) != n for k in names) or n < n_groups * 2:
        return {"status": "INSUFFICIENT_DATA", "periods": n}
    intervals = [(i, i) for i in range(n)]
    splits = purged_cpcv_splits(intervals, n_groups=n_groups, n_test_groups=n_test_groups, embargo=embargo)
    logits, below_median = [], 0
    for split in splits:
        if len(split["train_idx"]) < 2 or len(split["test_idx"]) < 2:
            continue
        def _score(name, idxs):
            vals = [candidate_returns[name][i] for i in idxs]
            m = fmean(vals)
            v = math.fsum((x - m) ** 2 for x in vals) / (len(vals) - 1)
            return m / math.sqrt(v) if v > 0 else float("-inf")
        winner = max(names, key=lambda k: _score(k, split["train_idx"]))
        oos_scores = sorted((_score(k, split["test_idx"]), k) for k in names)
        rank = next(idx for idx, (_, k) in enumerate(oos_scores, 1) if k == winner)
        w = rank / (len(names) + 1)
        if w <= 0.5:
            below_median += 1
        logits.append(math.log(w / (1.0 - w)))
    if not logits:
        return {"status": "INSUFFICIENT_DATA", "periods": n}
    return {
        "schema": "cpcv-pbo/1",
        "status": "SELECTION_INSTABILITY_DIAGNOSTIC",
        "splits_evaluated": len(logits),
        "pbo": below_median / len(logits),
        "median_logit": sorted(logits)[len(logits) // 2],
        "independent_final_evidence": False,
        "limitation": "Diagnostic for selection instability only; split dependence means PBO is never an independent final test.",
    }


def sequential_e_process(
    returns: list[float],
    *,
    lower_bound: float = 0.5,
    max_bet: float = 0.5,
    alpha: float = 0.05,
) -> dict:
    """Anytime-valid previsible betting e-process under H0: E[r_t | F_{t-1}] <= 0 with proven return floor (S016, S017)."""
    if not (0 < lower_bound <= 1.0 and 0 < max_bet < 1.0 and 0 < alpha < 1.0):
        raise ValueError("invalid e-process bounds")
    if not returns:
        return {"status": "INSUFFICIENT_DATA", "observations": 0}
    wealth, max_wealth, rejected_at = 1.0, 1.0, None
    running_sum, running_sq = 0.0, 0.0
    threshold = 1.0 / alpha
    for t, raw in enumerate(returns):
        r = float(raw)
        if not math.isfinite(r) or r < -lower_bound:
            raise ValueError(f"return {r} violates proven lower bound -{lower_bound}")
        # Strictly previsible bet lambda_t uses ONLY observations 0..t-1.
        if t < 5 or running_sq <= 0:
            lam = 0.0
        else:
            prev_mean = running_sum / t
            prev_var = max(running_sq / t - prev_mean * prev_mean, 1e-8)
            kelly = max(0.0, prev_mean / prev_var)
            lam = min(max_bet / lower_bound, 0.5 * kelly)
        factor = 1.0 + lam * r
        if factor <= 0:
            wealth = 0.0
            break
        wealth *= factor
        if wealth > max_wealth:
            max_wealth = wealth
        if rejected_at is None and wealth >= threshold:
            rejected_at = t + 1
        running_sum += r
        running_sq += r * r
    return {
        "schema": "sequential-e-process/1",
        "observations": len(returns),
        "lower_bound": lower_bound,
        "alpha": alpha,
        "threshold": threshold,
        "final_e_value": wealth,
        "max_e_value": max_wealth,
        "rejected_null": rejected_at is not None,
        "rejected_at_step": rejected_at,
        "anytime_valid_under_stated_floor": True,
        "independent_final_evidence": False,
    }
