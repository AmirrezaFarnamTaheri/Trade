"""Closed-bar diagnostics, real indicator warmup and exact historical cuts."""
import json
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from gym.cli import main
from gym.domain.indicators import indicator_values
from gym.services.technical_analysis import technical_report, technical_reports
from tests.support import START, market_db, quote


def test_missing_history_is_not_a_neutral_indicator():
    values = indicator_values([Decimal(100)] * 14)
    assert values["rsi_14"]["status"] == "WARMUP" and values["rsi_14"]["value"] is None
    assert values["sma_20"]["value"] is None
    assert values["macd_12_26_9"]["signal"] is None
    assert indicator_values([])["sma_50"]["status"] == "WARMUP"


def test_flat_rising_falling_and_wilder_update_are_explicit():
    assert Decimal(indicator_values([Decimal(10)] * 50)["rsi_14"]["value"]) == 50
    rise = [Decimal(i) for i in range(1, 16)]
    assert Decimal(indicator_values(rise)["rsi_14"]["value"]) == 100
    assert Decimal(indicator_values(list(reversed(rise)))["rsi_14"]["value"]) == 0
    with localcontext() as context:
        context.prec = 160
        expected = Decimal(1300) / 14
        assert Decimal(indicator_values(rise + [Decimal(14)])["rsi_14"]["value"]) == expected
    flat = indicator_values([Decimal(10)] * 50)
    assert Decimal(flat["sma_20"]["value"]) == 10
    assert Decimal(flat["macd_12_26_9"]["histogram"]) == 0


def test_macd_uses_historical_line_values_and_the_declared_native_seed():
    assert indicator_values([Decimal(i) for i in range(1, 34)])["macd_12_26_9"]["signal"] is None
    out = indicator_values([Decimal(i) for i in range(1, 35)])["macd_12_26_9"]
    # Closed-form EMA of the arithmetic sequence 1..t, seeded at its first value.
    def ema(n, t):
        lag = Fraction(n - 1, 2)
        return t - lag + lag * Fraction(n - 1, n + 1)**(t - 1)
    macds = [ema(12, t) - ema(26, t) for t in range(26, 35)]
    signal = Fraction(4, 5)**8 * macds[0] + sum(Fraction(1, 5) * Fraction(4, 5)**(8-i) * macds[i] for i in range(1, 9))
    with localcontext() as context:
        context.prec = 160
        expected = Decimal(signal.numerator) / signal.denominator
        assert Decimal(out["signal"]).quantize(Decimal("1e-20")) == expected.quantize(Decimal("1e-20"))
        assert out["status"] == "AVAILABLE"
        assert Decimal(out["histogram"]) == Decimal(out["line"]) - Decimal(out["signal"])


