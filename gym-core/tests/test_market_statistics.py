"""Reproducible observed spreads and their user-facing CLI report."""
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.services.market_statistics import spread_report
from tests.support import START, market_db, quote


def observation(spread, at=START, symbol="BTCUSDT"):
    half = Decimal(spread) / 2
    return replace(quote(at, str(10000 - half), str(10000 + half)), symbol=symbol)


def test_spreads_use_exact_decimals_venue_hours_and_qualified_snapshots(tmp_path):
    rows = [observation(value) for value in ("2", "4", "6", "8")]
    rows += [observation("10", START + timedelta(minutes=30)), observation("20", symbol="USDTTMN")]
    rows += [quote(START, "NaN", "1"), quote(START, "10", "11", ["STALE"])]
    rows += [observation("100", START + timedelta(hours=1))]
    db = market_db(tmp_path, rows)
    report = spread_report(db, START, START + timedelta(hours=1))
    assert report["samples"] == 6 and report["excluded"] == 2
    first = report["groups"][0]
    assert first["symbol"] == "BTCUSDT" and first["tehran_hour"] == 12 and first["samples"] == 4
    assert first["spread_bps"] == {"min": "2.0000", "median": "5.0000", "p95": "8.0000", "max": "8.0000"}
    assert report["groups"][1]["tehran_hour"] == 13
    assert report == spread_report(db, START, START + timedelta(hours=1))
    demo = spread_report(db, START, START + timedelta(hours=1), store="demo")
    assert demo["synthetic"] and any("not venue-cost evidence" in message for message in demo["limitations"])


def test_p95_uses_nearest_rank_not_the_maximum(tmp_path):
    db = market_db(tmp_path, [observation(str(value)) for value in range(1, 22)])
    statistics = spread_report(db, START, START + timedelta(minutes=1))["groups"][0]["spread_bps"]
    assert statistics["median"] == "11.0000"
    assert statistics["p95"] == "20.0000"


def test_empty_and_inverted_spread_ranges_are_truthful(tmp_path):
    db = market_db(tmp_path, [])
    report = spread_report(db, START, START + timedelta(hours=1))
    assert report["groups"] == [] and report["samples"] == report["excluded"] == 0
    with pytest.raises(ValueError, match="inverted"):
        spread_report(db, START, START)


def test_spread_cli_writes_report_and_includes_last_stored_quote(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, [observation("2"), observation("4", START + timedelta(minutes=1))]).c.close()
    output = tmp_path / "spreads.json"
    assert main(["--data", str(tmp_path), "spreads", "btcusdt", "--output", str(output)]) == 0
    report = json.loads(output.read_text("utf-8"))
    assert report["samples"] == 2 and not report["synthetic"]
    assert "2 observations" in capsys.readouterr().out
    original = output.read_bytes()
    assert main(["--data", str(tmp_path), "spreads", "--output", str(output)]) == 2
    assert output.read_bytes() == original
    assert main(["--data", str(tmp_path), "spreads", "--from", "2030-01-01T00:00:00Z", "--output", str(output)]) == 2
    assert output.read_bytes() == original


def test_missing_store_does_not_create_a_database(tmp_path, capsys):
    assert main(["--data", str(tmp_path), "spreads"]) == 2
    assert "no market data" in capsys.readouterr().err
    assert not (tmp_path / "live").exists()
