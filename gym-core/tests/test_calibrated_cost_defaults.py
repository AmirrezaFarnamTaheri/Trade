"""Phase A cost defaults require dated observable evidence, without hiding model uncertainty."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.account_observations import project_account
from gym.domain.model import iso
from gym.services.cost_defaults import calibrated_cost, save_calibration
from gym.services.external_journal import ExternalJournal
from tests.support import START


def _receipts(root, at):
    with ExternalJournal(root / "external_journal.db") as journal:
        journal.record(project_account("main", iso(at), balances={"USDT": {"value": "10", "locked": "0"}}),
                       fee_rates={"BTCUSDT": {"maker": "0.0007", "taker": "0.0018"}},
                       transport="INTERACTIVE_USER_GET")
    report = {
        "feed": {"last_receipt": iso(at), "negative_samples": 0,
                 "by_symbol": {"BTCUSDT": {"n": 30, "p50": 150, "p90": 325, "p99": 470}}},
        "paper_fills": {"fills": 30, "latency_drift_bps": {"n": 30, "p90": 50}},
        "synthetic": False,
    }
    saved = save_calibration(root, report, at=at)
    assert saved == save_calibration(root, report, at=at)
    return saved


def test_recent_account_maker_taker_and_feed_latency_are_distinct_and_dated(tmp_path):
    at = START + timedelta(minutes=30)
    _receipts(tmp_path, at)
    cost = calibrated_cost(tmp_path, "BTCUSDT", order_type="limit", now=at + timedelta(minutes=1))
    assert cost.fee_rate == Decimal("0.0018")
    assert cost.maker_fee == Decimal("0.0007")
    assert cost.latency == timedelta(milliseconds=325)
    evidence = cost.describe()["calibration"]
    assert evidence["fee_observed_at"] == iso(at)
    assert evidence["feed_observed_at"] == iso(at)
    assert evidence["slippage_status"] == "NOT_INDEPENDENTLY_MEASURED"
    assert not evidence["independent_order_latency"]
    assert "calibration" in cost.from_description(cost.describe()).describe()


def test_explicit_flags_win_and_stale_or_demo_data_cannot_change_defaults(tmp_path):
    at = START + timedelta(minutes=30)
    _receipts(tmp_path, at)
    old = calibrated_cost(tmp_path, "BTCUSDT", now=at + timedelta(days=2))
    assert old.describe() == {"fee_rate": "0.001", "latency_ms": 500, "max_wait_s": 60.0,
                              "fee_assumption": "fee-in-received-asset"}
    explicit = calibrated_cost(tmp_path, "BTCUSDT", fee="0.003", maker_fee="0.0015",
                               latency_ms=700, now=at + timedelta(minutes=1), order_type="limit")
    assert explicit.fee_rate == Decimal("0.003")
    assert explicit.maker_fee == Decimal("0.0015")
    assert explicit.latency == timedelta(milliseconds=700)
    assert "calibration" not in explicit.describe()
    other = calibrated_cost(tmp_path, "ETHUSDT", now=at + timedelta(minutes=1))
    assert "calibration" not in other.describe()


def test_synthetic_feed_does_not_set_live_latency(tmp_path):
    at = START + timedelta(hours=1)
    save_calibration(tmp_path, {
        "feed": {"last_receipt": iso(at), "negative_samples": 0,
                 "by_symbol": {"BTCUSDT": {"n": 40, "p90": 750}}},
        "paper_fills": {"fills": 0}, "synthetic": True,
    }, at=at)
    assert calibrated_cost(tmp_path, "BTCUSDT", now=at).latency == timedelta(milliseconds=500)
