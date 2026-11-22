"""Reconcile shared-account attribution from independently specified postings."""

from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB
from gym.domain.model import iso
from gym.services.data_portal import DataPortal
from gym.services.research_actions import research_action
from scripts.audit_shared_portfolio import audit
from tests.support import START
from tests.test_portfolio_mixed_route import setup


def test_archived_audit_reconciles_converted_cash_and_spot_holdings(tmp_path):
    value = setup(tmp_path, "OTC", "complete")
    value["to"] = iso(START + timedelta(minutes=2))
    reply = research_action(tmp_path, "portfolio-replay", value)
    run = research_action(tmp_path, "portfolio-read", {"run_id": reply["run_id"]})
    db = MarketDB(tmp_path / "market.db", readonly=True)
    try:
        portal = DataPortal(db)
        report = audit(run, portal)
        components = {key: Decimal(amount) for key, amount in report["components"].items()}
        assert components["conversion_net"] == Decimal("3.5")  # 4 USDT minus 50 TMN at 100 TMN per USDT
        assert components["passive_cash_fx"] == 0
        assert sum(components.values()) + Decimal(report["residual_at_display_precision"]) == Decimal(report["net"])
        run["result"]["postings"][0]["ref"] = "unknown-transfer"
        with pytest.raises(ValueError, match="unrecognized cash posting"):
            audit(run, portal)
    finally:
        db.c.close()
