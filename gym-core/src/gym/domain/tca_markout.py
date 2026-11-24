"""Strictly post-fill multi-horizon TCA markout & exit-liquidity stress (spec §4.5)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import BookTop

DEFAULT_HORIZONS_S = (5, 30, 300, 3600)


def max_post_tolerance_s(horizon_s: int) -> int:
    """Strictly post-fill tolerance: min(h, 60) seconds after t_fill + h."""
    return min(horizon_s, 60)


@dataclass(frozen=True)
class FillRecord:
    symbol: str
    side: str                         # "BUY" | "SELL"
    ts_fill: datetime
    fill_price: Decimal
    qty: Decimal
    decision_mid: Decimal
    arrival_mid: Decimal
    fee_quote_equiv: Decimal
    market_state: str = "NORMAL"


@dataclass(frozen=True)
class HorizonMarkout:
    horizon_s: int
    status: str                       # "OK" | "MISSING_POST_FILL_QUOTE"
    quote_ts: datetime | None
    quote_mid: Decimal | None
    markout_bps: Decimal | None       # positive = favorable move after fill; negative = adverse selection


@dataclass(frozen=True)
class ShortfallWaterfall:
    symbol: str
    side: str
    arrival_delay_drift_bps: Decimal
    spread_capture_bps: Decimal       # negative = spread captured inside mid; positive = crossing cost
    venue_fee_bps: Decimal
    adverse_markout_5m_bps: Decimal | None
    post_5m_signal_drift_bps: Decimal | None
    unfilled_deadline_unwind_bps: Decimal
    total_realized_cost_bps: Decimal


@dataclass(frozen=True)
class MarkoutReport:
    per_fill: tuple[tuple[FillRecord, tuple[HorizonMarkout, ...]], ...]
    missing_by_stratum: dict[tuple[str, str, str, int], int]
    coverage_by_horizon: dict[int, float]


def _signed_bps(side: str, ref_price: Decimal, price: Decimal) -> Decimal:
    raw = (price - ref_price) / ref_price * Decimal(10000)
    return raw if side == "BUY" else -raw


def compute_fill_markouts(
    fills: list[FillRecord],
    books_by_symbol: dict[str, list[BookTop]],
    *,
    horizons_s: tuple[int, ...] = DEFAULT_HORIZONS_S,
) -> MarkoutReport:
    """Strict post-fill markout lookup: requires t_fill + h <= quote.ts_avail <= t_fill + h + min(h, 60)."""
    sorted_books = {
        sym: sorted(rows, key=lambda b: b.ts_avail)
        for sym, rows in books_by_symbol.items()
    }
    missing: dict[tuple[str, str, str, int], int] = defaultdict(int)
    ok_counts: dict[int, int] = {h: 0 for h in horizons_s}
    out: list[tuple[FillRecord, tuple[HorizonMarkout, ...]]] = []

    for fill in fills:
        rows = sorted_books.get(fill.symbol, [])
        hm_list: list[HorizonMarkout] = []
        for h in horizons_s:
            lo = fill.ts_fill + timedelta(seconds=h)
            hi = lo + timedelta(seconds=max_post_tolerance_s(h))
            matched = next(
                (
                    b for b in rows
                    if lo <= b.ts_avail <= hi and b.bid is not None and b.ask is not None and b.bid > 0 and b.ask > 0
                ),
                None,
            )
            if matched is None:
                missing[(fill.symbol, fill.side, fill.market_state, h)] += 1
                hm_list.append(HorizonMarkout(h, "MISSING_POST_FILL_QUOTE", None, None, None))
            else:
                mid = (matched.bid + matched.ask) / Decimal(2)
                mk = _signed_bps(fill.side, fill.fill_price, mid)
                ok_counts[h] += 1
                hm_list.append(HorizonMarkout(h, "OK", matched.ts_avail, mid, mk))
        out.append((fill, tuple(hm_list)))

    n_fills = len(fills)
    coverage = {h: (ok_counts[h] / n_fills if n_fills else 0.0) for h in horizons_s}
    return MarkoutReport(tuple(out), dict(missing), coverage)


def compute_shortfall_waterfall(
    fill: FillRecord,
    markouts: tuple[HorizonMarkout, ...],
    *,
    unfilled_deadline_unwind_bps: Decimal = Decimal(0),
) -> ShortfallWaterfall:
    """Single-ledger shortfall decomposition (every leg counted once with consistent cost sign)."""
    delay_bps = _signed_bps(fill.side, fill.decision_mid, fill.arrival_mid)
    spread_bps = _signed_bps(fill.side, fill.arrival_mid, fill.fill_price)
    notional = fill.fill_price * fill.qty
    fee_bps = (fill.fee_quote_equiv / notional * Decimal(10000)) if notional > 0 else Decimal(0)
    m300 = next((m.markout_bps for m in markouts if m.horizon_s == 300 and m.status == "OK"), None)
    m3600 = next((m.markout_bps for m in markouts if m.horizon_s == 3600 and m.status == "OK"), None)
    adverse_5m = (-m300) if m300 is not None else None
    post_5m = (m3600 - m300) if (m300 is not None and m3600 is not None) else None
    total_realized = delay_bps + spread_bps + fee_bps + unfilled_deadline_unwind_bps
    return ShortfallWaterfall(
        symbol=fill.symbol,
        side=fill.side,
        arrival_delay_drift_bps=delay_bps,
        spread_capture_bps=spread_bps,
        venue_fee_bps=fee_bps,
        adverse_markout_5m_bps=adverse_5m,
        post_5m_signal_drift_bps=post_5m,
        unfilled_deadline_unwind_bps=unfilled_deadline_unwind_bps,
        total_realized_cost_bps=total_realized,
    )


@dataclass(frozen=True)
class ExitLiquidityStressReport:
    assumption: str                         # "no_replenishment" | "distinct_source_ref_only" | "full_displayed"
    initial_usdt_value: Decimal
    cash_recovered_usdt: Decimal
    residual_dust_usdt: Decimal
    unpriced_exposure_usdt: Decimal
    minutes_to_50pct: float | None
    minutes_to_90pct: float | None
    minutes_to_100pct: float | None


def _available_bid_qty(top: BookTop) -> Decimal:
    if top.depth and isinstance(top.depth, (list, tuple)) and len(top.depth) == 2 and top.depth[0]:
        return sum((Decimal(str(q)) for _, q in top.depth[0]), Decimal(0))
    return top.bid_qty or Decimal(0)


def compute_exit_liquidity_stress(
    held_base_qty: dict[str, Decimal],
    mark_usdt_prices: dict[str, Decimal],
    books_by_symbol: dict[str, list[BookTop]],
    start_at: datetime,
    deadline_at: datetime,
    *,
    assumption: str = "distinct_source_ref_only",
    participation_cap: Decimal = Decimal("0.25"),
    fee_rate: Decimal = Decimal("0.0013"),
) -> ExitLiquidityStressReport:
    """Compute value-weighted minutes to liquidate 50%/90%/100% under explicit depth replenishment modes."""
    if assumption not in ("no_replenishment", "distinct_source_ref_only", "full_displayed"):
        raise ValueError(f"unsupported replenishment assumption: {assumption!r}")

    remaining_qty = {sym: qty for sym, qty in held_base_qty.items() if qty > 0}
    initial_value = sum((qty * mark_usdt_prices.get(sym, Decimal(0)) for sym, qty in remaining_qty.items()), Decimal(0))
    unpriced = sum((qty * mark_usdt_prices.get(sym, Decimal(0)) for sym, qty in remaining_qty.items() if sym not in books_by_symbol), Decimal(0))

    events: list[tuple[datetime, str, BookTop]] = []
    for sym, rows in books_by_symbol.items():
        if sym not in remaining_qty:
            continue
        for b in rows:
            if start_at <= b.ts_avail <= deadline_at and b.bid is not None and b.bid > 0:
                events.append((b.ts_avail, sym, b))
    events.sort(key=lambda x: x[0])

    seen_keys: dict[str, set[tuple]] = defaultdict(set)
    consumed_once: set[str] = set()
    recovered_cash = Decimal(0)
    liquidated_initial_val = Decimal(0)
    t50 = t90 = t100 = None

    for ts, sym, top in events:
        rem = remaining_qty.get(sym, Decimal(0))
        if rem <= 0:
            continue
        if assumption == "no_replenishment" and sym in consumed_once:
            continue
        if assumption == "distinct_source_ref_only":
            k = top.key()
            if k in seen_keys[sym]:
                continue
            seen_keys[sym].add(k)
        consumed_once.add(sym)
        avail = _available_bid_qty(top) * participation_cap
        if avail <= 0:
            continue
        take = min(rem, avail)
        remaining_qty[sym] = rem - take
        assert top.bid is not None
        recovered_cash += take * top.bid * (Decimal(1) - fee_rate)
        liquidated_initial_val += take * mark_usdt_prices.get(sym, top.bid)
        if initial_value > 0:
            frac = liquidated_initial_val / initial_value
            mins = (ts - start_at).total_seconds() / 60.0
            if t50 is None and frac >= Decimal("0.50"):
                t50 = mins
            if t90 is None and frac >= Decimal("0.90"):
                t90 = mins
            if t100 is None and frac >= Decimal("0.999999"):
                t100 = mins

    residual_dust = sum((qty * mark_usdt_prices.get(sym, Decimal(0)) for sym, qty in remaining_qty.items()), Decimal(0))
    return ExitLiquidityStressReport(
        assumption=assumption,
        initial_usdt_value=initial_value,
        cash_recovered_usdt=recovered_cash,
        residual_dust_usdt=residual_dust,
        unpriced_exposure_usdt=unpriced,
        minutes_to_50pct=t50,
        minutes_to_90pct=t90,
        minutes_to_100pct=t100,
    )
