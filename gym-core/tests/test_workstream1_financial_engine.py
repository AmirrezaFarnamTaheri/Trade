"""Tests for Workstream 1: Financial Engine (spec §4.1–§4.6)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    simple_no_trade_band_allocator,
    solve_convex_portfolio,
    verify_post_solve_orders,
)
from gym.domain.dual_numeraire import (
    FxQuote,
    build_dual_numeraire_snapshot,
    decompose_tmn_return,
    tmn_to_executable_usdt,
    usdt_to_executable_tmn,
)
from gym.domain.execution_schedule import compare_execution_timing_arms
from gym.domain.model import BookTop, TradeTick
from gym.domain.passive_execution import PassiveOrderSpec, simulate_passive_orders
from gym.domain.tca_markout import (
    FillRecord,
    compute_exit_liquidity_stress,
    compute_fill_markouts,
    compute_shortfall_waterfall,
)
from gym.domain.tmn_carry import (
    TmnBorrowTerms,
    compare_fx_appreciation_scenarios,
    simulate_tmn_borrow_carry,
)
from gym.domain.venue_contracts import (
    InstrumentMaster,
    NavReference,
    QuoteSnapshot,
    wallex_l1_fee_schedule,
)

T0 = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def _top(sym: str, offset_s: float, bid: str, ask: str, bq: str = "10", aq: str = "10", depth=None) -> BookTop:
    return BookTop(sym, T0 + timedelta(seconds=offset_s), Decimal(bid), Decimal(ask), Decimal(bq), Decimal(aq), frozenset(), depth=depth)


def test_venue_contracts_and_nav_reference():
    usdt_sched = wallex_l1_fee_schedule("USDT", observed_at=T0)
    tmn_sched = wallex_l1_fee_schedule("TMN", observed_at=T0)
    assert usdt_sched.effective_rates(T0) == (Decimal("0.0010"), Decimal("0.0013"))
    assert tmn_sched.effective_rates(T0) == (Decimal("0.0025"), Decimal("0.0030"))
    assert usdt_sched.effective_rates(T0, zero_fee=True) == (Decimal(0), Decimal(0))

    nav = NavReference("SPYONUSDT", "SPY", Decimal("600"), Decimal("1.0002"), Decimal("1"), Decimal("1"), T0, True)
    assert nav.fair_quote_price() == Decimal("600.1200")

    top = _top("BTCUSDT", 0, "100000", "100020", "1.5", "2.0", depth=(((Decimal("100000"), Decimal("1.5")),), ((Decimal("100020"), Decimal("2.0")),)))
    qs = QuoteSnapshot.from_book_top("wallex", top)
    assert qs is not None and qs.ts_event is None and qs.spread_bps > 0


def test_passive_execution_arrival_classification_and_adversarial_print_modes():
    sched = wallex_l1_fee_schedule("USDT", observed_at=T0)
    books = [
        _top("BTCUSDT", 0, "100", "101", "0", "10"),
        # 5m post-fill quote moves UP to 105 (benign for BUY)
        _top("BTCUSDT", 310, "104.5", "105.5", "10", "10"),
    ]
    # Crossing limit with post_only=True is rejected; post_only=False executes as TAKER
    r_rej = simulate_passive_orders([PassiveOrderSpec("o1", "BTCUSDT", "BUY", Decimal("1"), Decimal("101"), T0, post_only=True)], books, [], sched)[0]
    assert r_rej.status == "POST_ONLY_REJECTED" and r_rej.filled_qty == 0

    r_tak = simulate_passive_orders([PassiveOrderSpec("o2", "BTCUSDT", "BUY", Decimal("1"), Decimal("101"), T0, post_only=False)], books, [], sched)[0]
    assert r_tak.status == "FILLED" and r_tak.fills[0].liquidity_role == "TAKER" and r_tak.total_fee_base == Decimal("0.0013")

    # Duplicate print on benign BUY fill: optimistic fills 2, deduplicated fills 1, adversarial fills 1 (ignores benign dup)
    trades = [
        TradeTick("BTCUSDT", T0 + timedelta(seconds=5), T0 + timedelta(seconds=5), Decimal("100"), Decimal("1"), "SELL"),
        TradeTick("BTCUSDT", T0 + timedelta(seconds=5), T0 + timedelta(seconds=5), Decimal("100"), Decimal("1"), "SELL"),
    ]
    spec = PassiveOrderSpec("o3", "BTCUSDT", "BUY", Decimal("2"), Decimal("100"), T0, post_only=True, max_wait_s=60)
    opt = simulate_passive_orders([spec], books, trades, sched, duplicate_print_mode="optimistic")[0]
    ded = simulate_passive_orders([spec], books, trades, sched, duplicate_print_mode="deduplicated")[0]
    adv = simulate_passive_orders([spec], books, trades, sched, duplicate_print_mode="adversarial_lower_bound")[0]
    assert opt.filled_qty == Decimal("2")
    assert ded.filled_qty == Decimal("1")
    assert adv.filled_qty == Decimal("1")

    # Now make 5m post-fill quote drop to 90 (adverse for BUY): adversarial fills 2!
    adverse_books = [_top("BTCUSDT", 0, "100", "101", "0", "10"), _top("BTCUSDT", 310, "89.5", "90.5", "10", "10")]
    adv_bad = simulate_passive_orders([spec], adverse_books, trades, sched, duplicate_print_mode="adversarial_lower_bound")[0]
    assert adv_bad.filled_qty == Decimal("2") and adv_bad.ambiguous_filled_qty == Decimal("1")


def test_convex_optimizer_l1_no_trade_zone_and_post_solve_verification():
    assert forecast_to_expected_return_bps(10.0, 0.05, 200.0) == 10.0
    prob = OptimizationProblem(
        symbols=("BTCUSDT", "ETHUSDT"),
        expected_returns=(0.0005, 0.0050),
        current_weights=(0.20, 0.10),
        covariance=((0.0004, 0.0003), (0.0003, 0.0005)),
        l1_fee_costs=(0.0020, 0.0020),
        l2_impact_costs=(0.0010, 0.0010),
        max_weight=0.40,
        cash_buffer=0.10,
    )
    res = solve_convex_portfolio(prob)
    assert res.converged and res.kkt_residual < 1e-7
    assert sum(res.weights) <= 0.90 + 1e-9
    # Strong forecast on ETH moves weight up; weak BTC stays near current weight inside L1 zone
    assert res.weights[1] > 0.10

    bench = simple_no_trade_band_allocator((0.20, 0.10), (0.25, 0.25), band=0.10)
    assert bench == (0.20, 0.25)

    insts = {
        "BTCUSDT": InstrumentMaster("wallex", "BTCUSDT", "BTC", None, "CRYPTO_SPOT", "24X7", 2, 5, Decimal("0.0001"), Decimal("5"), True, True, True),
        "ETHUSDT": InstrumentMaster("wallex", "ETHUSDT", "ETH", None, "CRYPTO_SPOT", "24X7", 2, 4, Decimal("0.001"), Decimal("5"), True, True, True),
    }
    plans = verify_post_solve_orders(
        ("BTCUSDT", "ETHUSDT"),
        res.weights,
        (0.20, 0.10),
        Decimal("1000"),
        Decimal("500"),
        {"BTCUSDT": Decimal("100000"), "ETHUSDT": Decimal("3000")},
        {"BTCUSDT": Decimal("1"), "ETHUSDT": Decimal("1")},
        insts,
        Decimal("0.0013"),
    )
    assert len(plans) == 2


def test_execution_timing_overlay_and_strict_post_fill_markouts():
    sched = wallex_l1_fee_schedule("USDT", observed_at=T0)
    books = [
        _top("BTCUSDT", 0, "100.0", "100.6", "5", "5"),      # 60 bps wide at t0
        _top("BTCUSDT", 10, "100.2", "100.3", "5", "5"),     # compressed to ~10 bps
        _top("BTCUSDT", 20, "100.2", "100.3", "0", "5"),     # distinct snapshot
        _top("BTCUSDT", 60, "100.3", "100.4", "5", "5"),
    ]
    trades = [TradeTick("BTCUSDT", T0 + timedelta(seconds=25), T0 + timedelta(seconds=25), Decimal("100.2"), Decimal("5"), "SELL")]
    comp = compare_execution_timing_arms("BTCUSDT", "BUY", Decimal("1"), T0, 60.0, books, trades, sched, p35_spread_bps=Decimal("15"))
    assert comp.immediate.filled_qty == Decimal("1")
    assert comp.opportunistic_recovery.filled_qty == Decimal("1")
    assert comp.opportunistic_recovery.total_cost_bps < comp.immediate.total_cost_bps

    # Strict post-fill markout: pre-fill quote at T0+4s must NEVER be used for h=5s
    fill = FillRecord("BTCUSDT", "BUY", T0, Decimal("100"), Decimal("1"), Decimal("100"), Decimal("100"), Decimal("0.10"))
    pre_only_books = {"BTCUSDT": [_top("BTCUSDT", 4, "105", "106")]}
    rep = compute_fill_markouts([fill], pre_only_books, horizons_s=(5, 300))
    assert rep.per_fill[0][1][0].status == "MISSING_POST_FILL_QUOTE"
    assert rep.coverage_by_horizon[5] == 0.0

    post_books = {"BTCUSDT": [_top("BTCUSDT", 6, "101", "101"), _top("BTCUSDT", 305, "99", "99"), _top("BTCUSDT", 3610, "102", "102")]}
    rep_ok = compute_fill_markouts([fill], post_books, horizons_s=(5, 300, 3600))
    wf = compute_shortfall_waterfall(fill, rep_ok.per_fill[0][1])
    assert wf.adverse_markout_5m_bps == Decimal("100")  # dropped 1% -> +100 bps adverse selection
    assert wf.post_5m_signal_drift_bps == Decimal("300")

    stress = compute_exit_liquidity_stress(
        {"BTCUSDT": Decimal("2")},
        {"BTCUSDT": Decimal("100")},
        {"BTCUSDT": [_top("BTCUSDT", 0, "100", "101", "4", "4"), _top("BTCUSDT", 60, "99.5", "100.5", "4", "4")]},
        T0,
        T0 + timedelta(minutes=5),
        assumption="distinct_source_ref_only",
        participation_cap=Decimal("0.25"),
    )
    assert stress.minutes_to_50pct == 0.0 and stress.minutes_to_100pct == 1.0


def test_dual_numeraire_fx_sides_and_tmn_borrow_carry():
    fx = FxQuote(bid=Decimal("100000"), ask=Decimal("101000"), taker_fee_rate=Decimal("0.0030"))
    # Positive TMN uses ask; negative TMN liability uses bid
    assert tmn_to_executable_usdt(Decimal("101000"), fx) == Decimal("0.9970")
    assert tmn_to_executable_usdt(Decimal("-100000"), fx) < Decimal("-1")
    # Positive USDT uses bid; negative USDT liability uses ask
    assert usdt_to_executable_tmn(Decimal("1"), fx) == Decimal("99700.0000")
    assert usdt_to_executable_tmn(Decimal("-1"), fx) < Decimal("-101000")

    snap = build_dual_numeraire_snapshot(
        initial_usdt_equity=Decimal("100"),
        initial_tmn_equity=Decimal("10000000"),
        booked_usdt=Decimal("105"),
        booked_tmn=Decimal("0"),
        liquidation_proceeds_usdt=Decimal("0"),
        unliquidated_residual_usdt=Decimal("0"),
        fx=fx,
    )
    assert snap.net_profit_usdt == Decimal("5")

    decomp = decompose_tmn_return(Decimal("0.10"), Decimal("0.20"))
    assert decomp.r_tmn == Decimal("0.32")

    # TMN borrow carry: rejected renewal at day 21 + scenario sweep
    terms_no_renew = TmnBorrowTerms("USDTTMN", Decimal("10000000"), Decimal("2"), allow_renewal_at_expiry=False)
    books_30d = [_top("USDTTMN", d * 86400, "100000", "100100", "10000", "10000") for d in range(30)]
    res_rej = simulate_tmn_borrow_carry(terms_no_renew, books_30d)
    assert res_rej.status == "RENEWAL_REJECTED_DAY21" and res_rej.total_extend_fees_tmn > 0

    terms_renew = TmnBorrowTerms("USDTTMN", Decimal("10000000"), Decimal("1.5"), allow_renewal_at_expiry=True)
    scen = compare_fx_appreciation_scenarios(terms_renew, start_at=T0, horizon_days=90)
    assert scen[Decimal("0.00")].excess_over_1x_tmn < 0  # flat Toman loses to 1x spot due to carry bleed
    assert scen[Decimal("0.50")].excess_over_1x_tmn > scen[Decimal("0.00")].excess_over_1x_tmn
