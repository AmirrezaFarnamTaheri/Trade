"""The funding filter reads only settled funding, needs a year of history, and skips coins that are not liquid."""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("funding_filter", SCRIPTS / "funding_filter.py")
funding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(funding)
import binance_archive as funding_archive  # noqa: E402

DAYS = [(date(2021, 1, 1) + timedelta(days=i)).isoformat() for i in range(500)]


def test_a_year_of_history_is_needed_and_a_spike_is_flagged():
    rates = {day: 0.0001 for day in DAYS}
    for day in DAYS[450:]:
        rates[day] = 0.001
    flags = funding.crowded(DAYS, rates, 0.9)
    assert flags[funding.CROWD_DAYS - 1 + funding.HISTORY - 1] is None
    assert flags[funding.CROWD_DAYS - 1 + funding.HISTORY] is False
    assert flags[455] is True


def test_funding_after_the_decision_day_is_never_used():
    rates = {day: 0.0001 * (i % 9) for i, day in enumerate(DAYS)}
    changed = dict(rates, **{day: 0.05 for day in DAYS[420:]})
    assert funding.crowded(DAYS, rates, 0.8)[:420] == funding.crowded(DAYS, changed, 0.8)[:420]


def test_a_crowded_day_holds_usdt_even_above_the_average():
    closes = [100 * 1.01 ** i for i in range(60)]
    days = DAYS[:60]
    plain = funding.returns(days, closes, None)
    blocked = funding.returns(days, closes, [True] * 60)
    assert all(r > 0 for _, r in plain[1:]) and all(r == 0 for _, r in blocked)


def test_a_coin_that_turns_illiquid_is_sold_and_charged_then_skipped():
    closes = [100 * 1.01 ** i for i in range(80)]
    eligible = [True] * 60 + [False] * 20
    rows = funding.returns(DAYS[:80], closes, None, eligible)
    assert rows[-1] == (DAYS[61], -funding.COST) and all(day <= DAYS[61] for day, _ in rows)


def test_liquidity_needs_thirty_prior_days_above_the_floor():
    volumes = [funding_archive.MIN_VOLUME * 2] * 40 + [1.0] * 40
    flags = funding_archive.liquid(volumes)
    assert flags[29] is False and flags[30] is True and flags[75] is False
