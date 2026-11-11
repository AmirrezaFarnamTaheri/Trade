"""Paired long/short margin paper replay, not venue orders."""
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from gym.domain.cross_market_models import ar1_half_life
from gym.domain.model import BookTop, iso
from gym.services.margin import _save
from gym.services.margin_pairs import _spread_statistics, margin_pairs_research
from gym.services.research_actions import research_action
from gym.services.research_process import HEAVY_ACTIONS
from tests.support import START, market_db


def rule(symbol):
    """One same-quote synthetic, fixed credit-ratio rule."""
    base = symbol.removesuffix("USDT")
    return {"symbol": symbol, "base": base, "quote": "USDT",
            "min_risk_coef": "1", "max_risk_coef": "10",
            "risk_coef_step": "0.5", "liquidity_margin": "0.15", "max_age": 1814400}


def preview(symbol, side):
    """Credit-ratio 2 paper preview with a quote-collateralized short."""
    base = symbol.removesuffix("USDT")
    return {"market": symbol, "side": side, "risk_coef": "2", "open_price": "100",
            "collateral": {"currency": "USDT", "value": "100"},
            "loan": {"currency": "USDT" if side == "long" else base,
                     "value": "200" if side == "long" else "2"},
            "trade_fee": {"currency": base if side == "long" else "USDT",
                          "value": "0.005" if side == "long" else "0.5"},
            "open_fee": {"currency": "USDT" if side == "long" else base,
                         "value": "0.03" if side == "long" else "0.0004"},
            "extend_fee": {"currency": "USDT" if side == "long" else base,
                           "value": "0.03" if side == "long" else "0.0004"},
            "extend_time": 14400, "max_age": 1814400,
            "call_price": "70" if side == "long" else "130",
            "liquidity_price": "60" if side == "long" else "140"}


def top(symbol, seconds, bid, ask):
    return BookTop(symbol, START + timedelta(seconds=seconds), Decimal(bid),
                   Decimal(ask), Decimal(10), Decimal(10), frozenset())


def fixture(tmp_path):
    """Save two immutable local preview receipts and publicly observed books."""
    a = _save(tmp_path, {"kind": "PREVIEW", "received_at": iso(START - timedelta(hours=1)),
                         "rule": rule("BTCUSDT"), "terms": preview("BTCUSDT", "long")})
    b = _save(tmp_path, {"kind": "PREVIEW", "received_at": iso(START - timedelta(hours=1)),
                         "rule": rule("ETHUSDT"), "terms": preview("ETHUSDT", "short")})
    points = [top("BTCUSDT", 0, "99", "100"), top("ETHUSDT", 0, "100", "101"),
              top("BTCUSDT", 14400, "110", "111"), top("ETHUSDT", 14400, "89", "90")]
    market_db(tmp_path, sorted(points, key=lambda q: q.ts_avail)).c.close()
    request = {"long_preview_id": a["run_id"], "short_preview_id": b["run_id"],
               "from": iso(START), "to": iso(START + timedelta(hours=4, seconds=1)),
               "exit_fee_rate": "0.001", "holding_seconds": 14400,
               "max_skew_seconds": 10}
    return request


def test_paired_margin_replay_uses_real_short_side_debt_math(tmp_path):
    request = fixture(tmp_path)
    assert "margin-pairs-replay" in HEAVY_ACTIONS
    out = margin_pairs_research(tmp_path, request, store="live")
    assert out["kind"] == "PAIR_REPLAY"
    assert out["long"]["state"] == out["short"]["state"] == "CLOSED"
    assert Decimal(out["short"]["cash_quote"]) == Decimal("119.247928")
    combined = (Decimal(out["long"]["cash_quote"])
                + Decimal(out["short"]["cash_quote"]) - Decimal(200))
    assert Decimal(out["net_quote"]) == combined
    assert Decimal(out["net_usdt"]) == combined
    assert out["funded_authority"] is False and out["order_submitted"] is False
    assert out["spread_stability"]["status"] == "INSUFFICIENT_SAMPLES"
    assert out["spread_stability"]["half_life_observations"] is None
    assert research_action(tmp_path, "margin-pairs-replay", request,
                           store="live")["net_usdt"] == out["net_usdt"]


def test_paired_margin_replay_rejects_missing_or_mismatched_receipts(tmp_path):
    request = fixture(tmp_path)
    for change in ({"short_preview_id": request["long_preview_id"]},
                   {"long_preview_id": "0" * 16},
                   {"max_skew_seconds": 999},
                   {"from": iso(START - timedelta(days=2))}):
        with pytest.raises(ValueError):
            margin_pairs_research(tmp_path, {**request, **change}, store="live")
    with pytest.raises(ValueError):
        margin_pairs_research(tmp_path, request, store="demo")


def test_future_quotes_cannot_change_historical_pair_report(tmp_path):
    request = fixture(tmp_path)
    first = margin_pairs_research(tmp_path, request, store="live")
    from gym.adapters.store import MarketDB

    db = MarketDB(tmp_path / "market.db")
    try:
        db.add_book_top(top("ETHUSDT", 14500, "1", "2"), None)
    finally:
        db.c.close()
    second = margin_pairs_research(tmp_path, request, store="live")
    assert second["net_usdt"] == first["net_usdt"]
    assert second["spread_stability"] == first["spread_stability"]


def test_spread_half_life_uses_training_quotes_and_names_observation_unit():
    """Holdout changes cannot leak into the fitted training AR(1) half-life."""
    long_points, short_points, training_values = [], [], []
    with localcontext() as context:
        context.prec = 90
        for i in range(30):
            # First 70% mean-reverts; deliberately different holdout follows.
            discount = (Decimal("0.4") / (2 ** i) if i < 21
                        else (Decimal("0.7") if i % 2 else Decimal("0.02")))
            long_bid = Decimal(100) * (1 + discount)
            short_bid = Decimal(100)
            long_ask = long_bid + Decimal("0.01")
            short_ask = short_bid + Decimal("0.01")
            long_points.append((top("BTCUSDT", i * 60, str(long_bid), str(long_ask)), False))
            short_points.append((top("ETHUSDT", i * 60, str(short_bid), str(short_ask)), False))
            if i < 21:
                training_values.append(((long_bid + long_ask) / (short_bid + short_ask)).ln())
    expected = ar1_half_life(training_values)
    stats = _spread_statistics(long_points, short_points, 10)
    assert stats["aligned_samples"] == 30
    assert stats["phi"] == expected["phi"]
    assert stats["half_life_observations"] == expected["half_life_bars"]
    assert "half_life_bars" not in stats
    assert "aligned long-leg quote-update observations" in stats["caveat"]
