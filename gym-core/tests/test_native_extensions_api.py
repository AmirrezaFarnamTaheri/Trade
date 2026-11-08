"""Authenticated GUI actions exercise actual native stores, evidence and replay engines."""
import asyncio
from datetime import timedelta

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.domain.model import iso
from gym.services.collector import Collector, now_utc
from gym.services.paper import paper
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history
from tests.test_depth_sequence import request as depth_request
from tests.test_depth_sequence import snapshot
from tests.test_venue_facts import sample


def test_all_native_extension_workflows_share_real_services_and_token_boundary(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    out = paper(db, "BTCUSDT", START, START + timedelta(minutes=30), resolution="1min", fast=2, slow=3)
    save_run(out, tmp_path / "runs")
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            async def action(name, value):
                body = {"action": name, "value": value}
                assert (await client.post("/api/research/action", json=body)).status == 403
                response = await client.post("/api/research/action", json=body, headers={"X-Gym-Token": "tok"})
                assert response.status == 200, await response.text()
                assert response.headers["Cache-Control"] == "no-store"
                return await response.json()
            record = (await action("replay-checkpoint", {"run_id": out["run_id"], "quote_count": 19}))["record"]
            assert (await action("replay-resume", {"checkpoint_id": record["id"]}))["status"] == "EXACT_MATCH"
            identity = {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"]}
            note = await action("annotation-add", {**identity, "decision_index": 5, "request_id": "a" * 32, "text": "<operator note>"})
            notes = await action("annotation-list", {**identity, "after": 0, "through": None, "limit": 20})
            assert notes["events"][0]["id"] == note["record"]["id"]
            page = await action("registry-page", {"kind": None, "parent": None, "after": 0, "through": None, "limit": 20})
            assert len(page["events"]) == 2
            locked = await action("entry-lock-add", {"run_id": out["run_id"], "scope": "GLOBAL", "reason": "COOLDOWN", "duration_seconds": 60, "threshold_percent": None})
            assert not locked["exit_blocked"] and len((await action("entry-locks", None))["rules"]) == 1
            assert (await action("venue-fact-import", sample()))["sequence"] == 1
            imported = await action("external-import", {"account_id": "main", "observed_at": "2026-11-01T00:00:00Z",
                                                        "orders": [{"client_id": "manual-1", "status": "UNKNOWN", "filled": "0"}]})
            assert imported["recorded_observations"] == 1 and not imported["origin_authenticated"]
            evidence = await action("evidence-report", {"run_id": out["run_id"]})
            assert not evidence["funded_authority"]
            decision = await action("evidence-decision", {"run_id": out["run_id"], "claim": "NONE", "cap": "0", "currency": "USDT", "note": "test-only offline review"})
            assert (tmp_path / "runs" / decision["decision_file"]).is_file() and not decision["funded_authority"]
            probe = await action("probe-stage", {"total_loss_limit": "1", "quote_asset": "USDT", "probe": {
                "probe_id": "offline-1", "kind": "CLIENT_ID_ECHO", "symbol": "BTCUSDT", "worst_case_total_loss": "0.25", "venue_minimum_quote": "0.2"}})
            assert not probe["order_submitted"] and probe["remaining_after"] == "0.75"
            instruction = {"instruction_id": "offline-c1", "account": "main", "symbol": "BTCUSDT", "side": "BUY", "requested_base": "1",
                           "arrival_price": "100", "fee_rate": "0.001", "started_at": "2026-11-01T00:00:00Z", "deadline": "2026-11-01T01:00:00Z", "max_spread_bps": "20", "quote_budget": "110"}
            conversion = await action("conversion-report", {"instruction": instruction, "fills": [], "mark_price": "100", "observed_at": "2026-11-01T01:00:00Z"})
            assert not conversion["settlement_verified"] and not conversion["funded_authority"]
            assert (await action("depth-audit", depth_request([snapshot()])))["status"] == "AVAILABLE"
            breadth = await action("market-breadth", {"groups": [{"name": "supplied", "symbols": ["BTCUSDT", "ETHUSDT"]}],
                                  "quote_currency": "USDT", "from": iso(START), "to": iso(START + timedelta(minutes=30)), "resolution": "1min"})
            assert breadth["groups"][0]["eligible_members"] == 1
            from tests.test_research_series import row
            await action("observe-import", {"observations": [row("value", "1000", unit="TMN", unit_epoch="old",
                components=[{"label": "part", "value": "1000"}]), row("factor", "0.1", unit="TMN/TMN")]})
            def reference(series, unit):
                return {"source_id": "supplied", "series": series, "subject": "index", "kind": "MACRO", "unit": unit}
            converted = await action("unit-convert", {"value": reference("value", "TMN"), "factor": reference("factor", "TMN/TMN"),
                "from_epoch": "old", "to_epoch": "new", "target_unit": "TMN", "as_of": iso(now_utc()), "max_age_seconds": 2678400, "max_skew_seconds": 0})
            assert converted["status"] == "AVAILABLE" and converted["value"] == "100.0"
    try:
        asyncio.run(check())
    finally:
        db.c.close()
