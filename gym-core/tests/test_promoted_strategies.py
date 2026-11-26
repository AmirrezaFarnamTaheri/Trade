"""Unit and integration tests for promoted paper-only strategies and main-engine integration."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from gym.domain.bars import Bar, BarSpec
from gym.domain.promoted_strategies import (
    PROMOTED_STRATEGY_MANIFEST,
    SlowCorePolicy,
    SlowS1Trend,
    admit_conditional_ignition,
    apply_cost_aware_band,
    apply_metals_reserve,
)
from gym.domain.registry import catalog, create_strategy
from gym.domain.strategy import Snapshot
from gym.services.promoted_portfolio import run_promoted_reference_portfolio


def _bar(ts: datetime, close: Decimal) -> Bar:
    spec = BarSpec("1day", "MID")
    return Bar("BTCUSDT", spec, ts - timedelta(days=1), ts, ts, close, close, close, close, Decimal("10"), 1, False)


def _snap(ts: datetime, close: Decimal, *, with_quote: bool = True) -> Snapshot:
    return Snapshot(
        as_of=ts,
        symbol="BTCUSDT",
        bar=_bar(ts, close),
        bid=close - Decimal("0.5") if with_quote else None,
        ask=close + Decimal("0.5") if with_quote else None,
        quote_time=ts if with_quote else None,
    )


def test_promoted_manifest_classifies_winners_challengers_and_retirements() -> None:
    assert PROMOTED_STRATEGY_MANIFEST["slow-s1-s5-cost-aware"]["tier"] == "REFERENCE_DEFAULT"
    assert PROMOTED_STRATEGY_MANIFEST["multi-issuer-metals-reserve"]["tier"] == "REFERENCE_DEFAULT"
    assert PROMOTED_STRATEGY_MANIFEST["momentum-ignition-2h-shadow"]["tier"] == "SHADOW_CHALLENGER"
    assert PROMOTED_STRATEGY_MANIFEST["bellman-early-exit"]["tier"] == "RETIRED_PARKED"
    assert PROMOTED_STRATEGY_MANIFEST["four-quadrant-leveraged-macro"]["tier"] == "RETIRED_PARKED"


def test_apply_cost_aware_band_suppresses_small_churn_and_allows_exits() -> None:
    cur = {"BTCUSDT": 0.25, "ETHUSDT": 0.20, "SOLUSDT": 0.15}
    # BTC change (+0.01) is inside 3.2% band -> held at 0.25
    # ETH target is 0.0 -> full exit MUST always execute
    # SOL change (+0.10) exceeds band -> updates to 0.25
    tgt = {"BTCUSDT": 0.26, "ETHUSDT": 0.0, "SOLUSDT": 0.25}
    out = apply_cost_aware_band(tgt, cur, leg_fee_rate=0.0016, min_band=0.032)
    assert out["BTCUSDT"] == pytest.approx(0.25)
    assert "ETHUSDT" not in out
    assert out["SOLUSDT"] == pytest.approx(0.25)

    # Gross cap rescales cleanly
    capped = apply_cost_aware_band({"A": 0.8, "B": 0.6}, {}, max_gross=0.95)
    assert sum(capped.values()) == pytest.approx(0.95, abs=1e-4)


def test_apply_metals_reserve_uses_only_free_cash_headroom() -> None:
    slow = {"BTCUSDT": 0.70, "XAUTUSDT": 0.10}
    reserve = {"XAUTUSDT": 0.25, "PAXGUSDT": 0.15, "SLVONUSDT": 0.10}
    out = apply_metals_reserve(slow, reserve, max_invested=0.95)
    # Free cash = 0.95 - 0.80 = 0.15 -> PAXGUSDT gets up to 0.15 (sorted order: PAXGUSDT first)
    assert sum(out.values()) <= 0.95 + 1e-6
    assert out["BTCUSDT"] == pytest.approx(0.70)
    assert out["PAXGUSDT"] == pytest.approx(0.15)


def test_admit_conditional_ignition_protects_slow_reserve() -> None:
    # 15% of $1,000 = $150 protected floor -> $200 cash leaves $50 spendable
    amt, status = admit_conditional_ignition(200.0, 1000.0, 40.0, slow_reserve_frac=0.15)
    assert status == "FULL" and amt == pytest.approx(40.0)

    amt_p, status_p = admit_conditional_ignition(200.0, 1000.0, 80.0, slow_reserve_frac=0.15)
    assert status_p == "PARTIAL" and amt_p == pytest.approx(50.0)

    amt_r, status_r = admit_conditional_ignition(155.0, 1000.0, 80.0, slow_reserve_frac=0.15, min_notional=10.0)
    assert status_r == "REJECTED_RESERVE" and amt_r == 0.0

    amt_i, status_i = admit_conditional_ignition(200.0, 1000.0, 0.0)
    assert status_i == "REJECTED_INVALID" and amt_i == 0.0


def test_slow_s1_trend_strategy_registry_and_lifecycle() -> None:
    ids = {item["id"] for item in catalog()}
    assert "slow-s1-trend" in ids

    with pytest.raises(ValueError):
        SlowS1Trend(fast=16, mid=8, slow=32)
    with pytest.raises(ValueError):
        SlowS1Trend(fast=2, mid=4, slow=8, hysteresis_bps=-1)

    strat = create_strategy("slow-s1-trend", {"fast": 2, "mid": 4, "slow": 8, "hysteresis_bps": 10})
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # Warmup bars -> ABSTAIN_WARMUP
    act, _, _, _ = strat.decide(_snap(t0, Decimal("100")), False)
    assert act == "ABSTAIN_WARMUP"

    # Strong monotonic uptrend across 60 bars -> BUY_REQUEST
    last_action = None
    for i in range(1, 65):
        px = Decimal(100 + i * 2)
        act, _, _, _ = strat.decide(_snap(t0 + timedelta(days=i), px), False)
        last_action = act
    assert last_action == "BUY_REQUEST"

    # Missing quote after warmup -> ABSTAIN_NO_QUOTE
    act_nq, _, _, _ = strat.decide(_snap(t0 + timedelta(days=65), Decimal("230"), with_quote=False), True)
    assert act_nq == "ABSTAIN_NO_QUOTE"

    # Sharp breakdown below regime EMA -> SELL_REQUEST while holding
    sell_seen = False
    for i in range(66, 95):
        px = Decimal(max(20, 230 - (i - 65) * 10))
        act, _, _, _ = strat.decide(_snap(t0 + timedelta(days=i), px), True)
        if act == "SELL_REQUEST":
            sell_seen = True
            break
    assert sell_seen is True


def test_promoted_reference_portfolio_handles_empty_db_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t INTEGER, o TEXT, h TEXT, l TEXT, c TEXT, v TEXT)")
    con.commit()
    con.close()

    res = run_promoted_reference_portfolio(db_path, policy=SlowCorePolicy())
    assert res["status"] == "INSUFFICIENT_CANDLES"
    assert res["mode"] == "PAPER_ONLY"
    assert res["executor_state"] == "DISARMED"
    assert res["arms"] == []


def test_promoted_reference_portfolio_runs_all_arms_on_synthetic_db(tmp_path: Path) -> None:
    from gym.domain.multi_asset_research import BASE_13_SYMBOLS

    db_path = tmp_path / "synth.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t TEXT, o TEXT, h TEXT, l TEXT, c TEXT, v TEXT)")
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    for idx, sym in enumerate(BASE_13_SYMBOLS, start=1):
        con.execute("INSERT INTO instruments VALUES (?, ?)", (idx, sym))
        px = 100.0 + idx * 5.0
        for d in range(170):
            ts = (t0 + timedelta(days=d)).isoformat().replace("+00:00", "Z")
            px = px * (1.003 if (d % 5 != 0) else 0.994)
            con.execute(
                "INSERT INTO venue_candles VALUES (?, '1d', ?, ?, ?, ?, ?, ?)",
                (idx, ts, f"{px * 0.995:.4f}", f"{px * 1.01:.4f}", f"{px * 0.99:.4f}", f"{px:.4f}", "500.0"),
            )
    con.commit()
    con.close()

    res = run_promoted_reference_portfolio(db_path, lookback_days=30, policy=SlowCorePolicy())
    assert res["status"] == "OK"
    assert res["mode"] == "PAPER_ONLY"
    assert res["executor_state"] == "DISARMED"
    arm_names = [a["arm"] for a in res["arms"]]
    assert arm_names == [
        "PROMOTED_SLOW_S1_S5_COST_AWARE",
        "SLOW_S1_S5_IMMEDIATE_CONTROL",
        "SLOW_40PCT_PLUS_CASH_CONTROL",
        "CASH_100PCT_CONTROL",
    ]
    assert res["arms"][-1]["ending_nav"] == 1000.0
    assert res["arms"][0]["fills"] <= res["arms"][1]["fills"]
