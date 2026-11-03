"""C2 dry-run order ticket semantics; never grants real venue money authority."""
import copy

import pytest

from gym.domain.assisted_ticket import (
    TicketUnsafe, OfflineTicketQueue, prepare_preview,
)


def valid(**changes):
    data = {
        "symbol": "BTCUSDT", "side": "BUY", "intent": "ENTRY",
        "quantity": "0.01", "bid": "100", "ask": "101",
        "worst_price": "103", "fee_rate": "0.002",
        "operator_quote_cap": "2", "available_quote": "2",
        "available_base": "0", "minimum_quote": "1",
        "observed_at": "2026-11-01T08:00:00Z",
        "expires_at": "2026-11-01T08:00:30Z",
        "snapshot_seq": 5, "quote_age_ms": 10,
    }
    data.update(changes)
    return data


def test_buy_preview_exact_decimal_worst_cost_and_non_executable_authority():
    p = prepare_preview(**valid())
    assert p["estimated_gross_quote"] == "1.01"
    assert p["worst_gross_quote"] == "1.03"
    assert p["worst_fee_quote"] == "0.00206"
    assert p["worst_total_quote"] == "1.03206"
    assert p["break_even_bid"] == "103.412826"
    assert p["client_id"] is None
    assert p["funded_authority"] is False
    assert p["mode"] == "DRY_RUN"
    assert len(p["preview_sha256"]) == 64
    assert prepare_preview(**valid())["preview_sha256"] == p["preview_sha256"]


def test_sell_exit_preview_respects_base_availability_and_not_entry_cap():
    p = prepare_preview(**valid(side="SELL", intent="EXIT",
        quantity="2", available_base="2", operator_quote_cap="1",
        bid="100", ask="101", worst_price="98", minimum_quote="1"))
    assert p["worst_total_quote"] == "195.608"
    assert p["funded_authority"] is False
    assert p["side"] == "SELL"
    with pytest.raises(TicketUnsafe, match="base"):
        prepare_preview(**valid(side="SELL", intent="EXIT", quantity="3",
            available_base="2", worst_price="98"))


@pytest.mark.parametrize("change", [
    {"quantity": 0.5},
    {"quantity": "-1"},
    {"quantity": "NaN"},
    {"quantity": "Infinity"},
    {"fee_rate": "0.999"},
    {"quote_age_ms": 3000},
    {"worst_price": "100"},  # BUY worst cannot be better than current ask
    {"bid": "101", "ask": "100"},  # crossed feed / invalid quote
    {"operator_quote_cap": "1"},
    {"available_quote": "1"},
    {"minimum_quote": "100"},
    {"expires_at": "2026-11-01T07:59:00Z"},
    {"expires_at": "2026-11-01T08:10:00Z"},
    {"snapshot_seq": 0},
    {"side": "POST"},
    {"intent": "EXIT"},
])
def test_untrusted_or_stale_ticket_inputs_fail_closed(change):
    with pytest.raises((TicketUnsafe, ValueError, TypeError)):
        prepare_preview(**valid(**change))


def test_review_queue_can_acknowledge_or_reject_only_an_offline_preview():
    p = prepare_preview(**valid())
    queue = OfflineTicketQueue()
    key = queue.add(p)
    assertion = queue.review(key, "ACKNOWLEDGE", at="2026-11-01T08:00:10Z")
    assert assertion["state"] == "ACKNOWLEDGED"
    assert assertion["funded_authority"] is False
    assert assertion["order_submitted"] is False
    assert not hasattr(queue, "submit")
    assert not hasattr(queue, "place_order")
    assert not hasattr(queue, "approve_live")
    with pytest.raises(TicketUnsafe):
        queue.review(key, "ACKNOWLEDGE", at="2026-11-01T08:00:11Z")


def test_review_queue_rejects_mutated_tickets_and_expired_reviews():
    p = prepare_preview(**valid())
    altered = copy.deepcopy(p)
    altered["worst_total_quote"] = "0"
    with pytest.raises(TicketUnsafe, match="integrity"):
        OfflineTicketQueue().add(altered)
    queue = OfflineTicketQueue()
    ident = queue.add(p)
    with pytest.raises(TicketUnsafe, match="expired"):
        queue.review(ident, "ACKNOWLEDGE", at="2026-11-01T08:00:30Z")
    # A genuine rejection remains offline and does not create a venue order.
    assert queue.review(ident, "REJECT", at="2026-11-01T08:00:15Z")["state"] == "REJECTED"

def test_decimal_multiplication_never_silently_rounds_extreme_precisions():
    ticket = prepare_preview(**valid(
        quantity="1.000000000000000001",
        bid="1", ask="1.000000000000000001",
        worst_price="1.000000000000000001",
        fee_rate="0.000000000000000001",
        operator_quote_cap="2", available_quote="2", minimum_quote="1",
    ))
    assert ticket["worst_gross_quote"] == "1.000000000000000002000000000000000001"
    assert ticket["worst_fee_quote"] == "0.000000000000000001000000000000000002000000000000000001"
    assert ticket["worst_total_quote"] == "1.000000000000000003000000000000000003000000000000000001"
