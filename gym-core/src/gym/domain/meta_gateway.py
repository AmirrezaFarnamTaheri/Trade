"""Meta-Gateway: Adaptive Voting control, veto-only calibrated L2 Logistic challenger & synthetic falsification (v2 spec §3–§4)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .strategy_sleeves import SleeveSignal

FEATURE_NAMES = (
    "s1_trend",
    "s2_residual_mom",
    "s5_defensive_gold",
    "consensus_score",
    "sleeve_std",
    "crypto_breadth",
    "yang_zhang_vol",
    "downside_vol_ratio",
    "fee_to_vol_ratio",
)


def extract_gateway_features(
    sig: SleeveSignal,
    *,
    consensus_score: float,
    round_trip_fee_bps: float = 26.0,
) -> list[float]:
    """Build deterministic fixed-order feature vector; absent sleeves encode as NaN for fold-local imputation."""
    vals = [v for v in (sig.s1_trend, sig.s2_residual_mom, sig.s5_defensive_gold) if v is not None]
    if len(vals) >= 2:
        m = sum(vals) / len(vals)
        s_std = math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))
    else:
        s_std = 0.0
    vol_bps = max(sig.yang_zhang_vol * 10000.0, 1.0)
    return [
        float("nan") if sig.s1_trend is None else float(sig.s1_trend),
        float("nan") if sig.s2_residual_mom is None else float(sig.s2_residual_mom),
        float("nan") if sig.s5_defensive_gold is None else float(sig.s5_defensive_gold),
        float(consensus_score),
        float(s_std),
        float("nan") if sig.crypto_breadth is None else float(sig.crypto_breadth),
        float(sig.yang_zhang_vol),
        float(sig.downside_vol_ratio),
        float(round_trip_fee_bps / vol_bps),
    ]


class AdaptiveVoteGateway:
    """Non-ML online decayed-Sharpe voting control with capped weights and explicit abstention remainder."""

    def __init__(
        self,
        sleeve_names: tuple[str, ...] = ("s1", "s2", "s5"),
        *,
        eta: float = 0.5,
        min_weight: float = 0.05,
        max_weight: float = 0.40,
    ) -> None:
        self.sleeve_names = sleeve_names
        self.eta = eta
        self.min_weight = min_weight
        self.max_weight = max_weight
        self._sum_r: dict[str, float] = {k: 0.0 for k in sleeve_names}
        self._sum_r2: dict[str, float] = {k: 0.0 for k in sleeve_names}
        self._count: dict[str, int] = {k: 0 for k in sleeve_names}

    def update_realized_outcome(self, sleeve: str, realized_return: float) -> None:
        if sleeve in self._count:
            self._sum_r[sleeve] += realized_return
            self._sum_r2[sleeve] += realized_return * realized_return
            self._count[sleeve] += 1

    def current_weights(self, available: tuple[str, ...]) -> tuple[dict[str, float], float]:
        """Return (capped sleeve weights, explicit abstention remainder)."""
        if not available:
            return {}, 1.0
        raw: dict[str, float] = {}
        for k in available:
            n = self._count.get(k, 0)
            if n < 10:
                sr = 0.0
            else:
                mean = self._sum_r[k] / n
                var = max(self._sum_r2[k] / n - mean * mean, 1e-8)
                sr = max(-2.0, min(2.0, mean / math.sqrt(var)))
            raw[k] = math.exp(self.eta * sr)
        total = sum(raw.values())
        weights = {k: max(self.min_weight, min(self.max_weight, raw[k] / total)) for k in available}
        w_sum = sum(weights.values())
        if w_sum > 1.0:
            weights = {k: v / w_sum for k, v in weights.items()}
            w_sum = 1.0
        return weights, max(0.0, 1.0 - w_sum)

    def combine_signal(self, sig: SleeveSignal) -> float:
        score_map = {"s1": sig.s1_trend, "s2": sig.s2_residual_mom, "s5": sig.s5_defensive_gold}
        avail = tuple(k for k in self.sleeve_names if score_map.get(k) is not None)
        weights, _ = self.current_weights(avail)
        return sum(weights[k] * float(score_map[k]) for k in avail)


@dataclass(frozen=True)
class CalibrationDiagnostics:
    n_samples: int
    base_rate: float
    brier_score: float
    base_rate_brier: float
    brier_skill_score: float
    log_loss: float
    ece: float


def compute_calibration_diagnostics(y_true: list[int], y_prob: list[float], *, n_bins: int = 10) -> CalibrationDiagnostics:
    """Compute Brier score, training-base-rate Brier Skill Score, log loss, and ECE."""
    n = len(y_true)
    if n == 0:
        return CalibrationDiagnostics(0, 0.0, 0.25, 0.25, 0.0, 0.693, 0.0)
    base_rate = sum(y_true) / n
    brier = sum((p - y) ** 2 for y, p in zip(y_true, y_prob, strict=True)) / n
    base_brier = sum((base_rate - y) ** 2 for y in y_true) / n
    bss = (1.0 - brier / base_brier) if base_brier > 1e-12 else 0.0
    eps = 1e-9
    ll = -sum(
        y * math.log(max(eps, min(1.0 - eps, p))) + (1 - y) * math.log(max(eps, min(1.0 - eps, 1.0 - p)))
        for y, p in zip(y_true, y_prob, strict=True)
    ) / n

    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idxs = [i for i, p in enumerate(y_prob) if (lo <= p < hi) or (b == n_bins - 1 and p == 1.0)]
        if not idxs:
            continue
        avg_p = sum(y_prob[i] for i in idxs) / len(idxs)
        avg_y = sum(y_true[i] for i in idxs) / len(idxs)
        ece += (len(idxs) / n) * abs(avg_p - avg_y)
    return CalibrationDiagnostics(n, base_rate, brier, base_brier, bss, ll, ece)


@dataclass(frozen=True)
class ShadowVetoStats:
    total_proposals: int
    accepted_count: int
    vetoed_count: int
    accepted_mean_net_bps: float
    vetoed_mean_net_bps: float
    avoided_losses_count: int
    foregone_winners_count: int
    net_veto_uplift_bps: float


class LogisticVetoGateway:
    """Veto-only L2 LogisticRegression with chronological inner-fold sigmoid calibration & EV gating.

    Lazily imports scikit-learn inside fit/predict so the core app remains importable without ML extras.
    """

    def __init__(self, *, c_reg: float = 0.2, safety_margin_bps: float = 5.0) -> None:
        self.c_reg = c_reg
        self.safety_margin_bps = safety_margin_bps
        self._pipeline = None
        self._cal_a = 1.0
        self._cal_b = 0.0
        self._mean_win_bps = 150.0
        self._mean_loss_bps = 100.0
        self._fitted = False

    def fit(
        self,
        features: list[list[float]],
        net_returns_bps: list[float],
        *,
        sample_weights: list[float] | None = None,
        purge_gap: int = 5,
        timestamps: list | None = None,
    ) -> CalibrationDiagnostics:
        """Fit L2 logistic on first 75% chronologically, calibrate sigmoid on last 25% after UTC-day or row purge_gap."""
        from datetime import timedelta

        import numpy as np
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import RobustScaler

        n = len(features)
        if n < 40:
            raise ValueError("LogisticVetoGateway requires >= 40 chronological training proposals")

        y = [1 if r > 0.0 else 0 for r in net_returns_bps]
        if len(set(y)) < 2:
            self._fitted = False
            return compute_calibration_diagnostics(y, [sum(y) / n] * n)

        split = int(0.75 * n)
        if timestamps is not None and len(timestamps) == n:
            cutoff_ts = timestamps[split - 1] + timedelta(days=purge_gap)
            cal_start = next((i for i in range(split, n) if timestamps[i] >= cutoff_ts), n - 10)
            cal_start = min(n - 10, max(split, cal_start))
        else:
            cal_start = min(n - 10, split + purge_gap)
        x_arr = np.asarray(features, dtype=float)
        y_arr = np.asarray(y, dtype=int)
        w_arr = np.asarray(sample_weights if sample_weights is not None else [1.0] * n, dtype=float)

        pipe = Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", RobustScaler()),
            ("clf", LogisticRegression(C=self.c_reg, max_iter=500)),
        ])
        pipe.fit(x_arr[:split], y_arr[:split], clf__sample_weight=w_arr[:split])

        # Chronological inner-fold Platt sigmoid calibration: logit(p) -> a*logit + b
        raw_cal_logits = pipe.decision_function(x_arr[cal_start:]).reshape(-1, 1)
        y_cal = y_arr[cal_start:]
        if len(set(y_cal.tolist())) == 2:
            cal_lr = LogisticRegression(C=1.0, max_iter=200)
            cal_lr.fit(raw_cal_logits, y_cal)
            self._cal_a = float(cal_lr.coef_[0][0])
            self._cal_b = float(cal_lr.intercept_[0])
        else:
            self._cal_a, self._cal_b = 1.0, 0.0

        wins = [r for r in net_returns_bps[:split] if r > 0]
        losses = [-r for r in net_returns_bps[:split] if r <= 0]
        self._mean_win_bps = sum(wins) / len(wins) if wins else 100.0
        self._mean_loss_bps = sum(losses) / len(losses) if losses else 100.0
        self._pipeline = pipe
        self._fitted = True

        cal_probs = [self._sigmoid(self._cal_a * float(z[0]) + self._cal_b) for z in raw_cal_logits]
        return compute_calibration_diagnostics(y_cal.tolist(), cal_probs)

    @staticmethod
    def _sigmoid(x: float) -> float:
        x_c = max(-30.0, min(30.0, x))
        return 1.0 / (1.0 + math.exp(-x_c))

    def predict_proba(self, feature_row: list[float]) -> float:
        if not self._fitted or self._pipeline is None:
            return 0.5
        import numpy as np

        z = float(self._pipeline.decision_function(np.asarray([feature_row], dtype=float))[0])
        return self._sigmoid(self._cal_a * z + self._cal_b)

    def should_accept(self, feature_row: list[float], *, incremental_cost_bps: float = 0.0) -> tuple[bool, float, float]:
        """Expected-value gate (no fixed 52% floor): returns (accept, calibrated_p, expected_ev_bps)."""
        p = self.predict_proba(feature_row)
        ev_bps = p * self._mean_win_bps - (1.0 - p) * self._mean_loss_bps - incremental_cost_bps
        return (ev_bps > self.safety_margin_bps), p, ev_bps


def evaluate_shadow_veto(
    decisions: list[tuple[bool, float]],
) -> ShadowVetoStats:
    """Score accepted vs rejected proposals on identical candidate stream."""
    accepted = [r for acc, r in decisions if acc]
    vetoed = [r for acc, r in decisions if not acc]
    acc_mean = sum(accepted) / len(accepted) if accepted else 0.0
    vet_mean = sum(vetoed) / len(vetoed) if vetoed else 0.0
    avoided_losses = sum(1 for r in vetoed if r < 0)
    foregone_wins = sum(1 for r in vetoed if r > 0)
    all_mean = sum(r for _, r in decisions) / len(decisions) if decisions else 0.0
    return ShadowVetoStats(
        total_proposals=len(decisions),
        accepted_count=len(accepted),
        vetoed_count=len(vetoed),
        accepted_mean_net_bps=round(acc_mean, 2),
        vetoed_mean_net_bps=round(vet_mean, 2),
        avoided_losses_count=avoided_losses,
        foregone_winners_count=foregone_wins,
        net_veto_uplift_bps=round(acc_mean - all_mean, 2),
    )


def run_synthetic_falsification_checks(*, seed: int = 42, n_samples: int = 400) -> dict:
    """Two mandatory pre-race synthetic falsification checks: pure null noise vs planted feasible edge."""
    rng = random.Random(seed)

    # 1. Pure Null Panel (common market shock + zero conditional edge)
    null_x: list[list[float]] = []
    null_r: list[float] = []
    for _ in range(n_samples):
        shock = rng.gauss(0.0, 120.0)
        feats = [rng.gauss(0.0, 1.0) for _ in range(len(FEATURE_NAMES))]
        null_x.append(feats)
        null_r.append(shock - 26.0)  # net after 26 bps cost, zero conditional edge

    # 2. Planted Feasible Edge Panel (feature 0 & 3 cleanly predict +180 bps net winners)
    edge_x: list[list[float]] = []
    edge_r: list[float] = []
    for _ in range(n_samples):
        feats = [rng.gauss(0.0, 1.0) for _ in range(len(FEATURE_NAMES))]
        true_signal = 1.2 * feats[0] + 0.8 * feats[3]
        ret_bps = (160.0 if true_signal > 0.3 else -120.0) + rng.gauss(0.0, 70.0)
        edge_x.append(feats)
        edge_r.append(ret_bps)

    split = int(0.70 * n_samples)
    gw_null = LogisticVetoGateway(c_reg=0.2, safety_margin_bps=10.0)
    gw_null.fit(null_x[:split], null_r[:split])
    null_oos = [gw_null.should_accept(x)[0] for x in null_x[split:]]
    null_acc_rate = sum(null_oos) / len(null_oos)
    null_probs = [gw_null.predict_proba(x) for x in null_x[split:]]
    null_cal = compute_calibration_diagnostics([1 if r > 0 else 0 for r in null_r[split:]], null_probs)

    gw_edge = LogisticVetoGateway(c_reg=0.2, safety_margin_bps=10.0)
    gw_edge.fit(edge_x[:split], edge_r[:split])
    edge_decisions = [(gw_edge.should_accept(x)[0], r) for x, r in zip(edge_x[split:], edge_r[split:], strict=True)]
    edge_shadow = evaluate_shadow_veto(edge_decisions)
    edge_probs = [gw_edge.predict_proba(x) for x in edge_x[split:]]
    edge_cal = compute_calibration_diagnostics([1 if r > 0 else 0 for r in edge_r[split:]], edge_probs)

    return {
        "null_panel": {
            "oos_acceptance_rate": round(null_acc_rate, 3),
            "oos_brier_skill_score": round(null_cal.brier_skill_score, 4),
            "rejected_noise": null_cal.brier_skill_score < 0.05,
        },
        "planted_edge_panel": {
            "oos_brier_skill_score": round(edge_cal.brier_skill_score, 4),
            "accepted_mean_net_bps": edge_shadow.accepted_mean_net_bps,
            "vetoed_mean_net_bps": edge_shadow.vetoed_mean_net_bps,
            "net_veto_uplift_bps": edge_shadow.net_veto_uplift_bps,
            "recovered_planted_edge": edge_cal.brier_skill_score > 0.10 and edge_shadow.net_veto_uplift_bps > 25.0,
        },
    }
