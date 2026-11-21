"""Outcome-perturbation no-peek invariants, journal idempotency, and SQLite lock resilience (E004, E006, E007, E015)."""
from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.adapters.store import MarketDB
from gym.domain.model import BookTop, InstrumentId
from gym.services.allocation import journal as alloc_journal
from gym.services.allocation import run_day
from gym.services.breadth_journal import journal as breadth_journal
from gym.services.breadth_journal import run_breadth_day
from gym.services.holdout_ledger import HoldoutLedger, HoldoutRefused
from gym.services.mix_journal import TOKENS, run_mix_day
from gym.services.mix_journal import journal as mix_journal
from gym.services.paper import paper
from gym.services.research_actions import review_runs
from gym.services.research_protocol import ResearchProtocol
from tests.support import START, market_db, quote, quote_history


def _proto_request():
    return {
        "symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
        "selection_end": (START - timedelta(minutes=10)).isoformat(),
        "test_from": START.isoformat(), "test_to": (START + timedelta(minutes=29)).isoformat(),
        "resolution": "1min", "cash": "1000", "fee_rate": "0.002",
    }


def test_unconsumed_protocol_and_cutoff_views_are_invariant_to_future_price_perturbation(tmp_path):
    """E004: shocking unreleased test-window prices cannot alter any unconsumed external output."""
    base_quotes = quote_history(n=180)
    shocked_quotes = [
        BookTop(q.symbol, q.ts_avail, q.bid * Decimal("5"), q.ask * Decimal("5"),
                q.bid_qty, q.ask_qty, q.flags, q.depth)
        if q.ts_avail >= START else q
        for q in base_quotes
    ]

    def run_unconsumed(root_name: str, rows: list[BookTop]):
        root = tmp_path / root_name
        db = market_db(root, rows)
        clock = {"at": START - timedelta(minutes=5)}
        try:
            with ResearchProtocol(root, clock=lambda: clock["at"]) as proto:
                registered = proto.register(_proto_request())
                key = registered["evaluation_id"]
                with pytest.raises(ValueError, match="not complete"):
                    proto.consume(key, db)
                eval_view = proto.evaluation(key)
                # Outcome record for an unreached horizon remains PENDING and reveals no post-cutoff data.
                saved = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
                save_run(saved, root / "runs")
                with pytest.raises(ValueError, match="cutoff"):
                    review_runs(root / "runs", [saved["run_id"]], as_of=START)
                pending = proto.record_outcome(saved["run_id"])
                outcomes_before = proto.outcomes(clock["at"])
                with pytest.raises(ValueError, match="future"):
                    proto.outcomes(START)
                return {
                    "registered": registered,
                    "evaluation": eval_view,
                    "pending_status": pending["status"],
                    "outcomes_before": outcomes_before,
                }
        finally:
            db.c.close()

    out_base = run_unconsumed("base", base_quotes)
    out_shock = run_unconsumed("shock", shocked_quotes)
    assert out_base == out_shock
    assert out_base["evaluation"]["state"] == "REGISTERED"
    assert out_base["pending_status"] == "PENDING"
    assert out_base["outcomes_before"]["outcomes"] == []


def test_holdout_overlap_blocks_shifted_shortened_and_revised_windows(tmp_path):
    """E006: shortened, shifted, or price-revised overlapping windows cannot create a fresh look."""
    with closing(HoldoutLedger(tmp_path / "holdout.sqlite3")) as ledger:
        first = ledger.look("w1", {"coverage": {"BTCUSDT": ["2024-01-01", "2024-06-30"]}}, 4, rescore=False)
        assert first["look"] == 1
        for label, window_key, span in [
            ("shortened", "w-short", ["2024-02-01", "2024-05-01"]),
            ("shifted-right", "w-shift", ["2024-06-30", "2024-12-31"]),
            ("shifted-left", "w-left", ["2023-10-01", "2024-01-01"]),
            ("revised-prices", "w-revised", ["2024-01-01", "2024-06-30"]),
        ]:
            with pytest.raises(HoldoutRefused, match="overlapping"):
                ledger.look(window_key, {"coverage": {"BTCUSDT": span}, "variant": label}, 3, rescore=False)
        # Disjoint later window is still allowed as a first look.
        disjoint = ledger.look("w-disjoint", {"coverage": {"BTCUSDT": ["2024-07-01", "2024-12-31"]}}, 2, rescore=False)
        assert disjoint["look"] == 1


