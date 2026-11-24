"""Tests for Workstream 2: Trading Framework & Multi-Signal Vector Pipeline (spec §5.1–§5.5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.bars import Bar, BarSpec
from gym.domain.forecast_graph import (
    CrossMarketBreadthRegimeNode,
    LeaveOneOutKalmanBasisNode,
    MicropriceOfiNode,
    MultiHorizonEwmacNode,
    MultiModalForecastGraph,
    run_2x2_attribution,
)
from gym.domain.kalman_models import KalmanBasisOutput
from gym.domain.microstructure import MicrostructureConsolidator, stoikov_microprice
from gym.domain.model import BookTop, TradeTick
from gym.domain.quoting_policy import (
    AvellanedaStoikovQuotingPolicy,
    FixedOffsetQuotingPolicy,
    KillSwitchEvaluator,
    KillSwitchState,
    is_nyse_core_session_open,
)
from gym.domain.strategy import Snapshot
from gym.domain.target_protocol import (
    LegacyStrategyAdapter,
    compute_required_child_delta,
)
from gym.domain.triggers import MultiTriggerCoordinator
from gym.domain.venue_contracts import NavReference

T0 = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 10:00 ET (NYSE open)


def test_microstructure_consolidator_microprice_ofi_l2_and_vpin():
    assert stoikov_microprice(Decimal("100"), Decimal("102"), Decimal("3"), Decimal("1")) == Decimal("101.5")
    c = MicrostructureConsolidator("BTCUSDT", vpin_bucket_volume=Decimal("2"), vpin_window_buckets=2)
    b1 = BookTop(
        "BTCUSDT", T0, Decimal("100"), Decimal("101"), Decimal("5"), Decimal("5"), frozenset(),
        depth=(((Decimal("100"), Decimal("5")), (Decimal("99"), Decimal("5"))), ((Decimal("101"), Decimal("2")), (Decimal("102"), Decimal("2")))),
    )
    s1 = c.on_book_top(b1)
    assert s1 is not None and s1.ts_event is None and s1.l2_depth5_imbalance is not None and s1.l2_depth5_imbalance > 0

    b2 = BookTop("BTCUSDT", T0 + timedelta(seconds=1), Decimal("100"), Decimal("101"), Decimal("8"), Decimal("3"), frozenset())
    s2 = c.on_book_top(b2)
    assert s2 is not None and s2.ofi_l1 == Decimal("5")  # +3 bid_qty - (-2 ask_qty)

    # 2 full buckets of pure BUY volume => VPIN == 1.0
    c.on_trade(TradeTick("BTCUSDT", T0 + timedelta(seconds=2), T0 + timedelta(seconds=2), Decimal("101"), Decimal("4"), "BUY"))
    bar = c.flush_bar(T0 + timedelta(seconds=60))
    assert bar is not None and bar.vpin == 1.0 and bar.vwap == Decimal("101") and bar.buy_aggressor_vol == Decimal("4")

    # Huge PEPE-scale 400M-unit print completes in O(1) via arithmetic batching; unknown side ignored for VPIN
    c_pepe = MicrostructureConsolidator("PEPEUSDT", vpin_bucket_volume=Decimal("1.0"), vpin_window_buckets=20)
    c_pepe.on_trade(TradeTick("PEPEUSDT", T0, T0, Decimal("0.00001"), Decimal("417602118"), "BUY"))
    c_pepe.on_trade(TradeTick("PEPEUSDT", T0 + timedelta(seconds=1), T0 + timedelta(seconds=1), Decimal("0.00001"), Decimal("1000"), "UNKNOWN"))
    assert c_pepe._current_vpin() == 1.0
    assert c_pepe._sell_vol == Decimal(0) and c_pepe._unknown_side_vol == Decimal("1000")


def test_legacy_strategy_adapter_preserves_fractional_free_cash_sizing():
    class StubStrategy:
        feature_values = {"sig": 1}

        def __init__(self, action: str, frac: str):
            self.action, self.frac = action, Decimal(frac)

        def decide(self, snap, holding):
            return self.action, self.frac, ("stub",), "abcd"

    bar = Bar("BTCUSDT", BarSpec("1h", "MID"), T0 - timedelta(hours=1), T0, T0, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("0"), 1, False)
    snap = Snapshot(T0, "BTCUSDT", bar, Decimal("100"), Decimal("101"), T0)

    # 20% held + 25% of 80% free cash == 40% (never 100%!)
    adapter = LegacyStrategyAdapter(StubStrategy("BUY_REQUEST", "0.25"))
    intent = adapter.evaluate(snap, held_base_qty=Decimal("2"), free_cash_quote=Decimal("800"), equity_quote=Decimal("1000"))
    assert intent.target_weight == Decimal("0.40")
    assert compute_required_child_delta(Decimal("4"), Decimal("2"), Decimal("0.5")) == Decimal("1.5")

    sell_adapter = LegacyStrategyAdapter(StubStrategy("SELL_REQUEST", "0.5"))
    sell_intent = sell_adapter.evaluate(snap, held_base_qty=Decimal("4"), free_cash_quote=Decimal("600"), equity_quote=Decimal("1000"))
    assert sell_intent.target_weight == Decimal("0.20")


def test_forecast_graph_separation_and_2x2_attribution():
    ewmac = MultiHorizonEwmacNode(pairs=((2, 4), (4, 8)))
    for px in [100 + i for i in range(12)]:
        slow_f = ewmac.update(float(px))
    assert slow_f > 0

    reg = CrossMarketBreadthRegimeNode().evaluate(0.8)
    basis_node = LeaveOneOutKalmanBasisNode()
    k_out = KalmanBasisOutput(40.0, 10.0, 30.0, 3.0, 12.0, -12.0, "ROUTINE_QUIET")
    assert basis_node.evaluate(k_out, quote_asset="USDT") == 12.0
    assert basis_node.evaluate(k_out, quote_asset="TMN") == -12.0

    graph = MultiModalForecastGraph()
    out = graph.combine(slow_trend_forecast=slow_f, regime_multiplier=reg, microstructure_forecast=4.0, kalman_basis_forecast=12.0)
    assert out.parent_forecast == slow_f * reg
    assert out.fast_overlay_forecast == 8.0 and out.suggested_quote_skew_bps > 0

    # MicropriceOfiNode toxicity veto check
    c = MicrostructureConsolidator("BTCUSDT", vpin_bucket_volume=Decimal("1"), vpin_window_buckets=1)
    c.on_trade(TradeTick("BTCUSDT", T0, T0, Decimal("100"), Decimal("1"), "SELL"))
    rs = c.on_book_top(BookTop("BTCUSDT", T0, Decimal("100"), Decimal("101"), Decimal("5"), Decimal("5"), frozenset()))
    assert rs is not None
    _, veto = MicropriceOfiNode().evaluate(rs)
    assert veto is True

    attr = run_2x2_attribution(Decimal("10"), Decimal("15"), Decimal("14"), Decimal("22"))
    assert attr.signal_effect + attr.execution_effect + attr.interaction_effect == attr.total_lift


def test_quoting_policy_kill_switches_nyse_calendar_and_trigger_precedence():
    # Nov 27, 2026 is Black Friday: early close at 13:00 ET (18:00 UTC)
    assert is_nyse_core_session_open(datetime(2026, 11, 27, 17, 30, tzinfo=UTC)) is True
    assert is_nyse_core_session_open(datetime(2026, 11, 27, 18, 5, tzinfo=UTC)) is False
    # Nov 26, 2026 is Thanksgiving (closed all day)
    assert is_nyse_core_session_open(datetime(2026, 11, 26, 15, 0, tzinfo=UTC)) is False

    fixed = FixedOffsetQuotingPolicy(Decimal("10"), Decimal("0.30"))
    q_cap = fixed.quote(Decimal("100"), Decimal("0.30"))
    assert q_cap.inventory_capped_buy is True and q_cap.bid_price is None and q_cap.ask_price is not None

    as_pol = AvellanedaStoikovQuotingPolicy(Decimal("10"), Decimal("0.30"), Decimal("2"))
    q_as = as_pol.quote(Decimal("100"), Decimal("0.20"), Decimal("0.05"))
    assert q_as.reservation_price < Decimal("100")

    ks = KillSwitchEvaluator()
    nav = NavReference("SPYONUSDT", "SPY", Decimal("600"), Decimal("1"), Decimal("1"), Decimal("1"), T0, True)
    bad_rwa = ks.evaluate(KillSwitchState(T0, 1.0, True, False, token_mid_quote=Decimal("620"), nav_reference=nav))
    assert bad_rwa.halted and "RWA_NAV_DEVIATION" in bad_rwa.reasons

    settled = []
    coord = MultiTriggerCoordinator(ks, non_bar_cooldown_s=30.0)
    res = coord.resolve(
        as_of=T0,
        kill_state=KillSwitchState(T0, 1.0, True, False),
        fixed_bar_closed=True,
        dislocation_bps=Decimal("50"),
        incremental_quote_volume=Decimal("60000"),
        has_working_parent_order=False,
        settle_open_orders_cb=lambda ts: settled.append(ts),
    )
    assert settled == [T0]
    assert res.should_evaluate_decision is True
    assert res.ordered_reasons == ("DISLOCATION", "QUOTE_VOLUME", "FIXED_BAR")
