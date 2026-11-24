"""Turnover-saving execution-timing overlay on already-required parent trades (spec §4.4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import BookTop, TradeTick
from .passive_execution import PassiveOrderSpec, simulate_passive_orders
from .venue_contracts import FeeSchedule


@dataclass(frozen=True)
class ExecutionArmSummary:
    arm: str                                # "IMMEDIATE" | "FIXED_PASSIVE" | "OPPORTUNISTIC_RECOVERY"
    filled_qty: Decimal
    avg_exec_price: Decimal
    decision_mid: Decimal
    shortfall_bps: Decimal                  # positive = cost vs decision_mid
    fee_quote_equiv: Decimal
    total_cost_bps: Decimal                 # shortfall_bps + fee_bps
    delay_exposure_s: float
    forced_completion_qty: Decimal


@dataclass(frozen=True)
class ExecutionOverlayComparison:
    symbol: str
    side: str
    parent_qty: Decimal
    decided_at: datetime
    deadline_at: datetime
    immediate: ExecutionArmSummary
    fixed_passive: ExecutionArmSummary
    opportunistic_recovery: ExecutionArmSummary


def _mid(top: BookTop) -> Decimal:
    assert top.bid is not None and top.ask is not None
    return (top.bid + top.ask) / Decimal(2)


def _signed_shortfall_bps(side: str, decision_mid: Decimal, exec_price: Decimal) -> Decimal:
    raw = (exec_price - decision_mid) / decision_mid * Decimal(10000)
    return raw if side == "BUY" else -raw


def _complete_at_touch(
    side: str,
    qty: Decimal,
    top: BookTop,
    taker_rate: Decimal,
) -> tuple[Decimal, Decimal]:
    px = top.ask if side == "BUY" else top.bid
    assert px is not None
    return px, px * qty * taker_rate


def _arm_summary(
    arm: str,
    side: str,
    parent_qty: Decimal,
    decision_mid: Decimal,
    passive_filled_qty: Decimal,
    passive_avg_px: Decimal | None,
    passive_fee_quote: Decimal,
    forced_qty: Decimal,
    forced_px: Decimal | None,
    forced_fee_quote: Decimal,
    delay_s: float,
) -> ExecutionArmSummary:
    total_notional = Decimal(0)
    if passive_filled_qty > 0 and passive_avg_px is not None:
        total_notional += passive_filled_qty * passive_avg_px
    if forced_qty > 0 and forced_px is not None:
        total_notional += forced_qty * forced_px
    filled = passive_filled_qty + forced_qty
    avg_px = total_notional / filled if filled > 0 else decision_mid
    sf_bps = _signed_shortfall_bps(side, decision_mid, avg_px)
    fee_q = passive_fee_quote + forced_fee_quote
    fee_bps = (fee_q / (parent_qty * decision_mid) * Decimal(10000)) if parent_qty > 0 else Decimal(0)
    return ExecutionArmSummary(
        arm=arm,
        filled_qty=filled,
        avg_exec_price=avg_px,
        decision_mid=decision_mid,
        shortfall_bps=sf_bps,
        fee_quote_equiv=fee_q,
        total_cost_bps=sf_bps + fee_bps,
        delay_exposure_s=delay_s,
        forced_completion_qty=forced_qty,
    )


def _find_opportunistic_trigger(
    books: list[BookTop],
    side: str,
    decision_mid: Decimal,
    t0: datetime,
    deadline: datetime,
    p35_spread_bps: Decimal,
    adverse_drift_limit_bps: Decimal,
    min_distinct_refs: int = 2,
) -> BookTop | None:
    """Wait inside [t0, deadline] until spread <= p35 or depth recovers across distinct snapshots, with stop-chase guard."""
    seen_keys: set[tuple] = set()
    for b in books:
        if b.ts_avail < t0 or b.ts_avail > deadline:
            continue
        if b.bid is None or b.ask is None or b.bid <= 0 or b.ask <= 0:
            continue
        seen_keys.add(b.key())
        drift = _signed_shortfall_bps(side, decision_mid, _mid(b))
        if drift >= adverse_drift_limit_bps:
            return b
        sp = b.spread_bps
        if sp is not None and sp <= p35_spread_bps and len(seen_keys) >= min_distinct_refs:
            return b
    return None


def compare_execution_timing_arms(
    symbol: str,
    side: str,
    parent_qty: Decimal,
    decided_at: datetime,
    max_wait_s: float,
    books: list[BookTop],
    trades: list[TradeTick],
    fee_schedule: FeeSchedule,
    *,
    p35_spread_bps: Decimal = Decimal("15"),
    adverse_drift_limit_bps: Decimal = Decimal("25"),
    duplicate_print_mode: str = "adversarial_lower_bound",
) -> ExecutionOverlayComparison:
    """Compare IMMEDIATE, FIXED_PASSIVE, and OPPORTUNISTIC_RECOVERY ending at identical target exposure."""
    sorted_books = sorted(books, key=lambda b: b.ts_avail)
    deadline = decided_at + timedelta(seconds=max_wait_s)
    t0_top = next((b for b in reversed(sorted_books) if b.ts_avail <= decided_at and b.bid and b.ask), None)
    if t0_top is None:
        raise ValueError("no qualified quote at or before decided_at")
    end_top = next((b for b in reversed(sorted_books) if b.ts_avail <= deadline and b.bid and b.ask), t0_top)
    decision_mid = _mid(t0_top)
    _, taker_rate = fee_schedule.effective_rates(decided_at)

    # Arm 1: IMMEDIATE
    imm_px, imm_fee = _complete_at_touch(side, parent_qty, t0_top, taker_rate)
    imm = _arm_summary("IMMEDIATE", side, parent_qty, decision_mid, Decimal(0), None, Decimal(0), parent_qty, imm_px, imm_fee, 0.0)

    # Arm 2: FIXED_PASSIVE resting at t0 touch for max_wait_s, then forced completion
    limit_px = t0_top.bid if side == "BUY" else t0_top.ask
    assert limit_px is not None
    spec = PassiveOrderSpec("fixed-passive", symbol, side, parent_qty, limit_px, decided_at, post_only=True, max_wait_s=max_wait_s)
    res_fp = simulate_passive_orders([spec], sorted_books, trades, fee_schedule, duplicate_print_mode=duplicate_print_mode)[0]
    fp_fee_q = res_fp.total_fee_quote + (res_fp.total_fee_base * (res_fp.avg_fill_price or decision_mid))
    fp_rem = parent_qty - res_fp.filled_qty
    fp_forced_px, fp_forced_fee = _complete_at_touch(side, fp_rem, end_top, taker_rate) if fp_rem > 0 else (None, Decimal(0))
    fp_delay = (res_fp.completed_at - decided_at).total_seconds() if fp_rem == 0 else max_wait_s
    fp = _arm_summary("FIXED_PASSIVE", side, parent_qty, decision_mid, res_fp.filled_qty, res_fp.avg_fill_price, fp_fee_q, fp_rem, fp_forced_px, fp_forced_fee, fp_delay)

    # Arm 3: OPPORTUNISTIC_RECOVERY
    trig_top = _find_opportunistic_trigger(sorted_books, side, decision_mid, decided_at, deadline, p35_spread_bps, adverse_drift_limit_bps)
    if trig_top is None:
        opp_px, opp_fee = _complete_at_touch(side, parent_qty, end_top, taker_rate)
        opp = _arm_summary("OPPORTUNISTIC_RECOVERY", side, parent_qty, decision_mid, Decimal(0), None, Decimal(0), parent_qty, opp_px, opp_fee, max_wait_s)
    else:
        rem_wait = max(0.0, (deadline - trig_top.ts_avail).total_seconds())
        drift = _signed_shortfall_bps(side, decision_mid, _mid(trig_top))
        if drift >= adverse_drift_limit_bps or rem_wait <= 0:
            opp_px, opp_fee = _complete_at_touch(side, parent_qty, trig_top, taker_rate)
            opp = _arm_summary("OPPORTUNISTIC_RECOVERY", side, parent_qty, decision_mid, Decimal(0), None, Decimal(0), parent_qty, opp_px, opp_fee, (trig_top.ts_avail - decided_at).total_seconds())
        else:
            trig_lim = trig_top.bid if side == "BUY" else trig_top.ask
            assert trig_lim is not None
            opp_spec = PassiveOrderSpec("opp-passive", symbol, side, parent_qty, trig_lim, trig_top.ts_avail, post_only=True, max_wait_s=rem_wait)
            res_opp = simulate_passive_orders([opp_spec], sorted_books, trades, fee_schedule, duplicate_print_mode=duplicate_print_mode)[0]
            opp_fee_q = res_opp.total_fee_quote + (res_opp.total_fee_base * (res_opp.avg_fill_price or decision_mid))
            opp_rem = parent_qty - res_opp.filled_qty
            opp_fpx, opp_ffee = _complete_at_touch(side, opp_rem, end_top, taker_rate) if opp_rem > 0 else (None, Decimal(0))
            opp_delay = (res_opp.completed_at - decided_at).total_seconds() if opp_rem == 0 else max_wait_s
            opp = _arm_summary("OPPORTUNISTIC_RECOVERY", side, parent_qty, decision_mid, res_opp.filled_qty, res_opp.avg_fill_price, opp_fee_q, opp_rem, opp_fpx, opp_ffee, opp_delay)

    return ExecutionOverlayComparison(symbol, side, parent_qty, decided_at, deadline, imm, fp, opp)
