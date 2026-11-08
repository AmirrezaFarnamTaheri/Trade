"""Volume-aware, bounded retrospective TWAP proposals. No venue order authority."""
from bisect import bisect_left
from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise

from ..domain.bars import qualified
from ..domain.market_models import rate
from ..domain.model import iso
from ..domain.strategy import digest
from .paper_twap import _floor, simulate_twap

MAX_OBSERVATIONS = 100000


def _slice_cost(child, top, fee):
    """Quote-equivalent modeled one-way spread, excess impact and fee on a paper fill."""
    if child["status"] == "NONFILL" or top is None:
        return None
    qty = Decimal(child["filled_quantity"])
    price = Decimal(child["price"])
    applied = Decimal(child.get("pricing", {}).get("applied_fee_rate", str(fee)))
    midpoint = (top.bid + top.ask) / 2
    return str(+(qty * (abs(price - midpoint) + price * applied)))


def adaptive_twap(instrument, quotes, trades, spec, start, end, *, side, quantity, slices,
                  participation, fee_rate, available_quote, available_base,
                  max_delay_seconds, store, cost=None, volume_lookback_seconds=300,
                  max_spread_bps=Decimal(20), urgency="NORMAL"):
    """Plan only from earlier public print volume and quotes; replay fills separately.

    A passive LIMIT proposal never claims a fill without queue/trade-through
    evidence. Its unfilled amount may be re-attempted at the next independent
    slot. Fills are retrospective outcomes, never a decision-time prediction.
    """
    if (type(slices) is not int or not 1 <= slices <= 100
            or type(volume_lookback_seconds) is not int or not 60 <= volume_lookback_seconds <= 3600
            or urgency not in ("NORMAL", "FINISH") or side not in ("BUY", "SELL")
            or store not in ("live", "demo") or type(max_spread_bps) is not Decimal
            or not max_spread_bps.is_finite() or not 0 <= max_spread_bps <= 10000):
        raise ValueError("invalid adaptive TWAP controls")
    if (type(quantity) is not Decimal or not quantity.is_finite() or quantity <= 0
            or type(participation) is not Decimal or not participation.is_finite()
            or not 0 < participation <= 1
            or any(type(x) is not Decimal or not x.is_finite() or x < 0
                   for x in (available_quote, available_base))):
        raise ValueError("invalid adaptive TWAP monetary fields")
    if (not start < end or end - start > timedelta(days=1)
            or type(max_delay_seconds) is not int or not 0 <= max_delay_seconds <= 3600):
        raise ValueError("invalid adaptive TWAP duration")
    fee = rate(str(fee_rate))
    if cost is not None:
        cost.assert_causal(start)
    if (len(quotes) > MAX_OBSERVATIONS or len(trades) > MAX_OBSERVATIONS
            or any(q.symbol != instrument.symbol for q in quotes)
            or any(t.symbol != instrument.symbol for t in trades)
            or any(a.ts_avail > b.ts_avail for a, b in pairwise(quotes))
            or any(a.ts_avail > b.ts_avail for a, b in pairwise(trades))
            or any(q.ts_avail < start - timedelta(seconds=volume_lookback_seconds)
                   or q.ts_avail >= end for q in quotes)
            or any(t.ts_avail < start - timedelta(seconds=volume_lookback_seconds)
                   or t.ts_avail >= end or not t.qty.is_finite() or t.qty <= 0 for t in trades)):
        raise ValueError("invalid or excessive adaptive TWAP observations")

    in_window = [q for q in quotes if q.ts_avail >= start]
    baseline = simulate_twap(instrument, in_window, spec, start, end, side=side,
                             quantity=quantity, slices=slices, participation=participation,
                             fee_rate=fee, available_quote=available_quote,
                             available_base=available_base, max_delay_seconds=max_delay_seconds,
                             store=store, cost=cost)
    times = [q.ts_avail for q in quotes]
    cash, base, filled = available_quote, available_base, Decimal(0)
    children = []
    with localcontext() as context:
        context.prec = 80
        for i in range(slices):
            slot = start + (end - start) * i / slices
            next_slot = start + (end - start) * (i + 1) / slices
            prior_index = bisect_left(times, slot) - 1
            prior = quotes[prior_index] if prior_index >= 0 else None
            volume = sum((t.qty for t in trades
                          if slot - timedelta(seconds=volume_lookback_seconds) <= t.ts_avail < slot), Decimal(0))
            target = _floor(min(max(Decimal(0), quantity - filled), volume * participation),
                            spec.qty_decimals)
            if target <= 0:
                target = Decimal(0)
            kind = "NONE"
            observed = prior is not None and qualified(prior) and "CLOSED" not in prior.flags and (
                slot - prior.ts_avail <= timedelta(seconds=120))
            # Report the blocking observation distinctly: missing prior quote
            # takes precedence when volume and price are both unavailable.
            status = "NO_PRIOR_VOLUME" if observed and not target else "NO_PRIOR_QUOTE"
            preview = None
            if target > 0 and observed:
                spread_bps = (prior.ask - prior.bid) / ((prior.ask + prior.bid) / 2) * 10000
                kind = "MARKET" if spread_bps <= max_spread_bps or urgency == "FINISH" and i == slices - 1 else "LIMIT"
                if kind == "LIMIT":
                    status = "NONFILL_LIMIT_QUEUE_UNKNOWN"
                else:
                    preview = simulate_twap(instrument,
                        [q for q in in_window if slot <= q.ts_avail < next_slot],
                        spec, slot, next_slot, side=side, quantity=target, slices=1,
                        participation=participation, fee_rate=fee, available_quote=cash,
                        available_base=base, max_delay_seconds=max_delay_seconds,
                        store=store, cost=cost)
                    status = preview["children"][0]["status"]
                    cash, base = Decimal(preview["remaining_quote"]), Decimal(preview["remaining_base"])
                    filled += Decimal(preview["filled_quantity"])
            child = preview["children"][0] if preview is not None else None
            marker = next((q for q in in_window if slot <= q.ts_avail < next_slot), None)
            children.append({
                "slice": i + 1, "scheduled_at": iso(slot),
                "decision_quote_at": iso(prior.ts_avail) if observed else None,
                "observed_prior_volume_base": str(+volume),
                "volume_cap_base": str(+(volume * participation)),
                "order_type": kind, "requested_quantity": str(target),
                "filled_quantity": child["filled_quantity"] if child else "0",
                "status": status,
                "fill_observation_at": child["observation_at"] if child else None,
                "modeled_price": child["price"] if child else None,
                "modeled_one_way_cost_quote": _slice_cost(child, marker, fee) if child else None,
                "pricing": child.get("pricing") if child else None,
                "queue_model": "NOT_MODELED" if kind == "LIMIT" else None,
            })
        benchmark_costs = []
        for i, child in enumerate(baseline["children"]):
            slot = start + (end - start) * i / slices
            marker = next((q for q in in_window if q.ts_avail >= slot), None)
            benchmark_costs.append(_slice_cost(child, marker, fee))
        comparable = (filled == quantity and Decimal(baseline["filled_quantity"]) == quantity)
        adaptive_cost = sum((Decimal(row["modeled_one_way_cost_quote"])
                             for row in children if row["modeled_one_way_cost_quote"] is not None), Decimal(0))
        equal_cost = sum((Decimal(x) for x in benchmark_costs if x is not None), Decimal(0))
        out = {
            "schema": "paper-volume-twap/1", "authority": "PAPER_ONLY",
            "funded_authority": False, "order_submitted": False, "cancel_submitted": False,
            "store": store, "symbol": instrument.symbol, "side": side,
            "from": iso(start), "to_exclusive": iso(end),
            "requested_quantity": str(quantity), "filled_quantity": str(filled),
            "cancelled_quantity": str(+(quantity - filled)),
            "participation": str(participation), "volume_lookback_seconds": volume_lookback_seconds,
            "max_spread_bps": str(max_spread_bps), "urgency": urgency,
            "remaining_quote": str(cash), "remaining_base": str(base), "children": children,
            "equal_slice_reference": baseline, "equal_slice_costs_quote": benchmark_costs,
            "cost_comparison": {
                "status": "FULL_FILL_RETROSPECTIVE" if comparable else "NOT_COMPARABLE",
                "reason": None if comparable else "UNEQUAL_OR_PARTIAL_FILL",
                "adaptive_cost_quote": str(+adaptive_cost) if comparable else None,
                "equal_slice_cost_quote": str(+equal_cost) if comparable else None,
                "model": "observed half-spread, fee and optional dated impact, paper only"},
            "almgren_chriss": "NOT_ENABLED_NO_SIGNIFICANT_INDEPENDENT_IMPACT_FIT",
            "limitations": [
                "Past printed volume caps an attempted child; it does not imply future available liquidity.",
                "Passive limits never fill without independent queue evidence.",
                "Post-slot quote fills and modeled costs are retrospective, not start-time predictions.",
                "Missing quantity expires at the window end, without placement, cancellation or retry authority.",
                "Cost comparisons are only meaningful when both schedules fill the same full requested quantity.",
            ],
        }
        out["report_id"] = digest(out)[:16]
        return out
