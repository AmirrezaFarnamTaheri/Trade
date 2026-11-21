"""Trial governance, two-trial budget, release bundles, analyst peeks, alert escalation, and safe CSV export."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from gym.services import alerts
from gym.services.csv_export import export_csv, safe_export_filename, sanitize_cell
from gym.services.evidence import trials
from gym.services.trial_governance import (
    build_release_bundle,
    enforce_two_trial_budget,
    journal_continuity_report,
    record_analyst_peek,
)


def test_two_trial_budget_rejects_third_active_trial_without_supersession():
    """E022: current trial-log has 2 OPEN forward trials; a 3rd requires explicit supersession."""
    live_rows = trials()
    open_ids = [r["id"] for r in live_rows if r["verdict"] == "OPEN"]
    assert len(open_ids) == 2

    with pytest.raises(ValueError, match="trial budget full"):
        enforce_two_trial_budget(live_rows, "new-maker-imbalance")

    # Superseding one active trial is explicitly permitted and documented.
    sup = enforce_two_trial_budget(live_rows, "new-maker-imbalance", supersedes=open_ids[0])
    assert sup["allowed"] and sup["superseded"] == open_ids[0] and len(sup["active_trials"]) == 2

    # Superseding a non-active trial fails closed.
    with pytest.raises(ValueError, match="non-active"):
        enforce_two_trial_budget(live_rows, "new-maker-imbalance", supersedes="nonexistent-trial")


def test_release_bundle_binds_digests_and_retains_aborted_or_failed_outcomes():
    """E008, E009, E018: immutable release bundle binds code/data digests and requires reasons for aborts."""
    at = datetime(2027, 2, 8, 12, 0, tzinfo=UTC)
    bundle = build_release_bundle(
        evaluation_id="eval-001",
        family_id="funding-confirmed-trend",
        code_commit_sha="8fba0b15115b617067fc93b9c9769c9351472900",
        engine_digest="a" * 64,
        data_digest="b" * 64,
        family_attempts_total=14,
        sample_count=82,
        missing_count=2,
        pass_criterion={"dsr_min": 0.95},
        verdict="FAIL",
        custodian="external-ci-runner",
        independent_custody=True,
        released_at=at,
    )
    assert len(bundle["bundle_sha256"]) == 64
    assert bundle["funded_authority"] is False
    assert bundle["family_attempts_total"] == 14

    with pytest.raises(ValueError, match="failure_reason"):
        build_release_bundle(
            evaluation_id="eval-002", family_id="fam", code_commit_sha="sha", engine_digest="e",
            data_digest="d", family_attempts_total=1, sample_count=0, missing_count=10,
            pass_criterion={}, verdict="ABORTED", custodian="local", independent_custody=False,
        )


def test_analyst_peek_log_records_oos_exposure_and_forbids_prose_as_evidence(tmp_path):
    """E021: human or AI peeks into OOS packets are durably logged."""
    entry = record_analyst_peek(
        tmp_path, analyst="agent-audit", family_id="breadth-trend-forward",
        source_packet="data/live/allocation/breadth-journal.jsonl",
        date_from="2026-11-17", date_to="2026-11-20", saw_candidate_oos=False,
        note="continuity audit only",
    )
    assert entry["prose_is_evidence"] is False
    lines = (tmp_path / "analyst_peeks.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["family_id"] == "breadth-trend-forward"


def test_journal_continuity_distinguishes_gaps_stale_quotes_and_checks_decimal_parity(tmp_path):
    """E010, E016, E017: missing calendar days and accounting mismatches are explicitly surfaced."""
    alloc_dir = tmp_path / "allocation"
    alloc_dir.mkdir(parents=True)
    # Day 1 buys 2 BTC at 100 + 0.2 fee -> quote=799.8, base=2; Day 3 skips Day 2 (gap) with no quote.
    e1 = {
        "symbol": "BTCUSDT", "day": "2026-11-15T00:00:00.000000Z", "at": "2026-11-16T00:15:00Z",
        "status": "READY", "holdings": {"base": "2", "quote": "799.8"}, "equity": "999.8",
        "quote": {"bid": "99.9", "ask": "100", "at": "2026-11-16T00:14:00Z"},
        "fill": {"side": "BUY", "qty": "2", "price": "100", "fee": "0.2"},
    }
    e2 = {
        "symbol": "BTCUSDT", "day": "2026-11-17T00:00:00.000000Z", "at": "2026-11-18T00:15:00Z",
        "status": "READY", "holdings": {"base": "2", "quote": "799.8"}, "equity": "1020",
        "quote": None,
    }
    (alloc_dir / "journal.jsonl").write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")

    rep = journal_continuity_report(tmp_path, now=datetime(2026, 11, 20, 0, 0, tzinfo=UTC))
    btc = rep["btc_daily_trend"]
    assert btc["evidence_status"] == "GAP_DETECTED"
    assert btc["missing_days_in_span"] == 1
    assert btc["missing_days_through_yesterday"] == 2
    assert btc["stale_or_nonready_days"] == 1
    assert btc["invented_zero_returns"] is False
    assert btc["accounting_parity"]["status"] == "OK"

    # Mutate holdings without a fill -> parity check catches the mismatch.
    e2_bad = {**e2, "holdings": {"base": "2", "quote": "999.8"}}
    (alloc_dir / "journal.jsonl").write_text(json.dumps(e1) + "\n" + json.dumps(e2_bad) + "\n", encoding="utf-8")
    bad = journal_continuity_report(tmp_path, now=datetime(2026, 11, 20, 0, 0, tzinfo=UTC))
    assert bad["btc_daily_trend"]["accounting_parity"]["status"] == "MISMATCH"


def test_alerts_escalate_when_outage_duration_or_disk_pressure_worsens(tmp_path, monkeypatch):
    """M020, O022: worsening outage age or shrinking disk runway triggers fresh escalation despite same WARN label."""
    sent = []
    monkeypatch.setattr(alerts, "toast", lambda title, body: sent.append((title, body)) or True)

    def make_rep(detail_feed: str, detail_disk: str = "25.0 GiB free"):
        return {
            "as_of": "2026-11-20T00:00:00+00:00",
            "status": "WARN",
            "checks": [
                {"check": "collector_feed", "status": "WARN", "detail": detail_feed},
                {"check": "free_space", "status": "WARN", "detail": detail_disk},
            ],
        }

    # Initial 15 min outage -> sent once; 30 min stays in same tier -> suppressed.
    assert alerts.notify(make_rep("newest quote 15 min old"), tmp_path)["sent"] is True
    assert alerts.notify(make_rep("newest quote 30 min old"), tmp_path)["sent"] is False
    # Crossing 60 min (1h+), 360 min (6h+), and 1440 min (24h+) MUST escalate!
    assert alerts.notify(make_rep("newest quote 75 min old"), tmp_path)["sent"] is True
    assert alerts.notify(make_rep("newest quote 400 min old"), tmp_path)["sent"] is True
    assert alerts.notify(make_rep("newest quote 1500 min old"), tmp_path)["sent"] is True
    # Shrinking free disk below 10 GiB escalates too!
    assert alerts.notify(make_rep("newest quote 1510 min old", "9.2 GiB free"), tmp_path)["sent"] is True
    assert len(sent) == 5


def test_csv_export_neutralizes_formula_injection_and_preserves_exact_decimals():
    """O020: spreadsheet formulas are neutralized while exact signed Decimals and currency remain intact."""
    assert sanitize_cell("=CMD|' /C calc'!A0") == "'=CMD|' /C calc'!A0"
    assert sanitize_cell("+HYPERLINK(\"http://x\")") == "'+HYPERLINK(\"http://x\")"
    assert sanitize_cell("@SUM(A1:A2)") == "'@SUM(A1:A2)"
    assert sanitize_cell("-123.4500") == "-123.4500"
    assert sanitize_cell(Decimal("-0.00000123")) == "-0.00000123"

    csv_text = export_csv(
        [{"symbol": "BTCUSDT", "note": "=1+1", "pnl": Decimal("-12.34567890")}],
        ["symbol", "note", "pnl"],
        currency="USDT",
    )
    assert "symbol,note,pnl,currency\n" in csv_text
    assert "BTCUSDT,'=1+1,-12.34567890,USDT\n" in csv_text

    assert safe_export_filename("paper_run-01.csv") == "paper_run-01.csv"
    for bad in ("../evil.csv", "a/b.csv", "export.exe", "=bad.csv"):
        with pytest.raises(ValueError, match="unsafe CSV"):
            safe_export_filename(bad)
