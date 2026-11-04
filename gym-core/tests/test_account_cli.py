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


def test_service_account_cli_never_loads_interactive_credentials(monkeypatch, capsys, tmp_path):
    import aiohttp
    from gym.adapters import secret_store, service_account_read
    from gym.cli import main
    from gym.services.external_journal import ExternalJournal

    def forbidden(*args, **kwargs):
        raise AssertionError("service reads must not load Python credentials or HTTP sessions")

    class Reader:
        async def balances(self):
            return {"BTC": {"value": "0.000000001", "locked": "0"}}

        async def fee_rates(self):
            return {"BTCUSDT": {"maker": "0.001", "taker": "0.001"}}

        async def manual_order_evidence(self, client_id):
            raise AssertionError("no order IDs requested")

    monkeypatch.setattr(secret_store, "load", forbidden)
    monkeypatch.setattr(aiohttp, "ClientSession", forbidden)
    monkeypatch.setattr(service_account_read, "ServiceAccountReader", Reader)
    assert main(["--data", str(tmp_path), "account", "--source", "service", "--record"]) == 0
    result = json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]
    assert result["transport"] == "EXECUTOR_SERVICE_WINHTTP"
    assert result["permission_status"] == "UNVERIFIED"
    assert result["funded_authority"] is False
    with ExternalJournal(tmp_path / "live" / "external_journal.db") as journal:
        snapshot = journal.latest_snapshot()
    assert snapshot["balances"][0]["venue_value"] == "0.000000001"
    assert snapshot["balances"][0]["spendable"] is None
    assert snapshot["fee_rates"]["BTCUSDT"]["taker"] == "0.001"
    assert snapshot["transport"] == "EXECUTOR_SERVICE_WINHTTP"
    assert snapshot["permission_status"] == "UNVERIFIED"
    assert snapshot["funded_authority"] is False


def test_service_account_failure_records_no_partial_observation(monkeypatch, capsys, tmp_path):
    from gym.adapters import service_account_read
    from gym.adapters.wallex_account_read import ReadUncertain
    from gym.cli import main

    class Reader:
        async def balances(self):
            return {"BTC": {"value": "1", "locked": "0"}}

        async def fee_rates(self):
            raise ReadUncertain("service account read unavailable")

    monkeypatch.setattr(service_account_read, "ServiceAccountReader", Reader)
    assert main(["--data", str(tmp_path), "account", "--source", "service", "--record"]) == 3
    assert "UNKNOWN" in capsys.readouterr().err
    assert not (tmp_path / "live" / "external_journal.db").exists()
