"""Daily allocation paper journal: causal decisions, honest fills, one decision per completed day."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.allocation import daily_target
from gym.services.allocation import journal, run_day
from tests.support import START, market_db, quote

NOW = START.replace(hour=0, minute=10)  # just after a UTC day completes


def closes(n=60, step=0.01, start=100.0):
    out = [start]
    for i in range(1, n):
        out.append(out[-1] * (1 + step + (0.03 if i % 2 else -0.03)))
    return out


def test_target_waits_sizes_bands_and_exits():
    assert daily_target(closes(40), 0.0)["status"] == "WARMING_UP"
    up = daily_target(closes(), 0.0)
    assert up["close"] > up["average"] and up["volatility"] > 0.4
    assert up["trade"] and up["target"] == pytest.approx(0.4 / up["volatility"])
    assert not daily_target(closes(), up["target"] - 0.05)["trade"]  # inside the band: hold
    down = daily_target(closes(step=-0.01), 0.3)
    assert down["wanted"] == 0.0 and down["trade"] and down["target"] == 0.0  # exits ignore the band


def seed(tmp_path, prices, *, fetched=NOW - timedelta(minutes=5), with_quote=True):
    rows = [quote(NOW - timedelta(minutes=1), "99.9", "100.1")] if with_quote else []
    db = market_db(tmp_path, rows)
    first = NOW.replace(hour=0, minute=0) - timedelta(days=len(prices))
    db.upsert_candles("BTCUSDT", "1d", [{"t": first + timedelta(days=i), "o": p, "h": p, "l": p, "c": p, "v": 1}
                                        for i, p in enumerate(prices)], fetched)
    return db


def test_run_day_buys_at_the_ask_once_per_completed_day(tmp_path):
    db = seed(tmp_path, closes())
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    target = entry["decision"]["target"]
    fill = entry["fill"]
    assert entry["status"] == "READY" and fill["side"] == "BUY" and fill["price"] == "100.1"
    spent = Decimal(fill["qty"]) * Decimal("100.1")
    assert float(spent) == pytest.approx(1000 * target, rel=1e-6)  # target share of equity, bought at the ask
    assert Decimal(entry["holdings"]["quote"]) == Decimal(1000) - spent - Decimal(fill["fee"])
    assert Decimal(fill["fee"]) == spent * Decimal("0.001")
    again = run_day(db, tmp_path, ["BTCUSDT"], NOW + timedelta(hours=1))[0]
    assert again["status"] == "ALREADY_DECIDED" and len(journal(tmp_path)) == 1


def test_no_quote_means_no_fill_and_later_vintages_are_invisible(tmp_path):
    db = seed(tmp_path, closes(), with_quote=False)
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    assert entry["status"] == "NO_QUOTE" and "fill" not in entry and entry["holdings"] == {"base": "0", "quote": "1000"}
    late = seed(tmp_path / "late", closes(), fetched=NOW + timedelta(hours=1))
    assert run_day(late, tmp_path / "late", ["BTCUSDT"], NOW)[0]["status"] == "NO_CANDLES"
