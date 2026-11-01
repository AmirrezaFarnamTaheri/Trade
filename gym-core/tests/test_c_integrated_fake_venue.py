"""C1 -> C2 -> C3 synthetic integration; no route creates a venue order."""
import hashlib

from gym.services.venue_facts import VenueFactsJournal
from gym.services.probe_budget import ProbeBudgetBook
from gym.domain.assisted_ticket import prepare_preview
from gym.services.offline_review_journal import OfflineReviewJournal
from gym.domain.conversion import ConversionWorkload
from gym.domain.shadow_autopilot import ShadowAutopilot
from gym.domain.reopening import ReopeningWindow


def test_offline_c_series_end_to_end_never_elevates_to_funded(tmp_path):
    with VenueFactsJournal(tmp_path/"facts.db") as facts:
        facts.record({
            "evidence_id": "dry-run-balance-1", "observed_at": "2026-11-01T08:00:00Z",
            "source": "SYNTHETIC_FIXTURE", "kind": "BALANCES",
            "endpoint": "ACCOUNT_BALANCES", "state": "OBSERVED",
            "account_scope": "main", "response_version": "v1",
            "evidence_sha256": hashlib.sha256(b"fake").hexdigest(),
        })
        assert facts.capabilities()["read_only_account"]["state"] == "EVIDENCE_ONLY"
        assert facts.capabilities()["venue_probe"]["state"] == "NOT_CERTIFIED"
        assert facts.capabilities()["autopilot"]["state"] == "BLOCKED"

    with ProbeBudgetBook(tmp_path/"budget.db", total_loss_limit="2", quote_asset="USDT") as budget:
        staged = budget.stage(
            probe_id="manual-probe-1", kind="CLIENT_ID_ECHO", symbol="BTCUSDT",
            worst_case_total_loss="1", venue_minimum_quote="0.5",
        )
        assert staged["order_submitted"] is False
        assert staged["client_id"] is None

    ticket = prepare_preview(
        symbol="BTCUSDT", side="BUY", intent="ENTRY", quantity="0.01",
        bid="100", ask="101", worst_price="103", fee_rate="0.002",
        operator_quote_cap="2", available_quote="2", available_base="0",
        minimum_quote="1", observed_at="2026-11-01T08:00:00Z",
        expires_at="2026-11-01T08:00:30Z", snapshot_seq=5, quote_age_ms=10,
    )
    with OfflineReviewJournal(tmp_path/"reviews.db") as queue:
        key = queue.record(ticket)
        ack = queue.review(key, "ACKNOWLEDGE", at="2026-11-01T08:00:10Z")
        assert ack["tier1_approval"] is False
        assert ack["order_submitted"] is False
        assert queue.tickets()[0]["state"] == "ACKNOWLEDGED_OFFLINE"

    conv = ConversionWorkload(
        instruction_id="convert-1", account="main", symbol="BTCUSDT",
        side="BUY", requested_base="0.01", arrival_price="100",
        fee_rate="0.002", started_at="2026-11-01T08:00:00Z",
        deadline="2026-11-01T08:01:00Z", max_spread_bps="20",
        quote_budget="2",
    )
    conv.observe_fake_fill(
        "fill-1", quantity="0.01", price="101", quote_fee="0.00202",
        observed_at="2026-11-01T08:00:15Z",
    )
    report = conv.shortfall(mark_price="105", observed_at="2026-11-01T08:00:20Z")
    assert report["execution_source"] == "FAKE_VENUE_ONLY"
    assert report["settlement_verified"] is False

    shadow = ShadowAutopilot(
        workload_id="single", account="main", runtime_epoch=2,
        total_cap_quanta=200, per_order_cap_quanta=100,
    )
    shadow.arm_shadow(2)
    entry = shadow.stage_entry(
        intent="synthetic-intent", instrument="BTCUSDT", budget_quanta=100,
        verified_available_quanta=200, runtime_epoch=2,
        qualified_quote=True, venue_open=True,
    )
    assert entry["client_id"] is None and entry["funded_authority"] is False
    crash = shadow.restart(new_runtime_epoch=3)
    assert crash.mode == "DISARMED"
    assert crash.pending_intents() == ["synthetic-intent"]
    assert crash.protection_state == "UNAVAILABLE"

    reopen = ReopeningWindow(
        instrument="BTCUSDT", policy="SELL_AT_REOPEN",
        quote_count=1, runtime_epoch=3,
    )
    out = reopen.observe(
        sequence=1, quote_age_ms=5, venue_open=True,
        unit_epoch_verified=True, no_unknown_orders=False, runtime_epoch=3,
    )
    assert out["reopening_advisory"] == "BLOCKED"
    assert out["funded_authority"] is False
