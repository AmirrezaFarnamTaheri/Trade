"""Decision-time state, conditional cash, durable failed trials and bounded AI evidence."""
import asyncio
import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.cli import main
from gym.domain.model import iso
from gym.domain.portfolio import rebalance_preview
from gym.services.collector import Collector, now_utc
from gym.services.experiment_registry import ExperimentRegistry
from gym.services.paper import paper
from gym.services.replay_debugger import execution_quality, replay_decisions
from gym.services.research_actions import research_action
from gym.services.research_actions import prepare_packet, save_notes
from gym.services.research_protocol import ResearchProtocol
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


@pytest.fixture
def artifact(tmp_path):
    db = market_db(tmp_path, quote_history(n=240))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=39), resolution="1min", fast=2, slow=3)
        save_run(out, tmp_path / "runs")
        yield db, out
    finally:
        db.c.close()


def test_decision_replay_separates_future_orders_and_preserves_actual_predecision_balance(tmp_path, artifact):
    _, out = artifact
    result = replay_decisions(tmp_path / "runs", {"run_id": out["run_id"], "offset": 0, "limit": 200}, store="live")
    assert result["total"] == len(out["result"]["decisions"])
    for row, recorded in zip(result["decisions"], out["result"]["decisions"]):
        assert row["balances_before"] == recorded["balances_before"]
        assert row["balance_status"] == "RECORDED_BEFORE_DECISION"
        assert "outcomes" not in row["known_at_decision"]
        assert "fill_time" not in row["known_at_decision"]
        assert row["known_at_decision"]["bar_known"]["available_at"] == recorded["t"]
        if row["subsequent_modeled_order"] and row["subsequent_modeled_order"]["status"] == "FILLED":
            assert row["subsequent_modeled_order"]["fill_time"] > recorded["t"]
    assert result["next_offset"] is None and not result["future_outcomes_are_decision_evidence"]
    for changes in ({"offset": -1}, {"offset": True}, {"limit": 201}):
        with pytest.raises(ValueError):
            replay_decisions(tmp_path / "runs", {"run_id": out["run_id"], "offset": 0, "limit": 1, **changes}, store="live")
    with pytest.raises(ValueError, match="store"):
        replay_decisions(tmp_path / "runs", {"run_id": out["run_id"], "offset": 0, "limit": 1}, store="demo")


def test_campaign_progress_retains_failed_and_unreported_attempts_without_claiming_liveness(tmp_path, artifact):
    _, out = artifact
    with ExperimentRegistry(tmp_path, store="live") as registry:
        definition = registry.append("EXPERIMENT", None, {"definition": {"hypothesis": "test recorded progress"}})
        attempts = [registry.append("ATTEMPT", definition["id"], {"state": "RESULT_PENDING", "trial": i}) for i in range(3)]
        registry.append("RESULT", definition["id"], {"attempt_id": attempts[0]["id"], "state": "COMPLETED",
            "run_id": out["run_id"], "outputs_digest": out["outputs_digest"]})
        registry.append("RESULT", definition["id"], {"attempt_id": attempts[1]["id"], "state": "FAILED", "reason": "NO_DATA"})
    with ExperimentRegistry(tmp_path, store="demo") as registry:
        registry.append("EXPERIMENT", None, {"definition": {"hypothesis": "different evidence store"}})
        registry.append("RESULT", None, {"attempt_id": "demo", "state": "FAILED", "reason": "DEMO_ONLY"})
    result = research_action(tmp_path, "campaign-status", {"limit": 10})
    assert result["registered_attempts"] == 3 and result["completed"] == 1 and result["unreported_attempts"] == 1
    assert result["terminal_states"]["FAILED"] == 1 and result["process_liveness"] == "UNKNOWN"
    assert result["verified_sample"]["results_sampled"] == 2
    assert result["verified_sample"]["rows"][1]["verification"] == "VERIFIED_NATIVE"
    (tmp_path / "runs" / (out["run_id"] + ".json")).write_text("{}", "utf-8")
    assert research_action(tmp_path, "campaign-status", {"limit": 10})["verified_sample"]["unavailable_runs"] == 1


def portfolio():
    return {"quote_currency": "USDT", "cash": "10", "reserved_cash": "5", "fee_rate": "0.01", "positions": [
        {"symbol": "BTCUSDT", "held": "10", "reserved": "8", "target_weight": "0", "bid": "10", "ask": "11", "quantity_step": "1", "minimum_quote": "1"},
        {"symbol": "ETHUSDT", "held": "0", "reserved": "0", "target_weight": "0.9", "bid": "10", "ask": "11", "quantity_step": "1", "minimum_quote": "1"}]}


