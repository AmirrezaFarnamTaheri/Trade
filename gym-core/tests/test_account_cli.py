import json
from types import SimpleNamespace

from gym.cli import account_cmd


def test_account_cli_uses_identity_bound_fill_fee_evidence(monkeypatch, capsys):
    import aiohttp
    from gym.adapters import secret_store, wallex_account_read

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {"headers": {"x-api-key": "fixture-read-key"}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    class Reader:
        def __init__(self, session):
            pass
        async def balances(self):
            return {"BTC": {"value": "0.999", "locked": "0"}}
        async def fee_rates(self):
            return {"BTCUSDT": {"maker": "0.001", "taker": "0.001"}}
        async def manual_order_evidence(self, client_id):
            assert client_id == "manual-1"
            return {"client_id": client_id, "raw_status": "FILLED", "symbol": "BTCUSDT",
                    "side": "BUY", "requested_qty": "1", "executed_qty": "1",
                    "fills": [{"quantity": "1", "price": "10", "fee": "0.001", "fee_asset": "BTC"}],
                    "fill_coverage": "REPORTED_QUANTITY_MATCHES", "settlement": "UNKNOWN", "money_authority": False}
        async def manual_order(self, client_id):
            raise AssertionError("the display-only parser must not supply C1 evidence")

    monkeypatch.setattr(secret_store, "load", lambda role: "fixture-read-key")
    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    monkeypatch.setattr(wallex_account_read, "WallexAccountReader", Reader)
    assert account_cmd(SimpleNamespace(order=["manual-1"], record=False)) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert "fixture-read-key" not in output
    assert result["funded_authority"] is False
    assert result["order_evidence"][0]["fills"][0]["fee_asset"] == "BTC"
    assert result["order_evidence"][0]["settlement"] == "UNKNOWN"
    assert result["orders"][0]["filled_observed"] == "1"
