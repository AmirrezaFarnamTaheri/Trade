"""Preview-reconciled TMN-borrow carry simulator vs 1x unlevered spot (spec §4.6)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import BookTop

DEFAULT_EXTEND_FEE_RATE = Decimal("0.00015")  # 0.015% every 4 hours
DEFAULT_EXTEND_SECONDS = 4 * 3600
DEFAULT_MAX_AGE_DAYS = 21


@dataclass(frozen=True)
class TmnBorrowTerms:
    symbol: str                               # e.g. "USDTTMN" | "XAUTTMN"
    collateral_tmn: Decimal
    leverage: Decimal                         # e.g. Decimal("1.5") or Decimal("2.0")
    open_fee_rate: Decimal = Decimal("0.0025")
    close_fee_rate: Decimal = Decimal("0.0030")
    extend_fee_rate: Decimal = DEFAULT_EXTEND_FEE_RATE
    extend_interval_s: int = DEFAULT_EXTEND_SECONDS
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    liquidation_margin_ratio: Decimal = Decimal("0.15")
    warning_margin_ratio: Decimal = Decimal("0.25")
    allow_renewal_at_expiry: bool = True

    def __post_init__(self) -> None:
        if self.collateral_tmn <= 0 or not (Decimal(1) < self.leverage <= Decimal("3")):
            raise ValueError("collateral_tmn must be > 0 and leverage in (1, 3]")


@dataclass(frozen=True)
class TmnCarryResult:
    symbol: str
    status: str                               # "CLOSED_AT_HORIZON" | "LIQUIDATED" | "RENEWAL_REJECTED_DAY21"
    initial_collateral_tmn: Decimal
    final_levered_equity_tmn: Decimal
    final_unlevered_1x_equity_tmn: Decimal
    excess_over_1x_tmn: Decimal
    total_extend_fees_tmn: Decimal
    total_roll_fees_tmn: Decimal
    roll_count: int
    warning_events: int
    liquidation_price_tmn: Decimal
    liquidation_fill_price_tmn: Decimal | None


def _walk_bid_exit(top: BookTop, qty: Decimal) -> Decimal:
    """Walk available bid depth; if thin depth gaps below liquidation, price fills at walked VWAP."""
    if top.depth and isinstance(top.depth, (list, tuple)) and len(top.depth) == 2 and top.depth[0]:
        rem = qty
        notional = Decimal(0)
        last_px = top.bid or Decimal(0)
        for p_raw, q_raw in top.depth[0]:
            p, q = Decimal(str(p_raw)), Decimal(str(q_raw))
            take = min(rem, q)
            notional += p * take
            rem -= take
            last_px = p
            if rem <= 0:
                break
        if rem > 0:
            notional += rem * last_px
        return notional / qty if qty > 0 else last_px
    return top.bid or Decimal(0)


def simulate_tmn_borrow_carry(
    terms: TmnBorrowTerms,
    books: list[BookTop],
    *,
    spot_fee_rate: Decimal = Decimal("0.0025"),
) -> TmnCarryResult:
    """Simulate long USDTTMN/XAUTTMN funded by TMN debt vs unlevered 1x spot on identical book path."""
    if not books:
        raise ValueError("books must be non-empty")
    ordered = sorted(books, key=lambda b: b.ts_avail)
    first = ordered[0]
    if first.ask is None or first.bid is None or first.ask <= 0 or first.bid <= 0:
        raise ValueError("initial quote must be two-sided")

    # Levered entry: borrow (leverage - 1) * collateral in TMN
    notional_open = terms.collateral_tmn * terms.leverage
    loan_tmn = terms.collateral_tmn * (terms.leverage - Decimal(1))
    open_fee = notional_open * terms.open_fee_rate
    base_qty = (notional_open - open_fee) / first.ask

    # Unlevered 1x benchmark on identical collateral and start time
    unlev_qty = (terms.collateral_tmn * (Decimal(1) - spot_fee_rate)) / first.ask

    # Liquidation and warning prices
    liq_px = (loan_tmn / base_qty) / (Decimal(1) - terms.liquidation_margin_ratio)
    warn_px = (loan_tmn / base_qty) / (Decimal(1) - terms.warning_margin_ratio)

    next_extend = first.ts_avail + timedelta(seconds=terms.extend_interval_s)
    next_roll = first.ts_avail + timedelta(days=terms.max_age_days)
    total_ext_fee = Decimal(0)
    total_roll_fee = Decimal(0)
    roll_count = 0
    warning_events = 0

    for top in ordered[1:]:
        if top.bid is None or top.ask is None or top.bid <= 0 or top.ask <= 0:
            continue
        # Accrue 4-hour extension fees and handle simultaneous 21-day expiry rolls cleanly
        while top.ts_avail >= next_extend:
            ext_fee = loan_tmn * terms.extend_fee_rate
            total_ext_fee += ext_fee
            loan_tmn += ext_fee
            next_extend += timedelta(seconds=terms.extend_interval_s)
        while top.ts_avail >= next_roll:
            if not terms.allow_renewal_at_expiry:
                exit_px = _walk_bid_exit(top, base_qty)
                close_fee = base_qty * exit_px * terms.close_fee_rate
                lev_eq = max(Decimal(0), base_qty * exit_px - close_fee - loan_tmn)
                unlev_eq = unlev_qty * top.bid * (Decimal(1) - spot_fee_rate)
                return TmnCarryResult(
                    terms.symbol, "RENEWAL_REJECTED_DAY21", terms.collateral_tmn,
                    lev_eq, unlev_eq, lev_eq - unlev_eq,
                    total_ext_fee, total_roll_fee, roll_count, warning_events, liq_px, exit_px,
                )
            roll_fee = (base_qty * top.bid) * (terms.close_fee_rate + terms.open_fee_rate)
            total_roll_fee += roll_fee
            loan_tmn += roll_fee
            roll_count += 1
            next_roll += timedelta(days=terms.max_age_days)

        liq_px = (loan_tmn / base_qty) / (Decimal(1) - terms.liquidation_margin_ratio)
        warn_px = (loan_tmn / base_qty) / (Decimal(1) - terms.warning_margin_ratio)
        if top.bid <= warn_px:
            warning_events += 1
        if top.bid <= liq_px:
            fill_px = _walk_bid_exit(top, base_qty)
            close_fee = base_qty * fill_px * terms.close_fee_rate
            lev_eq = max(Decimal(0), base_qty * fill_px - close_fee - loan_tmn)
            unlev_eq = unlev_qty * ordered[-1].bid * (Decimal(1) - spot_fee_rate) if ordered[-1].bid else Decimal(0)
            return TmnCarryResult(
                terms.symbol, "LIQUIDATED", terms.collateral_tmn,
                lev_eq, unlev_eq, lev_eq - unlev_eq,
                total_ext_fee, total_roll_fee, roll_count, warning_events, liq_px, fill_px,
            )

    last = ordered[-1]
    assert last.bid is not None
    exit_px = _walk_bid_exit(last, base_qty)
    close_fee = base_qty * exit_px * terms.close_fee_rate
    lev_eq = max(Decimal(0), base_qty * exit_px - close_fee - loan_tmn)
    unlev_eq = unlev_qty * last.bid * (Decimal(1) - spot_fee_rate)
    return TmnCarryResult(
        terms.symbol, "CLOSED_AT_HORIZON", terms.collateral_tmn,
        lev_eq, unlev_eq, lev_eq - unlev_eq,
        total_ext_fee, total_roll_fee, roll_count, warning_events, liq_px, exit_px,
    )


def compare_fx_appreciation_scenarios(
    terms: TmnBorrowTerms,
    *,
    start_at: datetime,
    horizon_days: int = 90,
    start_price_tmn: Decimal = Decimal("100000"),
    annual_fx_rates: tuple[Decimal, ...] = (Decimal("0.00"), Decimal("0.25"), Decimal("0.50")),
) -> dict[Decimal, TmnCarryResult]:
    """Compare TMN-borrow carry vs unlevered 1x ownership across 0%, 25%, 50% annual FX appreciation."""
    results: dict[Decimal, TmnCarryResult] = {}
    for ann_rate in annual_fx_rates:
        books: list[BookTop] = []
        for day in range(horizon_days + 1):
            frac = Decimal(day) / Decimal(365)
            mid = start_price_tmn * (Decimal(1) + ann_rate * frac)
            bid = mid * Decimal("0.9995")
            ask = mid * Decimal("1.0005")
            books.append(
                BookTop(
                    symbol=terms.symbol,
                    ts_avail=start_at + timedelta(days=day),
                    bid=bid,
                    ask=ask,
                    bid_qty=Decimal("100000"),
                    ask_qty=Decimal("100000"),
                    flags=frozenset(),
                )
            )
        results[ann_rate] = simulate_tmn_borrow_carry(terms, books)
    return results
