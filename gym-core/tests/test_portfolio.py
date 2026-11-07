"""Shared-cash portfolio replay over several markets."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def test_markets_share_one_cash_balance_and_equal_target_weights(tmp_path):
    db = market_db(tmp_path, quote_history(n=500) + quote_history(n=500, sym="ETHUSDT"))
    out = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), resolution="1min", cash=Decimal(1000),
                    params={"fast": 2, "slow": 3})
    result = out["result"]
    assert set(result["markets"]) == {"BTCUSDT", "ETHUSDT"} and out["mode"] == "PORTFOLIO"
    first_buys = [next(o for o in result["markets"][s]["orders"] if o["side"] == "BUY" and o["status"] == "FILLED")
                  for s in ("BTCUSDT", "ETHUSDT")]
    # Each entry targets half of portfolio equity, so neither market can take the whole balance.
    for buy in first_buys:
        assert Decimal(buy["qty"]) * Decimal(buy["price"]) <= Decimal(501)
    assert Decimal(result["balances"]["USDT"]) >= 0 and result["curve"]
    assert out["performance"]["status"] == "AVAILABLE"
    assert out["run_id"] == portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(hours=1), resolution="1min",
                                      cash=Decimal(1000), params={"fast": 2, "slow": 3})["run_id"]


def test_portfolio_rejects_mixed_quote_currencies_and_single_markets(tmp_path):
    db = market_db(tmp_path, quote_history(n=20) + quote_history(n=20, sym="BTCTMN"))
    with pytest.raises(ValueError, match="quote currency"):
        portfolio(db, ["BTCUSDT", "BTCTMN"], START, START + timedelta(hours=1))
    with pytest.raises(ValueError, match="2..8"):
        portfolio(db, ["BTCUSDT"], START, START + timedelta(hours=1))
