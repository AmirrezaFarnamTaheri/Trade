"""B1 private reader only permits explicit bounded GETs; no funded writes."""
import asyncio
import json
from contextlib import asynccontextmanager
from io import BytesIO

import pytest

from gym.adapters.wallex_account_read import WallexAccountReader, ReadUncertain


class Stream:
    def __init__(self, raw):
        self.raw = raw

    async def iter_chunked(self, chunk):
        for offset in range(0, len(self.raw), chunk):
            yield self.raw[offset:offset+chunk]


class Response:
    def __init__(self, status, data):
        self.status = status
        self.content = Stream(data)


class Session:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = json.dumps(data or {}).encode()
        self.paths = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.paths.append((url, kwargs))
        yield Response(self.status, self.data)


def run(coro):
    return asyncio.run(coro)


def test_read_only_fetches_balances_and_fails_on_unknown_shape():
    session = Session(data={"success": True, "result": {"USDT": {"value": "1.20", "locked": "0.1"}}})
    result = run(WallexAccountReader(session).balances())
    assert result == {"USDT": {"value": "1.20", "locked": "0.1"}}
    assert session.paths[0][0].endswith("/v1/account/balances")
    assert session.paths[0][1]["allow_redirects"] is False
    bad = Session(data={"success": True, "result": {"USDT": {"value": 1.2, "locked": "0.1"}}})
    with pytest.raises((TypeError, ValueError)):
        run(WallexAccountReader(bad).balances())


def test_read_only_manual_order_preserves_status_and_unverified_settlement():
    session = Session(data={"success": True, "result": {
        "status": "UNRECOGNIZED-WALLEX-STATUS", "filled": "0.001",
        "symbol": "BTCUSDT", "api_key": "SECRET-MUST-NOT-ECHO"}})
    result = run(WallexAccountReader(session).manual_order("outside-001"))
    assert result == {"client_id": "outside-001", "status": "UNRECOGNIZED-WALLEX-STATUS",
                      "filled": "0.001", "symbol": "BTCUSDT"}
    assert "SECRET-MUST-NOT-ECHO" not in str(result)
    assert session.paths[0][0].endswith("/v1/account/orders/outside-001")


def test_transport_errors_do_not_assert_order_absence_or_retry():
    for status in (301, 401, 404, 429, 500):
        session = Session(status=status)
        with pytest.raises(ReadUncertain):
            run(WallexAccountReader(session).manual_order("manual-1"))
        assert len(session.paths) == 1


def test_bounded_json_and_validated_order_id():
    session = Session(data={"success": True, "result": {}})
    with pytest.raises(ValueError):
        run(WallexAccountReader(session).manual_order("../../delete"))
    assert session.paths == []
    session.data = b'{"success":true,"result":{' + b"x" * 300000 + b"}}"
    with pytest.raises(ReadUncertain):
        run(WallexAccountReader(session, max_body=16384).balances())
    assert len(session.paths) == 1


def test_no_funded_operation_api_is_exposed():
    client = WallexAccountReader(Session())
    assert not any(hasattr(client, name) for name in ("post", "delete", "cancel_order", "place_order", "transfer"))
    with pytest.raises(ValueError):
        WallexAccountReader(Session(), base_url="http://evil.example")
