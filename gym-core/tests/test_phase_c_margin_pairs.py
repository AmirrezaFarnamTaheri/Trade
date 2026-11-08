"""Phase C item 27: paired long/short margin paper replay, not venue orders."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, iso
from gym.services.margin import _save
from gym.services.margin_pairs import margin_pairs_research
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
              top("BTCUSDT", 3600, "110", "111"), top("ETHUSDT", 3600, "89", "90")]
    market_db(tmp_path, sorted(points, key=lambda q: q.ts_avail)).c.close()
    request = {"long_preview_id": a["run_id"], "short_preview_id": b["run_id"],
               "from": iso(START), "to": iso(START + timedelta(hours=1, seconds=1)),
               "exit_fee_rate": "0.001", "holding_seconds": 3600,
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
    assert out["spread_stability"]["half_life_bars"] is None
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
        db.add_book_top(top("ETHUSDT", 3700, "1", "2"), None)
    finally:
        db.c.close()
    second = margin_pairs_research(tmp_path, request, store="live")
    assert second["net_usdt"] == first["net_usdt"]
    assert second["spread_stability"] == first["spread_stability"]
