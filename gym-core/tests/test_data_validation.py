"""Unambiguous external dates and explicit quote/trade price semantics."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.bars import BarSpec, Consolidator, qualified, quote_bars
from gym.domain.model import parse_ts
from tests.support import START, market_db, quote, quote_history


@pytest.mark.parametrize("value", ["20261029T090000Z", "2026-W44-4T09:00Z", "2026-1-2T09:00Z", "2026-10-29"])
def test_ambiguous_or_non_calendar_timestamp_is_rejected(value):
    with pytest.raises(ValueError):
        parse_ts(value)


def test_padded_timestamp_requires_a_zone():
    assert parse_ts("2026-10-29T12:30:00+03:30") == START
    with pytest.raises(ValueError, match="without zone"):
        parse_ts("2026-10-29T09:00:00")


@pytest.mark.parametrize(("price", "quantity"), [("NaN", "1"), ("Infinity", "1"), ("0", "1"), ("-1", "1"), ("1", "NaN"), ("1", "-1")])
def test_invalid_observation_leaves_the_forming_bar_unchanged(price, quantity):
    consolidator = Consolidator("BTCUSDT", BarSpec("1min"))
    consolidator.update(START, Decimal(100))
    before = consolidator.forming(START)
    with pytest.raises(ValueError, match="finite"):
        consolidator.update(START + timedelta(minutes=1), Decimal(price), Decimal(quantity))
    assert consolidator.forming(START) == before


@pytest.mark.parametrize(("bid", "ask"), [("NaN", "1"), ("1", "Infinity"), ("-1", "1"), ("2", "1"), ("1", "1")])
def test_invalid_quote_is_not_eligible_even_without_quality_flags(bid, ask):
    assert not qualified(quote(START, bid, ask))


@pytest.mark.parametrize("argument", ["--cash", "--fee"])
def test_invalid_cli_decimal_reports_an_error_instead_of_a_traceback(tmp_path, capsys, argument):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, quote_history(20)).c.close()
    assert main(["--data", str(tmp_path), "paper", "BTCUSDT", argument, "not-a-number"]) == 2
    assert capsys.readouterr().err.startswith("error:")

def test_quote_history_cannot_pretend_to_be_last_trade_bars():
    with pytest.raises(ValueError, match="trade prices"):
        quote_bars("BTCUSDT", BarSpec("1min", "LAST"), [quote(START, "100", "102")])
