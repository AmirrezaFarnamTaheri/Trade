"""Arrival-state passive matching, pegged child orders & O(1) adversarial print bound (spec §4.2)."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import BookTop, TradeTick
from .venue_contracts import FeeSchedule

DUPLICATE_MODES = ("optimistic", "deduplicated", "adversarial_lower_bound")


@dataclass(frozen=True)
class PassiveOrderSpec:
    order_id: str
    symbol: str
    side: str                         # "BUY" | "SELL"
    qty: Decimal
    limit_price: Decimal
    sent_at: datetime
    post_only: bool = True
    max_wait_s: float = 300.0
    send_latency_ms: int = 250
    cancel_latency_ms: int = 250
    repeg_offset_bps: Decimal | None = None
    repeg_cooldown_s: float = 15.0
    max_repegs: int = 0
    allow_quote_cross_fill: bool = False


@dataclass(frozen=True)
class PassiveFill:
    order_id: str
    symbol: str
    side: str
    ts_fill: datetime
    price: Decimal
    qty: Decimal
    liquidity_role: str               # "MAKER" | "TAKER"
    fee_rate: Decimal
    fee_amount: Decimal
    fee_asset: str                    # "BASE" | "QUOTE"
    from_ambiguous_duplicate: bool


@dataclass(frozen=True)
class PassiveOrderResult:
    order_id: str
    symbol: str
    side: str
    status: str                       # "FILLED" | "PARTIAL" | "UNFILLED" | "POST_ONLY_REJECTED" | "UNCERTAIN_CANCEL"
    duplicate_print_mode: str
    requested_qty: Decimal
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    total_fee_base: Decimal
    total_fee_quote: Decimal
    ambiguous_filled_qty: Decimal
    repeg_count: int
    fills: tuple[PassiveFill, ...]
    completed_at: datetime


def _latest_top_at_or_before(books: list[BookTop], ts: datetime, book_ts: list[datetime] | None = None) -> BookTop | None:
    if not books:
        return None
    if book_ts is not None:
        idx = bisect_right(book_ts, ts) - 1
        return books[idx] if idx >= 0 else None
    best: BookTop | None = None
    for b in books:
        if b.ts_avail <= ts:
            best = b
        else:
            break
    return best


def _post_fill_markout_bps(
    side: str,
    fill_price: Decimal,
    ts_fill: datetime,
    books: list[BookTop],
    horizon_s: int = 300,
    book_ts: list[datetime] | None = None,
) -> Decimal | None:
    """Strict post-fill markout: requires ts_avail >= ts_fill + horizon_s within min(horizon_s, 60)s."""
    target = ts_fill + timedelta(seconds=horizon_s)
    upper = target + timedelta(seconds=min(horizon_s, 60))
    start_idx = bisect_left(book_ts, target) if book_ts is not None else 0
    for idx in range(start_idx, len(books)):
        b = books[idx]
        if b.ts_avail < target:
            continue
        if b.ts_avail > upper:
            break
        if b.bid is not None and b.ask is not None and b.bid > 0 and b.ask > 0:
            mid = (b.bid + b.ask) / Decimal(2)
            raw = (mid - fill_price) / fill_price * Decimal(10000)
            return raw if side == "BUY" else -raw
    return None


def _is_ambiguous_duplicate(tick: TradeTick, seen_keys: set[tuple]) -> bool:
    key = (tick.ts_event, tick.price, tick.qty, tick.aggressor)
    if key in seen_keys:
        return True
    seen_keys.add(key)
    return False


def _print_matches_resting(side: str, limit_price: Decimal, tick: TradeTick) -> bool:
    if side == "BUY":
        return tick.aggressor == "SELL" and tick.price <= limit_price
    return tick.aggressor == "BUY" and tick.price >= limit_price


def _apply_fee(side: str, price: Decimal, qty: Decimal, rate: Decimal, fee_in_received_asset: bool) -> tuple[Decimal, str]:
    if fee_in_received_asset:
        if side == "BUY":
            return qty * rate, "BASE"
        return price * qty * rate, "QUOTE"
    return price * qty * rate, "QUOTE"


def _arrival_crosses(side: str, limit_price: Decimal, top: BookTop) -> bool:
    if side == "BUY":
        return top.ask is not None and limit_price >= top.ask
    return top.bid is not None and limit_price <= top.bid


def _pegged_price(side: str, top: BookTop, offset_bps: Decimal) -> Decimal | None:
    if side == "BUY" and top.bid is not None and top.bid > 0:
        return top.bid * (Decimal(1) - offset_bps / Decimal(10000))
    if side == "SELL" and top.ask is not None and top.ask > 0:
        return top.ask * (Decimal(1) + offset_bps / Decimal(10000))
    return None


def _collect_fill(
    spec: PassiveOrderSpec,
    ts_fill: datetime,
    price: Decimal,
    qty: Decimal,
    role: str,
    rate: Decimal,
    fee_in_received: bool,
    ambiguous: bool,
) -> PassiveFill:
    fee_amt, fee_asset = _apply_fee(spec.side, price, qty, rate, fee_in_received)
    return PassiveFill(
        order_id=spec.order_id,
        symbol=spec.symbol,
        side=spec.side,
        ts_fill=ts_fill,
        price=price,
        qty=qty,
        liquidity_role=role,
        fee_rate=rate,
        fee_amount=fee_amt,
        fee_asset=fee_asset,
        from_ambiguous_duplicate=ambiguous,
    )


def _summarize_result(
    spec: PassiveOrderSpec,
    mode: str,
    status: str,
    fills: list[PassiveFill],
    repeg_count: int,
    completed_at: datetime,
) -> PassiveOrderResult:
    filled = sum((f.qty for f in fills), Decimal(0))
    ambig = sum((f.qty for f in fills if f.from_ambiguous_duplicate), Decimal(0))
    fee_base = sum((f.fee_amount for f in fills if f.fee_asset == "BASE"), Decimal(0))
    fee_quote = sum((f.fee_amount for f in fills if f.fee_asset == "QUOTE"), Decimal(0))
    avg_px = (
        sum((f.price * f.qty for f in fills), Decimal(0)) / filled if filled > 0 else None
    )
    return PassiveOrderResult(
        order_id=spec.order_id,
        symbol=spec.symbol,
        side=spec.side,
        status=status,
        duplicate_print_mode=mode,
        requested_qty=spec.qty,
        filled_qty=filled,
        avg_fill_price=avg_px,
        total_fee_base=fee_base,
        total_fee_quote=fee_quote,
        ambiguous_filled_qty=ambig,
        repeg_count=repeg_count,
        fills=tuple(fills),
        completed_at=completed_at,
    )


def simulate_passive_orders(
    orders: list[PassiveOrderSpec],
    books: list[BookTop],
    trades: list[TradeTick],
    fee_schedule: FeeSchedule,
    *,
    duplicate_print_mode: str = "adversarial_lower_bound",
    feed_gap_windows: tuple[tuple[datetime, datetime], ...] = (),
    rolling_30d_volume: Decimal = Decimal(0),
) -> list[PassiveOrderResult]:
    """Simulate passive child orders with arrival classification, cancel-in-flight race, shared print capacity & O(1) print modes."""
    if duplicate_print_mode not in DUPLICATE_MODES:
        raise ValueError(f"duplicate_print_mode must be one of {DUPLICATE_MODES}")
    sorted_books = sorted(books, key=lambda b: b.ts_avail)
    sorted_trades = sorted(trades, key=lambda t: t.ts_avail)
    book_ts = [b.ts_avail for b in sorted_books]
    trade_ts = [t.ts_avail for t in sorted_trades]
    remaining_print_qty = [t.qty for t in sorted_trades]
    seen_keys: set[tuple] = set()
    is_dup = [_is_ambiguous_duplicate(t, seen_keys) for t in sorted_trades]

    results: list[PassiveOrderResult] = []
    for spec in orders:
        res = _simulate_single_order(
            spec,
            sorted_books,
            sorted_trades,
            book_ts,
            trade_ts,
            remaining_print_qty,
            is_dup,
            fee_schedule,
            duplicate_print_mode,
            feed_gap_windows,
            rolling_30d_volume,
        )
        results.append(res)
    return results


def _in_feed_gap(ts: datetime, gaps: tuple[tuple[datetime, datetime], ...]) -> bool:
    return any(start <= ts <= end for start, end in gaps)


def _simulate_single_order(
    spec: PassiveOrderSpec,
    books: list[BookTop],
    trades: list[TradeTick],
    book_ts: list[datetime],
    trade_ts: list[datetime],
    remaining_print_qty: list[Decimal],
    is_dup: list[bool],
    fee_schedule: FeeSchedule,
    mode: str,
    feed_gap_windows: tuple[tuple[datetime, datetime], ...],
    rolling_30d_volume: Decimal,
) -> PassiveOrderResult:
    t_arr = spec.sent_at + timedelta(milliseconds=spec.send_latency_ms)
    deadline = t_arr + timedelta(seconds=spec.max_wait_s)
    maker_rate, taker_rate = fee_schedule.effective_rates(t_arr, rolling_30d_volume)
    top_arr = _latest_top_at_or_before(books, t_arr, book_ts)

    if top_arr is None:
        return _summarize_result(spec, mode, "UNFILLED", [], 0, deadline)

    if _arrival_crosses(spec.side, spec.limit_price, top_arr):
        if spec.post_only:
            return _summarize_result(spec, mode, "POST_ONLY_REJECTED", [], 0, t_arr)
        exec_px = top_arr.ask if spec.side == "BUY" else top_arr.bid
        assert exec_px is not None
        fill = _collect_fill(spec, t_arr, exec_px, spec.qty, "TAKER", taker_rate, fee_schedule.fee_in_received_asset, False)
        return _summarize_result(spec, mode, "FILLED", [fill], 0, t_arr)

    active_limit = spec.limit_price
    queue_ahead = (
        (top_arr.bid_qty or Decimal(0))
        if (spec.side == "BUY" and top_arr.bid == active_limit)
        else (top_arr.ask_qty or Decimal(0))
        if (spec.side == "SELL" and top_arr.ask == active_limit)
        else Decimal(0)
    )
    remaining = spec.qty
    fills: list[PassiveFill] = []
    repeg_count = 0
    last_repeg_at = t_arr
    cancel_effective_at: datetime | None = None
    pending_new_limit: Decimal | None = None

    t_start = bisect_left(trade_ts, t_arr)
    t_end = bisect_right(trade_ts, deadline)
    for idx in range(t_start, t_end):
        tick = trades[idx]
        if remaining <= 0:
            break
        if _in_feed_gap(tick.ts_avail, feed_gap_windows):
            if cancel_effective_at is not None and tick.ts_avail <= cancel_effective_at:
                return _summarize_result(spec, mode, "UNCERTAIN_CANCEL", fills, repeg_count, tick.ts_avail)
            continue

        # Complete any cancel/re-peg whose cancel latency elapsed before this print
        if cancel_effective_at is not None and tick.ts_avail >= cancel_effective_at:
            assert pending_new_limit is not None
            active_limit = pending_new_limit
            top_now = _latest_top_at_or_before(books, tick.ts_avail, book_ts)
            queue_ahead = (
                (top_now.bid_qty or Decimal(0))
                if (top_now and spec.side == "BUY" and top_now.bid == active_limit)
                else (top_now.ask_qty or Decimal(0))
                if (top_now and spec.side == "SELL" and top_now.ask == active_limit)
                else Decimal(0)
            )
            cancel_effective_at = None
            pending_new_limit = None

        # Evaluate dynamic re-peg trigger (prior order remains exposed during cancel_latency!)
        if (
            cancel_effective_at is None
            and spec.repeg_offset_bps is not None
            and repeg_count < spec.max_repegs
            and (tick.ts_avail - last_repeg_at).total_seconds() >= spec.repeg_cooldown_s
        ):
            top_now = _latest_top_at_or_before(books, tick.ts_avail, book_ts)
            new_px = _pegged_price(spec.side, top_now, spec.repeg_offset_bps) if top_now else None
            if new_px is not None and new_px != active_limit and not _arrival_crosses(spec.side, new_px, top_now):
                cancel_effective_at = tick.ts_avail + timedelta(milliseconds=spec.cancel_latency_ms)
                pending_new_limit = new_px
                repeg_count += 1
                last_repeg_at = tick.ts_avail
                if _in_feed_gap(cancel_effective_at, feed_gap_windows):
                    return _summarize_result(spec, mode, "UNCERTAIN_CANCEL", fills, repeg_count, cancel_effective_at)

        avail_qty = remaining_print_qty[idx]
        if avail_qty <= 0 or not _print_matches_resting(spec.side, active_limit, tick):
            continue

        dup = is_dup[idx]
        if dup:
            if mode == "deduplicated":
                continue
            if mode == "adversarial_lower_bound":
                markout = _post_fill_markout_bps(spec.side, active_limit, tick.ts_avail, books, book_ts=book_ts)
                if markout is None or markout >= Decimal(0):
                    continue

        if queue_ahead >= avail_qty:
            queue_ahead -= avail_qty
            remaining_print_qty[idx] = Decimal(0)
            continue
        usable = avail_qty - queue_ahead
        queue_ahead = Decimal(0)
        take = min(remaining, usable)
        remaining -= take
        remaining_print_qty[idx] = avail_qty - take
        fills.append(
            _collect_fill(spec, tick.ts_avail, active_limit, take, "MAKER", maker_rate, fee_schedule.fee_in_received_asset, dup)
        )

    status = "FILLED" if remaining == 0 else "PARTIAL" if fills else "UNFILLED"
    completed = fills[-1].ts_fill if status == "FILLED" else deadline
    return _summarize_result(spec, mode, status, fills, repeg_count, completed)
