import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB
from gym.domain.model import BookTop, InstrumentId
from gym.services.breadth_journal import journal, run_breadth_day

DAY0 = datetime(2026, 8, 1, tzinfo=UTC)
NOW = DAY0 + timedelta(days=80, hours=11, minutes=30)  # 15:00 Tehran on the day after the last candle


def store(tmp_path, paths):
    db = MarketDB(tmp_path / "market.db")
    for symbol, closes in paths.items():
        db.upsert_instrument(InstrumentId.wallex(symbol, symbol[:-4], "USDT"), {}, {}, "test", DAY0)
        candles = [{"t": DAY0 + timedelta(days=i), "o": c, "h": c, "l": c, "c": c, "v": Decimal(100)}
                   for i, c in enumerate(closes)]
        db.upsert_candles(symbol, "1d", candles, DAY0 + timedelta(days=len(closes)))
        last = closes[-1]
        db.add_book_top(BookTop(symbol, NOW - timedelta(seconds=30), last, last * Decimal("1.002"), Decimal(10),
                                Decimal(10), frozenset()), None)
    db.c.commit()
    return db


def up(rate):
    return [(Decimal(100) * Decimal(rate) ** i).quantize(Decimal("0.0001")) for i in range(80)]


def test_one_entry_per_day_with_a_decision_for_every_coin(tmp_path):
    db = store(tmp_path, {"AAAUSDT": up("1.01"), "BBBUSDT": up("1.01"), "CCCUSDT": up("0.99")})
    root = tmp_path / "live"
    entry = run_breadth_day(db, root, NOW)
    assert entry["status"] == "READY" and entry["gate_open"]
    assert entry["decisions"] == {"AAAUSDT": "OPEN", "BBBUSDT": "OPEN", "CCCUSDT": "CASH"}
    assert [t["side"] for t in entry["trades"]] == ["BUY", "BUY"]
    assert Decimal(entry["usdt"]) > Decimal(333) and Decimal(entry["equity"]) < Decimal(1000)  # costs are paid
    assert run_breadth_day(db, root, NOW + timedelta(hours=1))["status"] == "ALREADY_DECIDED"
    assert len(journal(root)) == 1
    db.c.close()


def test_a_closed_gate_holds_only_usdt(tmp_path):
    db = store(tmp_path, {"AAAUSDT": up("1.01"), "BBBUSDT": up("0.99"), "CCCUSDT": up("0.99")})
    entry = run_breadth_day(db, tmp_path / "live", NOW)
    assert not entry["gate_open"] and entry["trades"] == [] and entry["usdt"] == "1000"
    db.c.close()


def test_one_market_fetched_a_day_early_does_not_decide_the_day(tmp_path):
    db = store(tmp_path, {"AAAUSDT": up("1.01"), "BBBUSDT": up("1.01"), "CCCUSDT": up("0.99")})
    early = DAY0 + timedelta(days=80)
    db.upsert_candles("CCCUSDT", "1d", [{"t": early, **{k: Decimal(50) for k in "ohlc"}, "v": Decimal(100)}],
                      early + timedelta(hours=1))
    db.c.commit()
    entry = run_breadth_day(db, tmp_path / "live", early + timedelta(days=1, hours=11, minutes=30))
    assert entry["day"] == "2026-10-19T00:00:00.000000Z"  # the day all three completed, not CCC's extra one
    assert entry["universe"] == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    db.c.close()


def test_a_held_coin_without_fresh_candles_or_quote_keeps_its_last_close_value(tmp_path):
    db = store(tmp_path, {"AAAUSDT": up("1.01"), "BBBUSDT": up("1.01"), "CCCUSDT": up("0.99")})
    root = tmp_path / "live"
    (root / "allocation").mkdir(parents=True)
    (root / "allocation" / "breadth-journal.jsonl").write_text(
        '{"day": "2026-10-01T00:00:00.000000Z", "usdt": "500", "units": {"GONEUSDT": "10"}}\n', "utf-8")
    db.upsert_instrument(InstrumentId.wallex("GONEUSDT", "GONE", "USDT"), {}, {}, "test", DAY0)
    db.upsert_candles("GONEUSDT", "1d", [{"t": DAY0, **{k: Decimal(7) for k in "ohlc"}, "v": Decimal(1)}], DAY0 + timedelta(days=1))
    db.c.commit()
    entry = run_breadth_day(db, root, NOW)
    assert entry["decisions"]["GONEUSDT"] == "SKIP_NO_PRICE"
    assert entry["units"]["GONEUSDT"] == "10"
    spent = sum(Decimal(t["qty"]) * Decimal(t["price"]) for t in entry["trades"])
    assert Decimal(entry["equity"]) > Decimal(70)  # the 10 units still count at the last close of 7
    assert spent > 0
    db.c.close()


