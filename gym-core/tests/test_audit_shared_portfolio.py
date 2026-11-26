"""Reconcile shared-account attribution from independently specified postings."""

from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB
from gym.domain.model import iso
from gym.domain.sim import CostModel
from gym.services.data_portal import DataPortal
from gym.services.research_actions import research_action
from scripts.audit_shared_portfolio import _spot_exit, audit
from tests.support import START, market_db, quote
from tests.test_portfolio_margin import setup as setup_margin
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
        conversion = report["strategy_fx_basis_by_component"]["conversion_net"]
        assert {asset: Decimal(amount) for asset, amount in conversion["booked_currencies"].items()} == {"USDT": 4, "TMN": -50}
        assert Decimal(conversion["opening_fx_usdt"]) == Decimal("3.5")
        assert Decimal(conversion["translation_to_terminal_fx_usdt"]) == 0
        run["result"]["postings"][0]["ref"] = "unknown-transfer"
        with pytest.raises(ValueError, match="unrecognized cash posting"):
            audit(run, portal)
    finally:
        db.c.close()


def test_terminal_exit_estimate_applies_displayed_limit_and_rejects_bad_latest_receipt(tmp_path):
    cutoff = START + timedelta(minutes=1)
    prior = quote(cutoff - timedelta(seconds=1), "99", "101")
    db = market_db(tmp_path, [prior, quote(cutoff, "199", "201")])
    cost = CostModel(latency=timedelta(0), max_wait=timedelta(0), max_participation=Decimal("0.25"))
    try:
        portal = DataPortal(db)
        row = _spot_exit(portal, [], cost, "BTCUSDT", Decimal(1), START, cutoff)
        assert row["status"] == "PARTIAL"
        assert row["receipt"] == iso(prior.ts_avail)
        assert Decimal(row["net_proceeds"]) == Decimal("24.72525")
        assert Decimal(row["residual_units"]) == Decimal("0.75")
        db.add_book_top(quote(prior.ts_avail, "101", "99"), None)
        row = _spot_exit(portal, [], cost, "BTCUSDT", Decimal(1), START, cutoff)
        assert row["status"] == "UNQUALIFIED_RECEIPT"
        assert Decimal(row["residual_units"]) == 1
    finally:
        db.c.close()


@pytest.mark.parametrize("side,price,expected_state", [("long", "110", "CLOSED"), ("short", "300", "CLOSED_WITH_DEBT")])
def test_audit_reconciles_margin_collateral_release_and_retained_debt(tmp_path, side, price, expected_state):
    db, value = setup_margin(tmp_path, side=side, price=price)
    try:
        reply = research_action(tmp_path, "portfolio-replay", value)
        run = research_action(tmp_path, "portfolio-read", {"run_id": reply["run_id"]})
        report = audit(run, DataPortal(db))
        row, = report["margin_positions"]
        assert row["state"] == expected_state and Decimal(row["collateral"]) == 100
        assert Decimal(row["retained_equity"]) == -Decimal(row["retained_quote_debt"])
        if expected_state == "CLOSED_WITH_DEBT":
            assert Decimal(report["components"]["margin_net"]) == -(100 + Decimal(row["retained_quote_debt"]))
        else:
            assert Decimal(row["retained_quote_debt"]) == 0 and Decimal(row["released_cash"]) > 100
        assert abs(Decimal(report["raw_reconciliation_residual_usdt"])) < Decimal("1e-18")
        release = next(p for p in run["result"]["postings"] if p["kind"] == "margin_release")
        release["amount"] = str(Decimal(release["amount"]) + 1)
        with pytest.raises(ValueError, match="margin collateral or release posting mismatch"):
            audit(run, DataPortal(db))
    finally:
        db.c.close()


def test_audit_reconciles_remaining_route_units_without_crediting_a_mark(tmp_path):
    value = setup(tmp_path, "OTC", "partial")
    value["to"] = iso(START + timedelta(minutes=2))
    reply = research_action(tmp_path, "portfolio-replay", value)
    run = research_action(tmp_path, "portfolio-read", {"run_id": reply["run_id"]})
    db = MarketDB(tmp_path / "market.db", readonly=True)
    try:
        report = audit(run, DataPortal(db))
        assert report["unvalued_route_residual_units"] == {"ADA": "0.5"}
        assert Decimal(report["components"]["conversion_net"]) == Decimal("2.0")
        run["result"]["mixed_route_residuals"]["ADA"] = "0.6"
        with pytest.raises(ValueError, match="inventory=.*ADA"):
            audit(run, DataPortal(db))
    finally:
        db.c.close()


@pytest.mark.parametrize("seconds_after_last_quote", [5, 45])
def test_audit_requires_a_reported_mark_for_open_margin(tmp_path, seconds_after_last_quote):
    db, value = setup_margin(tmp_path, price="110")
    value["margin_positions"][0]["holding_seconds"] = None
    value["to"] = iso(START + timedelta(minutes=8, seconds=seconds_after_last_quote))
    try:
        reply = research_action(tmp_path, "portfolio-replay", value)
        run = research_action(tmp_path, "portfolio-read", {"run_id": reply["run_id"]})
        position, = run["result"]["margin_positions"]
        assert position["outcome"]["state"] == "OPEN" and position["release_at"] is None
        if seconds_after_last_quote > 30:
            with pytest.raises(ValueError, match="lacks a reported closing mark"):
                audit(run, DataPortal(db))
        else:
            row, = audit(run, DataPortal(db))["margin_positions"]
            assert row["retained_equity"] == position["outcome"]["equity_quote"]
            assert row["retained_quote_debt"] == position["outcome"]["debt_quote"]
    finally:
        db.c.close()
