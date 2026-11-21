"""Strict executable-net qualification, depth-walk liquidation, latency/queue/stop contracts (X001-X022)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from .bars import qualified
from .model import BookTop, TradeTick, iso

EVIDENCE_LADDER = (
    "DEMO_SYNTHETIC",
    "OBSERVED_PUBLIC_DATA",
    "MODELED_PAPER_REFERENCE",
    "HISTORICALLY_CONSTRAINED_PAPER",
    "REGISTERED_FORWARD_PAPER",
    "INDEPENDENTLY_RELEASED",
    "AUTHENTICATED_VENUE",
)


def _order_size_reasons(quantity, spec, price, depth_levels):
    reasons = []
    step = Decimal(1).scaleb(-int(spec["stepSize"]))
    rounded = quantity.quantize(step, rounding=ROUND_DOWN)
    if not rounded or rounded < Decimal(str(spec["minQty"])) or rounded * price < Decimal(str(spec["minNotional"])):
        reasons.append("BELOW_MIN_LOT_OR_NOTIONAL")
    if depth_levels is not None:
        available = sum((size for level, size in depth_levels if level.is_finite() and level > 0
                         and size.is_finite() and size > 0), Decimal(0))
        if available <= 0:
            reasons.append("EMPTY_DEPTH")
        elif available < rounded:
            reasons.append("PARTIAL_DEPTH_ONLY")
    return reasons


def qualify_executable_net(
    *,
    side: str,
    order_type: str,
    quantity: Decimal,
    spec: dict | None,
    fee_rate: Decimal | None,
    fee_source: str | None,
    quote: BookTop | None,
    depth_levels: tuple[tuple[Decimal, Decimal], ...] | None = None,
    is_zero_fee: bool = False,
    halted: bool | None = None,
    execution_at: datetime | None = None,
    market_status_at: datetime | None = None,
    max_evidence_age: timedelta = timedelta(seconds=120),
) -> dict:
    """Enforce strict executable-net gate: missing as-of inputs yield REFUSED/UNKNOWN, never implied fill (X001, X002)."""
    if side not in ("BUY", "SELL") or order_type not in ("MARKET", "LIMIT"):
        raise ValueError("side must be BUY/SELL and order_type MARKET/LIMIT")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        raise ValueError("quantity must be a positive finite Decimal")
    reasons = []
    if halted:
        reasons.append("MARKET_HALTED")
    if order_type == "MARKET":
        if execution_at is None:
            reasons.append("UNKNOWN_EXECUTION_TIME")
        if halted is None or market_status_at is None:
            reasons.append("UNKNOWN_MARKET_STATUS")
        elif execution_at is not None and not timedelta(0) <= execution_at - market_status_at <= max_evidence_age:
            reasons.append("UNKNOWN_AS_OF_MARKET_STATUS")
        if depth_levels is None:
            reasons.append("UNKNOWN_DISPLAYED_DEPTH")
    if not isinstance(spec, dict) or not {"stepSize", "minQty", "minNotional"} <= spec.keys():
        reasons.append("UNKNOWN_MARKET_SPEC")
    elif order_type == "MARKET" and spec.get("isMarketTypeEnable") is not True:
        reasons.append("MARKET_ORDER_DISABLED" if spec.get("isMarketTypeEnable") is False else "UNKNOWN_ORDER_TYPE_ELIGIBILITY")
    if not is_zero_fee and (fee_rate is None or not fee_source):
        reasons.append("UNKNOWN_FEE_VINTAGE")
    elif fee_rate is not None and (not fee_rate.is_finite() or not 0 <= fee_rate < 1):
        reasons.append("INVALID_FEE_RATE")
    if quote is None:
        reasons.append("MISSING_QUOTE")
    elif not qualified(quote):
        reasons.append("UNQUALIFIED_OR_STALE_QUOTE")
    elif execution_at is not None and not timedelta(0) <= execution_at - quote.ts_avail <= max_evidence_age:
        reasons.append("UNQUALIFIED_OR_STALE_QUOTE")
    if not reasons:
        price = quote.ask if side == "BUY" else quote.bid
        reasons.extend(_order_size_reasons(quantity, spec, price, depth_levels))
    if reasons:
        status = "UNKNOWN" if any(r.startswith("UNKNOWN_") or r == "MISSING_QUOTE" for r in reasons) else "REFUSED"
        return {"status": status, "qualified": False, "reasons": reasons, "evidence_tier": "UNQUALIFIED"}
    return {"status": "QUALIFIED", "qualified": True, "reasons": [], "evidence_tier": "HISTORICALLY_CONSTRAINED_PAPER"}


def depth_walk_liquidation(
    side: str,
    quantity: Decimal,
    depth_levels: tuple[tuple[Decimal, Decimal], ...] | list[tuple[Decimal, Decimal]] | None,
    *,
    fee_rate: Decimal,
    quote_at: datetime | None = None,
) -> dict:
    """Walk actual dated order-book levels without extrapolating past displayed depth (X009, X010, F013, F024)."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        raise ValueError("quantity must be a positive finite Decimal")
    if not isinstance(fee_rate, Decimal) or not fee_rate.is_finite() or not 0 <= fee_rate < 1:
        raise ValueError("fee_rate must be in [0, 1)")
    base_report = {
        "basis": "DEPTH_WALK_MODELED_LIQUIDATION",
        "side": side,
        "requested_qty": str(quantity),
        "quote_at": iso(quote_at) if quote_at else None,
        "authenticated_settlement": False,
    }
    if not depth_levels:
        return {**base_report, "status": "UNAVAILABLE", "filled_qty": "0", "residual_qty": str(quantity),
                "gross_quote": None, "modeled_fee_quote": None, "net_quote": None, "vwap": None, "levels_consumed": 0}
    remaining, gross, consumed = quantity, Decimal(0), 0
    with localcontext() as ctx:
        ctx.prec = 28
        for price, size in depth_levels:
            p, s = Decimal(str(price)), Decimal(str(size))
            if p <= 0 or s <= 0:
                continue
            take = min(remaining, s)
            gross += take * p
            remaining -= take
            consumed += 1
            if remaining == 0:
                break
        filled = quantity - remaining
        if filled <= 0:
            return {**base_report, "status": "UNAVAILABLE", "filled_qty": "0", "residual_qty": str(quantity),
                    "gross_quote": None, "modeled_fee_quote": None, "net_quote": None, "vwap": None, "levels_consumed": 0}
        fee = gross * fee_rate
        net = gross - fee if side == "SELL" else gross + fee
        return {
            **base_report,
            "status": "FULL" if remaining == 0 else "PARTIAL",
            "filled_qty": str(filled),
            "residual_qty": str(remaining),
            "gross_quote": str(gross),
            "modeled_fee_quote": str(fee),
            "net_quote": str(net),
            "vwap": str(gross / filled),
            "levels_consumed": consumed,
        }


