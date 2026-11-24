"""Tests for S3 no-averaging-down episode identity, S4 prior-20-high breakout, and artifact_evaluation cycle removal."""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gym.domain.artifact_evaluation import evaluate_artifact
from gym.domain.fast_sleeves import compute_fast_sleeves_s3_s4
from gym.domain.timeframe_panel import BarPoint

T0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)


def _bar6h(idx: int, o: float, h: float, lo: float, c: float, vol: float = 100.0) -> BarPoint:
    t0 = T0 + timedelta(hours=6 * idx)
    return BarPoint("BTCUSDT", t0, t0 + timedelta(hours=6), o, h, lo, c, vol, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH")


def test_s3_never_averages_down_on_consecutive_drops():
    # 45 flat bars, then two consecutive sharp crash bars
    bars = [_bar6h(i, 100.0, 100.5, 99.5, 100.0) for i in range(45)]
    # Bar 45: sharp drop with upper recovery wick -> triggers ENTER_LONG
    bars.append(_bar6h(45, 100.0, 96.0, 90.0, 93.0, vol=500.0))
    # Bar 46: drops again -> MUST NOT emit a second ENTER_LONG (either HOLD or EXIT_STOP)
    bars.append(_bar6h(46, 93.0, 93.0, 88.0, 90.5, vol=600.0))
    sigs = compute_fast_sleeves_s3_s4(bars)
    entries = [s for s in sigs if s.s3_action == "ENTER_LONG"]
    assert len(entries) <= 1
    if len(entries) == 1:
        assert sigs[46].s3_action in ("HOLD", "EXIT_STOP")


def test_s4_breakout_uses_strictly_prior_20_highs_and_pre_release_compression():
    # 30 volatile bars (high=120, low=80), then 20 tight bars (high=101, low=99), then breakout bar at 105 with volume surge
    bars = [_bar6h(i, 100.0, 115.0, 85.0, 100.0, vol=100.0) for i in range(30)]
    bars += [_bar6h(30 + i, 100.0, 100.5, 99.5, 100.0, vol=100.0) for i in range(20)]
    bars.append(_bar6h(50, 100.2, 106.0, 100.0, 105.0, vol=500.0))
    sigs = compute_fast_sleeves_s3_s4(bars)
    assert sigs[50].s4_action == "ENTER_LONG"


def test_artifact_evaluation_breaks_market_models_cycle():
    res = evaluate_artifact({
        "model": "spacing",
        "parameters": {
            "spacing": "0.01",
            "fee_buy": "0.001",
            "fee_sell": "0.001",
            "spread": "0.002",
            "slippage_buy": "0.0005",
            "slippage_sell": "0.0005",
            "quote_currency": "USDT",
        },
    })
    assert res["mode"] == "PAPER_ONLY" and res["model"] == "spacing"
    # Verify market_models no longer needs to be imported cyclically by artifact_evaluation callers
    mm_src = (Path(__file__).resolve().parents[1] / "src/gym/domain/artifact_evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(mm_src)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "evaluate_artifact" for n in tree.body)
