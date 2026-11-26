"""Canonical paper-only runner for the promoted Slow S1+S5 Reference Portfolio.

Unifies the promoted research winners (Slow S1+S5 + Cost-Aware No-Trade Band + matched
CASH and 40%-Slow+Cash controls) on one snapshot-consistent SelfFinancingLedger path.
Strictly read-only against market.db; TradingGYMExecutor remains DISARMED ($0 funded budget).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ..domain.multi_asset_research import BASE_13_SYMBOLS
from ..domain.paper_ledger import SelfFinancingLedger
from ..domain.promoted_strategies import (
    PROMOTED_STRATEGY_MANIFEST,
    SlowCorePolicy,
    apply_cost_aware_band,
)
from .experiments.ensemble_study import portfolio_metrics
from .experiments.io_utils import readonly_snapshot
from .experiments.strategy_promotion_and_revival_study import _build_frozen_slow_targets
from .experiments.unified_book_helpers import resolve_bar_prices


def _simulate_reference_arm(
    panel_1d: dict,
    slow_targets: dict[datetime, dict[str, float]],
    win_ts: list[datetime],
    *,
    arm_name: str,
    policy: SlowCorePolicy,
    exposure_scale: float = 1.0,
    use_cost_aware_band: bool = True,
    starting_cash: Decimal = Decimal("1000"),
) -> dict:
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    ledger = SelfFinancingLedger(
        starting_cash,
        fee_rate=Decimal(str(policy.leg_fee_rate)),
        fee_in_received_asset=True,
    )
    nav_by_date: dict[str, float] = {}
    last_px: dict[str, float] = {}

    for ts in win_ts:
        ef, tradable = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        ep = {s: Decimal(str(p)) for s, p in ef.items()}
        nav_now = float(ledger.mark_nav(ep))
        cur_w = {
            s: float(ledger.units.get(s, Decimal("0"))) * ef.get(s, 0.0) / max(1e-9, nav_now)
            for s in BASE_13_SYMBOLS
        }
        raw_t = {s: w * exposure_scale for s, w in slow_targets[ts].items()}
        if use_cost_aware_band:
            targets = apply_cost_aware_band(
                raw_t,
                cur_w,
                leg_fee_rate=policy.leg_fee_rate,
                min_band=policy.min_no_trade_band,
                fee_multiplier=policy.fee_band_multiplier,
                max_gross=policy.max_gross_weight,
            )
        else:
            targets = {s: w for s, w in raw_t.items() if w > 1e-6}
        ledger.rebalance_to_targets(ts, targets, ep, tradable_symbols=tradable)
        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(ep))

    metrics = portfolio_metrics(nav_by_date, starting_nav=float(starting_cash))
    return {
        "arm": arm_name,
        "ending_nav": metrics["ending_nav"],
        "ret_pct": metrics["ret_pct"],
        "ann_sharpe": metrics["ann_sharpe"],
        "max_dd_pct": metrics["max_dd_pct"],
        "fills": len(ledger.fills),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "days": len(nav_by_date),
    }


def run_promoted_reference_portfolio(
    db_path: Path,
    *,
    policy: SlowCorePolicy | None = None,
    lookback_days: int | None = None,
    as_of: datetime | None = None,
    starting_cash: Decimal = Decimal("1000"),
) -> dict:
    """Evaluate the promoted Slow S1+S5 Reference Portfolio plus matched Cash & 40%-Slow controls."""
    policy = policy or SlowCorePolicy()
    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            panel_1d = {s: load_keyed_candles(con, s, "1d", as_of=as_of) for s in BASE_13_SYMBOLS}
    finally:
        con.close()

    slow_targets, _, _ = _build_frozen_slow_targets(panel_1d)
    all_ts = sorted(slow_targets)
    if not all_ts:
        return {
            "status": "INSUFFICIENT_CANDLES",
            "mode": "PAPER_ONLY",
            "executor_state": "DISARMED",
            "arms": [],
        }
    if lookback_days is not None and lookback_days > 0:
        cutoff = all_ts[-1] - timedelta(days=lookback_days)
        win_ts = [t for t in all_ts if t >= cutoff]
    else:
        win_ts = all_ts

    ref_band = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="PROMOTED_SLOW_S1_S5_COST_AWARE", policy=policy,
        exposure_scale=1.0, use_cost_aware_band=True, starting_cash=starting_cash,
    )
    ref_raw = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="SLOW_S1_S5_IMMEDIATE_CONTROL", policy=policy,
        exposure_scale=1.0, use_cost_aware_band=False, starting_cash=starting_cash,
    )
    slow_40 = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="SLOW_40PCT_PLUS_CASH_CONTROL", policy=policy,
        exposure_scale=0.40, use_cost_aware_band=True, starting_cash=starting_cash,
    )
    cash_ctrl = {
        "arm": "CASH_100PCT_CONTROL",
        "ending_nav": round(float(starting_cash), 2),
        "ret_pct": 0.0,
        "ann_sharpe": 0.0,
        "max_dd_pct": 0.0,
        "fills": 0,
        "fees_usdt": 0.0,
        "days": len(win_ts),
    }
    return {
        "status": "OK",
        "generated_at_utc": (as_of or datetime.now(UTC)).isoformat(),
        "mode": "PAPER_ONLY",
        "executor_state": "DISARMED",
        "window_start": win_ts[0].date().isoformat(),
        "window_end": win_ts[-1].date().isoformat(),
        "policy": {
            "leg_fee_rate": policy.leg_fee_rate,
            "min_no_trade_band": policy.min_no_trade_band,
            "fee_band_multiplier": policy.fee_band_multiplier,
            "max_gross_weight": policy.max_gross_weight,
        },
        "manifest_tiers": {k: v["tier"] for k, v in PROMOTED_STRATEGY_MANIFEST.items()},
        "arms": [ref_band, ref_raw, slow_40, cash_ctrl],
    }
