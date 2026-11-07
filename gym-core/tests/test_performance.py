"""FIFO trade ledger, risk-adjusted returns and selection-aware Sharpe tests."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.domain.performance import (
    deflated_sharpe,
    expected_max_sharpe,
    performance,
    probabilistic_sharpe,
    selection_check,
    trade_ledger,
)
from gym.services.reports import economic_report
from tests.support import START


def fill(side, qty, price, fee, minutes, ref=None):
    return {"ref": ref or f"o{minutes}", "side": side, "status": "FILLED", "qty": qty, "price": price, "fee": fee,
            "fee_ccy": "BTC" if side == "BUY" else "USDT", "fill_time": iso(START + timedelta(minutes=minutes))}


def test_scaled_entries_and_partial_exits_match_first_in_first_out():
    orders = [fill("BUY", "1", "100", "0", 0), fill("BUY", "1", "200", "0", 10),
              {"status": "NONFILL", "side": "SELL"},
              fill("SELL", "1.5", "300", "0", 20), fill("SELL", "0.5", "50", "0", 30)]
    ledger = trade_ledger(orders, "BTC")
    first, second = ledger["trades"]
    # 1 @ 100 + 0.5 @ 200 cost 200, sold 1.5 @ 300 = 450
    assert Decimal(first["cost"]) == 200 and Decimal(first["proceeds"]) == 450 and Decimal(first["pnl"]) == 250
    assert first["holding_seconds"] == 20 * 60
    # remaining 0.5 @ 200 = 100 cost, sold for 25
    assert Decimal(second["pnl"]) == -75 and Decimal(second["return"]) == Decimal("-0.75")
    assert Decimal(ledger["open"]["quantity"]) == 0


def test_buy_fee_in_base_raises_unit_cost_and_sell_fee_reduces_proceeds():
    ledger = trade_ledger([fill("BUY", "1", "100", "0.01", 0), fill("SELL", "0.99", "100", "0.099", 5)], "BTC")
    trade = ledger["trades"][0]
    assert Decimal(trade["cost"]) == 100 and Decimal(trade["proceeds"]) == Decimal("98.901")


def test_selling_more_than_was_bought_is_an_error():
    with pytest.raises(ValueError, match="exceeds"):
        trade_ledger([fill("SELL", "1", "100", "0", 0)], "BTC")


def test_scaled_posting_roundoff_does_not_invent_an_oversell_at_full_liquidation():
    rows = [("BUY", "0.839540976052006407257524429", "0.000839540976052006407257524429"),
            ("BUY", "8.60431328796926498077033281E-7", "8.60431328796926498077033281E-10"),
            ("BUY", "3.8005100908132862462395117", "0.0038005100908132862462395117"),
            ("SELL", "1.715102393886650186720050949", "0"),
            ("SELL", "1.080514508148589617633632098", "0"),
            ("SELL", "1.839794973334085024619427625", "0")]
    orders = [fill(side, qty, "1", fee, i) for i, (side, qty, fee) in enumerate(rows)]
    assert Decimal(trade_ledger(orders, "BTC")["open"]["quantity"]) == 0
    orders[-1]["qty"] = "1.839794973334085024619427626"
    with pytest.raises(ValueError, match="exceeds"):
        trade_ledger(orders, "BTC")


def test_economic_report_counts_every_closed_trade_not_only_the_last_buy():
    out = {"run_id": "r", "outputs_digest": "d", "baselines": {}, "warnings": [],
           "inputs": {"from": iso(START), "to": iso(START + timedelta(hours=1)), "store": "live", "cost": {}},
           "result": {"quote": "USDT", "base": "BTC", "start_cash": "1000", "curve": [],
                      "orders": [fill("BUY", "1", "100", "0", 0), fill("BUY", "1", "200", "0", 10),
                                 fill("SELL", "2", "180", "0", 20)],
                      "end": {"mark_time": iso(START + timedelta(hours=1)), "equity": "1060"}}}
    report = economic_report(out)
    assert report["completed_round_trips"] == 1
    assert report["mean_return"] == pytest.approx(60 / 300)  # old code used only the last buy: -10%
    perf = report["performance"]
    assert perf["total_return_pct"] == "6.0000" and perf["trades"]["win_rate"] == 1.0
    assert perf["trades"]["exposure"] == pytest.approx(20 / 60)
    assert perf["trades"]["turnover"] == "0.6600"


def test_equity_path_statistics_and_annualization_guard():
    curve = [(iso(START + timedelta(hours=i)), str(1000 + (5 if i % 2 else -3) * i)) for i in range(1, 49)]
    out = {"inputs": {"from": iso(START), "to": iso(START + timedelta(hours=49))},
           "result": {"quote": "USDT", "base": "BTC", "start_cash": "1000", "curve": curve, "orders": [],
                      "end": {"mark_time": iso(START + timedelta(hours=49)), "equity": "1100"}}}
    perf = performance(out)
    assert perf["returns"]["periods"] == 49 and perf["returns"]["volatility"] > 0
    assert perf["annualized_return_pct"] is None  # a two-day window is never compounded to a year
    assert perf["returns"]["sharpe_annualized"] is None and perf["returns"]["sharpe_per_period"] is not None
    assert 0 <= perf["returns"]["probabilistic_sharpe"] <= 1


def test_luck_threshold_grows_with_trials_and_deflates_the_best_result():
    assert expected_max_sharpe(1, 0.01) == 0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0
    plain = probabilistic_sharpe(0.2, 250, 0.0, 3.0)
    deflated = deflated_sharpe(0.2, 250, 0.0, 3.0, trials=50, sharpe_variance=0.01)
    assert plain > 0.99 and deflated < plain


def test_selection_check_names_the_best_candidate():
    def block(sharpe):
        return {"returns": {"sharpe_per_period": sharpe, "periods": 100, "skew": 0.0, "kurtosis": 3.0}}
    check = selection_check({"A": block(0.05), "B": block(0.15), "C": block(-0.02)})
    assert check["best"] == "B" and check["trials"] == 3 and 0 <= check["deflated_sharpe"] <= 1
    assert selection_check({"A": block(0.1)}) is None


def test_selection_counts_earlier_trials_and_raises_the_luck_threshold():
    def block(sharpe):
        return {"returns": {"sharpe_per_period": sharpe, "periods": 100, "skew": 0.0, "kurtosis": 3.0}}
    candidates = {"A": block(0.05), "B": block(0.15)}
    alone, searched = selection_check(candidates), selection_check(candidates, trials=40)
    assert alone["trials"] == 2 and searched["trials"] == 40 and searched["compared"] == 2
    assert searched["luck_threshold_per_period"] > alone["luck_threshold_per_period"]
    assert searched["deflated_sharpe"] < alone["deflated_sharpe"]


def test_earlier_configurations_are_counted_per_market_and_decision_close(tmp_path):
    from gym.adapters.run_store import save_run
    from gym.services.research import tried_before
    for i, (symbol, resolution, config) in enumerate([("BTCTMN", "15min", "a"), ("BTCTMN", "15min", "a"),
                                                       ("BTCTMN", "15min", "b"), ("BTCTMN", "1h", "c"), ("ETHTMN", "15min", "d")]):
        save_run({"run_id": f"{i:016x}", "inputs": {"symbol": symbol, "resolution": resolution, "config_hash": config},
                  "result": {"end": None}}, tmp_path)
    assert tried_before(tmp_path, "BTCTMN", "15min") == {"a", "b"}


def test_average_cost_view_differs_per_trade_but_matches_fifo_when_flat():
    orders = [fill("BUY", "1", "100", "0", 0), fill("BUY", "1", "200", "0", 10),
              fill("SELL", "1.5", "300", "0", 20), fill("SELL", "0.5", "50", "0", 30)]
    first, second = trade_ledger(orders, "BTC")["trades"]
    assert Decimal(first["average_cost_pnl"]) == 225 and Decimal(second["average_cost_pnl"]) == -50
    assert Decimal(first["pnl"]) + Decimal(second["pnl"]) == 175 == Decimal(first["average_cost_pnl"]) + Decimal(second["average_cost_pnl"])


def test_bootstrap_range_and_benchmark_against_holding_the_base():
    marks = [START + timedelta(hours=i) for i in range(1, 41)]
    prices = [100 + (3 if i % 3 else -2) * (i % 7) for i in range(40)]
    # Fully invested in the base: equity moves with the bid, so beta is one and alpha is zero.
    curve = [(iso(t), str(p * 10)) for t, p in zip(marks, prices)]
    decisions = [{"t": iso(t), "bid": str(p)} for t, p in zip(marks, prices)]
    out = {"inputs": {"from": iso(START), "to": iso(START + timedelta(hours=41))},
           "result": {"quote": "USDT", "base": "BTC", "start_cash": "1000", "curve": curve, "decisions": decisions, "orders": [],
                      "end": {"mark_time": iso(marks[-1]), "equity": curve[-1][1]}}}
    perf = performance(out)
    low, high = perf["returns"]["bootstrap_90"]["sharpe_per_period"]
    assert low <= high and perf["returns"]["bootstrap_90"] == performance(out)["returns"]["bootstrap_90"]
    bench = perf["benchmark"]
    assert bench["name"] == "hold BTC" and bench["beta"] == pytest.approx(1) and bench["alpha_per_period"] == pytest.approx(0, abs=1e-12)
    assert bench["correlation"] == pytest.approx(1)
