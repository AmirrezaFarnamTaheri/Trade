"""Cross-market hypotheses use only fresh recorded references and declared costs."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.model import BookTop
from gym.services.paper import paper
from gym.services.research import compare
from tests.support import START, market_db


def observations():
    rows = []
    for i in range(180):
        at = START + timedelta(seconds=i * 10)
        for symbol, price, spread in (("BTCTMN", 5700000 if i < 90 else 6100000, 100),
                                      ("BTCUSDT", 100, 1), ("USDTTMN", 60000, 10)):
            rows.append(BookTop(symbol, at, Decimal(price), Decimal(price + spread), Decimal(100), Decimal(100), frozenset()))
    return rows


def test_toman_discount_hypothesis_records_both_references_and_models_roundtrip(tmp_path):
    db = market_db(tmp_path, observations())
    try:
        out = paper(db, "BTCTMN", START, START + timedelta(minutes=29), resolution="1min",
                    strategy_id="toman-premium", cash=Decimal(300000000))
        assert out["result"]["fills"] >= 2
        assert out["inputs"]["auxiliary_symbols"] == ["BTCUSDT", "USDTTMN"]
        decisions = out["result"]["decisions"]
        entry = next(d for d in decisions if d["action"] == "BUY_REQUEST")
        assert {q["symbol"] for q in entry["auxiliary_known"]} == {"BTCUSDT", "USDTTMN"}
        assert Decimal(entry["feature_values"]["conversion_cost_bps"]) >= 0
        assert any(d["action"] == "SELL_REQUEST" for d in decisions)
    finally:
        db.c.close()


def test_missing_conversion_leg_abstains_without_inventing_fx(tmp_path):
    db = market_db(tmp_path, [q for q in observations() if q.symbol != "USDTTMN"])
    try:
        out = paper(db, "BTCTMN", START, START + timedelta(minutes=29), resolution="1min", strategy_id="toman-premium")
        assert out["result"]["fills"] == 0
        assert all(d["action"] == "ABSTAIN_NO_REFERENCE" for d in out["result"]["decisions"])
    finally:
        db.c.close()


def test_premium_comparison_shares_causal_reference_cut_with_other_strategies(tmp_path):
    db = market_db(tmp_path, observations())
    try:
        out = compare(db, "BTCTMN", START, START + timedelta(minutes=29),
            [{"strategy": "toman-premium"}, {"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}}], resolution="1min")
        assert len({r["inputs"]["snapshots"] for r in out["runs"]}) == 1
        assert all(r["inputs"]["auxiliary_symbols"] == ["BTCUSDT", "USDTTMN"] for r in out["runs"])
    finally:
        db.c.close()


def test_lead_lag_uses_same_quote_reference_and_resets_after_missing_history(tmp_path):
    rows = []
    for i in range(180):
        at = START + timedelta(seconds=i * 10)
        for symbol, price in (("SOLUSDT", 100 + i / Decimal(100)), ("BTCUSDT", 100 + i / Decimal(10))):
            rows.append(BookTop(symbol, at, Decimal(price), Decimal(price) + Decimal("0.01"), Decimal(100), Decimal(100), frozenset()))
    db = market_db(tmp_path, rows)
    try:
        out = paper(db, "SOLUSDT", START, START + timedelta(minutes=29), resolution="1min", strategy_id="lead-lag",
                    params={"lookback": 3, "reference": "BTCUSDT", "entry_bps": 10, "lag_bps": 10})
        assert out["result"]["fills"] > 0
        assert any(d["feature_values"].get("leader_return_bps") is not None for d in out["result"]["decisions"])
    finally:
        db.c.close()
