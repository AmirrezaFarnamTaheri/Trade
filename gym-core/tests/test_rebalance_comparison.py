"""Same-data evidence for a cost-aware paper rebalance band."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from gym.domain.sim import CostModel
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def test_cost_aware_band_lowers_executed_turnover_and_fees_on_identical_quotes(tmp_path):
    """Compare two paper policies on the exact same history and fee assumptions."""
    btc = quote_history(n=480)
    eth = [replace(top, bid=Decimal(70000) + Decimal(i) / 4,
                   ask=Decimal(70010) + Decimal(i) / 4)
           for i, top in enumerate(quote_history(n=480, sym="ETHUSDT"))]
    db = market_db(tmp_path, btc + eth)
    try:
        policy = {"rebalance": True, "rebalance_seconds": 60,
                  "rebalance_threshold": "0"}
        common = {"resolution": "1min", "params": {"fast": 2, "slow": 3},
                  "cost": CostModel(fee_rate=Decimal("0.015"))}
        fixed = portfolio(db, ["BTCUSDT", "ETHUSDT"], START,
                          START + timedelta(minutes=35), policy=policy, **common)
        adaptive = portfolio(db, ["BTCUSDT", "ETHUSDT"], START,
                             START + timedelta(minutes=35),
                             policy={**policy, "cost_aware_rebalance": True}, **common)

        def filled(out):
            return [o for market in out["result"]["markets"].values()
                    for o in market["orders"] if o["status"] == "FILLED"]

        def turnover(orders):
            return sum((Decimal(o["qty"]) * Decimal(o["price"]) for o in orders),
                       Decimal(0))

        def fees(orders):
            return sum((Decimal(o["fee"]) *
                        (Decimal(o["price"]) if o["fee_ccy"] != "USDT" else Decimal(1))
                        for o in orders), Decimal(0))

        normal, bounded = filled(fixed), filled(adaptive)
        assert normal and bounded
        assert turnover(normal) > turnover(bounded)
        assert fees(normal) > fees(bounded)
        evidence = [e for e in adaptive["result"]["policy_events"]
                    if e["kind"] == "REBALANCE_BAND" and e["status"] == "READY"]
        assert evidence
        assert all(Decimal(e["tracking_error_fraction"]) >= 0
                   and Decimal(e["estimated_roundtrip_cost_quote"]) >= 0 for e in evidence)
        assert all(e["source_quote_time"] <= e["at"] for e in evidence)
    finally:
        db.c.close()