def test_rebalance_respects_locks_fees_steps_and_conditional_sale_proceeds():
    result = rebalance_preview(portfolio())
    sell, buy = result["legs"]
    assert sell["gross_quantity"] == "2"  # Eight held units remain reserved.
    assert Decimal(result["conditional_sale_proceeds"]) == Decimal("19.80")
    assert buy["gross_quantity"] == "2" and buy["conditional_on_sale_settlement"]
    assert Decimal(result["conditional_remaining_cash"]) == Decimal("2.80")
    assert Decimal(buy["net_base_quantity"]) == Decimal("1.98")
    assert not result["settlement_verified"] and not result["funded_authority"]


@pytest.mark.parametrize("change", [{"reserved_cash": "11"}, {"fee_rate": "1"}, {"cash": "NaN"}])
def test_rebalance_rejects_invalid_cash_or_fees(change):
    with pytest.raises(ValueError):
        rebalance_preview({**portfolio(), **change})


def test_rebalance_unknown_minimum_does_not_spend_or_release_cash():
    request = portfolio()
    request["positions"][0]["minimum_quote"] = None
    result = rebalance_preview(request)
    assert result["legs"][0]["status"] == "UNKNOWN_MINIMUM"
    assert result["conditional_sale_proceeds"] == "0"
    assert result["legs"][1]["status"] == "NO_CAPACITY"


def test_rebalance_target_quantity_uses_bid_valuation_while_buy_budget_uses_ask():
    request = portfolio()
    request.update(cash="1000", reserved_cash="0")
    request["positions"] = [{**request["positions"][1], "target_weight": "0.5", "quantity_step": "0.01"}]
    result = rebalance_preview(request)
    assert Decimal(result["legs"][0]["gross_quantity"]) == Decimal("50.50")
    assert Decimal(result["concentration"][0]["conditional_held"]) == Decimal("49.9950")
    assert Decimal(result["concentration"][0]["target_quantity_shortfall"]) == Decimal("0.0050")
    assert Decimal(result["conditional_equity_after_costs"]) < 1000


def observation(order, **changes):
    return {"fill_id": "fill-1", "order_ref": order["ref"], "side": order["side"], "quantity": order["qty"],
            "price": order["price"], "fee": order["fee"], "fee_currency": order["fee_ccy"],
            "filled_at": order["fill_time"], "observed_at": order["fill_time"], **changes}


def test_fill_quality_reconciles_exact_fees_and_retains_unmatched_and_unobserved_orders(tmp_path, artifact):
    _, out = artifact
    order = next(row for row in out["result"]["orders"] if row["status"] == "FILLED")
    request = {"run_id": out["run_id"], "observations": [observation(order), observation(order, fill_id="foreign", order_ref="unknown")]}
    result = execution_quality(tmp_path / "runs", request, store="live")
    matched = next(row for row in result["comparisons"] if row["order_ref"] == order["ref"])
    assert Decimal(matched["quantity_difference"]) == Decimal(matched["fee_quote_difference"]) == Decimal(matched["adverse_price_bps"]) == 0
    assert result["unmatched"][0]["fill_id"] == "foreign" and not result["observations_authenticated"]
    with pytest.raises(ValueError, match="duplicate"):
        execution_quality(tmp_path / "runs", {**request, "observations": [observation(order)] * 2}, store="live")
    with pytest.raises(ValueError, match="currency"):
        execution_quality(tmp_path / "runs", {**request, "observations": [observation(order, fee_currency="USD")]}, store="live")
    with pytest.raises(ValueError, match="side/time"):
        execution_quality(tmp_path / "runs", {**request, "observations": [observation(order, side="SELL" if order["side"] == "BUY" else "BUY")]}, store="live")


def experiment():
    return {"hypothesis": "Compare a fixed strategy under stated costs and missing feed", "symbol": "BTCUSDT", "strategy": "ema-trend",
            "trials": [{"fast": 2, "slow": 3}], "windows": [{"from": iso(START), "to": iso(START + timedelta(minutes=39))}],
            "resolution": "1min", "cash": "1000", "scenarios": [
                {"fee_rate": "0.001", "latency_ms": 500, "outages": []},
                {"fee_rate": "0.01", "latency_ms": 1000, "outages": [{"from": iso(START), "to": iso(START + timedelta(minutes=39))}]}],
            "final_evaluation_id": None}


