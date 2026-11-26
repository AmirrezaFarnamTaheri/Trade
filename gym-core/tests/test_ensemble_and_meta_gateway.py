"""Tests for timeframe panel, slow sleeves (S1/S2/S5), self-financing ledger, and calibrated Meta-Gateway."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.meta_gateway import (
    AdaptiveVoteGateway,
    compute_calibration_diagnostics,
    evaluate_shadow_veto,
    run_synthetic_falsification_checks,
)
from gym.domain.paper_ledger import SelfFinancingLedger
from gym.domain.strategy_sleeves import compute_slow_sleeves
from gym.domain.timeframe_panel import BarPoint, resample_hourly_to_bucket

T0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)


def _bar(sym: str, day_idx: int, close: float, vol: float = 100.0) -> BarPoint:
    t0 = T0 + timedelta(days=day_idx)
    return BarPoint(sym, t0, t0 + timedelta(days=1), close * 0.995, close * 1.01, close * 0.99, close, vol, "NATIVE_1D", True, 1.0 if vol > 0 else 0.0, 0 if vol > 0 else 1, vol > 0, "FRESH" if vol > 0 else "STALE_MARK")


def test_hourly_resampling_completeness_offset_and_zero_volume_suppression():
    hourly = [
        BarPoint("BTCUSDT", T0 + timedelta(hours=h), T0 + timedelta(hours=h + 1), 100.0 + h, 102.0 + h, 99.0 + h, 101.0 + h, 0.0 if h >= 6 else 50.0, "NATIVE_1H", True, 0.0 if h >= 6 else 1.0, 0, h < 6, "FRESH")
        for h in range(12)
    ]
    b6 = resample_hourly_to_bucket(hourly, 6)
    assert len(b6) == 2
    assert b6[0].clock_complete is True and b6[0].entry_eligible is True
    # Second 6h bucket has zero volume -> entry_eligible must be False, mark_status STALE_MARK
    assert b6[1].clock_complete is True and b6[1].entry_eligible is False and b6[1].mark_status == "STALE_MARK"
    # +1h offset shifts bucket boundaries cleanly
    b6_off = resample_hourly_to_bucket(hourly, 6, offset_hours=1)
    assert any(not b.clock_complete for b in b6_off)


def test_self_financing_ledger_cash_buy_hold_sell_zero_cost_unchanged():
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0010"), fee_in_received_asset=True)
    # 1. Buy 50% BTC at 100 -> spend 500, receive 5 * (1 - 0.001) = 4.995 BTC, cash = 500
    f1 = ledger.rebalance_to_targets(T0, {"BTCUSDT": 0.50}, {"BTCUSDT": Decimal("100")})
    assert len(f1) == 1 and ledger.cash == Decimal("500.00000000")
    assert ledger.units["BTCUSDT"] == Decimal("4.995")
    assert ledger.mark_nav({"BTCUSDT": Decimal("100")}) == Decimal("999.5")

    # 2. Hold unchanged weight -> ZERO fills and ZERO extra fees
    f2 = ledger.rebalance_to_targets(T0 + timedelta(days=1), {"BTCUSDT": 0.49974987}, {"BTCUSDT": Decimal("100")})
    assert len(f2) == 0 and ledger.total_fees_quote_equiv == Decimal("0.5")

    # 3. Price doubles to 200 -> weight naturally drifts up, sell to flat -> fee debited in QUOTE
    assert ledger.current_weights(("BTCUSDT",), {"BTCUSDT": Decimal("200")})[0] > 0.66
    f3 = ledger.rebalance_to_targets(T0 + timedelta(days=2), {"BTCUSDT": 0.0}, {"BTCUSDT": Decimal("200")})
    assert len(f3) == 1 and f3[0].fee_asset == "QUOTE" and ledger.units["BTCUSDT"] == Decimal(0)
    expected_cash = Decimal("500") + Decimal("4.995") * Decimal("200") * Decimal("0.999")
    assert abs(ledger.cash - expected_cash) < Decimal("0.0001")


def test_slow_sleeves_causality_perturbation_and_gold_breadth_exclusion():
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")

    def _build_panel(shock_after: int | None = None):
        panel = {}
        for s_i, s in enumerate(syms):
            bars = []
            for d in range(160):
                px = 100.0 * (1.003 ** d) if s != "XAUTUSDT" else 2500.0 * (1.001 ** d)
                if shock_after is not None and d > shock_after:
                    px *= 0.5 if s_i % 2 == 0 else 1.8
                bars.append(_bar(s, d, px))
            panel[s] = bars
        return panel

    base_sigs = compute_slow_sleeves(_build_panel(), syms)
    pert_sigs = compute_slow_sleeves(_build_panel(shock_after=140), syms)
    cutoff_ts = T0 + timedelta(days=141)  # ts_avail of bar 140
    # Every signal on or before cutoff must be byte-identical after perturbing ALL future symbols!
    for ts in sorted(base_sigs):
        if ts <= cutoff_ts:
            assert base_sigs[ts] == pert_sigs[ts]
    # Crypto breadth excludes XAUTUSDT -> active_crypto_count == 4 (not 5)
    sample = base_sigs[cutoff_ts]["BTCUSDT"]
    assert sample.active_crypto_count == 4 and sample.s1_trend is not None


def test_meta_gateway_adaptive_vote_calibration_and_synthetic_falsification():
    av = AdaptiveVoteGateway()
    w, rem = av.current_weights(("s1", "s2"))
    # Two sleeves capped at 0.40 -> explicit 0.20 abstention remainder
    assert abs(sum(w.values()) - 0.80) < 1e-9 and abs(rem - 0.20) < 1e-9

    cal = compute_calibration_diagnostics([1, 0, 1, 0], [0.8, 0.2, 0.7, 0.3])
    assert cal.brier_skill_score > 0.5 and cal.ece < 0.3

    sh = evaluate_shadow_veto([(True, 120.0), (True, 80.0), (False, -150.0), (False, -50.0)])
    assert sh.avoided_losses_count == 2 and sh.foregone_winners_count == 0 and sh.net_veto_uplift_bps > 0

    synth = run_synthetic_falsification_checks(seed=42, n_samples=400)
    assert synth["null_panel"]["rejected_noise"] is True
    assert synth["planted_edge_panel"]["recovered_planted_edge"] is True
