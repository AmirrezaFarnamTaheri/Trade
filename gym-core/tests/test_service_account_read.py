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


def receipt_envelope(body, *, resource="BALANCES", sequence="2", request="11" * 16,
                     start="1000", received="1010"):
    import hashlib
    raw = json.loads(envelope(body))
    encoded = bytes.fromhex(raw["raw_body_hex"])
    raw["service_receipt"] = {
        "source": "EXECUTOR_SERVICE_JOURNAL", "authority": "OBSERVATION_ONLY",
        "resource": resource, "sequence": sequence, "runtime_epoch": "10",
        "started_at_ms": start, "received_at_ms": received,
        "credential_generation": "33" * 16, "request_id": request,
        "response_digest": hashlib.sha256(bytes(32) + len(encoded).to_bytes(8, "big") + encoded).hexdigest(),
        "event_hash": "55" * 32,
    }
    return raw


def order_receipt(client_id, *, sequence="4", request="44" * 16, start="1040"):
    body = {"success": True, "result": {"clientOrderId": client_id, "status": "CANCELED",
            "symbol": "BTCUSDT", "side": "BUY", "origQty": "1", "executedQty": "0.1",
            "fills": [{"quantity": "0.1", "price": "100", "fee": "0.00001",
                       "feeAsset": "BTC", "timestamp": 1762390000000}]}}
    raw = receipt_envelope(body, resource="ORDER_STATUS", sequence=sequence, request=request,
                           start=start, received=str(int(start) + 10))
    raw["service_receipt"]["client_id"] = client_id
    return raw


def page_receipt(*, resource="OPEN_ORDERS", page=1, per_page=10, sequence="5", request="55" * 16, start="1060"):
    order = json.loads(bytes.fromhex(order_receipt("manual-1")["raw_body_hex"]))["result"]
    body = {"success": True, "result": {"BTCUSDT": [order]},
            "result_info": {"page": page, "per_page": per_page}}
    raw = receipt_envelope(body, resource=resource, sequence=sequence, request=request,
                           start=start, received=str(int(start) + 10))
    raw["service_receipt"].update(page=str(page), per_page=str(per_page))
    return raw


def test_page_receipts_bind_request_and_refresh_only_the_requested_page(monkeypatch):
    reader = service.ServiceAccountReader()
    install(monkeypatch, json.dumps(page_receipt()).encode())
    observed = asyncio.run(reader.order_page(kind="OPEN", page=1, per_page=10))
    assert observed["pagination_echo"] == "MATCHED" and observed["absence_proven"] is False
    install(monkeypatch, json.dumps(page_receipt(page=2, sequence="6", request="66" * 16, start="1080")).encode())
    asyncio.run(reader.order_page(kind="OPEN", page=2, per_page=10))
    assert [row["page"] for row in reader.receipts] == ["1", "2"]
    install(monkeypatch, b"FAILED", code=2)
    with pytest.raises(ReadUncertain):
        asyncio.run(reader.order_page(kind="OPEN", page=1, per_page=10))
    assert [row["page"] for row in reader.receipts] == ["2"]
    install(monkeypatch, json.dumps(page_receipt(page=1, sequence="7", request="77" * 16, start="1100")).encode())
    with pytest.raises(ReadUncertain):
        asyncio.run(reader.order_page(kind="OPEN", page=3, per_page=10))
    assert [row["page"] for row in reader.receipts] == ["2"]


