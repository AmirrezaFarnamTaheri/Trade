"""One shared GUI/CLI path: pinned public calculators, durable terms and recorded quotes."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters import wallex_margin
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.services import margin
from gym.services.collector import Collector
from gym.services.research_actions import research_action
from gym.services.research_process import ResearchProcessFailure, calculate
from gym.services.rules import RuleService
from tests.support import START, market_db, quote
from tests.test_margin import path, preview, request, rule


def calculator(monkeypatch, *, collateral_min="50", returned=None):
    calls = []
    def read(endpoint, body=None):
        calls.append((endpoint, body))
        if endpoint == wallex_margin.MARKETS:
            return [rule()], "a" * 64
        if endpoint == wallex_margin.LOAN:
            return {"collateral": {"min": collateral_min, "max": "850"}, "loan": preview(body["side"])["loan"]}, "b" * 64
        assert endpoint == wallex_margin.PREVIEW
        return returned or preview(body["side"]), "c" * 64
    monkeypatch.setattr(margin, "public_margin", read)
    monkeypatch.setattr(margin, "now_utc", lambda: START)
    return calls


def saved_preview(tmp_path, monkeypatch, **kwargs):
    calls = calculator(monkeypatch, **kwargs)
    catalogue = research_action(tmp_path, "margin-markets")
    terms = research_action(tmp_path, "margin-preview", {"catalogue_id": catalogue["run_id"], "request": request()})
    return catalogue, terms, calls


def test_shared_actions_retain_venue_receipts_and_replay_after_terms_were_known(tmp_path, monkeypatch):
    catalogue, terms, calls = saved_preview(tmp_path, monkeypatch)
    assert [call[0] for call in calls] == [wallex_margin.MARKETS, wallex_margin.LOAN, wallex_margin.PREVIEW]
    assert terms["collateral_limits"] == {"min": "50", "max": "850"}
    assert terms["funded_authority"] is False and terms["loan_body_sha256"] == "b" * 64
    db = market_db(tmp_path, [top for top, _ in path()])
    db.c.close()
    end = START + timedelta(hours=1, seconds=1)
    monkeypatch.setattr(margin, "now_utc", lambda: end)
    payload = {"preview_id": terms["run_id"], "from": START.isoformat(), "to": end.isoformat(), "exit_fee_rate": "0.001", "holding_seconds": 3600}
    out = research_action(tmp_path, "margin-replay", payload)
    assert out["kind"] == "REPLAY" and out["result"]["state"] == "CLOSED"
    assert Decimal(out["result"]["cash_quote"]) == Decimal("119.20055")
    assert margin.load_receipt(tmp_path, out["run_id"], "REPLAY") == out
    assert research_action(tmp_path, "margin-replay", payload)["run_id"] == out["run_id"]
    assert catalogue["received_at"] == terms["received_at"]


def test_stale_future_catalogues_and_unavailable_collateral_do_not_call_preview(tmp_path, monkeypatch):
    calls = calculator(monkeypatch, collateral_min="150")
    catalogue = margin.margin_action(tmp_path, "margin-markets", None, store="live")
    value = {"catalogue_id": catalogue["run_id"], "request": request()}
    rejected = margin.margin_action(tmp_path, "margin-preview", value, store="live")
    assert rejected["kind"] == "COLLATERAL_LIMITS" and rejected["state"] == "OUTSIDE_LIMITS"
    assert rejected["collateral_limits"] == {"min": "150", "max": "850", "currency": "USDT"}
    assert len(calls) == 2
    for clock in (START - timedelta(seconds=1), START + timedelta(minutes=6)):
        monkeypatch.setattr(margin, "now_utc", lambda: clock)
        with pytest.raises(ValueError, match="not current"):
            margin.margin_action(tmp_path, "margin-preview", value, store="live")
    assert len(calls) == 2


def test_tampered_receipt_and_future_terms_cannot_become_historical_knowledge(tmp_path, monkeypatch):
    _, terms, _ = saved_preview(tmp_path, monkeypatch)
    payload = {"preview_id": terms["run_id"], "from": (START - timedelta(hours=1)).isoformat(), "to": START.isoformat(), "exit_fee_rate": "0", "holding_seconds": None}
    with pytest.raises(ValueError, match="no future terms"):
        margin.margin_action(tmp_path, "margin-replay", payload, store="live")
    file = tmp_path / "margin" / (terms["run_id"] + ".json")
    file.write_text(file.read_text().replace('"value": "200"', '"value": "999"'))
    with pytest.raises(ValueError, match="integrity"):
        margin.load_receipt(tmp_path, terms["run_id"], "PREVIEW")


def test_demo_and_unknown_fields_do_not_contact_the_venue(tmp_path, monkeypatch):
    calls = calculator(monkeypatch)
    with pytest.raises(ValueError):
        margin.margin_action(tmp_path, "margin-markets", None, store="demo")
    with pytest.raises(ValueError):
        margin.margin_action(tmp_path, "margin-markets", {"key": "refused"}, store="live")
    assert calls == []
    for receipt_id in (None, 1, [], "../secret"):
        with pytest.raises(ValueError):
            margin.load_receipt(tmp_path, receipt_id, "PREVIEW")


def test_transport_is_pinned_bounded_and_rejects_redirects_and_mutations(monkeypatch):
    for endpoint, body in (("/margin-trade/v1/positions", request()), (wallex_margin.MARKETS, {}), ("https://evil.example/", None)):
        with pytest.raises(ValueError, match="allowlist"):
            wallex_margin.public_margin(endpoint, body)
    with pytest.raises(ValueError, match="redirect"):
        wallex_margin.NoRedirect().redirect_request(None, None, None, None, None, "https://evil.example")
    calls = []
    class Response:
        status = 200
        headers = {}
        raw = b'{"success":true,"result":[]}'
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def geturl(self): return wallex_margin.ORIGIN + wallex_margin.MARKETS
        def read(self, size): return self.raw[:size]
    def open_request(req, timeout):
        calls.append(req)
        assert timeout == 12 and req.full_url == wallex_margin.ORIGIN + wallex_margin.MARKETS
        assert all(key.lower() != "x-api-key" for key in req.headers)
        return Response()
    monkeypatch.setattr(wallex_margin, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    assert wallex_margin.public_margin(wallex_margin.MARKETS)[0] == []
    for raw in (b'{"success":true,"result":{},"result":[]}', b'{"success":false}', b'x' * (wallex_margin.MAX_BODY + 1)):
        monkeypatch.setattr(Response, "raw", raw)
        with pytest.raises(ValueError):
            wallex_margin.public_margin(wallex_margin.MARKETS)
    assert len(calls) == 4


def test_gui_write_guard_and_shared_margin_action_dispatch(tmp_path, monkeypatch):
    calculator(monkeypatch)
    db = market_db(tmp_path, [quote(START, "99", "100")])
    seg = SegmentWriter(tmp_path / "raw", db)
    from gym.api import research
    async def compute(root, action, value, *, store):
        return research_action(root, action, value, store=store)
    monkeypatch.setattr(research, "calculate", compute)
    async def check():
        async with TestClient(TestServer(make_app(Collector(db, seg, None), RuleService(db), "secret", runs=tmp_path / "runs"))) as client:
            payload = {"action": "margin-markets", "value": None}
            assert (await client.post("/api/research/action", json=payload)).status == 403
            response = await client.post("/api/research/action", json=payload, headers={"X-Gym-Token": "secret"})
            result = await response.json()
            assert response.status == 200 and result["kind"] == "MARKETS" and result["funded_authority"] is False
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()


def test_supervised_margin_worker_refuses_missing_receipt_without_network(tmp_path):
    async def check():
        with pytest.raises(ResearchProcessFailure) as error:
            await calculate(tmp_path, "margin-preview", {"catalogue_id": "a" * 16, "request": request()})
        assert error.value.status == 400
    asyncio.run(check())
