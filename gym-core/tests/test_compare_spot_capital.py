from datetime import timedelta
from decimal import Decimal

from gym.domain.model import iso
from gym.domain.sim import CostModel
from gym.services.data_portal import DataPortal
from scripts.compare_spot_capital import liquidation_window
from tests.support import START, market_db, quote


def test_exit_window_consumes_each_receipt_once_and_reports_time_to_flat(tmp_path):
    def at(seconds):
        return START + timedelta(seconds=seconds)

    receipts = [quote(at(seconds), "100", "101") for seconds in (0, 2, 2, 3, 4)]
    db = market_db(tmp_path, receipts)
    cost = CostModel(latency=timedelta(seconds=1), max_participation=Decimal("0.5"), fee_rate=Decimal(0))
    run = {"inputs": {"from": iso(at(-60)), "to": iso(START), "rules_mode": "point-in-time", "cost": cost.describe()},
           "result": {"markets": {"BTCUSDT": {"holding": "1.5"}}}}
    try:
        partial, = liquidation_window(run, DataPortal(db), at(4))["positions"]
        assert partial["residual_units"] == Decimal("0.5")
        assert partial["seconds_to_first_fill"] == 2
        assert partial["seconds_to_flat"] is None
        flat, = liquidation_window(run, DataPortal(db), at(5))["positions"]
        assert flat["residual_units"] == 0
        assert flat["seconds_to_flat"] == 4
        assert flat["net_proceeds"] == 150
    finally:
        db.c.close()
