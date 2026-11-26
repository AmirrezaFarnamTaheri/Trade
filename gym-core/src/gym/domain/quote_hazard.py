"""Constrained hindsight DP ceiling & 4-outcome passive quote-hazard model (spec §6.4)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .model import BookTop
from .venue_contracts import FeeSchedule

EXECUTION_OUTCOMES = (
    "FILLED_BENIGN",
    "FILLED_ADVERSE",
    "CANCELED_UNFILLED",
    "EXPIRED_UNFILLED",
)


@dataclass(frozen=True)
class HindsightCeilingResult:
    symbol: str
    initial_cash_quote: Decimal
    max_terminal_cash_quote: Decimal
    net_return_bps: Decimal
    trade_count: int
    evaluated_quotes: int
    beats_cash_hurdle: bool


def hindsight_dp_ceiling(
    books: list[BookTop],
    *,
    initial_cash_quote: Decimal,
    fee_schedule: FeeSchedule,
    min_hurdle_bps: Decimal = Decimal("5"),
    min_displayed_notional: Decimal = Decimal("10"),
) -> HindsightCeilingResult:
    """Exact DP maximum self-financing terminal cash for a 1-lot cash-or-long policy with compulsory flat finish.

    Crosses recorded executable ask/bid within displayed depth and pays exact received-asset fees on both legs.
    """
    ordered = [
        b for b in sorted(books, key=lambda x: x.ts_avail)
        if b.bid is not None and b.ask is not None and b.bid > 0 and b.ask > 0
    ]
    symbol = ordered[0].symbol if ordered else "UNKNOWN"
    if len(ordered) < 2 or initial_cash_quote <= 0:
        return HindsightCeilingResult(symbol, initial_cash_quote, initial_cash_quote, Decimal(0), 0, len(ordered), False)

    # DP states:
    # cash_state: best (cash_quote, trades) when flat
    # long_state: best (base_qty, trades) when long 100% of equity
    best_cash = initial_cash_quote
    cash_trades = 0
    best_base = Decimal(0)
    base_trades = 0

    for top in ordered:
        assert top.bid is not None and top.ask is not None
        _, taker_rate = fee_schedule.effective_rates(top.ts_avail)
        ask_notional = top.ask * (top.ask_qty or Decimal(0))
        bid_notional = top.bid * (top.bid_qty or Decimal(0))

        # Candidate transition: Flat -> Long at executable ask (received-asset fee debited from base)
        cand_base = best_base
        cand_base_trades = base_trades
        if ask_notional >= min_displayed_notional and best_cash > 0:
            if fee_schedule.fee_in_received_asset:
                bought_base = (best_cash / top.ask) * (Decimal(1) - taker_rate)
            else:
                bought_base = (best_cash / (Decimal(1) + taker_rate)) / top.ask
            # Respect displayed top-of-book depth cap
            if top.ask_qty is not None and top.ask_qty > 0 and bought_base <= top.ask_qty:
                if bought_base > cand_base:
                    cand_base = bought_base
                    cand_base_trades = cash_trades + 1

        # Candidate transition: Long -> Flat at executable bid (received-asset fee debited from quote)
        cand_cash = best_cash
        cand_cash_trades = cash_trades
        if best_base > 0 and bid_notional >= min_displayed_notional:
            if top.bid_qty is not None and top.bid_qty > 0 and best_base <= top.bid_qty:
                proceeds = best_base * top.bid * (Decimal(1) - taker_rate)
                if proceeds > cand_cash:
                    cand_cash = proceeds
                    cand_cash_trades = base_trades + 1

        best_cash, cash_trades = cand_cash, cand_cash_trades
        best_base, base_trades = cand_base, cand_base_trades

    net_bps = ((best_cash - initial_cash_quote) / initial_cash_quote) * Decimal(10000)
    return HindsightCeilingResult(
        symbol=symbol,
        initial_cash_quote=initial_cash_quote,
        max_terminal_cash_quote=best_cash,
        net_return_bps=net_bps,
        trade_count=cash_trades,
        evaluated_quotes=len(ordered),
        beats_cash_hurdle=(net_bps >= min_hurdle_bps),
    )


def isotonic_pava(values: list[float], weights: list[float] | None = None, *, decreasing: bool = True) -> list[float]:
    """Pool-Adjacent-Violators Algorithm for monotone probability calibration (decreasing with offset by default)."""
    if not values:
        return []
    w = weights if weights is not None else [1.0] * len(values)
    seq = [-v for v in values] if decreasing else list(values)
    blocks: list[list[float]] = []  # [sum_wy, sum_w, count]
    for y, wi in zip(seq, w, strict=True):
        blocks.append([y * wi, wi, 1.0])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) > (blocks[-1][0] / blocks[-1][1]):
            b2 = blocks.pop()
            blocks[-1][0] += b2[0]
            blocks[-1][1] += b2[1]
            blocks[-1][2] += b2[2]
    out: list[float] = []
    for s_wy, s_w, cnt in blocks:
        val = s_wy / s_w
        out.extend([-val if decreasing else val] * int(cnt))
    return out


@dataclass(frozen=True)
class PassiveAttemptRecord:
    offset_bucket: str
    outcome: str                          # one of EXECUTION_OUTCOMES
    realized_net_bps: float
    mandatory_rebalance: bool


@dataclass(frozen=True)
class BucketPayoffEstimate:
    offset_bucket: str
    sample_count: int
    outcome_probs: dict[str, float]
    outcome_mean_payoff_bps: dict[str, float]
    expected_net_value_bps: float
    brier_score: float


def fit_execution_outcome_model(
    records: list[PassiveAttemptRecord],
    *,
    unfilled_mandatory_completion_cost_bps: float = -25.0,
) -> dict[str, BucketPayoffEstimate]:
    """Estimate mutually exclusive 4-outcome probabilities & expected net value, reporting Brier separately."""
    by_bucket: dict[str, list[PassiveAttemptRecord]] = defaultdict(list)
    for rec in records:
        if rec.outcome not in EXECUTION_OUTCOMES:
            raise ValueError(f"unknown outcome: {rec.outcome!r}")
        by_bucket[rec.offset_bucket].append(rec)

    estimates: dict[str, BucketPayoffEstimate] = {}
    for bucket, rows in by_bucket.items():
        n = len(rows)
        probs: dict[str, float] = {}
        payoffs: dict[str, float] = {}
        for o in EXECUTION_OUTCOMES:
            sub = [r for r in rows if r.outcome == o]
            probs[o] = len(sub) / n
            if not sub:
                payoffs[o] = 0.0
            elif o in ("CANCELED_UNFILLED", "EXPIRED_UNFILLED"):
                payoffs[o] = sum(
                    unfilled_mandatory_completion_cost_bps if r.mandatory_rebalance else 0.0
                    for r in sub
                ) / len(sub)
            else:
                payoffs[o] = sum(r.realized_net_bps for r in sub) / len(sub)

        exp_val = sum(probs[o] * payoffs[o] for o in EXECUTION_OUTCOMES)
        brier = 0.0
        for r in rows:
            for o in EXECUTION_OUTCOMES:
                y = 1.0 if r.outcome == o else 0.0
                brier += (probs[o] - y) ** 2
        brier /= (n * len(EXECUTION_OUTCOMES))
        estimates[bucket] = BucketPayoffEstimate(bucket, n, probs, payoffs, exp_val, brier)
    return estimates
