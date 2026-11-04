"""Protected service-helper observations never become money authority."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from gym.adapters import service_account_read as service
from gym.adapters.wallex_account_read import ReadUncertain
from gym.domain.account_observations import project_account
from gym.services.external_journal import ExternalJournal


def envelope(body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return json.dumps({
        "source": "EXECUTOR_SERVICE_WINHTTP", "state": "RAW_UNPARSED",
        "permission_status": "UNVERIFIED", "funded_authority": False,
        "raw_body_hex": raw.hex(),
    }).encode()


class Process:
    def __init__(self, raw, *, code=0, stall=False):
        self.raw, self.code, self.stall = raw, code, stall
        self.stdout = self
        self.returncode = None
        self.killed = False

    async def read(self, size):
        if self.stall:
            await asyncio.Event().wait()
        chunk, self.raw = self.raw[:size], self.raw[size:]
        return chunk

    async def wait(self):
        if self.returncode is None:
            self.returncode = self.code
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def install(monkeypatch, raw, **kwargs):
    process = Process(raw, **kwargs)
    calls = []
    helper = Path("C:/Program Files/TradingGYM/Executor/gym-account-read.exe")
    monkeypatch.setattr(service, "_helper_path", lambda: helper)

    async def spawn(*args, **options):
        calls.append((args, options))
        return process

    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", spawn)
    return process, calls, helper


def test_balances_use_only_fixed_helper_argv_and_sanitize(monkeypatch):
    _, calls, helper = install(monkeypatch, envelope({
        "success": True, "api_key": "DO-NOT-COPY", "result": {"balances": {
            "BTC": {"value": "0.00000012", "locked": "0", "secret": "DO-NOT-COPY"},
        }},
    }))
    result = asyncio.run(service.ServiceAccountReader().balances())
    assert result == {"BTC": {"value": "0.00000012", "locked": "0"}}
    args, options = calls[0]
    assert args == (str(helper), "balances")
    assert options["cwd"] == str(helper.parent)
    assert options["stdin"] == options["stderr"] == subprocess.DEVNULL
    assert options["stdout"] == subprocess.PIPE
    assert "shell" not in options and "env" not in options
    assert "DO-NOT-COPY" not in repr(result)


def test_service_fees_reuse_exact_documented_parser(monkeypatch):
    install(monkeypatch, envelope({"success": True, "result": {
        "BTCUSDT": {"makerFeeRate": "0.0010", "takerFeeRate": "0.002"},
        "levels": [], "api_key": "DO-NOT-COPY",
    }}))
    assert asyncio.run(service.ServiceAccountReader().fee_rates()) == {
        "BTCUSDT": {"maker": "0.0010", "taker": "0.002"},
    }


def test_service_order_is_identity_bound_and_journal_stays_unknown(monkeypatch, tmp_path):
    _, calls, _ = install(monkeypatch, envelope({"success": True, "result": {
        "clientOrderId": "manual-1", "status": "FILLED", "symbol": "BTCUSDT",
        "side": "BUY", "origQty": "1", "executedQty": "1", "api_key": "DO-NOT-COPY",
    }}))
    result = asyncio.run(service.ServiceAccountReader().manual_order_evidence("manual-1"))
    assert calls[0][0][1:] == ("known-client-order", "manual-1")
    assert result["settlement"] == "UNKNOWN" and result["money_authority"] is False
    snapshot = project_account("main", "2026-11-03T12:00:00Z", orders=[{
        "client_id": result["client_id"], "status": result["raw_status"],
        "symbol": result["symbol"], "filled": result["executed_qty"],
    }])
    with ExternalJournal(tmp_path / "journal.db") as journal:
        assert journal.record(snapshot) == 1
        assert journal.events()[0]["settlement"] == "UNKNOWN"
        assert journal.events()[0]["authority"] == "READ_ONLY"
    assert "DO-NOT-COPY" not in repr(result)


@pytest.mark.parametrize("field,value", [
    ("source", "CALLER"), ("state", "NORMALIZED"),
    ("permission_status", "VERIFIED"), ("funded_authority", 0),
    ("funded_authority", True), ("raw_body_hex", "00 ff"),
    ("raw_body_hex", "f"), ("raw_body_hex", "FF"), ("raw_body_hex", ""),
    ("raw_body_hex", 123),
])
def test_untrusted_envelope_fails_closed(monkeypatch, field, value):
    raw = json.loads(envelope({"success": True, "result": {"balances": {}}}))
    raw[field] = value
    install(monkeypatch, json.dumps(raw).encode())
    with pytest.raises(ReadUncertain):
        asyncio.run(service.ServiceAccountReader().balances())


@pytest.mark.parametrize("raw", [
    b'{"source":"DO-NOT-COPY","source":"EXECUTOR_SERVICE_WINHTTP"}',
    envelope(b'{"success":false,"success":true}'),
    envelope(b'{"success":true,"result":{},"extra":NaN}'),
    envelope(b'{"success":true,"result":{},"extra":1e9999}'),
    envelope(b'\xff'), b'\xff', envelope(b'[]'),
    envelope(b'[' * 1500 + b'0' + b']' * 1500),
    envelope(b'{"success":true,"result":{"balances":{"BTC":{"value":"1e999999999","locked":"0"}}}}'),
])
def test_malformed_or_nonfinite_json_is_static_uncertainty(monkeypatch, raw):
    install(monkeypatch, raw)
    with pytest.raises(ReadUncertain) as error:
        asyncio.run(service.ServiceAccountReader().balances())
    assert "DO-NOT-COPY" not in str(error.value)


def test_unknown_envelope_fields_are_rejected(monkeypatch):
    raw = json.loads(envelope({}))
    raw["api_key"] = "DO-NOT-COPY"
    install(monkeypatch, json.dumps(raw).encode())
    with pytest.raises(ReadUncertain):
        asyncio.run(service.ServiceAccountReader().balances())


def test_wrong_order_id_and_unsafe_input_never_become_observations(monkeypatch):
    _, calls, _ = install(monkeypatch, envelope({"success": True, "result": {
        "clientOrderId": "another-order",
    }}))
    reader = service.ServiceAccountReader()
    for value in ("../../unsafe", "--delete", "x\nkey", None):
        with pytest.raises(ValueError):
            asyncio.run(reader.manual_order_evidence(value))
    assert calls == []
    with pytest.raises(ReadUncertain, match="identity"):
        asyncio.run(reader.manual_order_evidence("manual-1"))


def test_helper_error_never_exposes_stderr_or_raw_stdout(monkeypatch):
    install(monkeypatch, b"DO-NOT-COPY", code=2)
    with pytest.raises(ReadUncertain) as error:
        asyncio.run(service.ServiceAccountReader().balances())
    assert "DO-NOT-COPY" not in str(error.value)


def test_helper_output_is_bounded_and_killed_on_overflow(monkeypatch):
    process, _, _ = install(monkeypatch, b"x" * (service._OUTPUT_LIMIT + 1))
    with pytest.raises(ReadUncertain, match="limit"):
        asyncio.run(service.ServiceAccountReader().balances())
    assert process.killed


def test_helper_timeout_kills_child_and_remains_unknown(monkeypatch):
    process, _, _ = install(monkeypatch, b"", stall=True)
    monkeypatch.setattr(service, "_TIMEOUT", 0.01)
    with pytest.raises(ReadUncertain, match="unavailable"):
        asyncio.run(service.ServiceAccountReader().balances())
    assert process.killed


def test_missing_helper_is_static_uncertainty(monkeypatch):
    async def missing(*args, **kwargs):
        raise OSError("DO-NOT-COPY")

    install(monkeypatch, b"")
    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", missing)
    with pytest.raises(ReadUncertain) as error:
        asyncio.run(service.ServiceAccountReader().balances())
    assert "DO-NOT-COPY" not in str(error.value)


def test_service_reader_exposes_no_funded_operations():
    reader = service.ServiceAccountReader()
    assert not any(hasattr(reader, name) for name in (
        "post", "delete", "cancel_order", "place_order", "transfer",
    ))