def model_latency_phases(
    event_at: datetime,
    *,
    receive_ms: int,
    publish_ms: int,
    decide_ms: int,
    send_ms: int,
    ack_ms: int,
) -> dict:
    """Separate event -> receive -> publish -> decide -> send -> active clocks causally (X003, X004)."""
    legs = (receive_ms, publish_ms, decide_ms, send_ms, ack_ms)
    if any(type(v) is not int or v < 0 for v in legs):
        raise ValueError("latency phase durations must be nonnegative integers (ms)")
    received = event_at + timedelta(milliseconds=receive_ms)
    published = received + timedelta(milliseconds=publish_ms)
    decided = published + timedelta(milliseconds=decide_ms)
    sent = decided + timedelta(milliseconds=send_ms)
    active = sent + timedelta(milliseconds=ack_ms)
    return {
        "event_at": iso(event_at),
        "received_at": iso(received),
        "published_at": iso(published),
        "decided_at": iso(decided),
        "sent_at": iso(sent),
        "active_at": iso(active),
        "total_latency_ms": sum(legs),
    }


def maker_queue_fill(
    *,
    side: str,
    limit_price: Decimal,
    order_qty: Decimal,
    queue_ahead: Decimal,
    trades: list[TradeTick],
    active_at: datetime,
    cancel_effective_at: datetime | None = None,
    post_only: bool = True,
    best_opposite_price: Decimal | None = None,
) -> dict:
    """Conservative maker queue model with post-only guard, cancel race, and identical-print sensitivity (X005-X008)."""
    if side not in ("BUY", "SELL") or order_qty <= 0 or queue_ahead < 0:
        raise ValueError("invalid maker queue inputs")
    if post_only and best_opposite_price is not None:
        crosses = limit_price >= best_opposite_price if side == "BUY" else limit_price <= best_opposite_price
        if crosses:
            return {"status": "POST_ONLY_REJECTED", "filled_qty": "0", "remaining_qty": str(order_qty),
                    "unambiguous_filled_qty": "0", "ambiguous_print_qty": "0"}
    ahead, filled, ambiguous_qty = queue_ahead, Decimal(0), Decimal(0)
    seen_prints: set[tuple[datetime, Decimal, Decimal, str]] = set()
    unambiguous_ahead, unambiguous_filled = queue_ahead, Decimal(0)

    aggressor = "SELL" if side == "BUY" else "BUY"
    for tick in sorted(trades, key=lambda t: (t.ts_avail, t.ts_event)):
        if min(tick.ts_event, tick.ts_avail) < active_at or tick.aggressor != aggressor:
            continue
        if cancel_effective_at is not None and max(tick.ts_event, tick.ts_avail) >= cancel_effective_at:
            continue
        qualifies = tick.price <= limit_price if side == "BUY" else tick.price >= limit_price
        if not qualifies:
            continue
        key = (tick.ts_event, tick.price, tick.qty, tick.aggressor)
        is_duplicate_shape = key in seen_prints
        seen_prints.add(key)
        if is_duplicate_shape:
            ambiguous_qty += tick.qty
        # Total queue drain (all qualifying observed prints)
        drain = min(ahead, tick.qty)
        ahead -= drain
        leftover = tick.qty - drain
        if leftover > 0 and filled < order_qty:
            filled += min(order_qty - filled, leftover)
        # Adverse sensitivity: exclude indistinguishable duplicate-field prints (M004, X008)
        if not is_duplicate_shape:
            u_drain = min(unambiguous_ahead, tick.qty)
            unambiguous_ahead -= u_drain
            u_left = tick.qty - u_drain
            if u_left > 0 and unambiguous_filled < order_qty:
                unambiguous_filled += min(order_qty - unambiguous_filled, u_left)

    remaining = order_qty - filled
    status = "FILLED" if remaining == 0 else "PARTIAL_CANCELED" if (filled > 0 and cancel_effective_at) else (
        "PARTIAL" if filled > 0 else "CANCELED" if cancel_effective_at else "UNFILLED"
    )
    return {
        "status": status,
        "filled_qty": str(filled),
        "remaining_qty": str(remaining),
        "unambiguous_filled_qty": str(unambiguous_filled),
        "ambiguous_print_qty": str(ambiguous_qty),
        "queue_ahead_remaining": str(ahead),
    }


