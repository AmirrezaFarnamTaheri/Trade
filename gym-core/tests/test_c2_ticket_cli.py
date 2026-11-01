"""C2 safe preview CLI only; never constructs a funded order."""
import json

from gym.cli import main


def test_c2_ticket_preview_cli_is_dry_run_only(tmp_path, capsys):
    params = {
        "symbol": "BTCUSDT", "side": "BUY", "intent": "ENTRY",
        "quantity": "0.01", "bid": "100", "ask": "101", "worst_price": "103",
        "fee_rate": "0.002", "operator_quote_cap": "2", "available_quote": "2",
        "available_base": "0", "minimum_quote": "1",
        "observed_at": "2026-11-01T08:00:00Z",
        "expires_at": "2026-11-01T08:00:30Z", "snapshot_seq": 5, "quote_age_ms": 10,
    }
    inp = tmp_path / "preview.json"
    inp.write_text(json.dumps(params), encoding="utf-8")
    assert main(["ticket-preview", str(inp)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "DRY_RUN" and out["funded_authority"] is False
    assert out["client_id"] is None
    assert out["order_submitted"] is False
    params["api_key"] = "SECRET-MUST-NEVER-APPEAR"
    inp.write_text(json.dumps(params), encoding="utf-8")
    assert main(["ticket-preview", str(inp)]) == 2
    captured = capsys.readouterr()
    assert "SECRET-MUST-NEVER-APPEAR" not in captured.err + captured.out
