"""Fixed btc-daily-trend replay: exact postings, closed-price causality and its frozen window."""
import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from gym.services.data_portal import DataPortal
from tests.support import market_db

spec = importlib.util.spec_from_file_location("daily_trend_replay", Path(__file__).parents[1] / "scripts/daily_trend_replay.py")
replay_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_script)


def test_fixed_t6_uses_the_engine_and_exact_postings_without_a_terminal_entry(tmp_path):
    db = market_db(tmp_path, [])
    try:
        days = [(replay_script.SPLIT + timedelta(days=i - 50), Decimal(100 if i < 50 else 110 if i < 53 else 90)) for i in range(56)]
        out = replay_script.replay(DataPortal(db), days)
        result = out["result"]
        assert result["fills"] == 2
        assert [o["side"] for o in result["orders"]] == ["BUY", "SELL"]
        assert result["orders"][0]["decision_time"] == "2024-01-02T00:00:00.000000Z"
        assert all(Decimal(v) >= 0 for v in result["balances"].values())
        assert Decimal(result["balances"]["USDT"]) == sum(
            (Decimal(p["amount"]) for p in result["postings"] if p["ccy"] == "USDT"), Decimal(1000))
        assert Decimal(result["balances"]["BTC"]) == 0
        changed = replay_script.replay(DataPortal(db), [*days[:-1], (days[-1][0], Decimal(1000))])
        assert changed["result"]["orders"] == result["orders"]
        assert out["inputs"]["engine"] == replay_script.ENGINE_VERSION
    finally:
        db.c.close()


def test_bad_candle_data_cannot_create_a_replay():
    with pytest.raises(ValueError, match="51 positive"):
        replay_script.replay(None, [])