def simulate_trailing_stop(
    *,
    side: str,
    quantity: Decimal,
    trail_fraction: Decimal,
    trades: list[TradeTick],
    quotes: list[BookTop],
    fee_rate: Decimal,
    halted_at: datetime | None = None,
    activation_delay: timedelta = timedelta(0),
    reference_price: Decimal | None = None,
) -> dict:
    """Causal trailing-stop paper contract: non-guaranteed exit on gap, halt, or insufficient depth (X014, X016)."""
    if side != "SELL" or quantity <= 0 or not Decimal(0) < trail_fraction < Decimal(1):
        raise ValueError("trailing stop supports SELL with positive quantity and trail_fraction in (0, 1)")
    if activation_delay < timedelta(0):
        raise ValueError("activation_delay must be nonnegative")
    if reference_price is not None and (not reference_price.is_finite() or reference_price <= 0):
        raise ValueError("reference_price must be positive and finite")
    high_water = reference_price
    trigger_trade: TradeTick | None = None
    trigger_level = high_water * (Decimal(1) - trail_fraction) if high_water is not None else None

    for tick in sorted(trades, key=lambda t: (t.ts_avail, t.ts_event)):
        if halted_at is not None and tick.ts_avail >= halted_at:
            return {"model": "trailing-stop/1", "status": "HALTED_EXPOSED", "high_water": str(high_water) if high_water else None,
                    "trigger_level": str(trigger_level) if trigger_level else None, "unfilled_qty": str(quantity)}
        if high_water is None or tick.price > high_water:
            high_water = tick.price
            trigger_level = high_water * (Decimal(1) - trail_fraction)
        elif trigger_level is not None and tick.price <= trigger_level:
            trigger_trade = tick
            break

    if trigger_trade is None:
        return {"model": "trailing-stop/1", "status": "NOT_TRIGGERED",
                "high_water": str(high_water) if high_water else None,
                "trigger_level": str(trigger_level) if trigger_level else None, "unfilled_qty": str(quantity)}

    active_at = trigger_trade.ts_avail + activation_delay
    next_quote = min((q for q in quotes if q.symbol == trigger_trade.symbol
                      and q.ts_avail >= active_at and qualified(q)), key=lambda q: q.ts_avail, default=None)
    timing = {"triggered_at": iso(trigger_trade.ts_avail), "trigger_event_at": iso(trigger_trade.ts_event),
              "active_at": iso(active_at)}
    if halted_at is not None and (next_quote is None or next_quote.ts_avail >= halted_at):
        return {"model": "trailing-stop/1", "status": "HALTED_EXPOSED", **timing,
                "trigger_level": str(trigger_level), "unfilled_qty": str(quantity)}
    if next_quote is None:
        return {"model": "trailing-stop/1", "status": "TRIGGERED_NO_QUOTE",
                **timing, "trigger_price": str(trigger_trade.price),
                "trigger_level": str(trigger_level), "unfilled_qty": str(quantity)}

    levels = next_quote.depth[0] if next_quote.depth else None
    if levels is None and next_quote.bid_qty is not None and next_quote.bid_qty.is_finite():
        levels = ((next_quote.bid, next_quote.bid_qty),)
    liq = depth_walk_liquidation("SELL", quantity, levels, fee_rate=fee_rate, quote_at=next_quote.ts_avail)
    return {
        "model": "trailing-stop/1",
        "status": "FILLED" if liq["status"] == "FULL" else "PARTIAL_EXPOSED" if liq["status"] == "PARTIAL" else "TRIGGERED_UNFILLED",
        "high_water": str(high_water),
        "trigger_level": str(trigger_level),
        **timing,
        "trigger_price": str(trigger_trade.price),
        "liquidation": liq,
        "unfilled_qty": liq["residual_qty"],
    }