def test_no_cash_means_no_zero_quantity_buy(tmp_path):
    db = store(tmp_path, {"AAAUSDT": up("1.01"), "BBBUSDT": up("1.01"), "CCCUSDT": up("0.99")})
    entry = run_breadth_day(db, tmp_path / "live", NOW, cash=Decimal(0))
    assert entry["trades"] == []
    assert set(entry["decisions"].values()) <= {"CASH", "SKIP_NO_CASH"}
    db.c.close()


def test_a_failed_refresh_still_records_the_day_from_stored_candles(tmp_path, monkeypatch):
    import gym.commands.research as research
    from gym.cli import main

    db = store(tmp_path / "live", {"AAAUSDT": up("1.01"), "BBBUSDT": up("1.01"), "CCCUSDT": up("0.99")})
    db.c.close()

    def unreachable(args):
        raise OSError("venue unreachable")

    monkeypatch.setattr(research, "history_cmd", unreachable)
    monkeypatch.setattr(research, "now_utc", lambda: NOW)
    assert main(["--data", str(tmp_path), "breadth-journal", "--refresh"]) == 0
    assert journal(tmp_path / "live")[0]["day"] == "2026-10-19T00:00:00.000000Z"
    monkeypatch.setattr(research, "now_utc", lambda: NOW + timedelta(days=1))
    assert main(["--data", str(tmp_path), "breadth-journal", "--refresh"]) == 1
    assert len(journal(tmp_path / "live")) == 1


def test_best_effort_refresh_skips_one_failing_symbol_without_stalling_universe(tmp_path, monkeypatch, capsys):
    """E013: a single unreadable USDT symbol must not abort the remaining 200+ markets in breadth-journal --refresh."""
    from contextlib import asynccontextmanager

    import gym.commands.research as research
    from gym.cli import main

    db = store(tmp_path / "live", {"AAAUSDT": up("1.01"), "BADUSDT": up("1.00"), "CCCUSDT": up("1.01")})
    db.c.close()
    next_day = DAY0 + timedelta(days=80)
    run_at = next_day + timedelta(days=1, hours=11, minutes=30)

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def fake_fetch(self, _session, symbol, resolution, _lo, _hi):
        if symbol == "BADUSDT":
            self.candle_errors += 1
            return 0
        self.db.upsert_candles(
            symbol, resolution,
            [{"t": next_day, "o": Decimal(250), "h": Decimal(255), "l": Decimal(245), "c": Decimal(250), "v": Decimal(100)}],
            run_at - timedelta(seconds=1),
        )
        self.db.c.commit()
        return 1

    monkeypatch.setattr(research.wallex, "public_session", fake_session)
    monkeypatch.setattr(research.Collector, "fetch_candles", fake_fetch)
    monkeypatch.setattr(research, "now_utc", lambda: run_at)
    assert main(["--data", str(tmp_path), "breadth-journal", "--refresh"]) == 0
    rows = journal(tmp_path / "live")
    assert len(rows) == 1 and rows[0]["day"] == "2026-10-20T00:00:00.000000Z"
    capsys.readouterr()
    assert main(["--data", str(tmp_path), "history", "BADUSDT", "CCCUSDT", "--resolution", "1d",
                 "--from", "2026-10-19T00:00:00Z", "--best-effort"]) == 3
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["candles"] == {"BADUSDT": 0, "CCCUSDT": 1}
    assert set(receipt["failed_symbols"]) == {"BADUSDT"}
