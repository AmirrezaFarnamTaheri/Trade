"""Regression examples for Phase E's CodeRabbit review boundary conditions."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.execution_costs import modeled_execution_cost
from gym.domain.model import InstrumentId, TradeTick, iso
from gym.domain.sim import CostModel, Spec
from gym.services import fair_price
from gym.services.adaptive_twap import adaptive_twap
from gym.services.feed_divergence import evaluate_divergence, persist_paper_feed_lock
from gym.services.postfill import post_fill_checks
from gym.services.shadow_drift import shadow_drift
from tests.support import START, quote
from tests.test_phase_e_promotion import source

PROFILE = {"schema": "postfill-adverse/1", "symbol": "BTCUSDT",
           "trained_until": iso(START), "penalty_bps": "12",
           "sample_count": 30, "source": "PAPER_MARKOUT_DIAGNOSTIC"}


def top(offset, bid="99", ask="101"):
    """Qualified timestamped public book with displayed capacity for paper tests."""
    return replace(quote(START + timedelta(seconds=offset), bid, ask),
                   bid_qty=Decimal(10), ask_qty=Decimal(10))


@pytest.mark.parametrize("bad", [None, 5, []])
def test_postfill_costs_reject_invalid_cutoff_with_value_error(bad):
    """Malformed imported cost profiles cannot crash the research worker."""
    profile = {**PROFILE, "trained_until": bad}
    with pytest.raises(ValueError, match="invalid paper postfill costs"):
        CostModel(postfill_costs={"BTCUSDT": profile})
    with pytest.raises(ValueError, match="invalid paper postfill costs"):
        CostModel.from_description({**CostModel().describe(),
                                    "postfill_costs": {"BTCUSDT": profile}})


def test_limit_order_receipt_has_no_unapplied_postfill_price_penalty():
    """Maker limit fills cannot report an adverse uplift absent from their fill price."""
    cost = CostModel(postfill_costs={"BTCUSDT": PROFILE}, order_type="limit")
    at = START + timedelta(minutes=10)
    maker = modeled_execution_cost(cost, "BTCUSDT", at, Decimal(1),
                                   Decimal(99), Decimal(101), maker=True)
    taker = modeled_execution_cost(cost, "BTCUSDT", at, Decimal(1),
                                   Decimal(99), Decimal(101), maker=False)
    assert maker["uplift_bps"] == 0
    assert "postfill_adverse_bps" not in maker["pricing"]
    assert taker["uplift_bps"] == Decimal(12)
    assert taker["pricing"]["postfill_adverse_bps"] == "12"


def test_twap_reports_target_complete_instead_of_missing_volume():
    """An already fully filled parent has no reason to request later children."""
    trades_at = START - timedelta(seconds=10)
    report = adaptive_twap(
        InstrumentId.wallex("BTCUSDT"),
        [top(-1), top(1), top(61)],
        [TradeTick("BTCUSDT", trades_at, trades_at, Decimal(100), Decimal(100), "BUY")],
        Spec(qty_decimals=2), START, START + timedelta(minutes=2),
        side="BUY", quantity=Decimal(2), slices=2,
        participation=Decimal("0.5"), fee_rate=Decimal(0),
        available_quote=Decimal(1000), available_base=Decimal(0),
        max_delay_seconds=10, store="demo",
        volume_lookback_seconds=120, max_spread_bps=Decimal(300))
    assert Decimal(report["children"][0]["filled_quantity"]) == 2
    assert Decimal(report["children"][1]["requested_quantity"]) == 0
    assert report["children"][1]["status"] == "TARGET_COMPLETE"


def test_oversize_fair_price_journal_still_allows_reads_but_refuses_writes(tmp_path, monkeypatch):
    """A full append-only journal must not strand its historical price evidence."""
    path = tmp_path / "fair_price.sqlite3"
    payload = {"ts": iso(START), "prices": {"BTCUSDT": "100"}}
    with fair_price.FairPriceJournal(path) as journal:
        journal.record(payload, received_at=START + timedelta(seconds=10))
    monkeypatch.setattr(fair_price, "MAX_DB_BYTES", 1)
    with fair_price.FairPriceJournal(path) as journal:
        valuation = journal.valuation("BTCUSDT", as_of=START + timedelta(seconds=11))
        assert valuation["status"] == "FRESH_NON_EXECUTABLE"
        with pytest.raises(ValueError, match="size|full|limit"):
            journal.record(payload, received_at=START + timedelta(seconds=12))


def test_near_future_event_timestamp_respects_five_second_ingest_grace(tmp_path):
    """An event timestamp ahead of receipt by five seconds remains usable briefly."""
    with fair_price.FairPriceJournal(tmp_path / "fair_price_future.sqlite3") as journal:
        journal.record({"ts": iso(START + timedelta(seconds=5)),
                        "prices": {"BTCUSDT": "100"}},
                       received_at=START)
        row = journal.valuation("BTCUSDT", as_of=START + timedelta(seconds=1))
    assert row["status"] == "FRESH_NON_EXECUTABLE"
    assert row["executable_quote"] is False


def test_stale_fair_price_event_is_not_fresh_just_because_received_recently(tmp_path):
    """Receipt freshness does not turn an old public midpoint into an executable mark."""
    with fair_price.FairPriceJournal(tmp_path / "fair_price.sqlite3") as journal:
        journal.record({"ts": iso(START), "prices": {"BTCUSDT": "100"}},
                       received_at=START + timedelta(minutes=10))
        row = journal.valuation("BTCUSDT", as_of=START + timedelta(minutes=10, seconds=1))
    assert row["status"] == "STALE"
    assert row["derived_rate"] is None
    assert row["executable_quote"] is False


def test_missing_or_stale_feed_does_not_create_unjustified_divergence_lock():
    """Fail-closed advisory status alone is not measured divergence evidence."""
    report = evaluate_divergence([], [], symbol="BTCUSDT", as_of=START,
                                 training_samples=20, alert_sigma=3)
    assert report["block_entry"] is True
    assert report["status"] == "STALE_OR_UNAVAILABLE"
    with pytest.raises(ValueError, match="discrepancy"):
        persist_paper_feed_lock(None, report, now=START)


def test_postfill_profile_uses_fill_time_midpoint_not_already_paid_half_spread():
    """Stable mids yield zero adverse-cost uplift despite negative ask-price markouts."""
    orders = [{"status": "FILLED", "side": "BUY", "qty": "1", "price": "101",
               "fill_time": iso(START + timedelta(seconds=i)), "ref": str(i)}
              for i in range(30)]
    quotes = [top(0), top(329)]
    result = post_fill_checks(orders, quotes, symbol="BTCUSDT",
                              strategy="ema-trend", order_type="market",
                              cutoff=START + timedelta(minutes=6))
    assert Decimal(result["groups"][0]["horizons"]["300"]["mean_adverse_bps"]) > 0
    assert result["postfill_cost_profile"]["BTCUSDT"]["penalty_bps"] == "0"
    assert result["postfill_cost_profile"]["BTCUSDT"]["sample_count"] == 30
    # A fill with no price observation at or before its time cannot train the profile.
    missing = post_fill_checks(orders, [top(329)], symbol="BTCUSDT",
                                strategy="ema-trend", order_type="market",
                                cutoff=START + timedelta(minutes=6))
    assert missing["postfill_cost_profile"] is None


@pytest.mark.parametrize("bad", ["broken-equity", None])
def test_malformed_shadow_equity_mark_raises_validation_error(bad):
    """Invalid immutable-run marks must not terminate the bounded research worker."""
    historical = source(0, ["0.01", "-0.01"] * 12)
    shadow = source(25, ["-0.08", "0.01"], prospective=True)
    historical["result"]["curve"][0] = (iso(START), bad)
    with pytest.raises(ValueError, match="malformed shadow equity mark"):
        shadow_drift(historical, shadow, observed_at=START + timedelta(days=30))
