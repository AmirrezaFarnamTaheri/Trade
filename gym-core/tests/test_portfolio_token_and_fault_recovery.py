"""Portfolio attribution/ES tail qualification, token/margin reconciliation, and WAL/interrupted-restore safety (F014-F022, C005-C016, O009, O011)."""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from decimal import Decimal
from random import Random

import pytest

from gym.domain.model import InstrumentId
from gym.domain.portfolio_diagnostics import (
    aggregate_portfolio_trade_stats,
    economic_portfolio_attribution,
    portfolio_inventory_timeline,
    qualify_es_tail,
)
from gym.domain.sim import CostModel
from gym.domain.token_and_margin_audit import (
    evaluate_token_tradability,
    reconcile_1x_margin_vs_spot,
)
from gym.services.encrypted_backup import BackupAuthenticationError
from gym.services.portfolio import portfolio
from gym.services.research_backup import (
    backup_research,
    latest_snapshot,
    restore_research,
)
from tests.support import START, market_db, quote, quote_history

PHRASE = "correct horse battery staple"


def test_portfolio_trade_stats_timeline_attribution_and_es_tail_qualification(tmp_path):
    """F014, F015, F020, F022."""
    syms = ["BTCUSDT", "ETHUSDT"]
    rows = [top for s in syms for top in quote_history(n=120, turn=1, sym=s)]
    db = market_db(tmp_path, rows)
    spec = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1"}
    for s in syms:
        db.upsert_instrument(InstrumentId.wallex(s, s[:-4], "USDT"), {}, spec, "test", START)
    try:
        out = portfolio(
            db, syms, START, START + timedelta(minutes=25), resolution="1min", cash=Decimal(1000),
            cost=CostModel(fee_rate=Decimal("0.001"), max_fraction=Decimal("0.25")),
            params={"fast": 2, "slow": 3, "position_model": "inventory/1"},
        )
        agg = aggregate_portfolio_trade_stats(out)
        assert agg["basis"] == "ACTUAL_SHARED_ACCOUNT_FILLS"
        assert agg["closed_trades"] == agg["winning_trades"] + agg["losing_trades"] + agg["flat_trades"]

        tl = portfolio_inventory_timeline(out)
        assert len(tl) == 2 and {r["symbol"] for r in tl} == set(syms)

        attr = economic_portfolio_attribution(out)
        assert out["performance"]["economic_attribution"] == attr
        assert attr["reconciled"] is True and attr["reconciliation_residual"] == "0" and attr["causal_alpha_claim"] is False
        direction = attr["directional_attribution"]
        assert Decimal(direction["signed_fees_at_terminal_bid"]) < 0
        assert Decimal(direction["gross_directional_quote"]) + Decimal(direction["signed_fees_at_terminal_bid"]) == Decimal(attr["net_change"])
        out["result"]["end"]["equity"] = str(Decimal(attr["end_equity"]) + 1)
        assert economic_portfolio_attribution(out)["reconciled"] is False
        assert Decimal(economic_portfolio_attribution(out)["directional_attribution"]["unexplained_quote"]) == 1
        out["result"]["end"]["equity"] = attr["end_equity"]
        out["result"]["balances"][attr["currency"]] = str(Decimal(attr["end_cash"]) + 1)
        assert economic_portfolio_attribution(out)["reconciled"] is False
    finally:
        db.c.close()

    # ES/CVaR tail observation qualification (F022).
    rng = Random(7)
    short_sample = [rng.gauss(0.0, 0.02) for _ in range(50)]  # only 2 adverse tail observations at 5%
    es_short = qualify_es_tail(short_sample, alpha=0.05, min_tail_observations=10)
    assert es_short["status"] == "UNDERPOWERED_TAIL" and es_short["qualified"] is False and es_short["adverse_tail_count"] == 2

    long_sample = [rng.gauss(0.0, 0.02) for _ in range(300)]  # 15 tail obs >= 10
    es_long = qualify_es_tail(long_sample, alpha=0.05, min_tail_observations=10)
    assert es_long["status"] == "QUALIFIED_TAIL_SAMPLE" and es_long["qualified"] is True and es_long["adverse_tail_count"] == 15


