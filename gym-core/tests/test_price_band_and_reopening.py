"""PriceBand vetoes (side-specific, Tehran-day reference) and reopening gap marks (SIM-04)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId
from gym.domain.rules import evaluate, parse_rule
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from gym.services.data_portal import DataPortal
from gym.services.session import PaperSession
from gym.services.rules import RuleService
from gym.domain.strategy import BuyAndHold

from .support import START, market_db

USDT = InstrumentId.wallex("USDTTMN")


def band(**params):
    return parse_rule({"id": "usdt-band", "family": "PriceBand", "class": "VENUE", "action": "BLOCK_ENTRY",
                       "scope": {"venue": "wallex", "symbols": ["USDTTMN"], "side": "BUY"},
                       "params": {"max_change_pct": "4", "direction": "UP", **params},
                       "effective_from": "2026-01-01T00:00:00Z", "source": "announcement", "status": "VERIFIED"})


def test_price_band_validation():
    with pytest.raises(ValueError):
        band(direction="SIDEWAYS")
    with pytest.raises(ValueError):
        band(max_change_pct=4.0)


def test_price_band_is_side_specific_and_warns_without_reference():
    rules = [band()]
    assert not evaluate(rules, USDT, "BUY", "ENTRY", START, day_change_pct=Decimal("4.10")).allowed
    assert evaluate(rules, USDT, "BUY", "ENTRY", START, day_change_pct=Decimal("3.99")).allowed
    assert evaluate(rules, USDT, "SELL", "EXIT", START, day_change_pct=Decimal("9")).allowed
    unknown = evaluate(rules, USDT, "BUY", "ENTRY", START)
    assert unknown.allowed and "day reference unknown" in unknown.warnings[0]["why"]


def test_simulator_band_lock_is_a_nonfill():
    top = BookTop("USDTTMN", START, Decimal(104900), Decimal(105000), Decimal(1), Decimal(1), frozenset())
    book = CashBook({"TMN": Decimal(1_000_000)})
    cost = CostModel(latency=timedelta(0))
    out = market_order(book, USDT, "BUY", Decimal(1), START, Decimal(105000), [top], 0, cost, Spec(None, None, None),
                       [band()], {}, "USDTTMN#1", day_open=Decimal(100000))
    assert out["status"] == "NONFILL" and out["reason"] == "RULE:usdt-band"
    assert book.get("TMN") == Decimal(1_000_000)


def test_reopening_gap_is_marked_once(tmp_path):
    # USDTTMN closes 23:30-11:30 Tehran (20:00-08:00 UTC) after 2026-10-18.
    before = START.replace(hour=19, minute=50)  # 23:20 Tehran
    rows = [BookTop("USDTTMN", before + timedelta(seconds=10 * i), Decimal(100000), Decimal(100010), Decimal(1), Decimal(1), frozenset())
            for i in range(30)]
    reopen = START.replace(hour=8, minute=0) + timedelta(days=1)
    rows += [BookTop("USDTTMN", reopen + timedelta(seconds=10 * i), Decimal(103000), Decimal(103010), Decimal(1), Decimal(1), frozenset())
             for i in range(30)]
    db = market_db(tmp_path, rows)
    portal = DataPortal(db)
    rules = RuleService(db).load(START)[1]
    session = PaperSession(portal, lambda t: rules, BuyAndHold(), "USDTTMN", before, "1min", Decimal(1_000_000),
                           CostModel(latency=timedelta(seconds=1)))
    for row in rows:
        session.feed(row)
    session.finish(rows[-1].ts_avail)
    assert len(session.reopenings) == 1
    gap = session.reopenings[0]
    held = Decimal(gap["base_held"])
    assert held > 0 and Decimal(gap["gap_value"]) == held * 3000
    assert gap["first_quote"].startswith("2026-10-30T08:00:00") and gap["reopened_at"].startswith("2026-10-30T08:00:00")
    assert session.curve[-1][0] >= gap["first_quote"]
