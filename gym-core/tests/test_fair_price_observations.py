"""Non-executable public fair-price observations."""
from datetime import timedelta

import pytest

from gym.services.fair_price import FairPriceJournal, parse_fair_price
from tests.support import START


def payload(price="100.12345678"):
    """Documented public:all@fairPrice full snapshot with exact decimal strings."""
    return {"ts": START.isoformat(), "prices": {"BTCUSDT": price, "ETHUSDT": "20.1"}}


def test_public_fairprice_parser_is_bounded_and_non_executable():
    parsed = parse_fair_price(payload(), received_at=START + timedelta(seconds=1))
    assert parsed["schema"] == "public-fairprice-observation/1"
    assert parsed["channel"] == "public:all@fairPrice"
    assert parsed["prices"]["BTCUSDT"] == "100.12345678"
    assert parsed["funded_authority"] is False
    assert parsed["executable_quote"] is False
    assert parsed["source_authenticated"] is False


def test_fairprice_journal_honors_availability_and_staleness(tmp_path):
    with FairPriceJournal(tmp_path / "fair_price.sqlite3") as journal:
        record = journal.record(payload(), received_at=START + timedelta(seconds=10))
        assert record["observation_id"]
        assert journal.valuation("BTCUSDT", as_of=START + timedelta(seconds=9))["status"] == "UNAVAILABLE"
        quote = journal.valuation("BTCUSDT", as_of=START + timedelta(seconds=11))
        assert quote["status"] == "FRESH_NON_EXECUTABLE"
        assert quote["derived_rate"] == "100.12345678"
        assert quote["executable_quote"] is False
        assert journal.valuation("BTCUSDT", as_of=START + timedelta(minutes=5))["status"] == "STALE"
        assert journal.valuation("NOTHEREUSDT", as_of=START + timedelta(seconds=11))["status"] == "UNAVAILABLE"
        assert journal.record(payload(), received_at=START + timedelta(seconds=10))["observation_id"] == record["observation_id"]


@pytest.mark.parametrize("value", [
    {"ts": "invalid", "prices": {"BTCUSDT": "1"}},
    {"ts": START.isoformat(), "prices": {"BTCUSDT": "NaN"}},
    {"ts": START.isoformat(), "prices": {"BTCUSDT": 1.2}},
    {"ts": START.isoformat(), "prices": {"../../BAD": "1"}},
    {"ts": START.isoformat(), "prices": {}},
])
def test_fairprice_rejects_forged_or_invalid_quotes(value):
    with pytest.raises(ValueError):
        parse_fair_price(value, received_at=START + timedelta(seconds=1))
