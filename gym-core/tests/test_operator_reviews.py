"""Native intent codecs, helper boundaries and actual local HTTP authorization."""

import asyncio
import json
import struct
from copy import deepcopy
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters import service_review
from gym.adapters.wallex_account_read import ReadUncertain
from gym.api import guard, operator_reviews
from gym.contracts.review_wire import (
    REPLY_SIZE,
    decode_reply,
    encode_request,
    parse_ticket,
    ticket_bytes,
)

FIXTURE = (
    Path(__file__).resolve().parents[2] / "contracts/v1/fixtures/operator-review-v1.hex"
)


def ticket():
    return {
        "client_id": "intent-1",
        "account": "main",
        "base": "BTC",
        "quote": "USDT",
        "side": "BUY",
        "base_decimals": 8,
        "price_decimals": 2,
        "quote_decimals": 6,
        "base_epoch": 1,
        "quote_epoch": 1,
        "runtime_epoch": "10",
        "ceiling_sequence": "1",
        "expires_at_ms": "20000",
        "quantity": "0.00010000",
        "worst_price": "80000.00",
        "max_quote_debit": "8.010000",
        "min_quote_credit": "0.000000",
        "preview_hash": "01" * 32,
        "rules_hash": "02" * 32,
        "credential_generation": "03" * 16,
    }


def reply(request, *, state=2, correlation=bytes([4]) * 16):
    raw = bytearray(REPLY_SIZE)
    raw[:8] = b"TGREPLY1"
    raw[8:11] = bytes([state, 0, int(state in (2, 3, 7))])
    raw[16:32] = correlation
    raw[32:40] = (10).to_bytes(8, "big")
    raw[56:64] = (1).to_bytes(8, "big")
    raw[64:80] = bytes([3]) * 16
    if state in (2, 3, 7):
        raw[40:56] = struct.pack(">QQ", 2, 1000)
        raw[80:] = ticket_bytes(request["ticket"])
    return bytes(raw)


def test_native_golden_contract_and_exact_amounts():
    request = {"action": "approve", "ticket": ticket()}
    lines = FIXTURE.read_text("ascii").splitlines()
    assert encode_request(request, bytes([4]) * 16) == bytes.fromhex(lines[0])
    assert reply(request) == bytes.fromhex(lines[1])
    result = decode_reply(bytes.fromhex(lines[1]), bytes([4]) * 16, request)
    assert result["ticket"] == ticket() and result["current_epoch"] == "10"
    assert not result["funded_authority"] and not result["order_submitted"]
    assert parse_ticket(ticket_bytes(ticket())) == ticket()
    for key, value in (
        ("quantity", 1.0),
        ("quantity", "0.000000001"),
        ("runtime_epoch", 9007199254740993),
        ("side", "LIMIT"),
        ("preview_hash", "00" * 32),
        ("base_epoch", True),
        ("max_quote_debit", "7.99"),
    ):
        bad = ticket()
        bad[key] = value
        with pytest.raises(ValueError):
            ticket_bytes(bad)
    for offset in (11, 15, 350, 431):
        bad = bytearray(bytes.fromhex(lines[1]))
        bad[offset] = 1
        with pytest.raises(ValueError):
            decode_reply(bytes(bad), bytes([4]) * 16, request)
    with pytest.raises(ValueError):
        decode_reply(reply(request), bytes([5]) * 16, request)
    for action in ("status", "revoke"):
        with pytest.raises(ValueError):
            decode_reply(reply(request), bytes([4]) * 16, {"action": action})
    with pytest.raises(ValueError):
        decode_reply(reply(request, state=3), bytes([4]) * 16, request)
    fractional = ticket()
    fractional.update(
        quantity="0.00000001", worst_price="0.01", max_quote_debit="0.000000"
    )
    with pytest.raises(ValueError):
        ticket_bytes(fractional)
    fractional["max_quote_debit"] = "0.000001"
    assert ticket_bytes(fractional)
    changed = deepcopy(request)
    changed["ticket"]["rules_hash"] = "05" * 32
    with pytest.raises(ValueError):
        decode_reply(reply(request), bytes([4]) * 16, changed)


def test_preparation_codec_keeps_exact_version_identity_and_no_authority():
    request = {"action": "prepare", "client_id": "intent-1", "expected_sequence": "1"}
    frame = encode_request(request, bytes([4]) * 16)
    assert frame[8] == 5 and int.from_bytes(frame[32:40], "big") == 1
    raw = reply({"ticket": ticket()}, state=7)
    result = decode_reply(raw, bytes([4]) * 16, request)
    assert result["state"] == "PREPARED" and result["ticket"] == ticket()
    assert not result["funded_authority"] and not result["order_submitted"]
    for bad in (
        {**request, "expected_sequence": "2"},
        {**request, "client_id": "other"},
        {"action": "status"},
    ):
        with pytest.raises(ValueError):
            decode_reply(raw, bytes([4]) * 16, bad)
    for bad in ({**request, "expected_sequence": 1}, {**request, "ticket": ticket()}):
        with pytest.raises(ValueError):
            encode_request(bad, bytes([4]) * 16)


