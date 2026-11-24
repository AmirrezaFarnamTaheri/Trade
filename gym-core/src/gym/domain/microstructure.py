"""Microstructure-complete consolidator and RichSnapshot (spec §5.1)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .model import BookTop, TradeTick, dec


@dataclass(frozen=True)
class RichSnapshot:
    symbol: str
    ts_avail: datetime
    ts_event: datetime | None
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    microprice: Decimal
    spread_bps: Decimal
    top_age_ms: float
    ofi_l1: Decimal
    l2_depth5_imbalance: Decimal | None
    depth_top_triggered: bool
    buy_aggressor_vol: Decimal
    sell_aggressor_vol: Decimal
    vwap: Decimal | None
    vpin: float | None
    flags: frozenset[str]


@dataclass(frozen=True)
class MicrostructureBar:
    symbol: str
    start: datetime
    end: datetime
    open_micro: Decimal
    high_micro: Decimal
    low_micro: Decimal
    close_micro: Decimal
    buy_aggressor_vol: Decimal
    sell_aggressor_vol: Decimal
    total_trade_vol: Decimal
    vwap: Decimal | None
    ofi_sum: Decimal
    vpin: float | None
    book_updates: int
    trade_count: int


def stoikov_microprice(bid: Decimal, ask: Decimal, bid_qty: Decimal, ask_qty: Decimal) -> Decimal:
    """Volume-weighted Stoikov microprice; falls back to mid if top quantities sum to zero."""
    denom = bid_qty + ask_qty
    if denom <= 0:
        return (bid + ask) / Decimal(2)
    return (bid * ask_qty + ask * bid_qty) / denom


def l2_depth_imbalance(depth: tuple | list | None) -> Decimal | None:
    """Compute normalized top-N L2 imbalance in [-1, +1] from stored (bids, asks) levels."""
    if not depth or not isinstance(depth, (list, tuple)) or len(depth) != 2:
        return None
    bids, asks = depth
    if not bids or not asks:
        return None
    b_sum = sum((dec(q) for _, q in bids), Decimal(0))
    a_sum = sum((dec(q) for _, q in asks), Decimal(0))
    denom = b_sum + a_sum
    if denom <= 0:
        return None
    return (b_sum - a_sum) / denom


def compute_ofi_step(prev: BookTop | None, curr: BookTop) -> Decimal:
    """Event-driven Cont-Kukanov-Stoikov L1 Order Flow Imbalance."""
    if prev is None or prev.bid is None or prev.ask is None or curr.bid is None or curr.ask is None:
        return Decimal(0)
    pb, pa = prev.bid, prev.ask
    pbq, paq = prev.bid_qty or Decimal(0), prev.ask_qty or Decimal(0)
    cb, ca = curr.bid, curr.ask
    cbq, caq = curr.bid_qty or Decimal(0), curr.ask_qty or Decimal(0)

    if cb > pb:
        eb = cbq
    elif cb == pb:
        eb = cbq - pbq
    else:
        eb = -pbq

    if ca > pa:
        ea = -paq
    elif ca == pa:
        ea = caq - paq
    else:
        ea = caq

    return eb - ea


class MicrostructureConsolidator:
    """Causal ts_avail-ordered consolidator computing microprice, L1 OFI, L2 depth5 imbalance, VWAP & VPIN."""

    def __init__(
        self,
        symbol: str,
        *,
        vpin_bucket_volume: Decimal = Decimal("1.0"),
        vpin_window_buckets: int = 20,
    ) -> None:
        if vpin_bucket_volume <= 0 or vpin_window_buckets < 1:
            raise ValueError("vpin_bucket_volume must be > 0 and vpin_window_buckets >= 1")
        self.symbol = symbol
        self.vpin_bucket_volume = vpin_bucket_volume
        self.vpin_window_buckets = vpin_window_buckets
        self._prev_top: BookTop | None = None
        self._last_top_change_at: datetime | None = None
        self._ofi_sum = Decimal(0)
        self._buy_vol = Decimal(0)
        self._sell_vol = Decimal(0)
        self._unknown_side_vol = Decimal(0)
        self._notional_sum = Decimal(0)
        self._trade_count = 0
        self._book_updates = 0
        self._bucket_buy = Decimal(0)
        self._bucket_sell = Decimal(0)
        self._bucket_imbalances: deque[Decimal] = deque(maxlen=vpin_window_buckets)
        self._bar_start: datetime | None = None
        self._open_m: Decimal | None = None
        self._high_m: Decimal | None = None
        self._low_m: Decimal | None = None
        self._close_m: Decimal | None = None

    def _current_vpin(self) -> float | None:
        if len(self._bucket_imbalances) < self.vpin_window_buckets:
            return None
        total = sum(self._bucket_imbalances, Decimal(0))
        return float(total / (Decimal(self.vpin_window_buckets) * self.vpin_bucket_volume))

    def on_trade(self, tick: TradeTick) -> None:
        if tick.qty <= 0 or tick.price <= 0:
            return
        self._trade_count += 1
        self._notional_sum += tick.price * tick.qty
        side = str(tick.aggressor).upper()
        if side == "BUY":
            self._buy_vol += tick.qty
        elif side == "SELL":
            self._sell_vol += tick.qty
        else:
            self._unknown_side_vol += tick.qty
            return

        rem = tick.qty
        filled_in_bucket = self._bucket_buy + self._bucket_sell
        if filled_in_bucket > 0:
            space = self.vpin_bucket_volume - filled_in_bucket
            take = min(rem, space)
            if side == "BUY":
                self._bucket_buy += take
            else:
                self._bucket_sell += take
            rem -= take
            if self._bucket_buy + self._bucket_sell >= self.vpin_bucket_volume:
                self._bucket_imbalances.append(abs(self._bucket_buy - self._bucket_sell))
                self._bucket_buy = Decimal(0)
                self._bucket_sell = Decimal(0)

        # Batch complete same-side buckets arithmetically so 400M-unit PEPE prints stay O(1).
        if rem >= self.vpin_bucket_volume:
            full_buckets, rem = divmod(rem, self.vpin_bucket_volume)
            append_count = min(int(full_buckets), self.vpin_window_buckets)
            for _ in range(append_count):
                self._bucket_imbalances.append(self.vpin_bucket_volume)

        if rem > 0:
            if side == "BUY":
                self._bucket_buy = rem
            else:
                self._bucket_sell = rem

    def on_book_top(self, top: BookTop, *, ts_event: datetime | None = None) -> RichSnapshot | None:
        if top.bid is None or top.ask is None or top.bid <= 0 or top.ask <= 0:
            return None
        ofi = compute_ofi_step(self._prev_top, top)
        self._ofi_sum += ofi
        self._book_updates += 1

        top_changed = self._prev_top is None or self._prev_top.key() != top.key()
        if top_changed or self._last_top_change_at is None:
            self._last_top_change_at = top.ts_avail
        top_age_ms = max(0.0, (top.ts_avail - self._last_top_change_at).total_seconds() * 1000.0)
        self._prev_top = top

        bq = top.bid_qty or Decimal(0)
        aq = top.ask_qty or Decimal(0)
        micro = stoikov_microprice(top.bid, top.ask, bq, aq)
        mid = (top.bid + top.ask) / Decimal(2)
        sp_bps = (top.ask - top.bid) / mid * Decimal(10000)

        if self._bar_start is None:
            self._bar_start = top.ts_avail
            self._open_m = self._high_m = self._low_m = self._close_m = micro
        else:
            assert self._high_m is not None and self._low_m is not None
            self._high_m = max(self._high_m, micro)
            self._low_m = min(self._low_m, micro)
            self._close_m = micro

        total_v = self._buy_vol + self._sell_vol
        vwap = (self._notional_sum / total_v) if total_v > 0 else None
        l2_imb = l2_depth_imbalance(top.depth)
        return RichSnapshot(
            symbol=self.symbol,
            ts_avail=top.ts_avail,
            ts_event=ts_event,
            bid=top.bid,
            ask=top.ask,
            bid_qty=bq,
            ask_qty=aq,
            microprice=micro,
            spread_bps=sp_bps,
            top_age_ms=top_age_ms,
            ofi_l1=ofi,
            l2_depth5_imbalance=l2_imb,
            depth_top_triggered=(l2_imb is not None and top_changed),
            buy_aggressor_vol=self._buy_vol,
            sell_aggressor_vol=self._sell_vol,
            vwap=vwap,
            vpin=self._current_vpin(),
            flags=top.flags,
        )

    def flush_bar(self, end_at: datetime) -> MicrostructureBar | None:
        if self._bar_start is None or self._open_m is None or self._high_m is None or self._low_m is None or self._close_m is None:
            return None
        total_v = self._buy_vol + self._sell_vol
        vwap = (self._notional_sum / total_v) if total_v > 0 else None
        bar = MicrostructureBar(
            symbol=self.symbol,
            start=self._bar_start,
            end=end_at,
            open_micro=self._open_m,
            high_micro=self._high_m,
            low_micro=self._low_m,
            close_micro=self._close_m,
            buy_aggressor_vol=self._buy_vol,
            sell_aggressor_vol=self._sell_vol,
            total_trade_vol=total_v,
            vwap=vwap,
            ofi_sum=self._ofi_sum,
            vpin=self._current_vpin(),
            book_updates=self._book_updates,
            trade_count=self._trade_count,
        )
        self._bar_start = None
        self._open_m = self._high_m = self._low_m = self._close_m = None
        self._ofi_sum = Decimal(0)
        self._buy_vol = Decimal(0)
        self._sell_vol = Decimal(0)
        self._unknown_side_vol = Decimal(0)
        self._notional_sum = Decimal(0)
        self._trade_count = 0
        self._book_updates = 0
        return bar
