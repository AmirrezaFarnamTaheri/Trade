"""Unit tests for v3 Dynamic Per-Moment Instrument Resolvers and multi-instrument causal replay ledger."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.dynamic_resolver_ledger import simulate_dynamic_resolver
from gym.domain.instrument_resolver import (
    MarketView,
    PositionState,
    ResolverConfig,
    best_candidate_for_market,
    build_local_venue_offers,
    dd_governor_leverage_cap,
    expected_carry_bps,
    max_liquidation_safe_leverage,
    resolve_a1_utility,
    resolve_a2_signed_admm,
    resolve_a3_state_machine,
    resolve_h12_hybrid,
)
from gym.domain.timeframe_panel import BarPoint


def _bar(sym: str, ts_start: datetime, o: float, h: float, low: float, c: float) -> BarPoint:
    return BarPoint(
        symbol=sym, ts_start=ts_start, ts_avail=ts_start + timedelta(hours=2),
        open=o, high=h, low=low, close=c, volume=1000.0,
        bar_source="test", clock_complete=True, nonzero_volume_fraction=1.0,
        last_trade_age_bars=0, entry_eligible=True, mark_status="LIVE",
    )


def test_5x_stop_barrier_and_dd_governor() -> None:
    cfg = ResolverConfig(max_venue_leverage=5.0)
    offers = build_local_venue_offers("BTCUSDT")
    nbx_long = [o for o in offers if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1][0]

    # Tight 250 bps stop with healthy DD -> unlocks 5.0x
    assert dd_governor_leverage_cap(1.0, cfg) == 5.0
    assert max_liquidation_safe_leverage(nbx_long, 250.0, cfg, dd_cap_leverage=5.0) == 5.0

    # Wide 1200 bps daily stop -> strictly rejects 5.0x, caps at 1.5x
    assert max_liquidation_safe_leverage(nbx_long, 1200.0, cfg, dd_cap_leverage=5.0) <= 1.5

    # Portfolio DD >= 6% forces 1.0x spot-only
    assert dd_governor_leverage_cap(6.5, cfg) == 1.0
    assert max_liquidation_safe_leverage(nbx_long, 200.0, cfg, dd_cap_leverage=1.0) == 1.0


def test_eod_intraday_zero_borrow_and_perp_funding_pays_shorts() -> None:
    offers = build_local_venue_offers("SOLUSDT", include_perp_future=True, perp_funding_8h_bps=1.5)
    nbx_long = [o for o in offers if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1][0]
    nbx_short = [o for o in offers if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == -1][0]
    perp_short = [o for o in offers if o.venue == "hyperliquid" and o.instrument_type == "PERP_FUTURE" and o.direction == -1][0]

    # Intraday Nobitex long closed before EOD UTC costs $0 borrow
    assert expected_carry_bps(nbx_long, 3.0, horizon_hours=8.0, hours_to_utc_eod=12.0) == 0.0
    # Overnight Nobitex long crossing 1 UTC midnight pays 5 bps * (L-1)/L
    assert expected_carry_bps(nbx_long, 2.0, horizon_hours=16.0, hours_to_utc_eod=6.0) == 2.5
    # Overnight Nobitex short borrows 100% of notional -> pays full 5 bps/day
    assert expected_carry_bps(nbx_short, 2.0, horizon_hours=16.0, hours_to_utc_eod=6.0) == 5.0
    # Hyperliquid perp short with positive funding EARNS negative carry
    assert expected_carry_bps(perp_short, 2.0, horizon_hours=16.0, hours_to_utc_eod=6.0) == -3.0


def test_all_four_resolvers_route_long_short_perp_and_anti_churn() -> None:
    ts = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    cfg = ResolverConfig(max_venue_leverage=5.0)
    views = {
        "BTCUSDT": MarketView("BTCUSDT", ts, expected_return_bps=140.0, horizon_hours=14.0, stop_distance_bps=220.0, realized_vol_ann=0.45, confidence=0.92, regime_breadth=0.70, source_tag="2h_gru"),
        "DOGEUSDT": MarketView("DOGEUSDT", ts, expected_return_bps=-130.0, horizon_hours=24.0, stop_distance_bps=320.0, realized_vol_ann=0.75, confidence=0.82, regime_breadth=0.20, source_tag="short"),
    }
    local_offers = {s: build_local_venue_offers(s) for s in views}
    perp_offers = {s: build_local_venue_offers(s, include_perp_future=True, perp_funding_8h_bps=1.5) for s in views}
    cov = {("BTCUSDT", "BTCUSDT"): 0.001, ("DOGEUSDT", "DOGEUSDT"): 0.002, ("BTCUSDT", "DOGEUSDT"): 0.0002, ("DOGEUSDT", "BTCUSDT"): 0.0002}

    for fn in (
        lambda: resolve_a1_utility(views, local_offers, {}, 1000.0, 14.0, 0.0, cfg),
        lambda: resolve_a2_signed_admm(views, local_offers, {}, 1000.0, 14.0, 0.0, cov, cfg),
        lambda: resolve_a3_state_machine(views, local_offers, {}, 1000.0, 14.0, 0.0, cfg),
        lambda: resolve_h12_hybrid(views, local_offers, {}, 1000.0, 14.0, 0.0, cov, cfg),
    ):
        acts = fn()
        assert acts["BTCUSDT"].direction == 1 and acts["BTCUSDT"].leverage >= 1.5
        assert acts["DOGEUSDT"].direction == -1 and acts["DOGEUSDT"].instrument_type == "ISOLATED_MARGIN"

    # When Hyperliquid Perp offer is plugged in, resolver automatically chooses PERP_FUTURE for the short!
    perp_best = best_candidate_for_market(views["DOGEUSDT"], perp_offers["DOGEUSDT"], None, 1000.0, 14.0, 0.0, cfg)
    assert perp_best is not None and perp_best.offer.instrument_type == "PERP_FUTURE" and perp_best.offer.venue == "hyperliquid"

    # Anti-churn: existing right-sized position with modest remaining edge stays HOLD; oversized past horizon reduces
    held_right = PositionState("BTCUSDT", "nobitex", "SPOT", 1, 1.0, 95.0, 95.0, 90000.0, 85000.0, 0.0, 12.0, 40.0, ts - timedelta(hours=12), horizon_hours=24.0)
    held_big = PositionState("BTCUSDT", "nobitex", "SPOT", 1, 1.0, 200.0, 200.0, 90000.0, 85000.0, 0.0, 40.0, 40.0, ts - timedelta(hours=40), horizon_hours=24.0)
    mild = {"BTCUSDT": MarketView("BTCUSDT", ts, expected_return_bps=22.0, horizon_hours=120.0, stop_distance_bps=800.0, realized_vol_ann=0.45, confidence=0.55, regime_breadth=0.50)}
    act_hold = resolve_a1_utility(mild, {"BTCUSDT": local_offers["BTCUSDT"]}, {"BTCUSDT": held_right}, 1000.0, 10.0, 0.0, cfg)["BTCUSDT"]
    act_red = resolve_a1_utility(mild, {"BTCUSDT": local_offers["BTCUSDT"]}, {"BTCUSDT": held_big}, 1000.0, 10.0, 0.0, cfg)["BTCUSDT"]
    assert act_hold.action == "HOLD" and act_red.action == "REDUCE"


def test_dynamic_resolver_ledger_accrues_pool_yield_and_executes_stop() -> None:
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    bars = [
        _bar("BTCUSDT", t0 + timedelta(hours=2 * i), px, px * 1.01, px * 0.99, px)
        for i, px in enumerate([100.0, 100.0, 102.0, 92.0, 93.0, 94.0])
    ]
    # Make bar 3 hit stop sharply (low=90) while view remains active through bar 2
    bars[3] = _bar("BTCUSDT", t0 + timedelta(hours=6), 102.0, 102.5, 90.0, 91.0)
    panel = {"BTCUSDT": bars}
    offers_static = {"BTCUSDT": build_local_venue_offers("BTCUSDT", idle_pool_apr=0.0264)}
    views_by_ts = {}
    offers_by_ts = {}
    for i, b in enumerate(bars[:-1]):
        if i <= 2:
            v = MarketView("BTCUSDT", b.ts_avail, expected_return_bps=160.0, horizon_hours=14.0, stop_distance_bps=300.0, realized_vol_ann=0.40, confidence=0.92, regime_breadth=0.70)
            views_by_ts[b.ts_avail] = {"BTCUSDT": v}
        else:
            views_by_ts[b.ts_avail] = {}
        offers_by_ts[b.ts_avail] = offers_static

    cfg = ResolverConfig(max_venue_leverage=3.0, idle_pool_apr=0.0264)
    summary, _ = simulate_dynamic_resolver(
        panel, views_by_ts, offers_by_ts, {},
        lambda v, o, p, eq, h, dd, _c, c: resolve_a1_utility(v, o, p, eq, h, dd, c),
        label="TEST_LEDGER", cfg=cfg,
    )
    assert summary.liquidations == 0
    assert summary.stop_outs == 1
    assert summary.total_pool_yield_usdt > 0.0
    assert summary.margin_long_entries == 1


def test_reduce_preserves_exact_equity_conservation() -> None:
    from gym.domain.dynamic_resolver_ledger import (
        _apply_closes_and_reduces,
        _OpenPos,
        _pos_equity,
    )
    from gym.domain.instrument_resolver import ResolvedAction

    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    for px_now in (125.0, 88.0):
        pos = _OpenPos(
            symbol="BTCUSDT", venue="nobitex", instrument_type="SPOT", direction=1, leverage=1.0,
            collateral=200.0, notional=200.0, qty=2.0, entry_price=100.0, stop_price=0.0,
            liq_price=0.0, carry_model="NONE", carry_rate_bps=0.0, exit_cost_bps=16.0,
            entry_ts=t0, last_utc_date="2026-11-20", horizon_hours=24.0,
        )
        eq_before = _pos_equity(pos, px_now)
        open_pos = {"BTCUSDT": pos}
        stats = {"fees": 0.0, "reduces": 0, "switches": 0}
        act = ResolvedAction("BTCUSDT", "REDUCE", "nobitex", "SPOT", 1, 1.0, 100.0, 100.0, 0.0, 10.0, "test")
        freed = _apply_closes_and_reduces({"BTCUSDT": act}, open_pos, {"BTCUSDT": px_now}, {"BTCUSDT"}, stats)
        eq_after = freed + _pos_equity(open_pos["BTCUSDT"], px_now)
        assert abs((eq_before - stats["fees"]) - eq_after) < 1e-9