def test_registry_retains_every_attempt_and_incomplete_outage_with_matched_native_baselines(tmp_path, artifact):
    db, _ = artifact
    with ExperimentRegistry(tmp_path, store="live") as registry:
        result = registry.run(db, experiment())["experiment"]
        assert result["engine_digest"] and result["selection_is_exploratory"]
        events = result["events"]
        assert [row["kind"] for row in events[:2]] == ["ATTEMPT", "ATTEMPT"]
        results = [row for row in events if row["kind"] == "RESULT"]
        assert [row["state"] for row in results] == ["COMPLETED", "INCOMPLETE"]
        assert results[1]["reason"] == "NO_QUALIFIED_DATA"
        assert "hold USDT" in results[0]["baselines"]
        assert len(registry.listing()["records"]) == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            registry.conn.execute("UPDATE events SET body='{}'")
    with ExperimentRegistry(tmp_path, store="live") as reopened:
        assert reopened.read(result["id"])["events"] == events
    with ExperimentRegistry(tmp_path, store="demo") as other:
        assert other.listing()["records"] == []
        with pytest.raises(ValueError, match="store"):
            other.read(result["id"])


@pytest.mark.parametrize("extra,symbol,strategy,params,blocked", [
    ("DOGEUSDT", "BTCUSDT", "ema-trend", {"fast": 2, "slow": 3}, False),
    ("BTCUSDT", "BTCUSDT", "ema-trend", {"fast": 2, "slow": 3}, True),
    ("ETHUSDT", "BTCUSDT", "relative-momentum", {"lookback": 3, "reference": "ETHUSDT"}, True),
    ("USDTTMN", "BTCTMN", "ema-trend", {"fast": 2, "slow": 3}, True),
    ("BTCUSDT", "ETHUSDT", "ema-trend", {"fast": 2, "slow": 3}, True),
])
def test_experiment_budget_counts_consumed_markets_reference_fx_and_baselines_only(tmp_path, artifact, extra, symbol, strategy, params, blocked):
    db, _ = artifact
    row = list(db.c.execute("SELECT * FROM book_top LIMIT 1").fetchone())
    row[0] = "wallex:" + extra
    db.c.execute("BEGIN")
    db.c.executemany(f"INSERT INTO book_top VALUES({','.join('?' * len(row))})", (row for _ in range(100001)))
    db.c.commit()
    request = {**experiment(), "symbol": symbol, "strategy": strategy, "trials": [params]}
    with ExperimentRegistry(tmp_path, store="live") as registry:
        if blocked:
            with pytest.raises(ValueError, match="observation budget"):
                registry.run(db, request)
            assert all(event["kind"] == "ATTEMPT" for event in registry.listing()["records"][0]["events"])
        else:
            completed = registry.run(db, request)["experiment"]
            assert [event["state"] for event in completed["events"] if event["kind"] == "RESULT"] == ["COMPLETED", "INCOMPLETE"]


def test_crash_after_attempt_registration_stays_visible_without_retrying_automatically(tmp_path, artifact, monkeypatch):
    db, _ = artifact
    def crash(*args, **kwargs):
        raise RuntimeError("simulated process failure")
    monkeypatch.setattr("gym.services.experiment_registry.paper", crash)
    with ExperimentRegistry(tmp_path, store="live") as registry:
        with pytest.raises(RuntimeError):
            registry.run(db, experiment())
        record = registry.listing()["records"][0]
        assert len(record["events"]) == 2 and all(row["kind"] == "ATTEMPT" for row in record["events"])
        assert not db.c.in_transaction