def test_helper_uses_only_fixed_stdin_frame_and_bounds_failure(
    monkeypatch, tmp_path, capsys
):
    from tests.test_service_account_read import Process

    request = {"action": "approve", "ticket": ticket()}
    raw = reply(request)

    class Input:
        def write(self, value):
            self.value = value

        async def drain(self):
            pass

        def close(self):
            pass

    async def check():
        process = Process(
            json.dumps(
                {
                    "source": "EXECUTOR_SERVICE_REVIEW",
                    "funded_authority": False,
                    "order_submitted": False,
                    "raw_reply_hex": raw.hex(),
                }
            ).encode()
        )
        process.stdin = Input()
        calls = []

        async def spawn(*args, **options):
            calls.append((args, options))
            return process

        monkeypatch.setattr(
            service_review,
            "_helper_path",
            lambda name: Path("C:/Program Files/TradingGYM/Executor") / name,
        )
        monkeypatch.setattr(
            service_review.secrets, "token_bytes", lambda count: bytes([4]) * count
        )
        monkeypatch.setattr(service_review.asyncio, "create_subprocess_exec", spawn)
        result = await service_review.review(request)
        assert result["state"] == "APPROVAL_RECORDED" and len(calls) == 1
        assert calls[0][0] == (
            str(Path("C:/Program Files/TradingGYM/Executor/gym-review.exe")),
        )
        assert process.stdin.value == encode_request(request, bytes([4]) * 16)
        bad = deepcopy(request)
        bad["ticket"]["funded_authority"] = True
        with pytest.raises(ValueError):
            await service_review.review(bad)
        assert len(calls) == 1
        process.raw = b"PRIVATE-MUST-NOT-ESCAPE" * 200
        process.returncode = None
        with pytest.raises(ReadUncertain) as error:
            await service_review.review(request)
        assert process.killed and "PRIVATE" not in str(error.value)

    asyncio.run(check())

    from gym.cli import main

    path = tmp_path / "review.json"
    path.write_text('{"action":"status"}', encoding="utf-8")

    async def cli_review(value):
        assert value == {"action": "status"}
        return {"state": "STATUS", "funded_authority": False, "order_submitted": False}

    monkeypatch.setattr(service_review, "review", cli_review)
    assert main(["operator-review", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["funded_authority"] is False

    async def unavailable(value):
        raise ReadUncertain("PRIVATE-MUST-NOT-ESCAPE")

    monkeypatch.setattr(service_review, "review", unavailable)
    assert main(["operator-review", str(path)]) == 3
    report = capsys.readouterr().out
    assert "PRIVATE" not in report
    assert json.loads(report)["operation_may_have_committed"] is True


def test_api_rejects_concurrent_and_oversize_work_before_helper(monkeypatch):
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def native(value):
            calls.append(value)
            entered.set()
            await release.wait()
            return {
                "state": "STATUS",
                "funded_authority": False,
                "order_submitted": False,
            }

        monkeypatch.setattr(operator_reviews, "review", native)
        app = web.Application(middlewares=[guard("tok")])
        operator_reviews.install(app, enabled=True)
        async with TestClient(TestServer(app)) as client:
            headers = {
                "X-Gym-Token": "tok",
                "Origin": str(client.make_url("/")).rstrip("/"),
            }
            assert (
                await client.post(
                    "/api/operator-reviews", data=b" " * 16385, headers=headers
                )
            ).status == 413
            assert calls == []
            first = asyncio.create_task(
                client.get("/api/operator-reviews", headers=headers)
            )
            try:
                await asyncio.wait_for(entered.wait(), 2)
                assert (
                    await client.get("/api/operator-reviews", headers=headers)
                ).status == 409
                assert len(calls) == 1
            finally:
                release.set()
                response = await first
                await response.read()
            assert response.status == 200 and len(calls) == 1

    asyncio.run(check())


def test_api_requires_session_and_origin_preserves_uncertainty_and_never_auto_retries(
    monkeypatch,
):
    calls = []

    async def native(value):
        calls.append(value)
        if value["action"] == "inspect":
            raise ReadUncertain("PRIVATE-MUST-NOT-ESCAPE")
        return {"state": "STATUS", "funded_authority": False, "order_submitted": False}

    monkeypatch.setattr(operator_reviews, "review", native)

    async def check():
        app = web.Application(middlewares=[guard("tok")])
        operator_reviews.install(app, enabled=True)
        async with TestClient(TestServer(app)) as client:
            headers = {
                "X-Gym-Token": "tok",
                "Origin": str(client.make_url("/")).rstrip("/"),
            }
            assert (await client.get("/api/operator-reviews")).status == 403
            assert (
                await client.post(
                    "/api/operator-reviews",
                    json={"action": "status"},
                    headers={"X-Gym-Token": "tok"},
                )
            ).status == 403
            assert (
                await client.post(
                    "/api/operator-reviews",
                    json={"action": "status"},
                    headers={**headers, "Origin": "https://untrusted.example"},
                )
            ).status == 403
            assert calls == []
            response = await client.get(
                "/api/operator-reviews", headers={"X-Gym-Token": "tok"}
            )
            assert (
                response.status == 200
                and response.headers["Cache-Control"] == "no-store"
            )
            response = await client.post(
                "/api/operator-reviews",
                json={"action": "inspect", "client_id": "intent-1"},
                headers=headers,
            )
            value = await response.json()
            assert (
                response.status == 503
                and not value["automatic_retry_allowed"]
                and value["operation_may_have_committed"]
            )
            assert "PRIVATE" not in str(value) and len(calls) == 2
            assert (
                await client.post(
                    "/api/operator-reviews",
                    data=b'{"action":"status","action":"approve"}',
                    headers=headers,
                )
            ).status == 400
            assert len(calls) == 2
        demo = web.Application(middlewares=[guard("tok")])
        operator_reviews.install(demo, enabled=False)
        async with TestClient(TestServer(demo)) as client:
            assert (
                await client.get(
                    "/api/operator-reviews", headers={"X-Gym-Token": "tok"}
                )
            ).status == 403
            assert len(calls) == 2

    asyncio.run(check())
