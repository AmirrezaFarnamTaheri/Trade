"""Cost defaults require dated observable evidence, without hiding model uncertainty."""
from datetime import timedelta
from decimal import Decimal

import pytest

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
    assert cost.for_market("BTCUSDT").fee_rate == Decimal("0.0018")
    zero = cost.for_market("BTCUSDT", zero_fee=True)
    assert zero.fee_rate == zero.maker_fee == 0
    assert zero.from_description(zero.describe()) == zero


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


def test_historical_replay_cannot_use_calibration_published_after_its_start(tmp_path):
    """A later account or feed receipt cannot be used as a historical cost input."""
    observed = START + timedelta(minutes=30)
    _receipts(tmp_path, observed)
    out = calibrated_cost(tmp_path, "BTCUSDT", order_type="limit", now=START)
    assert out.describe()["fee_rate"] == "0.001"
    assert out.describe()["latency_ms"] == 500
    assert "calibration" not in out.describe()


@pytest.mark.parametrize(("override", "value", "maker", "taker"), [
    ("fee", "0.003", "0.0002", "0.003"),
    ("maker_fee", "0.0015", "0.0015", "0.0009"),
])
def test_one_fee_override_preserves_the_other_rate_per_market(tmp_path, override, value, maker, taker):
    with ExternalJournal(tmp_path / "external_journal.db") as journal:
        journal.record(project_account("main", iso(START), balances={"USDT": {"value": "10", "locked": "0"}}),
                       fee_rates={"BTCUSDT": {"maker": "0.0007", "taker": "0.0018"},
                                  "ETHUSDT": {"maker": "0.0002", "taker": "0.0009"}},
                       transport="INTERACTIVE_USER_GET")
    cost = calibrated_cost(tmp_path, "BTCUSDT", order_type="limit", now=START, **{override: value})
    effective = cost.for_market("ETHUSDT")
    assert (effective.maker_fee, effective.fee_rate) == (Decimal(maker), Decimal(taker))


def test_synthetic_feed_does_not_set_live_latency(tmp_path):
    at = START + timedelta(hours=1)
    save_calibration(tmp_path, {
        "feed": {"last_receipt": iso(at), "negative_samples": 0,
                 "by_symbol": {"BTCUSDT": {"n": 40, "p90": 750}}},
        "paper_fills": {"fills": 0}, "synthetic": True,
    }, at=at)
    assert calibrated_cost(tmp_path, "BTCUSDT", now=at).latency == timedelta(milliseconds=500)


def test_replay_freezes_only_start_known_zero_fee_and_reports_effective_account_rate(tmp_path):
    from gym.domain.model import InstrumentId
    from gym.domain.sim import CostModel
    from gym.services.paper import paper
    from tests.support import market_db, quote_history

    db = market_db(tmp_path, quote_history(n=150))
    options = {"resolution": "1min", "params": {"fast": 2, "slow": 3},
               "cost": CostModel(market_fees={"BTCUSDT": {"maker": "0.0005", "taker": "0.002"}})}
    try:
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {}, {"isZeroFee": False}, "test", START - timedelta(seconds=1))
        before = paper(db, "BTCUSDT", START, START + timedelta(minutes=25), **options)
        assert before["result"]["effective_cost"]["fee_rate"] == "0.002"
        assert Decimal(before["result"]["end"]["waterfall"]["fees"]) < 0
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {}, {"isZeroFee": True}, "test", START + timedelta(minutes=1))
        later = paper(db, "BTCUSDT", START, START + timedelta(minutes=25), **options)
        assert later["result"]["end"] == before["result"]["end"]
        db.c.execute("UPDATE instrument_specs SET spec=? WHERE valid_from=?", ('{"isZeroFee":true}', iso(START - timedelta(seconds=1))))
        zero = paper(db, "BTCUSDT", START, START + timedelta(minutes=25), **options)
        assert zero["result"]["effective_cost"]["zero_fee"] is True
        assert Decimal(zero["result"]["end"]["waterfall"]["fees"]) == 0
        assert zero["run_id"] != before["run_id"]
    finally:
        db.c.close()
