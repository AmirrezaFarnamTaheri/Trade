"""Phase D item 32: TMN assets must account for the causal USDT/TMN risk factor."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote, quote_history


def fx_top(seconds, price):
    """Known USDT/TMN bid and ask at a specific availability timestamp."""
    return replace(quote(START + timedelta(seconds=seconds), str(price - 1),
                         str(price + 1)), symbol="USDTTMN")


def test_opt_in_tmn_fx_risk_uses_usdt_returns_and_records_factor(tmp_path):
    """No future FX value can influence an earlier paper target calculation."""
    fx = [fx_top(i * 60, 100 + i * 2) for i in range(30)]
    rows = (quote_history(n=180, sym="BTCTMN") +
            quote_history(n=180, sym="ETHTMN") + fx)
    db = market_db(tmp_path, rows)
    try:
        kwargs = dict(resolution="1min", cash=Decimal(1000),
                      policy={"method": "inverse-volatility", "lookback": 3,
                              "usdt_fx_risk": True})
        before = portfolio(db, ["BTCTMN", "ETHTMN"],
                           START, START + timedelta(minutes=20), **kwargs)
        assert before["inputs"]["portfolio_version"] >= 8
        assert any(event.get("risk_currency") == "USDT"
                   for event in before["result"]["policy_events"]
                   if event["kind"] == "TARGETS")
        assert any(event.get("status") == "READY"
                   for event in before["result"]["policy_events"]
                   if event["kind"] == "TARGETS")
        cutoff = iso(START + timedelta(minutes=12))
        db.c.execute("UPDATE book_top SET bid='90000', ask='90001' "
                     "WHERE instrument_id='wallex:USDTTMN' AND ts_avail>=?",
                     (cutoff,))
        after = portfolio(db, ["BTCTMN", "ETHTMN"],
                          START, START + timedelta(minutes=20), **kwargs)
        earlier = lambda result: [event for event in result["result"]["policy_events"]
                                  if event["kind"] == "TARGETS" and event["at"] < cutoff]
        assert earlier(before) == earlier(after)
    finally:
        db.c.close()


def test_tmn_fx_risk_fails_closed_on_missing_or_stale_rate(tmp_path):
    """Do not quietly model TMN-only variance as USDT variance."""
    db = market_db(tmp_path, quote_history(n=180, sym="BTCTMN") +
                   quote_history(n=180, sym="ETHTMN") + [fx_top(0, 100)])
    try:
        out = portfolio(db, ["BTCTMN", "ETHTMN"],
                        START, START + timedelta(minutes=20), resolution="1min",
                        policy={"method": "equal", "lookback": 3, "usdt_fx_risk": True})
        targets = [row for row in out["result"]["policy_events"] if row["kind"] == "TARGETS"]
        assert targets
        assert all(row["status"] != "READY" for row in targets[3:])
        assert all(sum(map(Decimal, row["weights"].values())) == 0
                   for row in targets[3:])
    finally:
        db.c.close()


@pytest.mark.parametrize("value", [0, "true", None, "yes"])
def test_fx_risk_flag_requires_boolean(value):
    """Reject ambiguous risk-factor policy configuration."""
    from gym.domain.portfolio_policy import PortfolioPolicy

    with pytest.raises(ValueError):
        PortfolioPolicy({"usdt_fx_risk": value}, ["BTCTMN", "ETHTMN"])