def paired_cost_ladder(scenarios: list[dict]) -> dict:
    """Summarize paired execution-cost scenarios without creating new selection trials (X019, X021, X022)."""
    if not scenarios:
        raise ValueError("at least one scenario is required")
    rows = []
    for item in scenarios:
        tier = item.get("evidence_tier")
        if tier not in EVIDENCE_LADDER:
            raise ValueError(f"unknown evidence tier: {tier}")
        rows.append({
            "name": item["name"],
            "evidence_tier": tier,
            "net_return": str(Decimal(str(item["net_return"]))),
            "max_drawdown": str(Decimal(str(item["max_drawdown"]))),
            "fill_fraction": str(Decimal(str(item["fill_fraction"]))),
            "residual_inventory": str(Decimal(str(item.get("residual_inventory", "0")))),
            "cost_drag_bps": str(Decimal(str(item.get("cost_drag_bps", "0")))),
        })
    return {"schema": "paired-cost-ladder/1", "creates_selection_trial": False, "scenarios": rows}


def venue_guard_transition_check(
    *,
    reference_price: Decimal | None,
    bid: Decimal | None,
    ask: Decimal | None,
    reference_age_s: float | None,
    max_age_s: float = 120.0,
    max_jump_bps: Decimal = Decimal("500"),
    depth_levels: tuple[tuple[Decimal, Decimal], ...] | None = None,
    halted: bool = False,
) -> dict:
    """Detect venue price-band discontinuities, stale surrogates, empty depth, and halts (X013)."""
    reasons = []
    if halted:
        reasons.append("MARKET_HALTED")
    if reference_price is None or reference_price <= 0:
        reasons.append("UNKNOWN_REFERENCE_PRICE")
    if reference_age_s is None or reference_age_s > max_age_s:
        reasons.append("STALE_REFERENCE_SURROGATE")
    if bid is None or ask is None or bid <= 0 or ask <= 0 or bid >= ask:
        reasons.append("INVALID_OR_CROSSED_QUOTE")
    if depth_levels is not None and sum((s for _, s in depth_levels), Decimal(0)) <= 0:
        reasons.append("EMPTY_DEPTH")
    jump_bps = None
    if reference_price and reference_price > 0 and bid and ask and bid < ask:
        mid = (bid + ask) / Decimal(2)
        jump_bps = (abs(mid - reference_price) / reference_price * Decimal("10000")).quantize(Decimal("0.01"))
        if jump_bps > max_jump_bps:
            reasons.append("REFERENCE_DISCONTINUITY")
    if reasons:
        status = "UNKNOWN" if any(r.startswith("UNKNOWN_") for r in reasons) else "REFUSED"
        return {"status": status, "pass": False, "reasons": reasons, "jump_bps": str(jump_bps) if jump_bps is not None else None}
    return {"status": "PASS", "pass": True, "reasons": [], "jump_bps": str(jump_bps)}


