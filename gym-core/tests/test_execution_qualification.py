"""Executable-net gate, depth-walk liquidation, latency/queue/stop contracts, and causal reconnect audits (X001-X022, M003-M005)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB
from gym.domain.execution_qualification import (
    depth_walk_liquidation,
    maker_queue_fill,
    model_latency_phases,
    paired_cost_ladder,
    qualify_executable_net,
    simulate_trailing_stop,
)
from gym.domain.model import BookTop, InstrumentId, TradeTick
from gym.services.collector import Collector
from gym.services.paper_stop import simulate_stop
from tests.support import START, quote


def _valid_spec():
    return {"stepSize": 4, "minQty": "0.001", "minNotional": "5", "isMarketTypeEnable": True}


def test_executable_net_gate_refuses_unknown_spec_fee_quote_halt_and_min_notional():
    """X001, X002, X012, X013: missing metadata yields UNKNOWN/REFUSED, never zero fee or implied fill."""
    q = quote(START, "100", "101")
    ok = qualify_executable_net(
        side="BUY", order_type="MARKET", quantity=Decimal("0.1"),
        spec=_valid_spec(), fee_rate=Decimal("0.001"), fee_source="/v1/account/fee@2026-11-01",
        quote=q, depth_levels=((Decimal("101"), Decimal("1.0")),),
    )
    assert ok["status"] == "QUALIFIED" and ok["evidence_tier"] == "HISTORICALLY_CONSTRAINED_PAPER"

    # Missing fee without explicit zero-fee flag -> UNKNOWN
    no_fee = qualify_executable_net(
        side="BUY", order_type="MARKET", quantity=Decimal("0.1"),
        spec=_valid_spec(), fee_rate=None, fee_source=None, quote=q,
    )
    assert no_fee["status"] == "UNKNOWN" and "UNKNOWN_FEE_VINTAGE" in no_fee["reasons"]

    # Explicit catalogue zero-fee flag allowed
    zero_fee = qualify_executable_net(
        side="BUY", order_type="MARKET", quantity=Decimal("0.1"),
        spec=_valid_spec(), fee_rate=Decimal("0"), fee_source="catalogue:is_zero_fee", quote=q, is_zero_fee=True,
    )
    assert zero_fee["qualified"] is True

    # Market orders disabled -> REFUSED
    no_mkt = qualify_executable_net(
        side="BUY", order_type="MARKET", quantity=Decimal("0.1"),
        spec={**_valid_spec(), "isMarketTypeEnable": False},
        fee_rate=Decimal("0.001"), fee_source="acct", quote=q,
    )
    assert no_mkt["status"] == "REFUSED" and "MARKET_ORDER_DISABLED" in no_mkt["reasons"]

    # Dust below minNotional -> REFUSED
    dust = qualify_executable_net(
        side="SELL", order_type="MARKET", quantity=Decimal("0.01"),
        spec=_valid_spec(), fee_rate=Decimal("0.001"), fee_source="acct", quote=q,
    )
    assert dust["status"] == "REFUSED" and "BELOW_MIN_LOT_OR_NOTIONAL" in dust["reasons"]

    # Halted market -> REFUSED
    halted = qualify_executable_net(
        side="SELL", order_type="LIMIT", quantity=Decimal("1"),
        spec=_valid_spec(), fee_rate=Decimal("0.001"), fee_source="acct", quote=q, halted=True,
    )
    assert halted["status"] == "REFUSED" and "MARKET_HALTED" in halted["reasons"]


def test_depth_walk_liquidation_reports_full_partial_and_unavailable_without_extrapolation():
    """X009, X010, X018, F013, F024: exact multi-level depth walk with explicit unsold residual."""
    levels = ((Decimal("100"), Decimal("2")), (Decimal("99"), Decimal("3")))
    full = depth_walk_liquidation("SELL", Decimal("4"), levels, fee_rate=Decimal("0.001"), quote_at=START)
    assert full["status"] == "FULL" and full["residual_qty"] == "0"
    assert Decimal(full["gross_quote"]) == Decimal("398")  # 2*100 + 2*99
    assert Decimal(full["net_quote"]) == Decimal("397.602")

    partial = depth_walk_liquidation("SELL", Decimal("8"), levels, fee_rate=Decimal("0.001"), quote_at=START)
    assert partial["status"] == "PARTIAL"
    assert partial["filled_qty"] == "5" and partial["residual_qty"] == "3"
    assert Decimal(partial["gross_quote"]) == Decimal("497")  # never extrapolates past last displayed level

    empty = depth_walk_liquidation("SELL", Decimal("1"), None, fee_rate=Decimal("0.001"))
    assert empty["status"] == "UNAVAILABLE" and empty["residual_qty"] == "1"


def test_latency_phases_and_maker_queue_post_only_cancel_race_and_duplicate_print_sensitivity():
    """X003-X008, M004: phase clocks, post-only crossing, cancel race, and identical-print ambiguity."""
    clocks = model_latency_phases(START, receive_ms=40, publish_ms=10, decide_ms=5, send_ms=60, ack_ms=85)
    assert clocks["total_latency_ms"] == 200

    # Post-only crossing opposite side is rejected immediately (X006).
    rej = maker_queue_fill(
        side="BUY", limit_price=Decimal("101"), order_qty=Decimal("1"), queue_ahead=Decimal("0"),
        trades=[], active_at=START, post_only=True, best_opposite_price=Decimal("101"),
    )
    assert rej["status"] == "POST_ONLY_REJECTED"

    # Identical-field prints (no venue trade ID) + pre-activation trade + post-cancel trade (X003, X005, X007, X008).
    t_pre = TradeTick("BTCUSDT", START - timedelta(seconds=1), START, Decimal("100"), Decimal("10"), "SELL")
    t1 = TradeTick("BTCUSDT", START + timedelta(seconds=1), START + timedelta(seconds=1), Decimal("100"), Decimal("2"), "SELL")
    t2 = TradeTick("BTCUSDT", START + timedelta(seconds=1), START + timedelta(seconds=1), Decimal("100"), Decimal("2"), "SELL")  # identical shape!
    t_after_cancel = TradeTick("BTCUSDT", START + timedelta(seconds=5), START + timedelta(seconds=5), Decimal("100"), Decimal("10"), "SELL")

    res = maker_queue_fill(
        side="BUY", limit_price=Decimal("100"), order_qty=Decimal("2"), queue_ahead=Decimal("2"),
        trades=[t_pre, t1, t2, t_after_cancel],
        active_at=START, cancel_effective_at=START + timedelta(seconds=4),
        post_only=True, best_opposite_price=Decimal("101"),
    )
    # t_pre ignored (before active_at); t1 drains queue_ahead=2; t2 fills 2 (but is duplicate shape -> unambiguous_filled=0); t_after_cancel ignored.
    assert res["status"] == "FILLED"
    assert res["filled_qty"] == "2"
    assert res["unambiguous_filled_qty"] == "0"
    assert res["ambiguous_print_qty"] == "2"


def test_stop_limit_and_causal_trailing_stop_contracts():
    """X014, X015, X016: stops are non-guaranteed exits; gap, halt, and missing quote remain exposed."""
    inst = InstrumentId.wallex("BTCUSDT")
    trades = [
        TradeTick("BTCUSDT", START + timedelta(seconds=10), START + timedelta(seconds=10), Decimal("100"), Decimal("1"), "BUY"),
        TradeTick("BTCUSDT", START + timedelta(seconds=20), START + timedelta(seconds=20), Decimal("110"), Decimal("1"), "BUY"),
        TradeTick("BTCUSDT", START + timedelta(seconds=30), START + timedelta(seconds=30), Decimal("104"), Decimal("1"), "SELL"),  # <= 110 * 0.95 = 104.5
    ]
    thin_quote = BookTop("BTCUSDT", START + timedelta(seconds=31), Decimal("103"), Decimal("104"),
                         Decimal("0.4"), Decimal("1"), frozenset(),
                         (((Decimal("103"), Decimal("0.4")),), ((Decimal("104"), Decimal("1")),)))

    # Partial depth leaves residual exposure explicitly reported.
    partial = simulate_trailing_stop(
        side="SELL", quantity=Decimal("1"), trail_fraction=Decimal("0.05"),
        trades=trades, quotes=[thin_quote], fee_rate=Decimal("0.001"),
    )
    assert partial["status"] == "PARTIAL_EXPOSED" and partial["unfilled_qty"] == "0.6" and partial["high_water"] == "110"

    # Halt before trigger leaves full exposure.
    halted = simulate_trailing_stop(
        side="SELL", quantity=Decimal("1"), trail_fraction=Decimal("0.05"),
        trades=trades, quotes=[thin_quote], fee_rate=Decimal("0.001"), halted_at=START + timedelta(seconds=25),
    )
    assert halted["status"] == "HALTED_EXPOSED" and halted["unfilled_qty"] == "1"

    # STOP_LIMIT activated but market gaps below limit_price -> ACTIVATED_UNFILLED (X015).
    sl = simulate_stop(
        inst, Decimal("100"),
        [TradeTick("BTCUSDT", START + timedelta(seconds=5), START + timedelta(seconds=5), Decimal("95"), Decimal("1"), "SELL")],
        [quote(START + timedelta(seconds=6), "90", "91")],
        None, START, START + timedelta(hours=1),
        side="SELL", quantity=Decimal("1"), stop_price=Decimal("95"),
        order_type="STOP_LIMIT", limit_price=Decimal("94"), fee_rate="0.001", store="demo",
    )
    assert sl["status"] == "ACTIVATED_UNFILLED" and sl["unfilled_quantity"] == "1"


def test_paired_cost_ladder_and_collector_reconnect_overlap_boundaries(tmp_path):
    """X019, X021, M003, M013: paired scenarios create zero selection trials; reconnect overlap preserves multiplicity and logs gaps."""
    ladder = paired_cost_ladder([
        {"name": "reference-mid", "evidence_tier": "MODELED_PAPER_REFERENCE", "net_return": "0.12", "max_drawdown": "0.10", "fill_fraction": "1.0"},
        {"name": "depth-latency", "evidence_tier": "HISTORICALLY_CONSTRAINED_PAPER", "net_return": "0.04", "max_drawdown": "0.14", "fill_fraction": "0.72", "residual_inventory": "0.28", "cost_drag_bps": "80"},
    ])
    assert ladder["creates_selection_trial"] is False and len(ladder["scenarios"]) == 2

    db = MarketDB(tmp_path / "market.db")
    try:
        inst = InstrumentId.wallex("BTCUSDT")
        db.upsert_instrument(inst, {}, {}, "test", START)
        from gym.adapters.store import SegmentWriter
        seg = SegmentWriter(tmp_path / "raw", db)
        col = Collector(db, seg, ["BTCUSDT"], demo=True)
        try:
            # First trade at START+1s; then reconnect REST batch starts at START+60s -> GAP logged (M013).
            row1 = {"timestamp": (START + timedelta(seconds=1)).isoformat(), "price": "100", "quantity": "1", "isBuyOrder": True}
            row2 = {"timestamp": (START + timedelta(seconds=1)).isoformat(), "price": "100", "quantity": "1", "isBuyOrder": True}
            col._seed_trades("BTCUSDT", [row1, row2], START + timedelta(seconds=2), "seg#1", None)
            # Re-seeding identical batch does not double-count; adding a 3rd identical print adds exactly 1.
            col._seed_trades("BTCUSDT", [row1, row2], START + timedelta(seconds=3), "seg#2", START + timedelta(seconds=1))
            assert db.c.execute("SELECT count(*) FROM trades").fetchone()[0] == 2
            col._seed_trades("BTCUSDT", [row1, row2, row1], START + timedelta(seconds=4), "seg#3", START + timedelta(seconds=1))
            assert db.c.execute("SELECT count(*) FROM trades").fetchone()[0] == 3
            # Disjoint later batch emits GAP quality event.
            later = {"timestamp": (START + timedelta(seconds=60)).isoformat(), "price": "101", "quantity": "1", "isBuyOrder": False}
            col._seed_trades("BTCUSDT", [later], START + timedelta(seconds=61), "seg#4", START + timedelta(seconds=1))
            gaps = db.c.execute("SELECT count(*) FROM quality_events WHERE flag='GAP'").fetchone()[0]
            assert gaps == 1
        finally:
            col.seg.close()
    finally:
        db.c.close()
