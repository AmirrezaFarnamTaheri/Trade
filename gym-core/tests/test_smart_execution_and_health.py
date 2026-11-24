"""Unit tests for Side-Asymmetric Smart Execution Simulator, Operational Health Watchdog, and EnsembleGRU JSON export."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from gym.services.experiments.gru_engine import EnsembleGRU
from gym.services.experiments.operational_health import run_operational_health_check
from gym.services.experiments.smart_execution_sim import (
    _evaluate_symbol_orders,
    walk_orderbook_vwap,
)


def test_walk_orderbook_vwap_partial_and_full_depth() -> None:
    levels = [(100.0, 1.0), (101.0, 2.0)]  # $100 @ 100, $202 @ 101
    vwap_full, fill_full = walk_orderbook_vwap(levels, 201.0)
    assert fill_full == 1.0
    assert 100.4 < vwap_full < 100.6

    vwap_part, fill_part = walk_orderbook_vwap(levels, 604.0)
    assert abs(fill_part - 0.5) < 1e-6
    assert 100.5 < vwap_part < 100.8


def test_side_asymmetric_router_beats_wallex_taker_when_passive_buy_fills() -> None:
    t0 = 1_700_000_000.0
    matched = [
        {
            "epoch": t0,
            "w_mid": 100.0,
            "n_mid": 100.0,
            "w_bids": [(99.85, 50.0)],
            "w_asks": [(100.15, 50.0)],
            "n_bids": [(99.95, 50.0)],
            "n_asks": [(100.05, 50.0)],
        },
        {
            "epoch": t0 + 60.0,
            "w_mid": 99.90,
            "n_mid": 99.90,
            "w_bids": [(99.80, 50.0)],
            "w_asks": [(99.94, 50.0)],  # dips below Nobitex passive bid 99.95 -> fills!
            "n_bids": [(99.88, 50.0)],
            "n_asks": [(99.94, 50.0)],
        },
    ]
    res = _evaluate_symbol_orders(
        matched,
        symbol="BTCUSDT",
        notional=250.0,
        w_maker_bps=10.0,
        w_taker_bps=13.0,
        n_maker_bps=7.0,
        n_taker_bps=9.1,
    )
    assert res["buy"]["asym_router_bps"] < res["buy"]["wallex_taker_bps"]
    assert res["sell"]["smart_taker_bps"] < res["sell"]["wallex_taker_bps"]
    assert res["buy"]["passive_buy_fill_pct"] >= 50.0


def test_ensemble_gru_json_roundtrip_is_bit_accurate(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(30, 8, 4))
    y = (x[:, -1, 0] > 0).astype(np.float64)
    ens = EnsembleGRU(input_dim=4, hidden_dim=6, task="binary", seeds=(11, 22))
    ens.fit(x, y, epochs=3, batch_size=15, lr=5e-3)
    before = ens.predict(x[:5])

    out_path = tmp_path / "gru-v1.json"
    ens.save_json(out_path, metadata={"strategy": "IGN18_2H"})
    loaded, meta = EnsembleGRU.load_json(out_path)
    after = loaded.predict(x[:5])
    assert meta["strategy"] == "IGN18_2H"
    assert np.allclose(before, after, atol=1e-12)


def test_operational_health_watchdog_reports_ok_on_fresh_fixtures(tmp_path: Path) -> None:
    now = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
    live = tmp_path / "data" / "live"
    (live / "allocation").mkdir(parents=True)
    (live / "models").mkdir(parents=True)

    # Minimal fresh market.db
    mdb = sqlite3.connect(live / "market.db")
    mdb.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    mdb.execute("CREATE TABLE book_top (ts_avail TEXT)")
    mdb.execute("CREATE TABLE trades (ts_avail TEXT)")
    mdb.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t INTEGER)")
    mdb.execute("INSERT INTO instruments VALUES (1, 'BTCUSDT')")
    fresh_iso = (now - timedelta(minutes=2)).isoformat()
    mdb.execute("INSERT INTO book_top VALUES (?)", (fresh_iso,))
    mdb.execute("INSERT INTO trades VALUES (?)", (fresh_iso,))
    mdb.execute("INSERT INTO venue_candles VALUES (1, '1d', ?)", (int((now - timedelta(hours=4)).timestamp()),))
    mdb.execute("INSERT INTO venue_candles VALUES (1, '1h', ?)", (int((now - timedelta(hours=2)).timestamp()),))
    mdb.commit()
    mdb.close()

    # Minimal fresh multi_venue_quotes.sqlite3
    mv = sqlite3.connect(live / "multi_venue_quotes.sqlite3")
    mv.execute("CREATE TABLE venue_quotes (venue TEXT, symbol TEXT, ts_avail TEXT)")
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT"):
        mv.execute("INSERT INTO venue_quotes VALUES ('nobitex', ?, ?)", (s, fresh_iso))
    mv.commit()
    mv.close()

    # Fresh journals + frozen GRU weights
    for fn in ("s1-s5-leader-journal.jsonl", "champion-ensemble-journal.jsonl", "mix-journal-v2.jsonl"):
        (live / "allocation" / fn).write_text(json.dumps({"as_of": fresh_iso}) + "\n", encoding="utf-8")
    (live / "models" / "gru-ignition-v1.json").write_text(
        json.dumps({"schema": "ensemble-gru-weights/1", "n_models": 3, "models": []}), encoding="utf-8",
    )

    rep = run_operational_health_check(tmp_path / "data", tmp_path / "evidence", now=now)
    assert rep["overall_status"] == "OK"
    assert rep["executor_state"] == "DISARMED"
