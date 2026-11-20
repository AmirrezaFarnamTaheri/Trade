from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from gym.adapters.run_store import save_run
from gym.domain.model import InstrumentId
from gym.domain.registry import create_strategy
from gym.domain.sim import CostModel
from gym.services.data_portal import DataPortal
from gym.services.paper import paper
from gym.services.portfolio import portfolio
from gym.services.replay_debugger import replay_decisions
from gym.services.session import PaperSession
from tests.support import START, market_db, quote_history


def test_exit_checks_are_separate_from_holding_and_lot_qualification(tmp_path):
    symbol = "BTCUSDT"
    db = market_db(tmp_path, [])
    inst = InstrumentId.wallex(symbol)
    rules = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1", "isMarketTypeEnable": True}
    db.upsert_instrument(inst, {}, rules, "test", START)
    stop = START + timedelta(minutes=1)
    db.upsert_instrument(inst, {}, {**rules, "isMarketTypeEnable": False}, "test", stop)
    db.upsert_instrument(inst, {}, {"isMarketTypeEnable": True}, "test", stop + timedelta(seconds=30))
    strategy = create_strategy("ema-trend", {"position_model": "inventory/2"})
    session = PaperSession(DataPortal(db), lambda _: (), strategy, symbol, START, "1min", Decimal(1000), CostModel())
    quote = quote_history(n=1)[0]
    quantity = Decimal("0.00007")
    try:
        for at, expected in [(START, "PAPER_CHECKS_PASS"), (stop, "BLOCKED_BY_MARKET_STATUS"),
                             (stop + timedelta(seconds=30), "UNKNOWN"), (stop + timedelta(minutes=2), "UNKNOWN")]:
            position = session.inventory_at(quantity, quote, at)["position_known"]
            assert position["exit_check"] == expected and Decimal(position["quantity"]) == quantity
        assert session.inventory_at(quantity, None, START)["position_known"]["exit_check"] == "UNKNOWN"
        session.pending = SimpleNamespace(record={"ref": "BTCUSDT#1", "side": "SELL", "status": "PENDING"}, max_qty=None)
        assert session.inventory_at(quantity, quote, START)["position_known"]["exit_check"] == "WORKING_ORDER"
    finally:
        db.c.close()


def test_small_inventory_remains_held_when_rules_make_it_dust(tmp_path):
    symbol = "BTCUSDT"
    db = market_db(tmp_path, quote_history(n=150, turn=1))
    instrument = InstrumentId.wallex(symbol)
    initial = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1"}
    db.upsert_instrument(instrument, {}, initial, "test", START)
    db.upsert_instrument(instrument, {}, {**initial, "minNotional": "6"}, "test", START + timedelta(minutes=6))
    args = (db, symbol, START, START + timedelta(minutes=20))
    cost = CostModel(max_fraction=Decimal("0.005"))
    params = {"fast": 2, "slow": 3}
    try:
        legacy = paper(*args, resolution="1min", cost=cost, params=params)
        exact = paper(*args, resolution="1min", cost=cost, params={**params, "position_model": "inventory/1"})
        assert legacy["result"]["fills"] > 1
        assert exact["result"]["fills"] == 1
        assert exact["run_id"] != legacy["run_id"]
        decisions = exact["result"]["decisions"]
        assert {d["position_known"]["state"] for d in decisions} == {"FLAT", "HELD_SELLABLE", "HELD_DUST"}
        final = decisions[-1]
        assert final["action"] == "HOLD"
        quantity = Decimal(final["position_known"]["quantity"])
        assert quantity > 0 and final["position_known"]["sellable_quantity_at_bid"] == "0"
        assert final["balances_before"]["BTC"] == str(quantity)
        assert Decimal(exact["result"]["end"]["equity"]) > Decimal(exact["result"]["balances"]["USDT"])

        root = tmp_path / "runs"
        save_run(exact, root)
        page = replay_decisions(root, {"run_id": exact["run_id"], "offset": len(decisions) - 1, "limit": 1}, store="live")
        assert page["decisions"][0]["known_at_decision"]["position_known"] == final["position_known"]
    finally:
        db.c.close()


def test_portfolio_terminal_evidence_preserves_dust_and_distinguishes_missing_rules(tmp_path):
    symbols = ["BTCUSDT", "ETHUSDT"]
    rows = [top for symbol in symbols for top in quote_history(n=150, turn=1, sym=symbol)]
    db = market_db(tmp_path, rows)
    btc = InstrumentId.wallex("BTCUSDT")
    initial = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1"}
    db.upsert_instrument(btc, {}, initial, "test", START)
    db.upsert_instrument(btc, {}, {**initial, "minNotional": "6"}, "test", START + timedelta(minutes=6))
    try:
        out = portfolio(db, symbols, START, START + timedelta(minutes=20), resolution="1min",
                        cost=CostModel(max_fraction=Decimal("0.005")),
                        params={"fast": 2, "slow": 3, "position_model": "inventory/1"})
        btc_result, eth_result = (out["result"]["markets"][symbol] for symbol in symbols)
        assert Decimal(btc_result["holding"]) > 0
        assert btc_result["position_known"]["state"] == "HELD_DUST"
        assert Decimal(eth_result["holding"]) > 0
        assert eth_result["position_known"]["state"] == "HELD_UNKNOWN"
        assert eth_result["position_known"]["sellable_quantity_at_bid"] is None
    finally:
        db.c.close()
