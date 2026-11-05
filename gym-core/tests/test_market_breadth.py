from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from tests.support import START, market_db, quote_history


def test_group_denominators_preserve_missing_markets_and_do_not_double_count(tmp_path):
    tops = quote_history(n=180)
    db = market_db(tmp_path, tops + [replace(t, symbol="ETHUSDT", bid=Decimal(100), ask=Decimal(101)) for t in tops])
    try:
        request = {"groups": [{"name": "supplied-group", "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}],
                   "quote_currency": "USDT", "from": iso(START), "to": iso(START + timedelta(minutes=30)), "resolution": "1min"}
        result = research_action(tmp_path, "market-breadth", request)
        group = result["groups"][0]
        assert group["declared_members"] == 3 and group["eligible_members"] == 2
        assert group["advances"] + group["declines"] + group["unchanged"] == 2
        assert len([m for m in group["members"] if m["excluded_reason"]]) == 1
        with pytest.raises(ValueError, match="overlap"):
            research_action(tmp_path, "market-breadth", {**request, "groups": request["groups"] + [{"name": "another-group", "symbols": ["BTCUSDT"]}]})
    finally:
        db.c.close()
