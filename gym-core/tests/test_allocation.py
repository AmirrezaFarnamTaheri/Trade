"""Daily allocation paper journal: causal decisions, honest fills, one decision per completed day."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.allocation import daily_target
from gym.domain.model import InstrumentId, iso
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


@pytest.mark.parametrize("name", ["lookback", "vol_days"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "30", None, 401])
def test_invalid_windows_are_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        daily_target(closes(), 0, **{name: value})


def test_windows_fit_the_400_day_history():
    assert daily_target(closes(400), 0, lookback=400, vol_days=399)["status"] == "READY"
    with pytest.raises(ValueError, match="vol_days"):
        daily_target(closes(400), 0, vol_days=400)


def test_run_day_validates_before_writing_even_without_candles(tmp_path):
    db = market_db(tmp_path, [])
    with pytest.raises(ValueError, match="lookback"):
        run_day(db, tmp_path, ["BTCUSDT"], NOW, lookback=0)
    assert not (tmp_path / "allocation").exists()


def test_run_day_can_use_all_400_completed_daily_candles(tmp_path):
    db = seed(tmp_path, closes(400))
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW, lookback=400, vol_days=399)[0]
    assert entry["status"] == "READY"


def test_repeated_symbols_are_decided_once_in_input_order(tmp_path):
    db = seed(tmp_path, closes())
    entries = run_day(db, tmp_path, ["BTCUSDT", "ETHUSDT", "BTCUSDT", "ETHUSDT"], NOW)
    assert [e["symbol"] for e in entries] == ["BTCUSDT", "ETHUSDT"]
    assert len(journal(tmp_path)) == 1


def set_spec(db, spec, at=NOW - timedelta(days=1)):
    db.upsert_instrument(InstrumentId.wallex("BTCUSDT", "BTC", "USDT"), {}, spec, "test", at)


def seed_exit(tmp_path):
    prior = {"symbol": "BTCUSDT", "day": iso(NOW - timedelta(days=2)),
             "holdings": {"base": "1.23456789", "quote": "10"}}
    path = tmp_path / "allocation" / "journal.jsonl"
    path.parent.mkdir()
    original = json.dumps(prior) + "\n"
    path.write_text(original, encoding="utf-8")
    return prior["holdings"], path.read_bytes()


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_fills_use_current_precision_and_preserve_quote_fees(tmp_path, side):
    db = seed(tmp_path, closes(step=0.01 if side == "BUY" else -0.01))
    holdings, original = ({"base": "0", "quote": "1000"}, b"") if side == "BUY" else seed_exit(tmp_path)
    set_spec(db, {"stepSize": 2, "minQty": "0.01", "minNotional": "1"})
    # A later, stricter vintage must not leak into today's fill.
    set_spec(db, {"stepSize": 0, "minNotional": "10000"}, NOW + timedelta(seconds=1))
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    fill = entry["fill"]
    quantity, price, fee = (Decimal(fill[k]) for k in ("qty", "price", "fee"))
    assert quantity > 0 and quantity == quantity.quantize(Decimal("0.01"))
    assert fill["side"] == side and fee == quantity * price * Decimal("0.001")
    sign = 1 if side == "BUY" else -1
    assert Decimal(entry["holdings"]["base"]) == Decimal(holdings["base"]) + sign * quantity
    assert Decimal(entry["holdings"]["quote"]) == Decimal(holdings["quote"]) - sign * quantity * price - fee
    if side == "SELL":
        assert quantity == Decimal("1.23") and Decimal(entry["holdings"]["base"]) == Decimal("0.00456789")
    assert (tmp_path / "allocation" / "journal.jsonl").read_bytes().startswith(original)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("spec", [{"minQty": "100"}, {"minNotional": "10000"}, "rounded", "rounded_notional"])
def test_known_minimum_violations_never_fill_or_change_holdings(tmp_path, side, spec):
    db = seed(tmp_path, closes(step=0.01 if side == "BUY" else -0.01))
    holdings, original = ({"base": "0", "quote": "1000"}, b"") if side == "BUY" else seed_exit(tmp_path)
    if spec == "rounded":
        spec = {"stepSize": 0, "minQty": "7.01" if side == "BUY" else "1.01"}
    elif spec == "rounded_notional":
        spec = {"stepSize": 0, "minNotional": "702" if side == "BUY" else "110"}
    set_spec(db, spec)
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    assert entry["status"] == "BLOCKED" and "fill" not in entry
    assert entry["holdings"] == holdings
    assert entry["blockers"] == ["BELOW_MIN_NOTIONAL"]
    assert (tmp_path / "allocation" / "journal.jsonl").read_bytes().startswith(original)


@pytest.mark.parametrize("vintage", ["missing", "expired", "future"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_unknown_specifications_follow_simulator_convention(tmp_path, vintage, side):
    db = seed(tmp_path, closes(step=0.01 if side == "BUY" else -0.01))
    if side == "SELL":
        seed_exit(tmp_path)
    if vintage != "missing":
        set_spec(db, {"stepSize": 0, "minNotional": "10000"},
                 NOW + timedelta(seconds=1) if vintage == "future" else NOW - timedelta(days=2))
        if vintage == "expired":
            db.c.execute("UPDATE instrument_specs SET valid_to=?", (iso(NOW - timedelta(days=1)),))
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    assert entry["status"] == "READY" and entry["fill"]["side"] == side
    quantity = Decimal(entry["fill"]["qty"])
    if side == "BUY":
        assert quantity != quantity.quantize(Decimal("0.00000001"))  # no invented venue precision
    else:
        assert quantity == Decimal("1.23456789") and Decimal(entry["holdings"]["base"]) == 0


def test_old_but_still_valid_specification_remains_enforced(tmp_path):
    db = seed(tmp_path, closes())
    set_spec(db, {"minNotional": "10000"}, NOW - timedelta(days=100))
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    assert entry["status"] == "BLOCKED" and "fill" not in entry


def test_full_allocation_leaves_enough_quote_for_the_fee(tmp_path):
    db = seed(tmp_path, [100 + i for i in range(60)])
    entry = run_day(db, tmp_path, ["BTCUSDT"], NOW)[0]
    assert entry["decision"]["target"] == 1
    assert Decimal(entry["holdings"]["quote"]) >= 0
    assert Decimal(entry["fill"]["fee"]) == Decimal(entry["fill"]["qty"]) * Decimal("100.1") * Decimal("0.001")