@pytest.mark.parametrize("change", ["page", "echo", "private", "authority", "receipt", "order"])
def test_saved_pages_revalidate_request_and_observations_before_append(tmp_path, change):
    from gym.adapters.wallex_order_evidence import parse_order_page
    raw = page_receipt()
    page = parse_order_page(json.loads(bytes.fromhex(raw["raw_body_hex"])), kind="OPEN", page=1, per_page=10)
    snapshot = project_account("main", "2026-11-06T00:00:00Z", orders=[{
        "client_id": "manual-1", "symbol": "BTCUSDT", "status": "CANCELED", "filled": "0.1"}])
    snapshot["order_pages"] = [page]
    snapshot["service_receipts"] = [raw["service_receipt"]]
    if change == "page":
        page["requested_page"] = True
    elif change == "echo":
        page["pagination_echo"] = "COMPLETE"
    elif change == "private":
        page["private"] = "DO-NOT-COPY"
    elif change == "authority":
        page["absence_proven"] = 0
    elif change == "receipt":
        snapshot["service_receipts"][0]["page"] = "2"
    else:
        page["orders"][0]["raw_status"] = "FILLED"
    with ExternalJournal(tmp_path / "journal.db") as journal:
        with pytest.raises(ValueError):
            journal.record(snapshot, transport="EXECUTOR_SERVICE_WINHTTP")
        assert journal.latest_snapshot() is None and journal.events() == []


def test_order_receipts_are_identity_bound_and_refresh_only_the_same_order(monkeypatch):
    reader = service.ServiceAccountReader()
    install(monkeypatch, json.dumps(order_receipt("manual-1")).encode())
    result = asyncio.run(reader.manual_order_evidence("manual-1"))
    assert result["settlement"] == "UNKNOWN" and result["executed_qty"] == "0.1"
    install(monkeypatch, json.dumps(order_receipt("manual-2", sequence="5", request="55" * 16, start="1060")).encode())
    asyncio.run(reader.manual_order_evidence("manual-2"))
    assert [row["client_id"] for row in reader.receipts] == ["manual-1", "manual-2"]
    install(monkeypatch, b"FAILED", code=2)
    with pytest.raises(ReadUncertain):
        asyncio.run(reader.manual_order_evidence("manual-1"))
    assert [row["client_id"] for row in reader.receipts] == ["manual-2"]
    raw = order_receipt("manual-1", sequence="6", request="66" * 16, start="1080")
    raw["service_receipt"]["client_id"] = "manual-2"
    install(monkeypatch, json.dumps(raw).encode())
    with pytest.raises(ReadUncertain):
        asyncio.run(reader.manual_order_evidence("manual-1"))
    assert [row["client_id"] for row in reader.receipts] == ["manual-2"]


@pytest.mark.parametrize("change", ["fee", "authority", "private", "identity", "receipt"])
def test_saved_order_details_refuse_tampering_before_any_journal_append(tmp_path, change):
    from gym.adapters.wallex_order_evidence import parse_manual_order_evidence
    raw = order_receipt("manual-1")
    details = parse_manual_order_evidence(json.loads(bytes.fromhex(raw["raw_body_hex"])), "manual-1")
    snapshot = project_account("main", "2026-11-06T00:00:00Z", orders=[{
        "client_id": "manual-1", "symbol": "BTCUSDT", "status": "CANCELED", "filled": "0.1"}])
    snapshot["order_evidence"] = [details]
    snapshot["service_receipts"] = [raw["service_receipt"]]
    if change == "fee":
        details["fills"][0]["fee"] = "-1"
    elif change == "authority":
        details["money_authority"] = 0
    elif change == "private":
        details["fills"][0]["private"] = "DO-NOT-COPY"
    elif change == "identity":
        details["raw_status"] = "FILLED"
    else:
        snapshot["service_receipts"][0]["client_id"] = "unrelated-order"
    with ExternalJournal(tmp_path / "journal.db") as journal:
        with pytest.raises(ValueError):
            journal.record(snapshot, transport="EXECUTOR_SERVICE_WINHTTP")
        assert journal.events() == [] and journal.latest_snapshot() is None


def test_nonadjacent_receipt_request_reuse_is_rejected():
    from gym.contracts.account_receipt import service_receipts
    rows = [order_receipt("manual-1")["service_receipt"],
            order_receipt("manual-2", sequence="5", request="55" * 16, start="1060")["service_receipt"],
            order_receipt("manual-3", sequence="6", start="1080")["service_receipt"]]
    with pytest.raises(ValueError, match="repeated.*request"):
        service_receipts(rows)


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