def test_margin_1x_vs_spot_reconciliation_and_token_tradability_no_backfill():
    """C005, C013, C014, C015, C016."""
    rec = reconcile_1x_margin_vs_spot(
        spot_net_quote=Decimal("50.00"),
        margin_net_quote=Decimal("47.85"),
        margin_opening_fee=Decimal("1.50"),
        margin_extension_fees=Decimal("0.45"),
        trade_fee_diff=Decimal("0.20"),
    )
    assert rec["reconciled"] is True and rec["financing_and_fee_drag"] == "2.15"

    # Stale token (like AAPLXUSDT stopped 53 days ago) is flagged UNTRADEABLE_OR_STALE and never backfilled.
    stale_tok = evaluate_token_tradability(
        "AAPLXUSDT",
        latest_candle_day=START - timedelta(days=53),
        latest_quote=None,
        exit_qty=Decimal("1"),
        fee_rate=Decimal("0.001"),
        reference_proxy_price=Decimal("220"),
        now=START,
    )
    assert stale_tok["tradable"] is False
    assert "STALE_VENUE_CANDLES" in stale_tok["issues"]
    assert "MISSING_VENUE_QUOTE" in stale_tok["issues"]
    assert stale_tok["backfilled_from_proxy"] is False

    # Fresh tradable token computes exact Wallex premium vs proxy and checks depth.
    fresh_tok = evaluate_token_tradability(
        "XAUTUSDT",
        latest_candle_day=START - timedelta(days=1),
        latest_quote=quote(START - timedelta(seconds=30), "3820", "3840"),
        exit_qty=Decimal("0.1"),
        fee_rate=Decimal("0.001"),
        reference_proxy_price=Decimal("3800"),
        spec={"minNotional": "5"},
        now=START,
    )
    assert fresh_tok["tradable"] is True and Decimal(fresh_tok["wallex_premium_vs_proxy_bps"]) > 0


def test_active_wal_writer_preserves_append_only_triggers_and_interrupted_restore_keeps_backup_intact(tmp_path):
    """O009 & O011: nested WAL SQLite preserves append-only triggers; interrupted restore leaves backup usable."""
    root = tmp_path / "live"
    db = market_db(root, quote_history(n=10))
    db.c.close()

    # Nested append-only WAL database kept open by an active writer during backup (O009).
    nested = root / "nested" / "append_only.sqlite3"
    nested.parent.mkdir(parents=True)
    writer = sqlite3.connect(nested)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE log(id INTEGER PRIMARY KEY, msg TEXT)")
        writer.execute("CREATE TRIGGER log_no_del BEFORE DELETE ON log BEGIN SELECT RAISE(ABORT, 'append-only'); END")
        writer.execute("INSERT INTO log VALUES (1, 'committed-in-wal')")
        writer.commit()

        dest = tmp_path / "backup"
        dest.mkdir()
        first = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START)
        restored = tmp_path / "restored-ok"
        restore_research(dest, restored, passphrase=PHRASE, expected_manifest_sha256=first["manifest_sha256"])

        with sqlite3.connect(restored / "nested" / "append_only.sqlite3") as check:
            assert check.execute("SELECT msg FROM log").fetchall() == [("committed-in-wal",)]
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                check.execute("DELETE FROM log")
    finally:
        writer.close()

    # Simulate an interrupted/corrupted second snapshot while keeping the first snapshot valid (O011).
    second = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START + timedelta(days=1), keep=2)
    snap2 = latest_snapshot(dest)
    (snap2 / "market.db.tgfile").write_bytes(b"truncated-mid-write")
    with pytest.raises((BackupAuthenticationError, ValueError)):
        restore_research(dest, tmp_path / "failed-restore", passphrase=PHRASE, expected_manifest_sha256=second["manifest_sha256"])
    # Earlier valid snapshot remains completely restorable!
    snap1_id = first["snapshot"].replace("\\", "/").split("/")[-1]
    recovered = restore_research(dest, tmp_path / "recovered-snap1", passphrase=PHRASE,
                                 snapshot_id=snap1_id, expected_manifest_sha256=first["manifest_sha256"])
    assert recovered["manifest_status"] == "PINNED"
