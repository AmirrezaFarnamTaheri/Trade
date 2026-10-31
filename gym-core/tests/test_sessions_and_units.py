"""Trading-session bars, the stale FX factor during closures, and IRT unit discontinuities."""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB, SegmentWriter
from gym.domain.bars import BarSpec, Consolidator, quote_bars
from gym.domain.model import TEHRAN, UTC, BookSide, InstrumentId
from gym.domain.rules import PRESETS, evaluate, is_closed, parse_rule, session_period
from gym.domain.units import UnitWatch, rescale_exponent
from gym.services.collector import Collector
from gym.services.paper import paper
from tests.support import START, market_db, quote

RULES = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
USDT, BTC = InstrumentId.wallex("USDTTMN"), InstrumentId.wallex("BTCTMN")


def teh(text):
    return datetime.fromisoformat(text).replace(tzinfo=TEHRAN).astimezone(UTC)


def test_session_is_the_open_stretch_between_closures():
    assert session_period(RULES, USDT, teh("2026-10-31T12:00")) == (teh("2026-10-31T11:30"), teh("2026-10-31T23:30"))
    assert session_period(RULES, USDT, teh("2026-10-31T23:45")) == (teh("2026-10-31T23:30"), teh("2026-11-01T11:30"))
    # The earlier 21:00-09:00 vintage bounds sessions before 18 October.
    assert session_period(RULES, USDT, teh("2026-10-10T12:00")) == (teh("2026-10-10T09:00"), teh("2026-10-10T21:00"))
    # A pair with no closure gets one session per Tehran day.
    assert session_period(RULES, BTC, teh("2026-10-31T12:00")) == (teh("2026-10-31T00:00"), teh("2026-11-01T00:00"))
    assert is_closed(RULES, USDT, teh("2026-10-31T02:00")) and not is_closed(RULES, BTC, teh("2026-10-31T02:00"))


def test_session_bars_need_rules_and_close_at_the_closure():
    with pytest.raises(ValueError, match="period"):
        Consolidator("USDTTMN", BarSpec("session"))
    with pytest.raises(ValueError, match="trading-window"):
        BarSpec("session").bucket(START)
    period = lambda t: session_period(RULES, USDT, t)  # noqa: E731
    tops = [replace(quote(teh("2026-10-31T12:00") + timedelta(hours=h), str(100 + h), str(101 + h)), symbol="USDTTMN")
            for h in range(11)]
    tops.append(replace(quote(teh("2026-11-01T12:00"), "200", "201"), symbol="USDTTMN"))
    bars = quote_bars("USDTTMN", BarSpec("session"), tops, period)
    assert [(b.start, b.end, b.avail) for b in bars] == [(teh("2026-10-31T11:30"), teh("2026-10-31T23:30"),
                                                          teh("2026-10-31T23:30"))]
    assert bars[0].open == Decimal("100.5") and bars[0].close == Decimal("110.5") and bars[0].count == 11


def test_replay_records_closures_as_closed_not_as_missing_data(tmp_path):
    t0, t1 = teh("2026-10-31T21:00"), teh("2026-11-01T14:00")
    open_hours = [teh("2026-10-31T21:00") + timedelta(minutes=m) for m in range(0, 150, 1)]
    open_hours += [teh("2026-11-01T11:30") + timedelta(minutes=m) for m in range(0, 150, 1)]
    rows = [replace(quote(t, str(1000 + i % 7), str(1002 + i % 7)), symbol="USDTTMN") for i, t in enumerate(open_hours)]
    out = paper(market_db(tmp_path, rows), "USDTTMN", t0, t1, resolution="1h", fast=2, slow=3)
    reasons = {(s["from"][:16], s["reason"]) for s in out["result"]["session"]["skipped"]}
    assert ("2026-10-31T20:00", "VENUE_CLOSED") in reasons  # 23:30 Tehran closure starts inside the 20:00Z bar
    assert not any(r == "NO_OBSERVATIONS" for _, r in reasons)


