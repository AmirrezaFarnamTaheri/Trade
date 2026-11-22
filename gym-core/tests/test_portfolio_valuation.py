"""Portfolio conversion uses causal FX marks and never disguises unavailable or stale rates."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB
from gym.domain.model import InstrumentId, parse_ts
from gym.domain.portfolio_diagnostics import economic_portfolio_attribution
from gym.services.portfolio import _Replay, _rule_timeline, portfolio
from gym.services.rules import RuleService
from tests.support import START, market_db, quote, quote_history


def replay(db):
    return portfolio(db, ["BTCTMN", "ETHTMN"], START, START + timedelta(minutes=30),
                     resolution="1min", params={"fast": 2, "slow": 3}, cash=Decimal(1000))


def rate(seconds, price):
    return replace(quote(START + timedelta(seconds=seconds), str(price - 1), str(price + 1)), symbol="USDTTMN")


def test_portfolio_fx_curve_never_reads_a_later_rate(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") +
                   [rate(0, 100), rate(900, 200)])
    try:
        out = replay(db)
        valuation = out["result"]["valuation"]
        assert out["inputs"]["portfolio_version"] == 5
        assert valuation["start"]["rate"] == "100" and valuation["end"]["rate"] == "200"
        before = [r for r in valuation["curve"] if parse_ts(r["at"]) < START + timedelta(minutes=15)]
        assert before and all(r["fx"]["rate"] == "100" for r in before)
        assert valuation["end"]["status"] == "STALE"
        expected = Decimal(out["result"]["end"]["equity"]) / 200 - Decimal(1000) / 100
        assert Decimal(out["result"]["end"]["net_usdt_eq"]) == expected.quantize(Decimal("0.0001"))
        fx = out["performance"]["economic_attribution"]["fx_attribution"]
        assert fx["close_rate_status"] == "STALE"
        assert Decimal(fx["translation_residual_usdt"]) == 0
        out["result"]["end"]["net_usdt_eq"] = str(expected.quantize(Decimal("0.0001")) + 1)
        assert Decimal(economic_portfolio_attribution(out)["fx_attribution"]["translation_residual_usdt"]) == -1
        old_id = out["run_id"]
        db.add_book_top(rate(1750, 300), None)
        changed = replay(db)
        assert changed["run_id"] != old_id
        assert changed["result"]["valuation"]["curve"][:10] == valuation["curve"][:10]
    finally:
        db.c.close()


def test_future_only_fx_cannot_value_start_or_net(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") + [rate(1500, 100)])
    try:
        out = replay(db)
        valuation = out["result"]["valuation"]
        assert valuation["start"]["status"] == "UNAVAILABLE"
        assert out["result"]["end"]["net_usdt_eq"] is None
        assert valuation["curve"][0]["equity_usdt_eq"] is None
        assert out["performance"]["economic_attribution"]["fx_attribution"]["status"] == "MISSING_FX_EVIDENCE"
    finally:
        db.c.close()


def test_usdt_portfolio_is_identity_valued(tmp_path):
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=30), resolution="1min")
        assert out["result"]["valuation"]["start"]["status"] == "IDENTITY"
        assert out["result"]["end"]["net_usdt_eq"] == out["result"]["end"]["net"]
    finally:
        db.c.close()


def test_closed_fx_boundary_keeps_old_rate_with_explicit_status(tmp_path):
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") + quote_history(n=180, sym="ETHTMN") + [rate(0, 100)])
    try:
        out = portfolio(db, ["BTCTMN", "ETHTMN"], START, START + timedelta(hours=12), resolution="1min")
        assert out["result"]["valuation"]["end"]["status"] == "STALE_CLOSED"
        assert out["result"]["valuation"]["end"]["rate"] == "100"
    finally:
        db.c.close()


def test_mixed_portfolio_fx_calendar_refreshes_on_tehran_day_and_rule_revision(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    try:
        svc = RuleService(db)
        start = parse_ts("2026-11-14T20:00:00Z")  # 23:30 Tehran on Saturday
        midnight = start + timedelta(minutes=30)
        disable_at = midnight + timedelta(minutes=10)
        svc.put({"id": "night", "family": "TradingWindow", "class": "VENUE", "action": "BLOCK_ALL",
                 "scope": {"symbols": ["USDTTMN"]},
                 "params": {"closed": [{"from": "23:30", "to": "01:00", "days": [5]}]},
                 "status": "VERIFIED", "source": "operator", "effective_from": "2026-11-01T00:00:00Z"},
                start - timedelta(days=1))
        svc.disable("night", disable_at)
        account = _Replay.__new__(_Replay)
        account.rules_for, _ = _rule_timeline(db, "point-in-time")
        account.fx_valuation_instrument = InstrumentId.wallex("USDTTMN")
        account._fx_valuation_calendar = (None, None, ())
        assert not account._fx_valuation_closed(start - timedelta(microseconds=1))
        assert account._fx_valuation_closed(start)
        assert account._fx_valuation_closed(midnight)
        assert account._fx_valuation_closed(disable_at - timedelta(microseconds=1))
        assert not account._fx_valuation_closed(disable_at)
        assert not account._fx_valuation_closed(start + timedelta(days=1))
    finally:
        db.c.close()