def test_service_receipt_checks_body_and_can_refresh_a_resource(monkeypatch):
    body = {"success": True, "result": {"balances": {"USDT": {"value": "10.20", "locked": "1"}}}}
    install(monkeypatch, json.dumps(receipt_envelope(body)).encode())
    reader = service.ServiceAccountReader()
    assert asyncio.run(reader.balances())["USDT"]["value"] == "10.20"
    assert reader.receipts[0]["sequence"] == "2"
    install(monkeypatch, json.dumps(receipt_envelope(body, sequence="3", request="22" * 16,
                                                  start="1020", received="1030")).encode())
    asyncio.run(reader.balances())
    assert len(reader.receipts) == 1 and reader.receipts[0]["sequence"] == "3"
    install(monkeypatch, b"FAILED", code=2)
    with pytest.raises(ReadUncertain):
        asyncio.run(reader.balances())
    assert reader.receipts == []


@pytest.mark.parametrize("field,value", [
    ("resource", "FEES"), ("source", "USER"), ("authority", "FUNDED"),
    ("sequence", "0"), ("sequence", "01"), ("sequence", True), ("sequence", "18446744073709551616"),
    ("runtime_epoch", "0"), ("started_at_ms", "0"), ("received_at_ms", "999"),
    ("received_at_ms", "13000"), ("request_id", "00" * 16),
    ("credential_generation", "33" * 32), ("response_digest", "66" * 32),
    ("event_hash", "AB" * 32), ("unknown", "DO-NOT-COPY"),
])
def test_service_receipt_rejects_malformed_context_without_exposing_input(monkeypatch, field, value):
    raw = receipt_envelope({"success": True, "result": {"balances": {}}})
    raw["service_receipt"][field] = value
    install(monkeypatch, json.dumps(raw).encode())
    with pytest.raises(ReadUncertain) as error:
        asyncio.run(service.ServiceAccountReader().balances())
    assert "DO-NOT-COPY" not in str(error.value)


def test_saved_service_receipts_reach_token_guarded_api_and_cli(monkeypatch, capsys, tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from gym.adapters.store import MarketDB, SegmentWriter
    from gym.api.server import make_app
    from gym.cli import main
    from gym.services.collector import Collector
    from gym.services.rules import RuleService

    balance_body = {"success": True, "result": {"balances": {"USDT": {"value": "10.20", "locked": "1"}}}}
    fee_body = {"success": True, "result": {"BTCUSDT": {"makerFeeRate": "0.001", "takerFeeRate": "0.002"}}}
    balance = receipt_envelope(balance_body)
    fees = receipt_envelope(fee_body, resource="FEES", sequence="3", request="22" * 16,
                            start="1020", received="1030")
    order = order_receipt("manual-1")
    opened = page_receipt()
    history = page_receipt(resource="ORDER_HISTORY", page=2, sequence="6", request="66" * 16, start="1080")
    helper = Path("C:/Program Files/TradingGYM/Executor/gym-account-read.exe")
    monkeypatch.setattr(service, "_helper_path", lambda: helper)

    async def spawn(*args, **_options):
        return Process(json.dumps({"balances": balance, "fees": fees, "known-client-order": order,
                                   "open-orders": opened, "order-history": history}[args[1]]).encode())

    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", spawn)
    assert main(["--data", str(tmp_path), "account", "--source", "service", "--order", "manual-1",
                 "--open-orders-page", "1", "--history-page", "2", "--per-page", "10", "--record"]) == 0
    printed = json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]
    expected = [balance["service_receipt"], fees["service_receipt"], order["service_receipt"],
                opened["service_receipt"], history["service_receipt"]]
    assert printed["service_receipts"] == expected
    assert printed["funded_authority"] is False

    async def inspect():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        with ExternalJournal(tmp_path / "live" / "external_journal.db") as journal:
            assert journal.latest_snapshot()["service_receipts"] == expected
            app = make_app(col, RuleService(db), "secret", external_journal=journal)
            async with TestClient(TestServer(app)) as client:
                assert (await client.get("/api/account-observations")).status == 403
                response = await client.get("/api/account-observations", headers={"X-Gym-Token": "secret"})
                saved = await response.json()
                assert saved["service_receipts"] == expected
                assert saved["balances"][0]["spendable"] is None and saved["funded_authority"] is False
                assert saved["order_evidence"] == printed["order_evidence"]
                assert saved["order_evidence"][0]["fills"][0]["fee_asset"] == "BTC"
                assert saved["order_evidence"][0]["settlement"] == "UNKNOWN"
                assert saved["order_pages"] == printed["order_pages"]
                assert len(saved["order_pages"]) == 2
                assert all(page["collection_complete"] is False for page in saved["order_pages"])
        db.c.close()
    asyncio.run(inspect())


