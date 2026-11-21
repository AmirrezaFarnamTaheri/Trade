"""1x margin vs spot reconciliation and Wallex token tradability/proxy diagnostics (C005, C013-C016)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .bars import qualified
from .execution_qualification import depth_walk_liquidation
from .model import BookTop, iso


def reconcile_1x_margin_vs_spot(
    *,
    spot_net_quote: Decimal,
    margin_net_quote: Decimal,
    margin_opening_fee: Decimal,
    margin_extension_fees: Decimal,
    trade_fee_diff: Decimal = Decimal(0),
) -> dict:
    """Reconcile 1x margin long vs 1x spot on identical quotes, isolating financing & opening fee drag (C005)."""
    expected_margin = spot_net_quote - margin_opening_fee - margin_extension_fees - trade_fee_diff
    residual = margin_net_quote - expected_margin
    return {
        "spot_net_quote": str(spot_net_quote),
        "margin_1x_net_quote": str(margin_net_quote),
        "financing_and_fee_drag": str(margin_opening_fee + margin_extension_fees + trade_fee_diff),
        "reconciliation_residual": str(residual),
        "reconciled": residual == 0,
    }


def evaluate_token_tradability(
    symbol: str,
    *,
    latest_candle_day: datetime | None,
    latest_quote: BookTop | None,
    exit_qty: Decimal,
    fee_rate: Decimal,
    reference_proxy_price: Decimal | None = None,
    spec: dict | None = None,
    now: datetime | None = None,
    max_candle_stale_days: int = 3,
    max_quote_age_seconds: int = 300,
) -> dict:
    """Evaluate authentic Wallex token tradability, premium vs proxy, and liquidation depth without backfilling (C013-C016)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    issues = []
    if latest_candle_day is None:
        issues.append("NO_VENUE_CANDLES")
    elif at - latest_candle_day > timedelta(days=max_candle_stale_days):
        issues.append("STALE_VENUE_CANDLES")

    if latest_quote is None:
        issues.append("MISSING_VENUE_QUOTE")
    elif not qualified(latest_quote) or (at - latest_quote.ts_avail).total_seconds() > max_quote_age_seconds:
        issues.append("STALE_OR_UNQUALIFIED_QUOTE")

    premium_bps = None
    if latest_quote is not None and reference_proxy_price is not None and reference_proxy_price > 0:
        mid = (latest_quote.bid + latest_quote.ask) / 2
        premium_bps = str(((mid / reference_proxy_price - 1) * 10000).quantize(Decimal("0.01")))

    liquidation = None
    if latest_quote is not None and exit_qty > 0:
        levels = latest_quote.depth[0] if latest_quote.depth else ((latest_quote.bid, latest_quote.bid_qty),)
        liquidation = depth_walk_liquidation("SELL", exit_qty, levels, fee_rate=fee_rate, quote_at=latest_quote.ts_avail)
        if liquidation["status"] != "FULL":
            issues.append("INSUFFICIENT_EXIT_DEPTH")

    if spec is not None and latest_quote is not None and exit_qty > 0:
        min_notional = Decimal(str(spec.get("minNotional", "0")))
        if exit_qty * latest_quote.bid < min_notional:
            issues.append("BELOW_MIN_NOTIONAL")

    return {
        "symbol": symbol,
        "as_of": iso(at),
        "tradable": not issues,
        "status": "TRADABLE_PAPER_OBSERVED" if not issues else "UNTRADEABLE_OR_STALE",
        "issues": issues,
        "wallex_premium_vs_proxy_bps": premium_bps,
        "liquidation_estimate": liquidation,
        "corporate_actions_modeled": False,
        "backfilled_from_proxy": False,
        "proxy_limitation": "Reference ETF/futures prices never establish Wallex token liquidity, dividends, halts, or settlement.",
    }
