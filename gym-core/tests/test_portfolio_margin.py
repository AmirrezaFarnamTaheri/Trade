"""Public-preview paper margin positions share one collateral budget with spot."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from gym.domain.model import iso
from gym.services import margin, research_ledger
from gym.services.research_actions import research_action
from gym.services.research_process import calculate
from tests.support import START, market_db, quote_history
from tests.test_margin import path, preview, rule
from tests.test_portfolio_workflow import request
from tests.test_research_ledger import schedule


def setup(root, *, side="long", price="110", opening="102"):
    terms = {**preview(side), **({"stop_loss": "95"} if side == "long" else {})}
    receipt = margin._save(root, {"kind": "PREVIEW", "received_at": iso(START), "rule": rule(), "terms": terms})
    points = path(side, end_price=price)
    # Retain opening quotes for the spot sessions and an earlier valuation mark.
    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=7), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=361, sym="USDTTMN")]
    db = market_db(root, [points[0][0], replace(points[1][0], ts_avail=START + timedelta(minutes=8))]
                   + quote_history(n=360, sym="ETHUSDT") + quote_history(n=360, sym="SOLTMN") + fx)
    value = {**request(), "symbols": ["BTCUSDT", "ETHUSDT", "SOLTMN"],
             "cash_by_currency": {"USDT": opening, "TMN": "100000"},
             "margin_positions": [{"preview_id": receipt["run_id"], "exit_fee_rate": "0.001",
                                   "holding_seconds": 480}]}
    return db, value


@pytest.mark.parametrize("side,price,outcome,action", [
    ("long", "110", "CLOSED", "PAPER_TIME_EXIT"),
    ("long", "90", "CLOSED", "PAPER_STOP"),
    ("short", "300", "CLOSED_WITH_DEBT", "PAPER_LIQUIDATION"),
])
def test_shared_margin_collateral_releases_or_carries_deficit(tmp_path, side, price, outcome, action):
    db, value = setup(tmp_path, side=side, price=price)
    db.c.close()
    run = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": run["run_id"]})
    assert saved["inputs"]["portfolio_version"] == 21
    result = saved["result"]
    position, = result["margin_positions"]
    assert position["outcome"]["state"] == outcome
    assert position["outcome"]["events"][-1]["action"] == action
    assert position["release_at"] > iso(START + timedelta(minutes=8))
    assert result["markets"]["BTCUSDT"]["reason"] == "MARGIN_POSITION"
    assert result["markets"]["BTCUSDT"]["fills"] == 0
    collateral, release = [row for row in result["postings"] if row["ref"] == position["id"]]
    assert (collateral["kind"], Decimal(collateral["amount"])) == ("margin_collateral", Decimal(-100))
    assert release["kind"] == "margin_release"
    assert Decimal(release["amount"]) == Decimal(position["outcome"]["cash_quote"])
    debt = Decimal(position["outcome"]["debt_quote"])
    if outcome == "CLOSED_WITH_DEBT":
        assert debt > 0 and Decimal(release["amount"]) == 0
        assert result["markets"]["ETHUSDT"]["fills"] == 0
        assert result["margin_risk_state"] == "MARGIN_DEFICIT"
    with localcontext() as ctx:
        ctx.prec = 400
        cash = {asset: Decimal(amount) for asset, amount in value["cash_by_currency"].items()}
        for entry in result["postings"]:
            asset = entry["ccy"]
            cash[asset] = cash.get(asset, Decimal(0)) + Decimal(entry["amount"])
        assert cash == {asset: Decimal(amount) for asset, amount in result["balances"].items()}
    for count in (20, 150):
        checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": run["run_id"], "quote_count": count})
        recovered = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["record"]["id"]})
        assert recovered["status"] == "EXACT_MATCH"


def test_margin_rejects_collateral_overcommit(tmp_path):
    db, value = setup(tmp_path, opening="99")
    db.c.close()
    with pytest.raises(ValueError, match="insufficient USDT cash"):
        research_action(tmp_path, "portfolio-replay", value)


@pytest.mark.parametrize("side,levels", [("long", [96, 98, 99]), ("short", [104, 102, 101])])
def test_signal_submits_preview_backed_order_after_latency(tmp_path, side, levels):
    db, value = setup(tmp_path, side=side)
    top = path(side)[0][0]
    for second, bid in zip((2, 4, 6, 8), [levels[0], levels[0], levels[1], levels[2]]):
        db.add_book_top(replace(top, ts_avail=START + timedelta(seconds=second),
                                bid=Decimal(bid), ask=Decimal(bid+1)), None)
    db.c.close()
    value["margin_positions"][0]["entry_breakout_ticks"] = 2
    run = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": run["run_id"]})
    assert saved["inputs"]["portfolio_version"] == 24
    outcome = saved["result"]["margin_positions"][0]["outcome"]
    assert outcome["entry_signal"]["at"] == iso(START + timedelta(seconds=6))
    assert outcome["entry"]["at"] == iso(START + timedelta(seconds=8))
    assert outcome["events"][0]["action"] == "PAPER_OPEN"


def test_absent_margin_signal_returns_unspent_collateral(tmp_path):
    db, value = setup(tmp_path)
    db.c.close()
    value["margin_positions"][0]["entry_breakout_ticks"] = 3
    run = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": run["run_id"]})
    position, = saved["result"]["margin_positions"]
    assert position["outcome"]["entry_signal"]["at"] is None
    assert position["outcome"]["entry"] is None
    assert position["release_at"] == value["to"]


def test_margin_order_cannot_trade_outside_curated_universe(tmp_path):
    db, value = setup(tmp_path)
    db.c.close()
    value["symbols"].remove("BTCUSDT")
    with pytest.raises(ValueError, match="selected portfolio symbol"):
        research_action(tmp_path, "portfolio-replay", value)


def test_expired_margin_signal_cannot_open_on_a_late_limit_touch(tmp_path):
    db, value = setup(tmp_path)
    top = path("long")[0][0]
    for sec, bid in ((2, 96), (4, 96), (6, 101), (70, 99)):
        db.add_book_top(replace(top, ts_avail=START + timedelta(seconds=sec),
                                bid=Decimal(bid), ask=Decimal(bid+1)), None)
    db.c.close()
    value["margin_positions"][0]["entry_breakout_ticks"] = 2
    run = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": run["run_id"]})
    outcome = saved["result"]["margin_positions"][0]["outcome"]
    assert outcome["entry_signal"]["at"] == iso(START + timedelta(seconds=6))
    assert outcome["entry"] is None
    assert outcome["nonfills"]["SIGNAL_ORDER_EXPIRED"] == 1


@pytest.mark.parametrize("side,levels,edit,action", [
    ("long", [110, 103], {"stop_loss": "105"}, "PAPER_STOP"),
    ("short", [89, 96], {"stop_loss": "95"}, "PAPER_STOP"),
    ("long", [105, 112], {"take_profit": "110"}, "PAPER_TARGET"),
    ("short", [97, 89], {"take_profit": "92"}, "PAPER_TARGET"),
])
def test_scheduler_applies_margin_protection_edit_after_open(tmp_path, side, levels, edit, action):
    db, value = setup(tmp_path, side=side)
    top = path(side)[0][0]
    for sec, bid in zip((12, 15), levels):
        db.add_book_top(replace(top, ts_avail=START + timedelta(seconds=sec),
                                bid=Decimal(bid), ask=Decimal(bid+1)), None)
    db.c.close()
    plan, = value["margin_positions"]
    plan["protection_edits"] = [{"after_open_seconds": 10, **edit}]
    due = iso(START + timedelta(hours=1))
    with research_ledger.ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        schedule(ledger, cash_by_currency=value["cash_by_currency"], portfolio_symbols=value["symbols"],
                 margin_positions=[plan])
    tick = asyncio.run(calculate(tmp_path, "tick", at=due))
    item, = tick["completed"]
    record = research_action(tmp_path, "portfolio-read", {"run_id": item["run_id"]})
    assert record["inputs"]["portfolio_version"] == 25
    events = record["result"]["margin_positions"][0]["outcome"]["events"]
    assert [e["action"] for e in events] == ["PAPER_OPEN", "PAPER_EDIT", action]
    assert events[1]["at"] == iso(START + timedelta(seconds=12))
    assert events[-1]["at"] == iso(START + timedelta(seconds=15))
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": item["run_id"], "quote_count": 9})
    resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["record"]["id"]})
    assert resumed["status"] == "EXACT_MATCH"


def test_unsettled_margin_keeps_collateral_and_marks_portfolio_stale(tmp_path):
    db, value = setup(tmp_path)
    db.c.close()
    value["to"] = iso(START + timedelta(minutes=5))
    run = research_action(tmp_path, "portfolio-replay", value)
    result = research_action(tmp_path, "portfolio-read", {"run_id": run["run_id"]})["result"]
    position, = result["margin_positions"]
    assert position["release_at"] is None
    assert Decimal(position["outcome"]["debt_quote"]) == 200
    assert result["end"]["valuation_status"] == "STALE_VALUATION"
    assert Decimal(result["balances"]["USDT"]) == 2


def test_margin_worker_publishes_saved_preview_backed_portfolio(tmp_path):
    db, value = setup(tmp_path)
    db.c.close()
    due = iso(START + timedelta(hours=1))
    with research_ledger.ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        schedule(ledger, cash_by_currency=value["cash_by_currency"], portfolio_symbols=value["symbols"],
                 margin_positions=value["margin_positions"])
    response = asyncio.run(calculate(tmp_path, "tick", at=due))
    completed, = response["completed"]
    artifact = research_action(tmp_path, "portfolio-read", {"run_id": completed["run_id"]})
    assert artifact["result"]["margin_positions"][0]["outcome"]["state"] == "CLOSED"
    assert not asyncio.run(calculate(tmp_path, "tick", at=due))["completed"]


def test_margin_scheduler_recovers_one_published_artifact(tmp_path, monkeypatch):
    db, value = setup(tmp_path)
    due = START + timedelta(hours=1)
    file = tmp_path / "research.sqlite3"
    save = research_ledger.save_run

    def fail_after_save(result, root):
        save(result, root)
        raise OSError("injected interruption")

    try:
        with research_ledger.ResearchLedger(file) as ledger:
            schedule(ledger, cash_by_currency=value["cash_by_currency"], portfolio_symbols=value["symbols"],
                     margin_positions=value["margin_positions"])
        with monkeypatch.context() as fault, research_ledger.ResearchLedger(file) as ledger:
            fault.setattr(research_ledger, "save_run", fail_after_save)
            with pytest.raises(OSError, match="injected"):
                ledger.run_due(db, iso(due))
        with research_ledger.ResearchLedger(file) as ledger:
            assert not ledger.run_due(db, iso(due))["completed"]
            resumed = ledger.run_due(db, iso(due + research_ledger.MULTICURRENCY_ABANDONED_AFTER))
            completed, = resumed["completed"]
            assert not ledger.run_due(db, iso(due))["completed"]
        artifact = research_action(tmp_path, "portfolio-read", {"run_id": completed["run_id"]})
        assert artifact["result"]["margin_positions"][0]["outcome"]["state"] == "CLOSED"
        assert len(list((tmp_path / "runs" / "portfolios").glob("*.json"))) == 1
    finally:
        db.c.close()
