"""Tests for Phase B Multi-Venue Plug-In Adapters: Nobitex & AbanTether (spec §8.1–§8.2)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from gym.adapters.abantether import (
    ABANTETHER_INSTRUMENT_CATALOG,
    OtcQuote,
    abantether_otc_fee_schedule,
    evaluate_abantether_guards,
)
from gym.adapters.nobitex import (
    evaluate_prefunded_arb_capital_day,
    nobitex_fee_schedule,
    parse_nobitex_orderbook,
)
from gym.domain.venue_contracts import NavReference

T_NYSE_OPEN = datetime(2026, 11, 24, 15, 30, tzinfo=UTC)  # 10:30 ET
T_NYSE_EARLY_CLOSED = datetime(2026, 11, 27, 18, 15, tzinfo=UTC)  # 13:15 ET Black Friday


def test_nobitex_adapter_fees_rial_conversion_and_capital_day_arb():
    undisc = nobitex_fee_schedule("USDT", observed_at=T_NYSE_OPEN)
    disc = nobitex_fee_schedule("USDT", permanent_discount=Decimal("0.30"), observed_at=T_NYSE_OPEN)
    assert undisc.effective_rates(T_NYSE_OPEN) == (Decimal("0.0010"), Decimal("0.0013"))
    assert disc.effective_rates(T_NYSE_OPEN) == (Decimal("0.00070"), Decimal("0.00091"))

    disc_irt = nobitex_fee_schedule("IRT", permanent_discount=Decimal("0.30"), observed_at=T_NYSE_OPEN)
    assert disc_irt.effective_rates(T_NYSE_OPEN) == (Decimal("0.00140"), Decimal("0.00175"))

    # RLS -> TMN conversion (divide by 10)
    qs = parse_nobitex_orderbook(
        "USDTIRT",
        {"bids": [["1000000", "500"]], "asks": [["1001000", "400"]]},
        T_NYSE_OPEN,
    )
    assert qs is not None and qs.symbol == "USDTTMN" and qs.bid == Decimal("100000") and qs.ask == Decimal("100100")

    arb = evaluate_prefunded_arb_capital_day(
        buy_venue_ask=Decimal("100000"),
        sell_venue_bid=Decimal("100400"),
        leg1_filled_qty=Decimal("0.1"),
        leg2_filled_qty=Decimal("0.08"),
        buy_fee_rate=Decimal("0.00091"),
        sell_fee_rate=Decimal("0.0013"),
        replenishment_transfer_fee_usdt=Decimal("2.0"),
        residual_unwind_slippage_bps=Decimal("15"),
        total_prefunded_capital_usdt=Decimal("20000"),
        cycle_days=Decimal("1"),
    )
    assert arb.gross_edge_usdt == Decimal("32.0")
    assert arb.second_leg_residual_cost_usdt > 0
    assert arb.net_usdt_per_capital_day == arb.net_proceeds_usdt / Decimal("20000")


def test_abantether_otc_catalog_and_five_hardcoded_guards():
    sched = abantether_otc_fee_schedule("USDT", observed_at=T_NYSE_OPEN)
    assert sched.venue_kind == "OTC_QUOTE" and sched.effective_rates(T_NYSE_OPEN) == (Decimal("0"), Decimal("0"))
    assert ABANTETHER_INSTRUMENT_CATALOG["USOON"].underlying_id == "USO"
    assert ABANTETHER_INSTRUMENT_CATALOG["COPXON"].underlying_id == "COPX"

    nav_ok = NavReference("SPYON", "SPY", Decimal("600"), Decimal("1"), Decimal("1"), Decimal("1"), T_NYSE_OPEN, True)
    q_ok = OtcQuote("SPYON", "USDT", Decimal("601.674"), Decimal("598.326"), T_NYSE_OPEN, 30.0, Decimal("50000"))
    assert round(q_ok.round_trip_spread_pct, 3) == Decimal("0.556")

    res_ok = evaluate_abantether_guards(
        q_ok, nav_ok, as_of=T_NYSE_OPEN, order_notional_quote=Decimal("1000"),
        current_issuer_weight=Decimal("0.05"), current_venue_weight=Decimal("0.10"), proposed_delta_weight=Decimal("0.05"),
    )
    assert res_ok.allowed is True

    # Test exclusions, early-close calendar, NAV deviation, and custody caps
    q_bad = OtcQuote("TQQQB", "USDT", Decimal("630"), Decimal("625"), T_NYSE_EARLY_CLOSED, 30.0, Decimal("50000"))
    res_bad = evaluate_abantether_guards(
        q_bad, nav_ok, as_of=T_NYSE_EARLY_CLOSED, order_notional_quote=Decimal("1000"),
        current_issuer_weight=Decimal("0.18"), current_venue_weight=Decimal("0.34"), proposed_delta_weight=Decimal("0.05"),
    )
    assert res_bad.allowed is False
    for expected in ("LEVERAGED_3X_EXCLUDED", "NYSE_SESSION_CLOSED", "NAV_PREMIUM_EXCEEDS_LIMIT", "ISSUER_CUSTODY_CAP_EXCEEDED", "VENUE_CUSTODY_CAP_EXCEEDED"):
        assert expected in res_bad.reasons
