"""Tests for Workstream 3: Quantitative Modeling & Statistical Governance (spec §6.1–§6.5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.async_covariance import (
    coarse_bar_shrunk_covariance,
    hayashi_yoshida_covariance,
)
from gym.domain.kalman_models import (
    KalmanBasisFilter,
    classify_gap,
    irregular_decay_alpha,
    leave_one_out_fx_interval,
)
from gym.domain.model import BookTop
from gym.domain.quote_hazard import (
    PassiveAttemptRecord,
    fit_execution_outcome_model,
    hindsight_dp_ceiling,
    isotonic_pava,
)
from gym.domain.signal_gatekeeper import (
    append_mix_journal_v2,
    build_mix_journal_v2_entry,
    check_causality_perturbation,
    operational_health_check_sealed_window,
    run_path_preserving_placebo,
    simulate_joint_gate_power,
)
from gym.domain.venue_contracts import wallex_l1_fee_schedule
from gym.domain.volatility_models import (
    OhlcBar,
    asymmetric_ewma_volatility,
    yang_zhang_volatility,
)

T0 = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def _top(sym: str, offset_s: float, bid: str, ask: str, qty: str = "10") -> BookTop:
    return BookTop(sym, T0 + timedelta(seconds=offset_s), Decimal(bid), Decimal(ask), Decimal(qty), Decimal(qty), frozenset())


def test_kalman_models_leave_one_out_fx_and_traded_leg_signs():
    assert classify_gap(60.0, shard_connected=False) == "CAPTURE_OUTAGE"
    assert 0.0 < irregular_decay_alpha(10.0, 0.1) < 1.0

    # 6 dual-quoted pairs at FX=100,000, except BTC shocked to 110,000 on TMN leg
    quotes = {
        "BTCTMN": _top("BTCTMN", 0, "11000000000", "11010000000"),
        "BTCUSDT": _top("BTCUSDT", 0, "100000", "100010"),
        "ETHTMN": _top("ETHTMN", 0, "300000000", "300100000"),
        "ETHUSDT": _top("ETHUSDT", 0, "3000", "3001"),
        "SOLTMN": _top("SOLTMN", 0, "20000000", "20010000"),
        "SOLUSDT": _top("SOLUSDT", 0, "200", "200.1"),
        "XRPTMN": _top("XRPTMN", 0, "100000", "100100"),
        "XRPUSDT": _top("XRPUSDT", 0, "1.000", "1.001"),
        "XAUTTMN": _top("XAUTTMN", 0, "260000000", "260100000"),
        "XAUTUSDT": _top("XAUTUSDT", 0, "2600", "2601"),
        "PEPETMN": _top("PEPETMN", 0, "1.0", "1.001"),
        "PEPEUSDT": _top("PEPEUSDT", 0, "0.00001", "0.00001001"),
    }
    est = leave_one_out_fx_interval("BTC", quotes, T0)
    assert est.status == "OK" and est.peer_count == 5 and est.fx_center is not None
    # BTC's +10% shock has ZERO influence on peer FX center (~100,000)
    assert Decimal("99500") < est.fx_center < Decimal("100500")

    kf = KalmanBasisFilter(z_entry=1.0)
    kf.update(as_of=T0, coin_tmn_mid=Decimal("10000000000"), coin_usdt_mid=Decimal("100000"), peer_fx_center=Decimal("100000"))
    # Now BTCTMN jumps +100 bps rich relative to BTCUSDT & peer FX
    out = kf.update(as_of=T0 + timedelta(seconds=60), coin_tmn_mid=Decimal("10100000000"), coin_usdt_mid=Decimal("100000"), peer_fx_center=Decimal("100000"))
    assert out.z_score > 1.0
    assert out.forecast_usdt_leg > 0  # BUY BTCUSDT
    assert out.forecast_tmn_leg <= 0  # SELL/skip BTCTMN


def test_async_covariance_and_volatility_models():
    s_a = [(T0 + timedelta(seconds=i * 10), 100.0 + i * 0.5) for i in range(10)]
    s_b = [(T0 + timedelta(seconds=i * 10 + 3), 200.0 + i * 1.0) for i in range(10)]
    hy = hayashi_yoshida_covariance({"A": s_a, "B": s_b})
    assert hy.symbols == ("A", "B") and hy.matrix[0][1] > 0 and hy.joint_coverage_ratio == 1.0

    syms, coarse = coarse_bar_shrunk_covariance({"A": [0.01, -0.02, 0.03, 0.01], "B": [0.02, -0.03, 0.04, 0.02]})
    assert syms == ("A", "B") and coarse[0][1] > 0

    bars = [OhlcBar(100, 105, 98, 103), OhlcBar(106, 110, 104, 108), OhlcBar(107, 112, 102, 105), OhlcBar(104, 109, 101, 107)]
    assert yang_zhang_volatility(bars) > 0.01
    down_vol = asymmetric_ewma_volatility([-0.03, -0.02, -0.04])
    up_vol = asymmetric_ewma_volatility([0.03, 0.02, 0.04])
    assert down_vol > up_vol


def test_hindsight_dp_ceiling_pava_and_outcome_model():
    sched = wallex_l1_fee_schedule("USDT", observed_at=T0)
    # Flat market: ceiling must NOT beat cash hurdle
    flat = [_top("BTCUSDT", i * 60, "100", "100.2", "50") for i in range(10)]
    c_flat = hindsight_dp_ceiling(flat, initial_cash_quote=Decimal("1000"), fee_schedule=sched)
    assert c_flat.max_terminal_cash_quote == Decimal("1000") and c_flat.beats_cash_hurdle is False

    # Clear +5% round-trip swing: ceiling beats hurdle cleanly
    swing = [_top("BTCUSDT", 0, "99.9", "100.0", "50"), _top("BTCUSDT", 60, "105.0", "105.1", "50")]
    c_swing = hindsight_dp_ceiling(swing, initial_cash_quote=Decimal("1000"), fee_schedule=sched)
    assert c_swing.beats_cash_hurdle is True and c_swing.net_return_bps > Decimal("450")

    mono = isotonic_pava([0.7, 0.8, 0.4, 0.5, 0.1], decreasing=True)
    assert all(mono[i] >= mono[i + 1] - 1e-12 for i in range(len(mono) - 1))

    recs = [
        PassiveAttemptRecord("0bps", "FILLED_BENIGN", 8.0, False),
        PassiveAttemptRecord("0bps", "FILLED_ADVERSE", -12.0, False),
        PassiveAttemptRecord("0bps", "EXPIRED_UNFILLED", 0.0, True),
    ]
    model = fit_execution_outcome_model(recs, unfilled_mandatory_completion_cost_bps=-25.0)
    assert abs(sum(model["0bps"].outcome_probs.values()) - 1.0) < 1e-12
    assert model["0bps"].brier_score >= 0.0


def test_signal_gatekeeper_power_placebo_causality_and_mix_v2(tmp_path):
    # Power simulation with strong synthetic edge clears >= 80% power
    hist = [0.001, -0.001, 0.002, -0.002, 0.0005, -0.0005, 0.0015, -0.0015]
    pwr = simulate_joint_gate_power(hist, edge_bps_per_step=15.0, horizon_steps=120, n_trials=5, replications=100, e_lower_bound=0.02)
    assert pwr.meets_80pct_power is True

    # Planted synthetic alpha passes path-preserving placebo on a non-periodic return path
    import random
    rng = random.Random(7)
    rets = [rng.gauss(0.0, 0.01) for _ in range(80)]
    planted_sigs = [1.0 if r > 0 else -1.0 for r in rets]
    placebo_alpha = run_path_preserving_placebo(rets, planted_sigs, replications=500)
    assert placebo_alpha.p_value < 0.05

    # Causality perturbation gate: causal momentum passes, future-peeking close[t+1] FAILS!
    prices = [100.0 + i * 0.5 for i in range(20)]
    causal_fn = lambda ps: [0.0 if i == 0 else ps[i] - ps[i - 1] for i in range(len(ps))]
    leaking_fn = lambda ps: [ps[min(i + 1, len(ps) - 1)] - ps[i] for i in range(len(ps))]
    assert check_causality_perturbation(causal_fn, prices, cutoff_index=10) is True
    assert check_causality_perturbation(leaking_fn, prices, cutoff_index=10) is False

    # Mix journal v2 refuses overwriting v1 control and enforces earliest_release >= start + 90d
    entry = build_mix_journal_v2_entry(
        as_of=T0,
        cohort_start=T0,
        symbol="BTCUSDT",
        intended_size_usdt=Decimal("250"),
        displayed_depth_usdt=Decimal("5000"),
        fee_vintage="L1-2026-11-24",
        missed_qty_usdt=Decimal("0"),
        tracking_error_bps=Decimal("3.5"),
    )
    v2_path = tmp_path / "mix-journal-v2.jsonl"
    append_mix_journal_v2(v2_path, entry)
    assert v2_path.exists()

    health = operational_health_check_sealed_window(
        "mix-journal-v2",
        as_of=datetime(2027, 2, 8, tzinfo=UTC),
        earliest_release=T0 + timedelta(days=90),
        expected_days=76,
        recorded_days=76,
    )
    assert health.mature_for_scoring is False and health.status == "IMMATURE_AT_CHECKPOINT"