def _seed_candles_for_concurrent_tests(tmp_path):
    day0 = datetime(2026, 8, 1, tzinfo=UTC)
    now = day0 + timedelta(days=80, hours=11, minutes=30)
    db = MarketDB(tmp_path / "market.db")
    symbols = list(dict.fromkeys(["BTCUSDT", *TOKENS.values(), "AAAUSDT", "BBBUSDT", "CCCUSDT"]))
    for idx, sym in enumerate(symbols):
        base = sym[:-4]
        db.upsert_instrument(InstrumentId.wallex(sym, base, "USDT"), {}, {}, "test", day0)
        rate = Decimal("1.008") if idx % 3 != 2 else Decimal("0.995")
        closes = [(Decimal(100) * rate ** i).quantize(Decimal("0.0001")) for i in range(80)]
        candles = [{"t": day0 + timedelta(days=i), "o": c, "h": c, "l": c, "c": c, "v": Decimal(200)}
                   for i, c in enumerate(closes)]
        db.upsert_candles(sym, "1d", candles, day0 + timedelta(days=80))
        last = closes[-1]
        db.add_book_top(BookTop(sym, now - timedelta(seconds=30), last, last * Decimal("1.001"),
                                Decimal(10), Decimal(10), frozenset()), None)
    db.c.commit()
    db.c.close()
    return tmp_path / "market.db", now


def test_concurrent_forward_journal_runs_append_exactly_one_entry_per_day(tmp_path):
    """E015: parallel invocations of allocation, mix, and breadth journals never duplicate a study day."""
    db_path, now = _seed_candles_for_concurrent_tests(tmp_path)
    root = tmp_path / "live"
    workers = 6

    def run_parallel(fn):
        barrier = threading.Barrier(workers)

        def call():
            local_db = MarketDB(db_path, readonly=True)
            try:
                barrier.wait(timeout=5)
                return fn(local_db)
            finally:
                local_db.c.close()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return [fut.result() for fut in [pool.submit(call) for _ in range(workers)]]

    alloc_results = run_parallel(lambda db: run_day(db, root, ["BTCUSDT"], now)[0])
    assert len(alloc_journal(root)) == 1
    assert sum(1 for r in alloc_results if r["status"] == "ALREADY_DECIDED") == workers - 1

    mix_results = run_parallel(lambda db: run_mix_day(db, root, now))
    assert len(mix_journal(root)) == 1
    assert sum(1 for r in mix_results if r["status"] == "ALREADY_DECIDED") == workers - 1

    breadth_results = run_parallel(lambda db: run_breadth_day(db, root, now))
    assert len(breadth_journal(root)) == 1
    assert sum(1 for r in breadth_results if r["status"] == "ALREADY_DECIDED") == workers - 1

    # Verify every JSONL file parses cleanly with no interleaved/torn lines.
    for rel in ("allocation/journal.jsonl", "allocation/mix-journal.jsonl", "allocation/breadth-journal.jsonl"):
        lines = [line for line in (root / rel).read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 1
        assert isinstance(json.loads(lines[0]), dict)


def test_market_db_busy_timeout_survives_transient_concurrent_writer_lock(tmp_path):
    """Regression for 2026-11-20 collector sqlite3.OperationalError: database is locked crash."""
    path = tmp_path / "market.db"
    setup = MarketDB(path)
    setup.c.close()

    locked = threading.Event()

    def hold_briefly():
        holder = sqlite3.connect(path, isolation_level=None)
        try:
            holder.execute("BEGIN IMMEDIATE")
            locked.set()
            threading.Event().wait(0.25)
            holder.commit()
        finally:
            holder.close()

    releaser = threading.Thread(target=hold_briefly)
    releaser.start()
    assert locked.wait(timeout=5)
    try:
        contender = MarketDB(path)
        try:
            assert contender.c.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000
            contender.add_book_top(quote(START, "100", "101"), None)
            contender.c.commit()
            assert contender.c.execute("SELECT count(*) FROM book_top").fetchone()[0] == 1
        finally:
            contender.c.close()
    finally:
        releaser.join(timeout=5)