def test_fx_factor_is_labeled_stale_while_usdt_irt_is_closed(tmp_path):
    t0, t1 = teh("2026-10-31T12:00"), teh("2026-11-01T01:00")  # ends inside the 23:30-11:30 closure
    steps = int((t1 - t0).total_seconds() // 60)
    rows = [replace(quote(t0 + timedelta(minutes=i), "1000", "1002"), symbol="USDTTMN") for i in range(0, 690)]
    rows += [replace(quote(t0 + timedelta(minutes=i), str(70000000 + i), str(70000100 + i)), symbol="BTCTMN")
             for i in range(steps)]
    out = paper(market_db(tmp_path, rows), "BTCTMN", t0, t1, resolution="15min", fast=2, slow=3)
    assert (out["fx"]["start_status"], out["fx"]["end_status"]) == ("LIVE", "STALE_CLOSED")
    assert any("STALE_CLOSED" in w for w in out["warnings"])


def test_rescale_exponent_recognises_only_powers_of_ten():
    assert rescale_exponent(Decimal("0.001")) == -3 and rescale_exponent(Decimal("1000.9")) == 3
    assert rescale_exponent(Decimal("1.04")) is None and rescale_exponent(Decimal("3")) is None


def mids(scale, drift=Decimal(1)):
    usdt = Decimal("100000") * scale * drift
    return {("USDT", "TMN"): usdt, ("BTC", "USDT"): Decimal("70000") * drift,
            ("BTC", "TMN"): Decimal("70000") * usdt * drift, ("ETH", "USDT"): Decimal("2500"),
            ("ETH", "TMN"): Decimal("2500") * usdt}


def test_unit_watch_ignores_market_moves_and_lone_glitches():
    watch = UnitWatch()
    assert watch.observe(mids(1)) is None
    assert watch.observe(mids(1, Decimal("1.3"))) is None  # a 30% crash in IRT is a market move, not a unit change
    glitch = mids(1, Decimal("1.3")) | {("ETH", "TMN"): mids(1, Decimal("1.3"))["ETH", "TMN"] * 1000}
    assert watch.observe(glitch) is None  # one asset alone is not a redenomination


def test_redenomination_freezes_irt_entries_but_never_exits(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    symbols = ["USDTTMN", "BTCTMN", "BTCUSDT", "ETHTMN", "ETHUSDT"]
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), symbols)
    now = START

    def show(scale, at):
        for (base, quote_ccy), mid in mids(scale).items():
            side = lambda p: BookSide([(p, Decimal(1))] * 3, at)  # noqa: E731
            col.books[base + quote_ccy] = {"bid": side(mid * Decimal("0.9999")), "ask": side(mid * Decimal("1.0001"))}
        col.tick(at)

    show(Decimal(1), now)
    show(Decimal("0.001"), now + timedelta(seconds=2))  # every IRT price /1000 at once; USDT prices unchanged
    flags = db.c.execute("select detail from quality_events where flag='UNIT_DISCONTINUITY'").fetchall()
    assert len(flags) == 1 and json.loads(flags[0][0])["exponent"] == -3
    rules = [parse_rule(d) for d in db.rules_as_of()[1].values()]
    later = now + timedelta(minutes=1)
    assert not evaluate(rules, BTC, "BUY", "ENTRY", later).allowed
    assert evaluate(rules, BTC, "SELL", "EXIT", later).allowed
    assert evaluate(rules, InstrumentId.wallex("BTCUSDT"), "BUY", "ENTRY", later).allowed
    show(Decimal("0.001"), now + timedelta(seconds=4))  # the new level is the new reference: no repeat event
    assert db.c.execute("select count(*) from quality_events where flag='UNIT_DISCONTINUITY'").fetchone()[0] == 1
    # Stored observations are kept exactly as observed (change-only: the repeat is not rewritten).
    stored = db.c.execute("select bid from book_top where instrument_id='wallex:USDTTMN' order by ts_avail").fetchall()
    assert [Decimal(b) for (b,) in stored] == [Decimal("99990.0000"), Decimal("99.9900000")]
