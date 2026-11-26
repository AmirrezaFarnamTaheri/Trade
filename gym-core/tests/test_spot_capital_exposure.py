import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from scripts.match_spot_exposure import compare
from scripts.spot_capital_exposure import spot_capital_exposure
from tests.support import START, market_db, quote_history
from tests.test_portfolio_workflow import request


def _run():
    def fill(symbol, index, side, seconds, base, quote, quantity, cash):
        ref, at = f"{symbol}#{index}", iso(START + timedelta(seconds=seconds))
        order = {"ref": ref, "fill_time": at, "side": side, "status": "FILLED"}
        posts = [{"ref": ref, "t": at, "ccy": asset, "amount": amount}
                 for asset, amount in ((base, quantity), (quote, cash))]
        return order, posts

    buy, first = fill("ETHUSDT", 1, "BUY", 1, "ETH", "USDT", "9.9", "-100")
    sell, second = fill("ETHUSDT", 2, "SELL", 4, "ETH", "USDT", "-4.95", "70")
    other, third = fill("BTCTMN", 1, "BUY", 2, "BTC", "TMN", "1", "-6000")
    return {"inputs": {"from": iso(START), "to": iso(START + timedelta(seconds=7)),
                       "trade_accounting": "booked-notional/1", "cash_by_currency": {"USDT": "900", "TMN": "10000"},
                       "instruments": {"ETHUSDT": {"base": "ETH", "quote": "USDT"},
                                       "BTCTMN": {"base": "BTC", "quote": "TMN"}}},
            "result": {"start_cash": "1000", "quote": "USDT",
                       "markets": {"ETHUSDT": {"orders": [buy, sell], "holding": "4.95"},
                                   "BTCTMN": {"orders": [other], "holding": "1"}},
                       "postings": first + third + second}}


def test_exposure_integrates_carry_in_fees_partial_sales_and_both_book_currencies():
    exposure = spot_capital_exposure(_run(), Decimal(100), start=START + timedelta(seconds=2),
                                     end=START + timedelta(seconds=6))
    assert {asset: Decimal(amount) for asset, amount in exposure["quote_seconds"].items()} == {
        "USDT": Decimal(300), "TMN": Decimal(24000),
    }
    assert Decimal(exposure["mean_deployed_capital"]) == Decimal(135)
    assert Decimal(exposure["mean_deployed_share_of_opening_equity"]) == Decimal("0.135")


def test_exposure_refuses_unlinked_or_unreconciled_postings():
    run = _run()
    run["result"]["postings"].pop()
    with pytest.raises(ValueError, match="missing booked spot fill legs"):
        spot_capital_exposure(run, Decimal(100))
    run = _run()
    run["result"]["markets"]["ETHUSDT"]["holding"] = "5"
    with pytest.raises(ValueError, match="quantities do not reconcile"):
        spot_capital_exposure(run, Decimal(100))


def test_capped_comparison_freezes_training_selection_and_preserves_runs(tmp_path):
    tops = quote_history(n=60, turn=1) + quote_history(n=60, sym="ETHTMN", turn=1)
    tops += [replace(top, ts_avail=top.ts_avail - timedelta(seconds=1), bid=Decimal(99), ask=Decimal(101))
             for top in quote_history(n=61, sym="USDTTMN")]
    db = market_db(tmp_path, tops)
    db.c.close()
    value = {**request(), "symbols": ["BTCUSDT", "ETHTMN"], "to": iso(START + timedelta(minutes=10)),
             "cash_by_currency": {"TMN": "100000", "USDT": "1000"},
             "rank_gate": {"method": "momentum", "top_n_per_quote": 1, "min_breadth": "0", "seed": 1}}
    received = research_action(tmp_path, "portfolio-replay", value)
    target = research_action(tmp_path, "portfolio-read", {"run_id": received["run_id"]})
    output = tmp_path / "study"
    split = START + timedelta(minutes=6)
    result = asyncio.run(compare(tmp_path / "market.db", output, target, split,
                                 [Decimal("0.25"), Decimal("0.5")], Decimal("0.005"), store="live"))
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["train_to"] == iso(split)
    assert Decimal(manifest["target_training_share"]) > 0
    assert result["selected_cap"] == min(result["training"], key=lambda row: (Decimal(row["gap"]), Decimal(row["cap"])))["cap"]
    assert result["later"]["target"]["marked_return_bps"] is not None
    assert len(list((output / "runs").glob("*.json"))) == 3
    attempts = [json.loads(line) for line in (output / "training.jsonl").read_text().splitlines()]
    assert [row["status"] for row in attempts] == ["COMPLETED", "COMPLETED"]
