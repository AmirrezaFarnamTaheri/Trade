"""Tests for S2 incumbent hysteresis, OLS factor attribution, causal execution quantile, and cycle removal."""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.domain.execution_schedule import (
    causal_spread_quantile_bps,
    compare_execution_timing_arms,
)
from gym.domain.leader_attribution import (
    apply_s2_incumbent_hysteresis,
    decompose_factor_attribution,
)
from gym.domain.model import BookTop
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.venue_contracts import wallex_l1_fee_schedule

T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


def test_market_models_has_no_forecast_or_portfolio_imports() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "gym" / "domain" / "market_models.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "forecast_evaluation" not in imported
    assert "portfolio" not in imported


def test_decompose_factor_attribution_recovers_exact_alpha_and_betas() -> None:
    btc = {f"2026-01-{i:02d}": (0.01 if i % 2 == 0 else -0.005) + 0.001 * (i % 3) for i in range(1, 31)}
    gold = {f"2026-01-{i:02d}": (0.004 if i % 3 == 0 else -0.002) for i in range(1, 31)}
    port = {d: 0.0005 + 0.4 * btc[d] + 0.3 * gold[d] for d in btc}
    fa = decompose_factor_attribution(port, btc, gold)
    assert fa.observations == 30
    assert abs(fa.beta_btc - 0.4) < 1e-3
    assert abs(fa.beta_gold - 0.3) < 1e-3
    assert abs(fa.ann_alpha_pct - (0.0005 * 365.0 * 100.0)) < 0.05
    assert fa.r_squared > 0.999


def test_s2_incumbent_hysteresis_retains_incumbent_until_hold_band_exit() -> None:
    def _sig(sym: str, ts: datetime, s2: float) -> SleeveSignal:
        return SleeveSignal(
            symbol=sym, as_of=ts, s1_trend=0.2, s2_residual_mom=s2, s5_defensive_gold=None,
            crypto_breadth=0.6, active_crypto_count=4, yang_zhang_vol=0.03,
            downside_vol_ratio=1.0, eligible_for_entry=True,
        )

    t1, t2, t3 = T0, T0 + timedelta(days=1), T0 + timedelta(days=2)
    signals = {
        # Day 1: A is #1 (enters top 25%), B/C/D are lower
        t1: {"A": _sig("A", t1, 0.9), "B": _sig("B", t1, 0.4), "C": _sig("C", t1, 0.1), "D": _sig("D", t1, -0.2)},
        # Day 2: A slips to #2 (still inside top 50% hold band) -> retained! B is #1 -> enters!
        t2: {"A": _sig("A", t2, 0.2), "B": _sig("B", t2, 0.8), "C": _sig("C", t2, 0.05), "D": _sig("D", t2, -0.3)},
        # Day 3: A slips to #4 (outside hold band) -> exits to 0.0
        t3: {"A": _sig("A", t3, -0.4), "B": _sig("B", t3, 0.7), "C": _sig("C", t3, 0.3), "D": _sig("D", t3, 0.1)},
    }
    adj = apply_s2_incumbent_hysteresis(signals, entry_top_frac=0.25, hold_top_frac=0.50, hold_conviction_floor=0.35)
    assert adj[t1]["A"].s2_residual_mom == 0.9
    assert adj[t1]["B"].s2_residual_mom == 0.0
    assert adj[t2]["A"].s2_residual_mom == 0.35  # retained at floor!
    assert adj[t2]["B"].s2_residual_mom == 0.8
    assert adj[t3]["A"].s2_residual_mom == 0.0


def test_causal_spread_quantile_ignores_future_quotes_and_enforces_displayed_size() -> None:
    books = []
    # 25 prior wide-spread quotes (spread ~ 40 bps), followed by future tight quotes (spread ~ 2 bps)
    for i in range(25):
        books.append(BookTop("BTCUSDT", T0 + timedelta(seconds=i * 10), Decimal("100.00"), Decimal("100.40"), Decimal("1"), Decimal("1"), frozenset()))
    decided_at = T0 + timedelta(seconds=250)
    books.append(BookTop("BTCUSDT", decided_at, Decimal("100.00"), Decimal("100.40"), Decimal("0.5"), Decimal("0.5"), frozenset()))
    for i in range(1, 30):
        books.append(BookTop("BTCUSDT", decided_at + timedelta(seconds=i * 10), Decimal("100.00"), Decimal("100.02"), Decimal("10"), Decimal("10"), frozenset()))

    p35 = causal_spread_quantile_bps(books, decided_at)
    # Must reflect ONLY the ~40 bps prior quotes, NOT the 2 bps future quotes!
    assert p35 >= Decimal("35")

    sched = wallex_l1_fee_schedule("USDT")
    comp = compare_execution_timing_arms(
        "BTCUSDT", "BUY", Decimal("2.0"), decided_at, 60.0, books, [], sched,
        p35_spread_bps=None, enforce_displayed_size=True,
    )
    # Immediate arm only has 0.5 displayed ask_qty -> 1.5 remains unfilled!
    assert comp.immediate.filled_qty == Decimal("0.5")
    assert comp.immediate.unfilled_qty == Decimal("1.5")