def build_fill_audit_trail(
    *,
    decision_at: datetime,
    symbol: str,
    side: str,
    order_type: str,
    requested_qty: Decimal,
    filled_qty: Decimal,
    fill_price: Decimal | None,
    fee_rate: Decimal | None,
    fee_source: str | None,
    rule_vintage_at: datetime | None,
    latency_phases: dict | None = None,
    matched_trade_count: int = 0,
    queue_ahead_remaining: Decimal | None = None,
    nonfill_reason: str | None = None,
    cash_postings: list[dict] | None = None,
) -> dict:
    """Emit a deterministic per-fill audit trail linking decision, vintage, queue, latency, and postings (X020)."""
    return {
        "schema": "fill-audit/1",
        "decision_cutoff": iso(decision_at),
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "requested_qty": str(requested_qty),
        "filled_qty": str(filled_qty),
        "fill_price": str(fill_price) if fill_price is not None else None,
        "fee_rate": str(fee_rate) if fee_rate is not None else None,
        "fee_source": fee_source or "UNKNOWN",
        "rule_vintage_at": iso(rule_vintage_at) if rule_vintage_at else None,
        "latency_phases": latency_phases,
        "matched_trade_count": matched_trade_count,
        "queue_ahead_remaining": str(queue_ahead_remaining) if queue_ahead_remaining is not None else None,
        "nonfill_reason": nonfill_reason,
        "cash_postings": list(cash_postings or []),
        "authenticated_venue_fill": False,
    }
