"""C operator CLI must allow offline evidence, not secrets or funded orders."""
import json
from pathlib import Path

from gym.cli import main
from gym.services.probe_budget import ProbeBudgetBook


def test_probe_budget_cli_is_persistent_and_unable_to_raise_ceiling(tmp_path, capsys):
    request = {
        "probe_id": "manual-001", "kind": "CLIENT_ID_ECHO", "symbol": "BTCUSDT",
        "worst_case_total_loss": "0.25", "venue_minimum_quote": "0.20",
    }
    source = tmp_path / "safe.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    params = ["--data", str(tmp_path), "probe-budget-stage",
              "--total-loss-limit", "1.00", "--quote-asset", "USDT", str(source)]
    assert main(params) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["funded_authority"] is False
    assert report["client_id"] is None
    assert report["order_submitted"] is False
    with ProbeBudgetBook(tmp_path/"live"/"probe_budget.db",
                         total_loss_limit="1", quote_asset="USDT") as book:
        assert book.remaining() == "0.75"
    assert main(params) == 2
    assert main(["--data", str(tmp_path), "probe-budget-stage",
                 "--total-loss-limit", "2", "--quote-asset", "USDT", str(source)]) == 2


def test_conversion_report_cli_is_synthetic_only_and_never_accepts_secret(tmp_path, capsys):
    instruction = {
        "instruction_id": "c1", "account": "main", "symbol": "BTCUSDT",
        "side": "BUY", "requested_base": "2", "arrival_price": "100",
        "fee_rate": "0.002", "started_at": "2026-11-01T08:00:00Z",
        "deadline": "2026-11-01T09:00:00Z", "max_spread_bps": "20",
        "quote_budget": "220",
    }
    payload = {"instruction": instruction, "fills": [
        {"fill_id": "fake-1", "quantity": "1", "price": "99",
         "quote_fee": "0.1", "observed_at": "2026-11-01T08:10:00Z"},
    ], "mark_price": "104", "observed_at": "2026-11-01T09:00:00Z"}
    src = tmp_path / "fake.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["conversion-report", str(src)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["execution_shortfall_quote"] == "3.1"
    assert report["state"] == "SYNTHETIC_DEADLINE_UNFILLED"
    assert report["settlement_verified"] is False
    assert report["funded_authority"] is False

    payload["api_key"] = "UNSAFE_PRIVATE_KEY"
    src.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["conversion-report", str(src)]) == 2
    assert "UNSAFE_PRIVATE_KEY" not in repr(capsys.readouterr())


def test_cli_rejects_ambiguous_duplicate_json_fields(tmp_path):
    src = tmp_path / "ambiguous.json"
    src.write_text('{"probe_id":"a","probe_id":"b"}', encoding="utf-8")
    assert main(["--data", str(tmp_path), "probe-budget-stage",
                 "--total-loss-limit", "1", "--quote-asset", "USDT", str(src)]) == 2
