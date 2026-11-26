"""Regression and counterexample tests for the 2026-11-26 due-diligence remediation bundle."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from gym.domain.timeframe_panel import BarPoint
from gym.services.experiments.champion_forward_journal import (
    _resolve_event_prices,
    _validate_live_quote,
    append_jsonl_locked,
    score_champion_forward_journal,
)
from gym.services.experiments.gru_engine import (
    CompactGRU,
    EnsembleGRU,
    GRUArtifactError,
)
from gym.services.experiments.operational_health import run_operational_health_check
from gym.services.experiments.strategy_promotion_and_revival_study import (
    _run_bellman_exit_fork,
    _run_offline_research_gates,
    _write_markdown_report,
)
from gym.services.offline_review_journal import OfflineReviewJournal
from gym.services.research_process import ResearchProcessFailure, _sanitize_stderr_tail


def test_f01_mixed_engine_cohort_flagged_and_blocked_when_strict(tmp_path: Path) -> None:
    journal = tmp_path / "champion.jsonl"
    db = tmp_path / "missing.db"
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    rows = [
        {
            "slot_key": "2026-11-20|s1",
            "as_of": t0.isoformat(),
            "engine_digest": "digest_old",
            "gru_model_sha256": "sha_a",
            "blended_weights": {"BTCUSDT": 0.5},
            "live_quotes": {"BTCUSDT": {"nobitex_mid": 100.0, "nobitex_ts": t0.isoformat()}},
        },
        {
            "slot_key": "2026-11-21|s2",
            "as_of": (t0 + timedelta(days=1)).isoformat(),
            "engine_digest": "digest_new",
            "gru_model_sha256": "sha_a",
            "blended_weights": {"BTCUSDT": 0.5},
            "live_quotes": {"BTCUSDT": {"nobitex_mid": 110.0, "nobitex_ts": (t0 + timedelta(days=1)).isoformat()}},
        },
    ]
    journal.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    exploratory = score_champion_forward_journal(journal, db)
    assert exploratory["cohort_mixed"] is True
    assert exploratory["cohort_label"] == "EXPLORATORY_MIXED_COHORT"
    assert exploratory["engine_digests"] == ["digest_new", "digest_old"]

    strict = score_champion_forward_journal(journal, db, allow_mixed_cohorts=False)
    assert strict["status"] == "COHORT_MISMATCH"
    assert strict["cohort_mixed"] is True


def test_f02_terminal_nav_includes_final_rebalance_fee(tmp_path: Path) -> None:
    journal = tmp_path / "champion.jsonl"
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    rec = {
        "slot_key": "2026-11-20|s1",
        "as_of": t0.isoformat(),
        "engine_digest": "d1",
        "gru_model_sha256": "m1",
        "blended_weights": {"BTCUSDT": 1.0},
        "live_quotes": {"BTCUSDT": {"nobitex_mid": 100.0, "nobitex_ts": t0.isoformat()}},
    }
    journal.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    scored = score_champion_forward_journal(journal, tmp_path / "none.db", leg_fee_bps=100.0)
    assert scored["total_fees_usdt"] > 0.0
    assert scored["paper_nav"] < 1000.0
    assert abs(scored["paper_nav"] - (1000.0 - scored["total_fees_usdt"])) <= 0.15


def test_f03_stale_crossed_and_route_inconsistent_quotes_handled() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    # Crossed quote (bid >= ask) rejected
    assert _validate_live_quote("101", "100", now.isoformat(), ref_ts=now, max_quote_age_s=1800.0) is None
    # Stale quote rejected
    old_ts = (now - timedelta(hours=3)).isoformat()
    assert _validate_live_quote("99", "101", old_ts, ref_ts=now, max_quote_age_s=1800.0) is None

    # Route consistency: recommended_venue=wallex picks wallex_mid over nobitex_mid
    rec = {
        "live_quotes": {
            "BTCUSDT": {
                "recommended_venue": "wallex",
                "wallex_mid": 99.5,
                "wallex_ts": now.isoformat(),
                "nobitex_mid": 105.0,
                "nobitex_ts": now.isoformat(),
            },
            "ETHUSDT": {
                "recommended_venue": "nobitex",
                "nobitex_mid": 2500.0,
                "nobitex_ts": old_ts,  # stale -> must be ignored
            },
        }
    }
    px = _resolve_event_prices(rec, {}, now, max_quote_age_s=1800.0)
    assert px["BTCUSDT"] == pytest.approx(99.5)
    assert "ETHUSDT" not in px


def test_f04_os_released_lock_and_torn_tail_resilience(tmp_path: Path) -> None:
    journal = tmp_path / "champ.jsonl"
    # Pre-create an orphaned .lock file (would deadlock O_CREAT|O_EXCL forever)
    lock_file = journal.with_suffix(".jsonl.lock")
    lock_file.write_text("stale", encoding="utf-8")

    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    rec = {
        "slot_key": "s1",
        "as_of": t0.isoformat(),
        "blended_weights": {},
        "live_quotes": {},
    }
    assert append_jsonl_locked(journal, rec, timeout_s=2.0) is True
    assert append_jsonl_locked(journal, rec, timeout_s=2.0) is False

    # Append a torn trailing JSON line and ensure scorer survives and counts it
    with journal.open("a", encoding="utf-8") as fh:
        fh.write('{"slot_key": "torn_line\n')
    scored = score_champion_forward_journal(journal, tmp_path / "none.db")
    assert scored["status"] == "TRACKING"
    assert scored["corrupt_lines"] == 1
    assert scored["unique_slots"] == 1


def test_f05_f06_f07_operational_health_rejects_bad_models_future_ts_and_isolates_faults(tmp_path: Path) -> None:
    now = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
    live = tmp_path / "data" / "live"
    (live / "allocation").mkdir(parents=True)
    (live / "models").mkdir(parents=True)
    # Corrupt SQLite market.db file
    (live / "market.db").write_bytes(b"not-a-sqlite-db")
    # Future-dated journal entry
    future_iso = (now + timedelta(hours=2)).isoformat()
    (live / "allocation" / "champion-ensemble-journal.jsonl").write_text(
        json.dumps({"as_of": future_iso}) + "\n", encoding="utf-8"
    )
    # Empty models array (previously false-green)
    (live / "models" / "gru-ignition-v1.json").write_text(
        json.dumps({"schema": "ensemble-gru-weights/1", "n_models": 3, "models": []}), encoding="utf-8"
    )
    report_path = tmp_path / "health-report.json"

    rep = run_operational_health_check(tmp_path / "data", tmp_path / "evidence", report_path=report_path, now=now)
    assert report_path.is_file()
    assert rep["overall_status"] == "FAIL"
    assert rep["checks"]["market_db"]["status"] == "FAIL"
    assert rep["checks"]["champion_ensemble_journal"]["status"] == "FAIL"
    assert rep["checks"]["champion_ensemble_journal"]["future_timestamp_violation"] is True
    assert rep["checks"]["gru_ignition_model"]["status"] == "FAIL"


def test_f10_offline_review_journal_readonly_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "offline-reviews.sqlite3"
    with OfflineReviewJournal(db) as rw:
        assert rw.tickets() == []
    with OfflineReviewJournal(db, read_only=True) as ro:
        assert ro.tickets() == []
        assert ro.review_events() == []
        with pytest.raises(sqlite3.OperationalError):
            ro.conn.execute("CREATE TABLE should_fail (x INT)")


def test_f16_f18_bellman_sparse_schema_renders_without_keyerror(tmp_path: Path) -> None:
    bm = _run_bellman_exit_fork({}, [])
    assert bm["status"] == "INSUFFICIENT_DATA"
    assert bm["oos_evaluated_states"] == 0
    assert bm["oos_evaluated_lots"] == 0
    receipt = {
        "run_id": "test123",
        "generated_at_utc": datetime(2026, 11, 25, tzinfo=UTC).isoformat(),
        "exp1_conditional_capital_admission": {
            "arms": [],
            "contested_capital_fork": {
                "contested_slots": 0,
                "ignition_win_rate_pct": 0.0,
                "mean_ign_minus_slow_bps": 0.0,
            },
        },
        "exp2_standalone_internal_netting": {
            "crossed_events": 0,
            "crossed_notional_usdt": 0.0,
            "separate_routing_fees_usdt": 0.0,
            "internal_netting_fees_usdt": 0.0,
            "saved_fees_usdt": 0.0,
            "fee_reduction_pct": 0.0,
            "exposure_invariant_verified": True,
        },
        "exp3_partial_revivals": {
            "s2_retention_bands": [],
            "bellman_exit_fork": bm,
            "bear_buy_deferral_vs_cash": [],
            "accel_execution_speed": [],
        },
        "exp4_offline_research_gates": {
            "bar_offset_sensitivity": {},
            "hindsight_ceiling_2h_16bps": {},
        },
    }
    md = tmp_path / "report.md"
    _write_markdown_report(receipt, md)
    assert "INSUFFICIENT_DATA" in md.read_text(encoding="utf-8")


def test_f19_hindsight_dp_does_not_reinvest_before_sale() -> None:
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    bars = []
    # 20 bars where each bar opens at 100 and closes at 110 (+10% per bar, 0 fee).
    # Non-overlapping trades can capture +10% on every bar: 1000 * 1.1**20.
    # A buggy DP that funded entry at j open from dp[j] (after j close) would double-count bar j!
    for i in range(20):
        ts_s = t0 + timedelta(hours=2 * i)
        bars.append(
            BarPoint(
                symbol="BTCUSDT",
                ts_start=ts_s,
                ts_avail=ts_s + timedelta(hours=2),
                open=100.0,
                high=110.0,
                low=100.0,
                close=110.0,
                volume=10.0,
                bar_source="test",
                clock_complete=True,
                nonzero_volume_fraction=1.0,
                last_trade_age_bars=0,
                entry_eligible=True,
                mark_status="LIVE",
            )
        )
    out = _run_offline_research_gates({"BTCUSDT": []}, {"BTCUSDT": bars}, {}, leg_cost=0.0)
    expected = round(1000.0 * (1.1**20), 2)
    assert out["hindsight_ceiling_2h_16bps"]["BTCUSDT"]["hindsight_max_nav_usdt"] == pytest.approx(expected, abs=0.05)


def test_e01_gru_artifact_validation_and_safe_abstention(tmp_path: Path) -> None:
    ens = EnsembleGRU(input_dim=4, hidden_dim=3, task="binary", seeds=(42,))
    good_path = tmp_path / "good.json"
    ens.save_json(good_path)
    loaded, _ = EnsembleGRU.load_json(good_path)
    preds, err = loaded.predict_safe(np.zeros((1, 5, 4)))
    assert err is None and preds is not None

    # NaN input triggers structured abstention
    bad_preds, bad_err = loaded.predict_safe(np.full((1, 5, 4), np.nan))
    assert bad_preds is None and bad_err is not None

    # Corrupt artifact: zero feat_std rejected
    payload = ens.to_dict()
    payload["models"][0]["feat_std"][0] = 0.0
    with pytest.raises(GRUArtifactError):
        EnsembleGRU.from_dict(payload)

    # Corrupt artifact: empty models rejected
    with pytest.raises(GRUArtifactError):
        EnsembleGRU.from_dict({"schema": "ensemble-gru-weights/1", "n_models": 0, "models": []})

    # Corrupt artifact: NaN weight rejected
    bad_m = CompactGRU(4, 3).to_dict()
    bad_m["params"]["Wo"][0][0] = float("nan")
    with pytest.raises(GRUArtifactError):
        CompactGRU.from_dict(bad_m)


def test_e04_research_process_stderr_sanitization() -> None:
    tail = _sanitize_stderr_tail(b"  Traceback:\n  ValueError: bad state\n")
    assert tail == "Traceback: ValueError: bad state"
    exc = ResearchProcessFailure("failed", terminated=True, exit_code=2, stderr_tail=tail)
    assert exc.exit_code == 2
    assert exc.stderr_tail == tail
    assert exc.report["exit_code"] == 2