def test_final_evaluation_link_requires_matching_selection_and_frozen_engine(tmp_path, artifact):
    db, _ = artifact
    now = now_utc()
    with ResearchProtocol(tmp_path, store="live") as protocol:
        final = protocol.register({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
            "selection_end": iso(START + timedelta(days=1)), "test_from": iso(now + timedelta(days=1)),
            "test_to": iso(now + timedelta(days=2)), "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})
    request = {**experiment(), "final_evaluation_id": final["evaluation_id"]}
    with ExperimentRegistry(tmp_path, store="live") as registry:
        with pytest.raises(ValueError, match="does not match"):
            registry.run(db, {**request, "cash": "500"})
        linked = registry.run(db, request)["experiment"]
        assert linked["final_evaluation_at_registration"]["evaluation_id"] == final["evaluation_id"]


def test_ai_packet_and_notes_exclude_private_fields_reject_invented_citations_and_preserve_disagreements(tmp_path, artifact):
    _, out = artifact
    path = tmp_path / "runs" / (out["run_id"] + ".json")
    body = json.loads(path.read_text())
    body["private_notes"] = "PRIVATE-CANARY"
    path.write_text(json.dumps(body))
    with ExperimentRegistry(tmp_path, store="live") as registry:
        prepared = prepare_packet(registry, {"run_ids": [out["run_id"]]})
        assert "PRIVATE-CANARY" not in prepared["prompt"] and not prepared["paid_request_sent"]
        packet = prepared["packet"]
        note = {"role": "risk", "observation": "Recorded marks do not establish future risk.", "citations": [packet["citations"][0]], "claims": [], "disagrees_with": []}
        saved = save_notes(registry, {"packet_id": packet["id"], "preset": "local-preset", "notes": [note]})
        assert not saved["record"]["semantic_grounding_verified"]
        assert registry.read(packet["id"])["events"][0]["kind"] == "RESEARCH_NOTES"
        with pytest.raises(ValueError, match="outside"):
            save_notes(registry, {"packet_id": packet["id"], "preset": "local-preset", "notes": [{**note, "citations": ["invented"]}]})
        with pytest.raises(ValueError, match="absent"):
            save_notes(registry, {"packet_id": packet["id"], "preset": "local-preset", "notes": [{**note, "disagrees_with": ["performance"]}]})


def test_shared_actions_expose_coverage_screen_replay_and_registry_and_reject_backdating(tmp_path, artifact):
    _, out = artifact
    window = {"symbol": "BTCUSDT", "from": iso(START), "to": iso(START + timedelta(minutes=30)), "resolution": "1min"}
    assert research_action(tmp_path, "coverage", window)["observations"] > 0
    assert research_action(tmp_path, "replay", {"run_id": out["run_id"], "offset": 0, "limit": 1})["decisions"]
    assert research_action(tmp_path, "experiment-list")["records"] == []
    with pytest.raises(ValueError, match="actual clock"):
        research_action(tmp_path, "experiment-run", experiment(), at=iso(START))


def test_new_api_actions_require_token_reject_ambiguous_json_and_use_same_services(tmp_path, artifact):
    db, out = artifact
    collector = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    async def check():
        async with TestClient(TestServer(make_app(collector, RuleService(db), "tok", tmp_path / "runs"))) as client:
            route, headers = "/api/research/action", {"X-Gym-Token": "tok"}
            request = {"action": "replay", "value": {"run_id": out["run_id"], "offset": 0, "limit": 1}}
            assert (await client.post(route, json=request)).status == 403
            response = await client.post(route, json=request, headers=headers)
            assert response.status == 200 and (await response.json())["decisions"]
            assert response.headers["Cache-Control"] == "no-store"
            for raw in ('{"action":"experiment-list","action":"replay","value":null}',
                        '{"action":"replay","value":{"run_id":"x","offset":NaN,"limit":1}}'):
                assert (await client.post(route, data=raw, headers=headers)).status == 400
            response = await client.post(route, json={"action": "rebalance", "value": portfolio()}, headers=headers)
            assert response.status == 200 and not (await response.json())["funded_authority"]
            from tests.test_strategy_audit import request as audit_request
            for action, value, schema in (
                ("strategy-audit", audit_request(), "strategy-audit/1"),
                ("return-bootstrap", {"run_id": out["run_id"], "seed": 21, "simulations": 100,
                                      "mean_block_length": 5, "max_gap_seconds": 120}, "return-bootstrap/1"),
                ("return-correlations", {"symbols": ["BTCUSDT", "ETHUSDT"], "quote_currency": "USDT",
                                         "from": iso(START), "to": iso(START + timedelta(minutes=39)),
                                         "resolution": "1min", "min_overlap": 10}, "return-correlations/1"),
            ):
                response = await client.post(route, json={"action": action, "value": value}, headers=headers)
                assert response.status == 200, await response.text()
                report = await response.json()
                assert report["schema"] == schema and not report["funded_authority"]
            response = await client.post(route, json={"action": "experiment-run", "value": experiment()}, headers=headers)
            assert response.status == 200
            key = (await response.json())["experiment"]["id"]
            response = await client.post(route, json={"action": "experiment-status", "value": key}, headers=headers)
            assert response.status == 200 and len((await response.json())["events"]) == 4
    asyncio.run(check())


def test_cli_replay_reuses_verified_artifact_and_experiment_listing(tmp_path, artifact, capsys):
    _, out = artifact
    save_run(out, tmp_path / "live" / "runs")
    request = tmp_path / "replay-request.json"
    request.write_text(json.dumps({"run_id": out["run_id"], "offset": 0, "limit": 1}))
    assert main(["--data", str(tmp_path), "research", "replay", str(request)]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == out["run_id"]
    assert main(["--data", str(tmp_path), "research", "experiment-list"]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == []
