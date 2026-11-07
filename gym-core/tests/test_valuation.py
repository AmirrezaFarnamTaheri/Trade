"""Historical valuation cannot borrow a future quote for starting cash."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history


def test_curve_valuation_is_causal_and_bound_to_native_identity(tmp_path):
    observations = [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [replace(quote(START, "100", "102"), symbol="USDTTMN"),
                     replace(quote(START + timedelta(minutes=8), "200", "202"), symbol="USDTTMN")]
    db = market_db(tmp_path, observations)
    try:
        out = paper(db, "BTCTMN", START, START + timedelta(minutes=12), resolution="1min", fast=2, slow=3)
        curve = out["result"]["valuation"]["curve"]
        early = [row for row in curve if row["at"] < "2026-10-29T09:08:00"]
        assert all(row["fx"]["rate"] == "101" for row in early)
        assert curve[-1]["fx"]["status"] == "STALE"
        assert len(curve) == len(out["result"]["curve"])
        assert Decimal(curve[0]["equity_usdt_eq"]) == Decimal(out["result"]["curve"][0][1]) / 101
        db.c.execute("UPDATE book_top SET bid='300',ask='302' WHERE instrument_id='wallex:USDTTMN' AND ts_avail>?",
                     ("2026-10-29T09:07:00",))
        db.c.commit()
        changed = paper(db, "BTCTMN", START, START + timedelta(minutes=12), resolution="1min", fast=2, slow=3)
        assert changed["run_id"] != out["run_id"]
        assert changed["result"]["valuation"]["curve"][:len(early)] == early
    finally:
        db.c.close()


def test_missing_fx_marks_remain_missing_and_usdt_identity_is_exact(tmp_path):
    observations = quote_history(80)
    observations += [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [replace(quote(START + timedelta(minutes=5), "100", "102"), symbol="USDTTMN")]
    db = market_db(tmp_path, observations)
    try:
        out = paper(db, "BTCTMN", START, START + timedelta(minutes=12), resolution="1min", fast=2, slow=3)
        assert out["result"]["valuation"]["start"]["status"] == "UNAVAILABLE"
        assert out["result"]["valuation"]["curve"][0]["equity_usdt_eq"] is None
        identity = paper(db, "BTCUSDT", START, START + timedelta(minutes=12), resolution="1min", fast=2, slow=3)
        assert identity["result"]["quote"] == "USDT" and identity["fx"] is None
        assert "valuation" not in identity["inputs"]
        assert identity["result"]["end"]["net_usdt_eq"] == identity["result"]["end"]["net"]
    finally:
        db.c.close()


def test_fx_already_known_at_both_boundaries_remains_available(tmp_path):
    observations = [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [replace(quote(START, "100", "102"), symbol="USDTTMN"),
                     replace(quote(START + timedelta(minutes=10), "110", "112"), symbol="USDTTMN")]
    output = paper(market_db(tmp_path, observations), "BTCTMN", START, START + timedelta(minutes=12),
                   resolution="1min", fast=2, slow=3)
    assert output["fx"]["start"] == "101" and output["fx"]["end"] == "111"
    assert output["numeraire"] == "USDT-equivalent"
    assert "net_usdt_eq" in output["result"]["end"]


def test_future_only_fx_cannot_value_starting_cash(tmp_path):
    observations = [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [
        replace(quote(START + timedelta(minutes=2), "100", "102"), symbol="USDTTMN"),
        replace(quote(START + timedelta(minutes=10), "110", "112"), symbol="USDTTMN"),
    ]
    output = paper(market_db(tmp_path, observations), "BTCTMN", START, START + timedelta(minutes=12),
                   resolution="1min", fast=2, slow=3)
    assert output["fx"] is None
    assert output["numeraire"] == "TMN"
    assert "net_usdt_eq" not in output["result"]["end"]
    assert any("USDT-equivalent unavailable" in warning for warning in output["warnings"])
