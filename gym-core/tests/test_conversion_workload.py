"""C2 conversion workload and implementation shortfall with deterministic fake fills."""
import pytest

from gym.domain.conversion import ConversionWorkload, ConversionUnsafe


def conversion(**kwargs):
    args = {
        "instruction_id": "conversion-one", "account": "main", "symbol": "BTCUSDT",
        "side": "BUY", "requested_base": "2",
        "arrival_price": "100", "fee_rate": "0.002",
        "started_at": "2026-11-01T08:00:00Z",
        "deadline": "2026-11-01T09:00:00Z",
        "max_spread_bps": "20", "quote_budget": "220",
    }
    args.update(kwargs)
    return ConversionWorkload(**args)


def test_fill_aware_conversion_shortfall_includes_fees_and_arrival():
    work = conversion()
    allowed = work.opportunity(
        observed_at="2026-11-01T08:00:04Z",
        bid="99.9", ask="100", quote_age_ms=50, venue_open=True,
    )
    assert allowed["state"] == "DRY_RUN_CANDIDATE"
    assert allowed["executable"] is False
    work.observe_fake_fill("fill-1", quantity="1", price="99", quote_fee="0.1",
                           observed_at="2026-11-01T08:01:00Z")
    work.observe_fake_fill("fill-2", quantity="1", price="102", quote_fee="0.2",
                           observed_at="2026-11-01T08:02:00Z")
    out = work.shortfall(mark_price="105", observed_at="2026-11-01T08:03:00Z")
    assert out["benchmark_quote"] == "200"
    assert out["filled_base"] == "2"
    assert out["unfilled_base"] == "0"
    assert out["execution_shortfall_quote"] == "1.3"
    assert out["fill_slippage_quote"] == "1"
    assert out["fees_quote"] == "0.3"
    assert out["unfilled_opportunity_quote"] == "0"
    assert out["state"] == "SYNTHETIC_FILLED_UNVERIFIED"
    assert out["settlement_verified"] is False
    assert out["funded_authority"] is False


def test_partially_unconverted_at_deadline_counts_opportunity_cost():
    work = conversion()
    work.observe_fake_fill("fill-1", quantity="1", price="99", quote_fee="0.1",
                           observed_at="2026-11-01T08:15:00Z")
    out = work.shortfall(mark_price="104", observed_at="2026-11-01T09:00:00Z")
    assert out["filled_base"] == "1" and out["unfilled_base"] == "1"
    assert out["fill_slippage_quote"] == "-1"
    assert out["fees_quote"] == "0.1"
    assert out["unfilled_opportunity_quote"] == "4"
    assert out["execution_shortfall_quote"] == "3.1"
    assert out["state"] == "SYNTHETIC_DEADLINE_UNFILLED"


def test_conversion_cannot_execute_when_stale_closed_over_spread_or_budget():
    work = conversion()
    conditions = [
        {"venue_open": False},
        {"quote_age_ms": 5000},
        {"bid": "98"},
    ]
    for change in conditions:
        params = {"observed_at": "2026-11-01T08:00:01Z", "bid": "99.9",
                  "ask": "100", "quote_age_ms": 10, "venue_open": True}
        params.update(change)
        result = work.opportunity(**params)
        assert result["state"] == "BLOCKED"
        assert result["executable"] is False
        assert result["funded_authority"] is False
    at_deadline = work.opportunity(observed_at="2026-11-01T09:00:00Z",
        bid="99.9", ask="100", quote_age_ms=10, venue_open=True)
    assert at_deadline["state"] == "BLOCKED"
    with pytest.raises(ConversionUnsafe, match="budget"):
        conversion(quote_budget="100")


def test_fake_fill_idempotency_is_exact_and_never_overfills():
    work = conversion()
    kw = dict(quantity="1", price="99", quote_fee="0.1",
              observed_at="2026-11-01T08:15:00Z")
    assert work.observe_fake_fill("fill-1", **kw) == 1
    assert work.observe_fake_fill("fill-1", **kw) == 1
    with pytest.raises(ConversionUnsafe, match="conflict"):
        work.observe_fake_fill("fill-1", **{**kw, "price": "100"})
    with pytest.raises(ConversionUnsafe, match="exceeds"):
        work.observe_fake_fill("fill-2", **{**kw, "quantity": "2"})
    assert work.shortfall(mark_price="103", observed_at="2026-11-01T08:30:00Z")["filled_base"] == "1"


def test_sell_conversion_shortfall_is_sign_reversed_and_base_scoped():
    w = conversion(side="SELL", quote_budget="1")
    w.observe_fake_fill("sell", quantity="2", price="97", quote_fee="0.3",
                        observed_at="2026-11-01T08:10:00Z")
    out = w.shortfall(mark_price="95", observed_at="2026-11-01T09:00:00Z")
    assert out["benchmark_quote"] == "200"
    assert out["fill_slippage_quote"] == "6"
    assert out["fees_quote"] == "0.3"
    assert out["execution_shortfall_quote"] == "6.3"


@pytest.mark.parametrize("change", [
    {"requested_base": 1.2},
    {"requested_base": "NaN"},
    {"requested_base": "-1"},
    {"arrival_price": "0"},
    {"started_at": "2026-11-01T09:00:00Z"},
    {"deadline": "2026-11-01T08:00:00Z"},
    {"side": "SHORT"},
    {"account": "https://evil.invalid"},
])
def test_unsupported_conversion_request_never_creates_a_workload(change):
    with pytest.raises((ConversionUnsafe, ValueError, TypeError)):
        conversion(**change)