def test_receipt_context_changes_refuse_combined_snapshot(monkeypatch):
    reader = service.ServiceAccountReader()
    balance_body = {"success": True, "result": {"balances": {}}}
    fee_body = {"success": True, "result": {"BTCUSDT": {"makerFeeRate": "0.001", "takerFeeRate": "0.002"}}}
    install(monkeypatch, json.dumps(receipt_envelope(balance_body)).encode())
    asyncio.run(reader.balances())
    fees = receipt_envelope(fee_body, resource="FEES", sequence="3", request="22" * 16,
                            start="1020", received="1030")
    fees["service_receipt"]["runtime_epoch"] = "11"
    install(monkeypatch, json.dumps(fees).encode())
    with pytest.raises(ReadUncertain, match="inconsistent"):
        asyncio.run(reader.fee_rates())


def test_persisted_receipt_metadata_is_sanitized_again(tmp_path):
    from gym.contracts.account_receipt import service_receipts
    data = project_account("main", "2026-11-05T12:00:00Z", balances={})
    receipts = [receipt_envelope({"success": True, "result": {"balances": {}}})["service_receipt"]]
    data["service_receipts"] = receipts
    with ExternalJournal(tmp_path / "journal.db") as journal:
        with pytest.raises(ValueError):
            journal.record(data, transport="MANUAL_IMPORT")
        data["service_receipts"][0]["private"] = "DO-NOT-COPY"
        with pytest.raises(ValueError):
            journal.record(data, transport="EXECUTOR_SERVICE_WINHTTP")
        assert journal.latest_snapshot() is None
    with pytest.raises(ValueError):
        service_receipts(receipts * 3)


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


@pytest.mark.parametrize("kind,command", [("OPEN", "open-orders"), ("HISTORY", "order-history")])
def test_order_pages_validate_before_helper_and_bind_pagination(monkeypatch, kind, command):
    from gym.adapters.wallex_order_evidence import InvalidOrderEvidence
    _, calls, helper = install(monkeypatch, envelope({"success": True, "result": {},
        "result_info": {"page": 2, "per_page": 10}}))
    reader = service.ServiceAccountReader()
    for page, count in ((0, 10), (1001, 10), (True, 10), (1, 101)):
        with pytest.raises(InvalidOrderEvidence):
            asyncio.run(reader.order_page(kind=kind, page=page, per_page=count))
    assert calls == []
    result = asyncio.run(reader.order_page(kind=kind, page=2, per_page=10))
    assert calls[0][0] == (str(helper), command, "2", "10")
    assert result["pagination_echo"] == "MATCHED" and not result["absence_proven"]
    install(monkeypatch, envelope({"success": True, "result": {},
        "result_info": {"page": 1, "per_page": 10}}))
    with pytest.raises(ReadUncertain, match="identity"):
        asyncio.run(reader.order_page(kind=kind, page=2, per_page=10))
