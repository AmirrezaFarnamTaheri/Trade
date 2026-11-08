"""Observed trade flow is exact, availability bounded and never a fill forecast."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.model import TradeTick
from gym.services.market_statistics import trade_flow_report
from tests.support import START, market_db


def tick(price="100", qty="1", *, seconds=0, delay=0, side="BUY", symbol="BTCUSDT"):
    at = START + timedelta(seconds=seconds)
    return TradeTick(symbol, at, at + timedelta(seconds=delay), Decimal(price), Decimal(qty), side)


def test_exact_weighted_flow_keeps_units_and_unknown_direction(tmp_path):
    db = market_db(tmp_path, [])
    for row in [tick("100", "0.123456789"), tick("110", "0.25", side="SELL"),
                tick("120", "0.125", seconds=1800, side=None), tick(symbol="USDTTMN")]:
        db.add_trade(row, "test")
    report = trade_flow_report(db, START, START + timedelta(hours=1))
    first, second, third = report["groups"]
    assert first["symbol"] == "BTCUSDT" and first["tehran_hour"] == 12
    assert first["base_volume"] == "0.373456789"
    assert first["quote_notional"] == "39.845678900"
    assert Decimal(first["vwap"]) * Decimal(first["base_volume"]) == Decimal(first["quote_notional"])
    assert first["average_trade_quote"] == "19.922839450"
    assert Decimal(first["aggressor_imbalance"]) < 0
    assert second["tehran_hour"] == 13 and second["unknown_base"] == "0.125"
    assert second["aggressor_imbalance"] is None
    assert third["symbol"] == "USDTTMN" and third["quote_currency"] == "TMN"
    assert report["samples"] == 4 and report["excluded"] == 0
    assert report == trade_flow_report(db, START, START + timedelta(hours=1))
    assert report["funded_authority"] is False and report["complete_tape_verified"] is False
    db.c.close()


def test_cutoff_excludes_late_receipts_and_future_events(tmp_path):
    db = market_db(tmp_path, [])
    for row in [tick(), tick("500", delay=60), tick("700", seconds=60), tick("900", delay=-1)]:
        db.add_trade(row, "test")
    early = trade_flow_report(db, START, START + timedelta(minutes=1))
    assert early["samples"] == 1 and early["excluded"] == 1
    assert early["groups"][0]["vwap"] == "100"
    later = trade_flow_report(db, START, START + timedelta(seconds=61))
    assert later["samples"] == 3 and later["data_digest"] != early["data_digest"]
    db.c.close()


@pytest.mark.parametrize("price,qty", [("NaN", "1"), ("Infinity", "1"), ("0", "1"),
                                      ("-1", "1"), ("100", "0"), ("100", "-2")])
def test_invalid_rows_do_not_become_numeric_flow(tmp_path, price, qty):
    db = market_db(tmp_path, [])
    db.add_trade(tick(price, qty), "test")
    report = trade_flow_report(db, START, START + timedelta(minutes=1))
    assert report["samples"] == 0 and report["excluded"] == 1 and report["groups"] == []
    db.c.close()


def test_native_scientific_decimal_storage_preserves_small_trades(tmp_path):
    db = market_db(tmp_path, [])
    db.add_trade(tick("1E-8", "1E-8"), "test")
    group = trade_flow_report(db, START, START + timedelta(minutes=1))["groups"][0]
    assert Decimal(group["vwap"]) == Decimal("1E-8")
    assert Decimal(group["quote_notional"]) == Decimal("1E-16")
    db.c.close()


def test_empty_demo_and_bad_requests_are_explicit(tmp_path):
    db = market_db(tmp_path, [])
    report = trade_flow_report(db, START, START + timedelta(minutes=1), store="demo")
    assert report["status"] == "UNAVAILABLE" and report["synthetic"]
    assert any("DEMO" in text for text in report["limitations"])
    for symbol in ["../x", "btc", 1]:
        with pytest.raises(ValueError, match="symbol"):
            trade_flow_report(db, START, START + timedelta(minutes=1), symbol=symbol)
    with pytest.raises(ValueError, match="range"):
        trade_flow_report(db, START, START)
    db.c.close()


def test_legacy_timestamps_keep_exact_subsecond_cuts(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, [])
    for row in [tick(), tick(seconds=0.25), tick(seconds=0.75)]:
        db.add_trade(row, "test")
    db.c.execute("update trades set ts_event=replace(ts_event,'.000000Z','Z'), "
                 "ts_avail=replace(ts_avail,'.000000Z','Z')")
    report = trade_flow_report(db, START, START + timedelta(seconds=0.5))
    assert report["samples"] == 2
    db.c.close()
    output = tmp_path / "flow.json"
    assert main(["--data", str(tmp_path), "trade-flow", "--output", str(output)]) == 0
    saved = json.loads(output.read_text("utf-8"))
    assert saved["samples"] == 3 and saved["to_exclusive"].endswith("00.750001Z")


def test_cli_reads_store_and_never_overwrites_reports(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, [])
    db.add_trade(tick(delay=5), "test")
    db.c.close()
    output = tmp_path / "flow.json"
    assert main(["--data", str(tmp_path), "trade-flow", "btcusdt", "--output", str(output)]) == 0
    report = json.loads(output.read_text("utf-8"))
    assert report["samples"] == 1 and report["groups"][0]["vwap"] == "100"
    assert report["to_exclusive"].endswith("05.000001Z")
    assert "1 observations" in capsys.readouterr().out
    original = output.read_bytes()
    assert main(["--data", str(tmp_path), "trade-flow", "--output", str(output)]) == 2
    assert output.read_bytes() == original
    missing = tmp_path / "missing"
    assert main(["--data", str(missing), "trade-flow"]) == 2
    assert not missing.exists()
