"""Regressions in honest measurement: fee provenance, calibration choice and trial-ledger safety."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from gym.domain.account_observations import project_account
from gym.domain.model import iso
from gym.services.attribution import toman_attribution
from gym.services.cost_defaults import calibrated_cost, save_calibration
from gym.services.data_quality_gate import quote_coverage
from gym.services.external_journal import ExternalJournal
from gym.services.research_actions import research_action
from gym.services.spa import scorecard_spa
from gym.services.trial_ledger import TrialLedger
from tests.support import START, market_db, quote_history


def test_extreme_fx_attribution_does_not_raise_after_rounding():
    out = {"mode": "PAPER", "result": {"quote": "TMN", "start_cash": "1",
                                      "end": {"equity": "10000"}},
           "fx": {"start": "100", "end": "1"}}
    value = toman_attribution(out)
    assert value["status"] == "AVAILABLE"
    assert (Decimal(value["usdt_return"]) + Decimal(value["toman_move"])
            + Decimal(value["interaction"])) == Decimal(value["total_toman_return"])


def test_historical_fee_observation_survives_later_snapshot(tmp_path):
    first = START + timedelta(minutes=30)
    second = first + timedelta(minutes=10)
    with ExternalJournal(tmp_path / "external_journal.db") as journal:
        for at, fee in ((first, "0.0018"), (second, "0.0030")):
            journal.record(project_account(
                "main", iso(at), balances={"USDT": {"value": "10", "locked": "0"}}),
                fee_rates={"BTCUSDT": {"maker": "0.0007", "taker": fee}},
                transport="INTERACTIVE_USER_GET")
    observed = calibrated_cost(tmp_path, "BTCUSDT", fee=None, latency_ms=500,
                               now=first + timedelta(minutes=1))
    assert observed.fee_rate == Decimal("0.0018")
    assert observed.describe()["calibration"]["fee_observed_at"] == iso(first)


def test_explicit_market_fee_does_not_read_or_change_fee_provenance(tmp_path):
    (tmp_path / "external_journal.db").write_bytes(b"not a valid journal")
    explicit = calibrated_cost(tmp_path, "BTCUSDT", fee="0.002", latency_ms=500,
                               order_type="market", now=START)
    assert explicit.fee_rate == Decimal("0.002")
    assert "calibration" not in explicit.describe()
    fallback = calibrated_cost(tmp_path, "BTCUSDT", latency_ms=500,
                               order_type="market", now=START)
    assert fallback.fee_rate == Decimal("0.001")
    assert "calibration" not in fallback.describe()


def test_newest_calibration_wins_after_500_irrelevant_receipts(tmp_path):
    directory = tmp_path / "cost_calibrations"
    directory.mkdir()
    for i in range(500):
        (directory / f"00000{i:04d}.json").write_text("{}", encoding="utf-8")
    at = START + timedelta(hours=1)
    save_calibration(tmp_path, {
        "feed": {"last_receipt": iso(at), "negative_samples": 0,
                 "by_symbol": {"BTCUSDT": {"n": 30, "p90": 123}}},
        "paper_fills": {"fills": 0}, "synthetic": False,
    }, at=at)
    cost = calibrated_cost(tmp_path, "BTCUSDT", fee="0.002", latency_ms=None, now=at)
    assert cost.latency == timedelta(milliseconds=123)


def test_invalid_portfolio_quality_threshold_does_not_count_as_trial(tmp_path):
    from tests.test_portfolio_workflow import request

    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    db.c.close()
    bad = {**request(), "quality_max_bad_share": "nonsense"}
    try:
        research_action(tmp_path, "portfolio-replay", bad)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid quality threshold accepted")
    with TrialLedger(tmp_path) as ledger:
        assert ledger.count(symbol="BTCUSDT,ETHUSDT", start=START,
                            end=START + timedelta(minutes=30), hypothesis="ad-hoc") == 0


def test_trial_ledger_initialization_is_safe_for_concurrent_workers(tmp_path):
    barrier = Barrier(2)

    def worker(i):
        barrier.wait()
        with TrialLedger(tmp_path) as ledger:
            return ledger.record(symbol="BTCUSDT", start=START,
                                 end=START + timedelta(minutes=30),
                                 hypothesis="parallel", source="paper", config_hash=str(i))

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(worker, range(2)))
    assert sorted(row["trials"] for row in attempts) == [1, 2]


def test_quote_coverage_reuses_rules_across_decision_buckets(tmp_path, monkeypatch):
    from gym.services.rules import RuleService

    db = market_db(tmp_path, quote_history(n=180))
    original = RuleService.load
    calls = []

    def counting(self, at=None):
        calls.append(at)
        return original(self, at)

    monkeypatch.setattr(RuleService, "load", counting)
    try:
        result = quote_coverage(db, "BTCUSDT", START, START + timedelta(minutes=30), "1min")
        assert result["eligible_buckets"] == 30
        assert len(calls) == 1
    finally:
        db.c.close()


def test_spa_discloses_unverified_candidates_in_family():
    rows = [{"window": "w1", "scenario": "default", "attempt_id": f"a{i}", "trial": i}
            for i in range(3)]
    report = scorecard_spa(rows, verified={})
    assert report[0]["status"] == "INSUFFICIENT_COMPARABLE_DATA"
    assert report[0]["registered_candidates"] == 3
