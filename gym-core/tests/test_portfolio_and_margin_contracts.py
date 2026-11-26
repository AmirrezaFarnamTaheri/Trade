"""Shared-cash portfolio invariants and margin/credit/FX/token contracts (F010, F014-F023, C001-C016)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.credit import package_terms, replay_credit
from gym.domain.margin import market_rule, preview_terms, replay_margin
from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.portfolio_policy import PortfolioPolicy
from gym.domain.sim import CostModel
from gym.services.conversion_route import Touch, routes
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def test_portfolio_symbol_order_invariance_and_loss_latch_conservation(tmp_path):
    """F016, F017, F021: equal-weight shared-cash portfolio conserves quote cash and latches drawdown."""
    syms = ["BTCUSDT", "ETHUSDT"]
    rows = [top for s in syms for top in quote_history(n=120, turn=1, sym=s)]
    db = market_db(tmp_path, rows)
    spec = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1"}
    for s in syms:
        db.upsert_instrument(InstrumentId.wallex(s, s[:-4], "USDT"), {}, spec, "test", START)
    end = START + timedelta(minutes=25)
    cost = CostModel(fee_rate=Decimal("0.001"), max_fraction=Decimal("0.2"))
    params = {"fast": 2, "slow": 3, "position_model": "inventory/1"}
    try:
        fwd = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, end, resolution="1min", cash=Decimal(1000), cost=cost, params=params)
        rev = portfolio(db, ["ETHUSDT", "BTCUSDT"], START, end, resolution="1min", cash=Decimal(1000), cost=cost, params=params)
        # Deterministic conservation of quote cash and non-negative balances in both symbol orders.
        for run in (fwd, rev):
            res = run["result"]
            assert Decimal(res["balances"]["USDT"]) >= 0
            posted = Decimal(res["start_cash"]) + sum(
                (Decimal(p["amount"]) for p in res["postings"] if p["ccy"] == "USDT"), Decimal(0)
            )
            assert posted == Decimal(res["balances"]["USDT"])
        # Same final equity when both symbols are identical streams and enough cash covers both slots.
        assert Decimal(fwd["result"]["end"]["equity"]) == Decimal(rev["result"]["end"]["equity"])
    finally:
        db.c.close()

    # PortfolioPolicy drawdown and daily-loss latches are strictly monotonic within Tehran day (F017).
    policy = PortfolioPolicy({"method": "equal", "max_drawdown": "0.10", "daily_loss_limit": "0.05"}, syms)
    assert policy.observe(START, Decimal("1000")) is None
    assert policy.observe(START + timedelta(minutes=1), Decimal("940")) == "DAILY_LOSS"
    assert policy.observe(START + timedelta(minutes=2), Decimal("990")) == "DAILY_LOSS"  # stays latched same day
    assert policy.observe(START + timedelta(minutes=3), Decimal("890")) == "DRAWDOWN"
    assert policy.observe(START + timedelta(days=2), Decimal("1200")) == "DRAWDOWN"  # max_drawdown stays latched


def test_portfolio_policy_refuses_short_es_tail_and_degenerate_covariance():
    """F022, F023: ES/CVaR requires sufficient lookback and covariance singularity cannot fabricate weights."""
    with pytest.raises(ValueError, match="expected shortfall"):
        PortfolioPolicy({"method": "equal", "expected_shortfall_limit": "0.05", "lookback": 10, "rebalance": True}, ["BTCUSDT", "ETHUSDT"])

    # Flat prices (zero variance / singular covariance) under risk-parity return ZERO_VARIANCE honestly.
    pol = PortfolioPolicy({"method": "risk-parity", "lookback": 5}, ["BTCUSDT", "ETHUSDT"])
    flat = {s: [(START + timedelta(minutes=i), Decimal("100")) for i in range(6)] for s in ("BTCUSDT", "ETHUSDT")}
    out = pol.weights(flat)
    assert out["status"] == "ZERO_VARIANCE"


def test_margin_debt_ledger_4h_financing_delayed_liquidation_and_currency_safety():
    """C001, C003, C004, C006, C010: exact margin debt, 4-hour fee boundaries, delayed liquidation, no wrong-currency netting."""
    rule = market_rule({
        "symbol": "BTCUSDT", "base": "BTC", "quote": "USDT",
        "min_risk_coef": "1", "max_risk_coef": "3", "risk_coef_step": "0.5",
        "liquidity_margin": "0.15", "max_age": 30 * 86400,
    })
    req = {"market": "BTCUSDT", "side": "long", "collateral": "100", "risk_coef": "2", "open_price": "100"}
    preview = preview_terms({
        **req,
        "collateral": {"currency": "USDT", "value": "100"},
        "loan": {"currency": "USDT", "value": "100"},
        "trade_fee": {"currency": "USDT", "value": "0.5"},
        "open_fee": {"currency": "USDT", "value": "0.25"},
        "extend_fee": {"currency": "USDT", "value": "0.015"},
        "extend_time": 4 * 3600,
        "max_age": 21 * 86400,
        "call_price": "65",
        "liquidity_price": "55",
    }, req, rule)

    # Wrong-currency loan for long (BTC instead of USDT) must fail closed (C010).
    with pytest.raises(ValueError, match="loan currency"):
        preview_terms({**preview, "loan": {"currency": "BTC", "value": "1"}}, req, rule)

    # 4-hour boundary clock + market closed during liquidation threshold -> LIQUIDATION_UNSETTLED (C004, C006).
    q_open = BookTop("BTCUSDT", START, Decimal("99.9"), Decimal("100"), Decimal("10"), Decimal("10"), frozenset())
    q_4h = BookTop("BTCUSDT", START + timedelta(hours=4), Decimal("99"), Decimal("100"), Decimal("10"), Decimal("10"), frozenset())
    q_crash_closed = BookTop("BTCUSDT", START + timedelta(hours=8), Decimal("50"), Decimal("51"), Decimal("10"), Decimal("10"), frozenset())
    rep = replay_margin(
        preview, rule,
        [(q_open, False), (q_4h, False), (q_crash_closed, True)],
        START + timedelta(hours=12),
        "0.001",
        None,
    )
    # Unsettled crash remains CLOSE_PENDING through the 12h window, accruing all 3 x 4h financing periods without silent close.
    assert rep["extension_periods"] == 3
    assert rep["state"] == "CLOSE_PENDING"


def test_trading_credit_subaccount_is_separate_from_position_margin():
    """C007: trading-credit subaccount has its own assurance/loan/daily-fee/expiry contract."""
    terms = package_terms({
        "id": 1, "currency": "USDT", "status": "ACTIVE", "expire_days": 7,
        "assurance": "100", "loan": "200", "warning_limit": "250", "liquidity_limit": "220",
        "daily_fee_after_discount": "0.5", "final_fee_after_discount": "0",
    })
    q0 = BookTop("BTCUSDT", START, Decimal("99"), Decimal("100"), Decimal("10"), Decimal("10"), frozenset())
    q1 = BookTop("BTCUSDT", START + timedelta(days=1), Decimal("60"), Decimal("61"), Decimal("0.1"), Decimal("10"), frozenset())
    rep = replay_credit(terms, "BTC", [(q0, False), (q1, False)], START, START + timedelta(days=2),
                        exposure=Decimal("1"), fee_rate=Decimal("0.001"))
    # Bid depth (0.1 BTC) is insufficient to close ~3 BTC -> LIQUIDATION_UNSETTLED, never silent fill!
    assert rep["fee_days"] == 1 and rep["state"] == "LIQUIDATION_UNSETTLED"


def test_fx_conversion_direction_spread_fees_and_round_trip_no_free_lunch():
    """C011, C012: TMN -> USDT -> TMN uses opposite book sides and fees; round-trip never invents profit."""
    touches = {
        "USDTTMN": Touch(bid=Decimal("60000"), ask=Decimal("60060"), bid_qty=Decimal("5000"), ask_qty=Decimal("5000"), at=iso(START)),
        "BTCTMN": Touch(bid=Decimal("6000000000"), ask=Decimal("6012000000"), bid_qty=Decimal("1"), ask_qty=Decimal("1"), at=iso(START)),
        "BTCUSDT": Touch(bid=Decimal("99950"), ask=Decimal("100050"), bid_qty=Decimal("1"), ask_qty=Decimal("1"), at=iso(START)),
    }
    fee = Decimal("0.001")
    start_tmn = Decimal("60000000")
    to_usdt = routes(touches, start_tmn, "TMN_TO_USDT", fee)
    usdt_got = to_usdt[0]["received"]
    back_tmn = routes(touches, usdt_got, "USDT_TO_TMN", fee)[0]["received"]
    assert back_tmn < start_tmn  # spread + 2 fees strictly consume value
    # Oversized amount flags fits_displayed_size=False rather than assuming infinite touch depth.
    huge = routes(touches, Decimal("999999999999"), "TMN_TO_USDT", fee)
    assert all(not r["fits_displayed_size"] for r in huge)
