"""Original D backlog #2/#3: canonical periods and causal event delivery."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from itertools import permutations
from random import Random

import pytest

from gym.domain.bars import (BarSpec, ClockEvent, CloseSubscriptions, Consolidator, EventClock,
                             quote_bars)
from gym.domain.model import TEHRAN, UTC, TradeTick, parse_ts
from gym.domain.periods import Calendar, Count, DirectionalChange, Fixed, Mixed, Volume
from tests.support import START, quote


def test_fixed_anchor_half_open_boundaries_quiet_scan_and_lag():
    anchor = START + timedelta(seconds=7)
    c = Consolidator("X", BarSpec("1min"), Fixed(timedelta(minutes=5), anchor),
                     publication_lag=timedelta(seconds=3))
    assert c.update(anchor - timedelta(microseconds=1), D(10)) == []
    assert c.update(anchor, D(20)) == []
    assert c.forming(anchor).open == 20 and c.forming(anchor).forming
    assert c.scan(anchor + timedelta(seconds=2)) == []
    closed, = c.scan(anchor + timedelta(seconds=3))
    assert (closed.start, closed.end, closed.avail, closed.close) == (
        anchor - timedelta(minutes=5), anchor, anchor + timedelta(seconds=3), D(10))
    assert not closed.forming
    assert c.scan(anchor + timedelta(minutes=5)) == []
    assert c.forming(anchor + timedelta(minutes=5)) is None
    assert c.scan(anchor + timedelta(minutes=5, seconds=3))[0].close == 20
    assert c.scan(anchor + timedelta(days=10)) == []  # no fabricated empty bars


@pytest.mark.parametrize(("date", "hours"), [("2021-03-22T12:00:00+04:30", 23),
                                             ("2021-09-21T12:00:00+04:30", 25),
                                             ("2026-10-29T12:00:00+03:30", 24)])
def test_tehran_daily_actual_dst_boundaries(date, hours):
    t = parse_ts(date)
    c = Consolidator("X", BarSpec("1day"))
    start, end = c.period_of(t)
    assert start <= t < end
    assert end - start == timedelta(hours=hours)
    assert c.spec.bucket(t) == start
    assert c.period_of(end)[0] == end
    c.update(t, D(1))
    bar, = c.scan(end)
    assert (bar.start, bar.end, bar.avail) == (start, end, end)


def test_same_utc_instant_in_tehran_has_identical_fixed_bucket():
    p = Fixed(timedelta(hours=1))
    assert p(START) == p(START.astimezone(TEHRAN))
    assert BarSpec("1h").bucket(START) == BarSpec("1h").bucket(START.astimezone(TEHRAN))


@pytest.mark.parametrize("period", [Count(2), Volume(D("0.3"))])
def test_trade_threshold_exact_boundary_whole_trade_and_no_quiet_close(period):
    c = Consolidator("X", BarSpec("1min", "LAST"), period)
    assert c.update(START, D(10), D("0.1")) == []
    assert c.scan(START + timedelta(days=1)) == []
    end = START + timedelta(days=1, seconds=1)
    bar, = c.update(end, D(12), D("0.2"))
    assert (bar.start, bar.end, bar.avail, bar.volume, bar.count) == (START, end, end, D("0.3"), 2)
    assert (bar.open, bar.high, bar.low, bar.close) == (10, 12, 10, 12)
    assert c.forming(end) is None
    c.update(end, D(11), D("0.05"))
    assert c.forming(end).count == 1
    overshoot = Consolidator("X", BarSpec("1min", "LAST"), Volume(D(1)))
    bar, = overshoot.update(START, D(10), D(3))
    assert bar.volume == 3 and overshoot.forming(START) is None


def test_mixed_first_limit_wins_and_no_trade_double_counting():
    period = Mixed((Fixed(timedelta(minutes=1), START), Count(3), Volume(D(5))))
    c = Consolidator("X", BarSpec("1min", "LAST"), period)
    c.update(START, D(10), D(1))
    v, = c.update(START + timedelta(seconds=1), D(11), D(4))
    assert v.count == 2 and v.volume == 5
    for i in (2, 3):
        assert c.update(START + timedelta(seconds=i), D(10), D(1)) == []
    n, = c.update(START + timedelta(seconds=4), D(10), D(1))
    assert n.count == 3 and n.start > v.end
    c.update(START + timedelta(seconds=5), D(12), D(1))
    timed, = c.update(START + timedelta(minutes=1), D(20), D(1))
    assert timed.count == 1 and timed.close == 12 and timed.start > n.end
    assert c.forming(START + timedelta(minutes=1)).open == 20
    assert sum(b.count for b in (v, n, timed)) + c.forming(START + timedelta(minutes=1)).count == 7


def test_calendar_consumes_exact_supplied_jalali_month_boundaries():
    # Exact published civil dates for Farvardin/Ordibehesht 1403, not a conversion algorithm.
    edges = [parse_ts(s) for s in ("2024-03-20T00:00:00+03:30", "2024-04-20T00:00:00+03:30",
                                   "2024-05-21T00:00:00+03:30")]
    def boundaries(t):
        return next((a, b) for a, b in zip(edges, edges[1:]) if a <= t < b)
    c = Consolidator("X", BarSpec("1day"), Calendar(boundaries))
    c.update(edges[0], D(10))
    bar, = c.update(edges[1], D(20))
    assert (bar.start, bar.end, bar.count) == (edges[0], edges[1], 1)
    assert c.forming(edges[1]).start == edges[1]


@pytest.mark.parametrize("bounds", [(START, START), (START + timedelta(seconds=1), START + timedelta(days=1)),
                                    (START.replace(tzinfo=None), START + timedelta(days=1))])
def test_invalid_calendar_does_not_advance_or_mutate(bounds):
    c = Consolidator("X", BarSpec("1min"), Calendar(lambda t: bounds))
    with pytest.raises(ValueError):
        c.update(START, D(1))
    assert c.cur is None and c.watermark is None


def test_dc_bid_ask_confirmation_asymmetry_and_actual_confirmation_time():
    c = Consolidator("X", BarSpec("1min"), DirectionalChange(D("0.1"), D("0.2")),
                     publication_lag=timedelta(seconds=2))
    def feed(i, bid, ask):
        return c.update(START + timedelta(seconds=i), (D(bid) + D(ask)) / 2, bid=D(bid), ask=D(ask))
    assert feed(0, "100", "101") == []
    assert feed(1, "90", "91") == []  # low extreme, not confirmation time
    assert feed(2, "99", "110") == []  # ask crosses upward threshold, bid does not
    assert feed(3, "100", "111") == []  # bid confirms, publication delayed
    assert c.forming(START + timedelta(seconds=3)) is None
    up, = c.scan(START + timedelta(seconds=5))
    assert up.end == START + timedelta(seconds=3) and up.avail == START + timedelta(seconds=5)
    assert c.direction == 1
    assert feed(6, "120", "121") == []
    assert feed(7, "90", "100") == []  # bid crosses downward threshold, ask does not
    assert feed(8, "90", "98") == []
    down, = c.scan(START + timedelta(seconds=10))
    assert down.end == START + timedelta(seconds=8) and c.direction == -1


@pytest.mark.parametrize("factory", [lambda: Fixed(timedelta(0)), lambda: Count(True), lambda: Count(0),
    lambda: Volume(D("NaN")), lambda: Volume(1.0), lambda: Mixed((Count(1),)),
    lambda: DirectionalChange(D(0)), lambda: DirectionalChange(D("Infinity")),
    lambda: Calendar(None)])
def test_period_parameters_reject_invalid_values(factory):
    with pytest.raises(ValueError):
        factory()


def test_dc_exact_log_threshold_and_same_instant_trade_count():
    delta = (D(110) / D(100)).ln()
    c = Consolidator("X", BarSpec("1min", "LAST"), DirectionalChange(delta))
    c.update(START, D(100))
    closed, = c.update(START, D(110))
    assert closed.count == 2 and closed.end == closed.avail == START
    assert c.direction == 1
    count = Consolidator("X", BarSpec("1min", "LAST"), Count(2))
    assert count.update(START, D(1), D(1)) == []
    assert count.update(START, D(1), D(1))[0].count == 2


def test_invalid_or_late_input_never_mutates_existing_bar():
    c = Consolidator("X", BarSpec("1min"), DirectionalChange(D("0.1")))
    c.update(START, D(100))
    before = c.forming(START), c.extreme, c.direction
    for t, kwargs in [(START - timedelta(seconds=1), {}), (START.replace(tzinfo=None), {}),
                      (START + timedelta(seconds=1), {"bid": D(101), "ask": D(100)})]:
        with pytest.raises(ValueError):
            c.update(t, D(100), **kwargs)
        assert (c.forming(START), c.extreme, c.direction) == before


@pytest.mark.parametrize("period", [Fixed(timedelta(seconds=30), START), Count(7), Volume(D("1.7")),
    Mixed((Fixed(timedelta(seconds=30), START), Count(5))),
    Calendar(Fixed(timedelta(minutes=1), START)), DirectionalChange(D("0.015"))])
def test_seeded_raw_ticks_identical_under_chunked_stream_feeding(period):
    rng = Random(42)
    rows = [(START + timedelta(seconds=i), D(100 + rng.randrange(-5, 6)), D("0.3")) for i in range(100)]
    def run(chunk):
        c, out = Consolidator("X", BarSpec("1min", "LAST"), period), []
        for offset in range(0, len(rows), chunk):
            for row in rows[offset:offset + chunk]:
                out += c.update(*row)
        out += c.scan(START + timedelta(minutes=5))
        return out, c.forming(START + timedelta(minutes=5))
    assert run(1) == run(9) == run(100)


def test_clock_permutations_deliver_identical_causal_close_event_regime_order():
    boundary = START + timedelta(minutes=15)
    closes = CloseSubscriptions("X", ("15min", "1min"))
    closes.update(START, D(10))
    bars = closes.scan(boundary)
    # The minute bar closed earlier; use actual simultaneous 15-minute/minute closes.
    minute = Consolidator("X", BarSpec("1min"))
    minute.update(boundary - timedelta(seconds=1), D(10))
    bars = [minute.scan(boundary)[0], next(b for b in bars if b.spec.resolution == "15min")]
    events = [ClockEvent("close", b.spec.resolution, b.end, b.avail, i, b) for i, b in enumerate(bars)]
    events += [ClockEvent("event", "dc_up", boundary - timedelta(seconds=3), boundary, 8),
               ClockEvent("regime", "window_close", boundary, boundary, 9)]
    expected = None
    for arrival in permutations(events):
        clock = EventClock()
        clock.on_regime("window_close")
        clock.on_close("15min")
        clock.on_event("dc_up")
        clock.on_close("1min")
        clock.on_event("dc_up")  # subscription order breaks equal resolution rank
        for event in arrival:
            clock.publish(event)
        assert clock.drain(boundary - timedelta(microseconds=1)) == []
        delivered = clock.drain(boundary)
        trace = [(index, e.kind, e.name, e.sequence) for index, e in delivered]
        assert [i for i, _ in delivered] == [3, 1, 0, 2, 4]
        expected = trace if expected is None else expected
        assert trace == expected
        assert clock.drain(boundary) == []
        with pytest.raises(ValueError, match="late"):
            clock.publish(events[0])


def test_clock_availability_stable_sequence_validation_and_forming_rejection():
    clock = EventClock()
    clock.on_event("dc")
    delayed = ClockEvent("event", "dc", START, START + timedelta(seconds=10), 1)
    clock.publish(delayed)
    with pytest.raises(ValueError, match="duplicate"):
        clock.publish(delayed)
    clock.publish(replace(delayed, sequence=0))
    assert clock.drain(START) == []
    assert [e.sequence for _, e in clock.drain(delayed.avail)] == [0, 1]
    with pytest.raises(ValueError, match="backwards"):
        clock.drain(START)
    with pytest.raises(ValueError, match="confirmation"):
        ClockEvent("event", "dc", delayed.avail, START, 0)
    with pytest.raises(ValueError):
        clock.on_regime("invented")
    c = Consolidator("X", BarSpec("1min"))
    c.update(START, D(10))
    with pytest.raises(ValueError, match="forming"):
        EventClock().publish_close(c.forming(START), 0)
    b, = c.scan(START + timedelta(minutes=1))
    other = EventClock()
    other.on_close("1min")
    other.publish_close(b, 0)
    assert other.drain(b.avail) == [(0, ClockEvent("close", "1min", b.end, b.avail, 0, b))]


def test_delayed_trade_prints_use_availability_and_reject_quote_counting():
    c = Consolidator("X", BarSpec("1min", "LAST"), Count(1))
    trade = TradeTick("X", START - timedelta(minutes=10), START, D(10), D(2), "BUY")
    bar, = c.update_trade(trade)
    assert bar.start == bar.end == bar.avail == START
    with pytest.raises(ValueError, match="trade prints"):
        c.update_quote(quote(START, "10", "11"))
    with pytest.raises(ValueError, match="symbol"):
        c.update_trade(replace(trade, symbol="OTHER"))
    with pytest.raises(ValueError, match="times"):
        c.update_trade(replace(trade, ts_event=START + timedelta(seconds=1)))
    assert c.forming(START) is None


def test_dc_quote_batch_and_real_confirmation_feed_event_clock():
    rows = [quote(START + timedelta(seconds=i), bid, ask) for i, (bid, ask) in
            enumerate([("100", "101"), ("90", "91"), ("99", "110"), ("100", "111")])]
    c = Consolidator("X", BarSpec("1min"), DirectionalChange(D("0.1")))
    out = []
    for row in rows:
        out += c.update_quote(row)
    assert out == quote_bars("X", BarSpec("1min"), rows, DirectionalChange(D("0.1")))
    confirmed, = out
    clock = EventClock()
    clock.on_event("dc_up")
    clock.publish(ClockEvent("event", "dc_up", confirmed.end, confirmed.avail, 0, confirmed))
    assert clock.drain(confirmed.end - timedelta(microseconds=1)) == []
    assert clock.drain(confirmed.end)[0][1].payload == confirmed


def test_existing_quote_batch_uses_the_same_calendar_streaming_path():
    period = Calendar(Fixed(timedelta(minutes=2), START))
    tops = [quote(START + timedelta(minutes=i), str(100 + i), str(102 + i)) for i in range(5)]
    c, out = Consolidator("X", BarSpec("1min"), period), []
    for top in tops:
        out += c.update(top.ts_avail, c.spec.price(top))
    assert out == quote_bars("X", BarSpec("1min"), tops, period)
