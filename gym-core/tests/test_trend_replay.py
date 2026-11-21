import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.trend_replay import trend_replay


def packet():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(270):
        bid = Decimal(100 + i + i % 3)
        rows.append(dict(at=(start + timedelta(days=i)).isoformat(), bid=str(bid), ask=str(bid + Decimal(".01"))))
    return dict(symbol="BTCUSDT", quote_currency="USDT", cash="10000", fee_rate="0.0005",
                band="0.05", quantity_step="0.1", minimum_quote="10", observations=rows)


def test_cli_books_daily_spot_costs_and_compares_cash(tmp_path, capsys):
    path = tmp_path / "trend.json"
    path.write_text(json.dumps(packet()))
    assert main(["--data", str(tmp_path / "data"), "research", "trend-replay", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    first = report["decisions"][0]
    leg, = first["legs"]
    assert first["execution_at"] > first["signal_at"]
    assert leg["status"] == "PLANNED" and Decimal(leg["gross_quantity"]) % Decimal(".1") == 0
    assert Decimal(report["fees_quote"]) > 0 and Decimal(report["turnover_quote"]) > 0
    last = report["decisions"][-1]
    assert Decimal(last["cash"]) + Decimal(last["held"]) * Decimal(packet()["observations"][-1]["bid"]) == Decimal(report["terminal_bid_equity"])
    assert Decimal(report["terminal_bid_equity"]) - Decimal(report["excess_quote"]) == Decimal(report["cash_benchmark"]) == 10000
    assert not report["registered_trial"] and not (tmp_path / "data").exists()


def test_replay_prefix_cost_and_dust():
    data = packet()
    now = datetime.now(UTC)
    full = trend_replay(data, now)
    assert trend_replay({**data, "observations": data["observations"][:-3]}, now)["decisions"] == full["decisions"][:-3]
    blocked = trend_replay({**data, "fee_rate": "0.02"}, now)
    assert all(d["sizing"] == "BLOCKED_COST_OF_SPEED" for d in blocked["decisions"])
    dust = trend_replay({**data, "minimum_quote": "10001"}, now)
    assert dust["turnover_quote"] == "0" and dust["decisions"][0]["legs"][0]["status"] == "BELOW_MINIMUM"
    del data["observations"][10]
    with pytest.raises(ValueError, match="consecutive"):
        trend_replay(data, now)