@pytest.mark.parametrize("value", [0.1, "10", Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_prices_never_become_indicator_values(value):
    with pytest.raises(ValueError):
        indicator_values([value])


def observations(minutes=60):
    return [quote(START + timedelta(minutes=i, seconds=10), str(100+i), str(102+i)) for i in range(minutes)]


def test_report_excludes_forming_future_and_partial_bars_and_is_read_only(tmp_path):
    db = market_db(tmp_path, observations())
    try:
        first = technical_report(db, "BTCUSDT", START, START + timedelta(minutes=59, seconds=20), resolution="1min")
        assert first["closed_bars"] == 59 and first["last_closed_bar"]["close"] == "159"
        assert first["volume_available"] is False and first["funded_authority"] is False
        assert first["indicators"]["rsi_14"]["status"] == "AVAILABLE"
        db.add_book_top(quote(START + timedelta(hours=2), "999", "1000"), None)
        assert technical_report(db, "BTCUSDT", START, START + timedelta(minutes=59, seconds=20), resolution="1min") == first
        partial = technical_report(db, "BTCUSDT", START + timedelta(seconds=20), START + timedelta(minutes=3), resolution="1min")
        assert partial["closed_bars"] == 2 and partial["indicators"]["rsi_14"]["value"] is None
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_missing_and_invalid_bar_intervals_reset_warmup(tmp_path):
    tops = observations(40) + [quote(START + timedelta(minutes=41, seconds=10), "150", "152")]
    tops.append(quote(START + timedelta(minutes=42, seconds=10), "150", "152", ["STALE"]))
    tops += [quote(START + timedelta(minutes=i, seconds=10), "150", "152") for i in (43, 44)]
    db = market_db(tmp_path, tops)
    try:
        out = technical_report(db, "BTCUSDT", START, START + timedelta(minutes=45), resolution="1min")
        assert out["excluded_bad_bars"] == 0 and out["disqualified_intervals"] == 1 and out["gap_count"] == 2
        assert out["contiguous_bars"] == 2 and out["indicators"]["rsi_14"]["value"] is None
    finally:
        db.c.close()


def test_stale_and_empty_results_remain_visible(tmp_path):
    db = market_db(tmp_path, observations(3))
    try:
        out = technical_report(db, "BTCUSDT", START, START + timedelta(minutes=10), resolution="1min")
        assert out["status"] == "STALE" and out["quote_age_seconds"] == 470
        empty = technical_report(db, "ETHUSDT", START, START + timedelta(minutes=10), resolution="1min")
        assert empty["status"] == "UNAVAILABLE" and empty["last_closed_bar"] is None
        assert empty["indicators"]["rsi_14"]["value"] is None
    finally:
        db.c.close()


def test_a_bar_containing_an_invalid_quote_is_excluded_and_trailing_bad_quote_is_degraded(tmp_path):
    tops = observations(20)
    tops.append(quote(START + timedelta(minutes=19, seconds=20), "120", "122", ["STALE"]))
    db = market_db(tmp_path, tops)
    try:
        out = technical_report(db, "BTCUSDT", START, START + timedelta(minutes=20), resolution="1min")
        assert out["status"] == "DEGRADED" and out["excluded_bad_bars"] == 1
        assert out["closed_bars"] == 19 and out["last_closed_bar"]["close"] == "119"
    finally:
        db.c.close()


def test_bounded_ranges_resolution_and_observation_count(tmp_path, monkeypatch):
    import gym.services.technical_analysis as service
    db = market_db(tmp_path, observations(3))
    try:
        for changes in ({"symbol": "../secret"}, {"resolution": "session"},
                        {"end": START + timedelta(days=32)}, {"end": START}):
            options = {"symbol": "BTCUSDT", "start": START, "end": START + timedelta(minutes=10), **changes}
            with pytest.raises(ValueError):
                technical_report(db, **options)
        monkeypatch.setattr(service, "MAX_OBSERVATIONS", 2)
        with pytest.raises(ValueError, match="observations"):
            technical_report(db, "BTCUSDT", START, START + timedelta(minutes=10))
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_real_cli_reads_existing_store_without_creating_research_state(tmp_path, capsys):
    live = tmp_path / "live"
    live.mkdir()
    market_db(live, observations()).c.close()
    target = tmp_path / "technicals.json"
    args = ["--data", str(tmp_path), "technicals", "BTCUSDT", "--from", START.isoformat(),
            "--to", (START + timedelta(hours=1)).isoformat(), "--res", "1min", "--output", str(target)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(target.read_text())
    assert result["closed_bars"] == 60 and not result["order_submitted"]
    assert not (live / "research.sqlite3").exists()
    assert main(args) == 2


def test_timeframes_share_one_read_and_keep_the_single_report_contract(tmp_path, monkeypatch):
    import gym.services.technical_analysis as service
    db = market_db(tmp_path, observations())
    try:
        expected = technical_report(db, "BTCUSDT", START, START + timedelta(hours=1), resolution="1min")
        original = service.DataPortal.tops
        calls = []
        def read(portal, *args):
            calls.append(args)
            return original(portal, *args)
        monkeypatch.setattr(service.DataPortal, "tops", read)
        result = technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), resolutions=["1min", "15min", "1h"])
        assert len(calls) == 1 and not db.c.in_transaction
        assert result["timeframes"]["1min"] == expected
        assert [r["closed_bars"] for r in result["timeframes"].values()] == [60, 4, 1]
        assert len({r["data_digest"] for r in result["timeframes"].values()}) == 1
        assert result["timeframes"]["15min"]["indicators"]["rsi_14"]["value"] is None
        assert result["funded_authority"] is False and result["order_submitted"] is False
    finally:
        db.c.close()


@pytest.mark.parametrize("resolutions", [[], ["1min"] * 2, ["session"], ["7min"], "1min", ["1min"] * 5])
def test_invalid_timeframe_sets_reject_before_reading(tmp_path, resolutions):
    db = market_db(tmp_path, observations(1))
    try:
        with pytest.raises(ValueError):
            technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), resolutions=resolutions)
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_repeated_resolution_cli_creates_one_consistent_report(tmp_path, capsys):
    live = tmp_path / "live"
    live.mkdir()
    market_db(live, observations()).c.close()
    target = tmp_path / "timeframes.json"
    args = ["--data", str(tmp_path), "technicals", "BTCUSDT", "--from", START.isoformat(),
            "--to", (START + timedelta(hours=1)).isoformat(), "--res", "1min", "--res", "15min", "--output", str(target)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(target.read_text())
    assert list(result["timeframes"]) == ["1min", "15min"]
    assert main(args) == 2
    assert not (live / "research.sqlite3").exists()


def test_writer_between_timeframe_calculations_cannot_change_the_snapshot(tmp_path, monkeypatch):
    import gym.services.technical_analysis as service
    from gym.adapters.store import MarketDB
    db = market_db(tmp_path, observations())
    writer = MarketDB(tmp_path / "market.db")
    try:
        options = {"resolutions": ["1min", "15min"]}
        expected = technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), **options)
        original = service._report_from_quotes
        calls = []
        def calculate(*args):
            calls.append(args[4].resolution)
            if len(calls) == 1:
                writer.add_book_top(quote(START + timedelta(minutes=14, seconds=50), "999", "1001"), None)
            return original(*args)
        monkeypatch.setattr(service, "_report_from_quotes", calculate)
        actual = technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), **options)
        assert calls == ["1min", "15min"] and actual == expected
        assert technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), **options) != expected
    finally:
        db.c.close()
        writer.c.close()


def test_total_bar_budget_and_empty_timeframes_stay_explicit(tmp_path):
    db = market_db(tmp_path, [])
    try:
        with pytest.raises(ValueError, match="10000"):
            technical_reports(db, "BTCUSDT", START, START + timedelta(minutes=9500), resolutions=["1min", "15min"])
        assert not db.c.in_transaction
        result = technical_reports(db, "BTCUSDT", START, START + timedelta(hours=1), resolutions=["1min", "1h"])
        assert all(r["status"] == "UNAVAILABLE" for r in result["timeframes"].values())
        assert all(r["indicators"]["rsi_14"]["value"] is None for r in result["timeframes"].values())
    finally:
        db.c.close()
