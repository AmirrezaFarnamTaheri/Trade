"""Paged observations preserve unknown coverage and never establish order absence."""
import asyncio
from copy import deepcopy

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.wallex_order_evidence import InvalidOrderEvidence, parse_order_page
from gym.api import guard
from gym.api.research import install
from gym.services.external_journal import ExternalJournal


def payload():
    return {"success": True, "result": {"orders": [{"clientOrderId": "External_1", "symbol": "BTCUSDT",
        "side": "BUY", "status": "NEW", "origQty": "0.01", "executedQty": "0.003", "secretExtra": "DO-NOT-COPY"}]},
        "result_info": {"page": 2, "per_page": 10}}


def test_page_identity_quantity_bounds_and_unverified_coverage():
    result = parse_order_page(payload(), kind="OPEN", page=2, per_page=10)
    assert len(result["orders"]) == 1 and result["pagination_echo"] == "MATCHED"
    assert result["orders"][0]["executed_qty"] == "0.003" and result["orders"][0]["settlement"] == "UNKNOWN"
    assert not result["collection_complete"] and not result["snapshot_atomic"] and not result["absence_proven"]
    assert "DO-NOT-COPY" not in str(result)
    empty = parse_order_page({"success": True, "result": {}}, kind="HISTORY", page=1, per_page=100)
    assert not empty["absence_proven"] and empty["pagination_echo"] == "UNVERIFIED"
    for modify in (
        lambda p: p["result_info"].update(page=1),
        lambda p: p["result_info"].update(page=True),
        lambda p: p.update(success=False),
        lambda p: p.update(result=[]),
        lambda p: p["result"]["orders"].append(deepcopy(p["result"]["orders"][0])),
        lambda p: p["result"]["orders"][0].update(executedQty="0.02"),
        lambda p: p["result"]["orders"][0].update(clientOrderId="../unsafe"),
    ):
        changed = deepcopy(payload())
        modify(changed)
        with pytest.raises(InvalidOrderEvidence):
            parse_order_page(changed, kind="OPEN", page=2, per_page=10)
    for kind, page, count in (("INVALID", 1, 10), ("OPEN", True, 10), ("OPEN", 0, 10), ("HISTORY", 1001, 10), ("OPEN", 1, 101)):
        with pytest.raises(InvalidOrderEvidence):
            parse_order_page(payload(), kind=kind, page=page, per_page=count)


def test_page_import_is_authenticated_sanitized_and_not_complete_account_state(tmp_path):
    async def check():
        app = web.Application(middlewares=[guard("tok")])
        install(app, tmp_path, store="live")
        value = {"account_id": "main", "observed_at": "2026-10-29T10:00:00Z", "kind": "OPEN", "page": 2, "per_page": 10, "payload": payload()}
        async with TestClient(TestServer(app)) as client:
            assert (await client.post("/api/research/action", json={"action": "order-page-import", "value": value})).status == 403
            assert not (tmp_path / "external_journal.db").exists()
            response = await client.post("/api/research/action", json={"action": "order-page-import", "value": value}, headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            result = await response.json()
            assert not result["origin_authenticated"] and not result["collection_complete"] and not result["funded_authority"]
        with ExternalJournal(tmp_path / "external_journal.db") as journal:
            events = journal.conn.execute("SELECT raw_status,filled_observed,settlement FROM external_order_events").fetchall()
            assert events == [("NEW", "0.003", "UNKNOWN")]
            assert "DO-NOT-COPY" not in str(journal.conn.execute("SELECT snapshot_json FROM external_account_snapshots").fetchall())
    asyncio.run(check())
