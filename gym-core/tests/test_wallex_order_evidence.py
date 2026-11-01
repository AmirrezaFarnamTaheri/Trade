"""Strict, read-only Wallex manual-order fill evidence; never settlement authority."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from gym.adapters.wallex_account_read import WallexAccountReader, ReadUncertain


class Stream:
    def __init__(self, data):
        self.data = data

    async def iter_chunked(self, size):
        for i in range(0, len(self.data), size):
            yield self.data[i:i + size]


class Response:
    def __init__(self, raw):
        self.status = 200
        self.content = Stream(raw)


class Session:
    def __init__(self, payload=None, raw=None):
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.requests = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        yield Response(self.raw)


def fetch(payload=None, *, raw=None, requested="manual-1"):
    session = Session(payload, raw)
    observation = asyncio.run(WallexAccountReader(session).manual_order_evidence(requested))
    return observation, session


def order(*, fills=None, executed="0.4", client_id="manual-1"):
    result = {
        "clientOrderId": client_id, "status": "PARTIALLY_FILLED",
        "symbol": "BTCUSDT", "side": "BUY", "origQty": "1",
        "executedQty": executed, "api_key": "SECRET-DO-NOT-COPY",
    }
    if fills is not None:
        result["fills"] = fills
    return {"success": True, "result": result, "token": "TOP-LEVEL-SECRET"}


def fill(quantity="0.4", fee="0.0002", asset="BTC"):
    return {
        "price": "25000.00", "quantity": quantity, "fee": fee,
        "feeAsset": asset, "timestamp": 1770000000,
        "isBuyer": True, "secretAccessKey": "SECRET-DO-NOT-COPY",
    }


def test_verified_identity_and_exact_fee_evidence_are_observational_only():
    result, session = fetch(order(fills=[fill()]))
    assert result == {
        "client_id": "manual-1", "raw_status": "PARTIALLY_FILLED",
        "symbol": "BTCUSDT", "side": "BUY", "requested_qty": "1",
        "executed_qty": "0.4", "fills": [
            {"quantity": "0.4", "price": "25000", "fee": "0.0002",
             "fee_asset": "BTC", "timestamp": 1770000000}
        ], "fill_coverage": "REPORTED_QUANTITY_MATCHES",
        "settlement": "UNKNOWN", "money_authority": False,
    }
    assert "SECRET" not in repr(result) and "TOP-LEVEL-SECRET" not in repr(result)
    assert len(session.requests) == 1
    assert session.requests[0][0] == "https://api.wallex.ir/v1/account/orders/manual-1"
    assert session.requests[0][1]["allow_redirects"] is False


def test_wrong_or_missing_order_identity_fails_closed():
    for requested in ("other", None, "", "MANUAL-1"):
        with pytest.raises(ReadUncertain, match="identity"):
            fetch(order(client_id=requested))
    with pytest.raises(ValueError):
        fetch(order(), requested="../../unsafe")


def test_absent_fill_details_never_imply_no_fees_or_settlement():
    result, _ = fetch(order())
    assert result["executed_qty"] == "0.4"
    assert result["fills"] == []
    assert result["fill_coverage"] == "UNVERIFIED"
    assert result["settlement"] == "UNKNOWN"
    assert result["money_authority"] is False


def test_inconsistent_or_malformed_fills_are_not_reconciled():
    for payload in [
        order(fills=[fill(quantity="0.2")]),
        order(fills=[fill(fee="-0.1")]),
        order(fills=[fill(quantity=0.4)]),  # float must not become exact money
        order(fills=[fill(asset="../../SECRET")]),
        order(fills=[fill()] * 257),
        order(fills={"fee": "0"}),
        order(fills=[fill(quantity="NaN")]),
    ]:
        with pytest.raises(ReadUncertain):
            fetch(payload)


def test_no_fills_and_zero_executed_quantity_are_unverified():
    result, _ = fetch(order(executed="0", fills=[]))
    assert result["fill_coverage"] == "UNVERIFIED"
    assert result["settlement"] == "UNKNOWN"


def test_duplicate_json_keys_are_rejected_instead_of_last_value_winning():
    data = b'{"success":false,"success":true,"result":{"status":"NEW"}}'
    with pytest.raises(ReadUncertain, match="duplicate|unreadable"):
        fetch(raw=data)
    nested = (b'{"success":true,"result":{"clientOrderId":"manual-1",'
              b'"status":"NEW","executedQty":"0","origQty":"1","symbol":"BTCUSDT",'
              b'"side":"BUY","api_key":"a","api_key":"b"}}')
    with pytest.raises(ReadUncertain, match="duplicate|unreadable"):
        fetch(raw=nested)


def test_order_fee_asset_must_be_observed_and_exact():
    for asset in ("", "BTC<script>", "BTC USD"):
        with pytest.raises(ReadUncertain):
            fetch(order(fills=[fill(asset=asset)]))
    with pytest.raises(ReadUncertain):
        fetch(order(fills=[fill(fee=float("inf"))]))


def test_partial_fill_fee_uses_actual_asset_not_quote_assumption():
    result, _ = fetch(order(fills=[fill(asset="USDT")]))
    assert result["fills"][0]["fee_asset"] == "USDT"
    assert result["settlement"] == "UNKNOWN"
