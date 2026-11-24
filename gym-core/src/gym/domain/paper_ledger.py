"""Self-financing exact-Decimal shared spot ledger with drifting holdings & received-asset fees (v2 spec §1, §4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .model import dec


@dataclass(frozen=True)
class LedgerFill:
    ts: datetime
    symbol: str
    side: str                         # "BUY" | "SELL"
    price: Decimal
    gross_qty: Decimal
    fee_amount: Decimal
    fee_asset: str                    # "BASE" | "QUOTE"
    notional_quote: Decimal


class SelfFinancingLedger:
    """Single-account spot ledger reconciling cash -> buy -> hold -> sell with zero cost on unchanged units."""

    def __init__(
        self,
        starting_cash_usdt: Decimal,
        *,
        fee_rate: Decimal = Decimal("0.0013"),
        fee_in_received_asset: bool = True,
        min_trade_notional: Decimal = Decimal("5"),
    ) -> None:
        if starting_cash_usdt <= 0:
            raise ValueError("starting_cash_usdt must be > 0")
        self.starting_cash = dec(starting_cash_usdt)
        self.cash = dec(starting_cash_usdt)
        self.fee_rate = dec(fee_rate)
        self.fee_in_received_asset = fee_in_received_asset
        self.min_trade_notional = dec(min_trade_notional)
        self.units: dict[str, Decimal] = {}
        self.fills: list[LedgerFill] = []
        self.total_fees_quote_equiv = Decimal(0)
        self.cumulative_turnover_quote = Decimal(0)

    def mark_nav(self, prices: dict[str, Decimal]) -> Decimal:
        """Exact NAV = cash + sum(held_units * mark_price)."""
        pos_val = Decimal(0)
        for sym, qty in self.units.items():
            if qty > 0:
                px = prices.get(sym)
                if px is None or px <= 0:
                    raise ValueError(f"missing valid mark price for held symbol {sym!r}")
                pos_val += qty * px
        return self.cash + pos_val

    def current_weights(self, symbols: tuple[str, ...], prices: dict[str, Decimal]) -> tuple[float, ...]:
        """Actual price-drifted portfolio weights at current mark prices."""
        nav = self.mark_nav(prices)
        if nav <= 0:
            return tuple(0.0 for _ in symbols)
        out = []
        for sym in symbols:
            qty = self.units.get(sym, Decimal(0))
            px = prices.get(sym, Decimal(0))
            out.append(float((qty * px) / nav) if qty > 0 and px > 0 else 0.0)
        return tuple(out)

    def rebalance_to_targets(
        self,
        ts: datetime,
        target_weights: dict[str, float],
        exec_prices: dict[str, Decimal],
        *,
        tradable_symbols: set[str] | None = None,
    ) -> list[LedgerFill]:
        """Execute sells first (freeing cash), then buys, charging fees strictly once on actual unit deltas."""
        nav = self.mark_nav(exec_prices)
        if nav <= 0:
            return []

        step_fills: list[LedgerFill] = []
        sells: list[tuple[str, Decimal, Decimal]] = []
        buys: list[tuple[str, Decimal, Decimal]] = []

        all_syms = sorted(set(self.units) | set(target_weights))
        for sym in all_syms:
            if tradable_symbols is not None and sym not in tradable_symbols:
                continue
            px = exec_prices.get(sym)
            if px is None or px <= 0:
                continue
            held_qty = self.units.get(sym, Decimal(0))
            tw = Decimal(str(round(max(0.0, target_weights.get(sym, 0.0)), 8)))
            desired_qty = (nav * tw) / px
            delta_qty = desired_qty - held_qty
            if abs(delta_qty) * px < self.min_trade_notional:
                continue
            if delta_qty < 0:
                sells.append((sym, min(held_qty, -delta_qty), px))
            elif delta_qty > 0:
                buys.append((sym, delta_qty, px))

        # 1. Execute SELLS first to free quote cash
        for sym, qty, px in sells:
            gross_quote = qty * px
            fee_quote = gross_quote * self.fee_rate
            self.units[sym] = self.units.get(sym, Decimal(0)) - qty
            if self.units[sym] <= Decimal("1e-12"):
                self.units[sym] = Decimal(0)
            self.cash += gross_quote - fee_quote
            self.total_fees_quote_equiv += fee_quote
            self.cumulative_turnover_quote += gross_quote
            fill = LedgerFill(ts, sym, "SELL", px, qty, fee_quote, "QUOTE", gross_quote)
            self.fills.append(fill)
            step_fills.append(fill)

        # 2. Execute BUYS strictly bounded by available free cash
        for sym, qty, px in buys:
            gross_quote = qty * px
            if self.fee_in_received_asset:
                spend = min(gross_quote, self.cash)
                if spend < self.min_trade_notional:
                    continue
                actual_gross_qty = spend / px
                fee_base = actual_gross_qty * self.fee_rate
                net_base = actual_gross_qty - fee_base
                self.cash -= spend
                self.units[sym] = self.units.get(sym, Decimal(0)) + net_base
                self.total_fees_quote_equiv += fee_base * px
                self.cumulative_turnover_quote += spend
                fill = LedgerFill(ts, sym, "BUY", px, actual_gross_qty, fee_base, "BASE", spend)
            else:
                max_gross = self.cash / (Decimal(1) + self.fee_rate)
                spend = min(gross_quote, max_gross)
                if spend < self.min_trade_notional:
                    continue
                actual_gross_qty = spend / px
                fee_quote = spend * self.fee_rate
                self.cash -= spend + fee_quote
                self.units[sym] = self.units.get(sym, Decimal(0)) + actual_gross_qty
                self.total_fees_quote_equiv += fee_quote
                self.cumulative_turnover_quote += spend
                fill = LedgerFill(ts, sym, "BUY", px, actual_gross_qty, fee_quote, "QUOTE", spend)
            self.fills.append(fill)
            step_fills.append(fill)

        return step_fills
