"""Offline daily spot EWMAC replay with a matched zero-yield quote-cash account."""
from datetime import timedelta
from decimal import Decimal
from math import sqrt
from statistics import stdev

from .market_models import currency, decimal, fields, instant, rate
from .portfolio import rebalance_preview
from .research_prototypes import (
    edge_of_band_target,
    ewmac_forecast,
    vol_target_position,
)


def trend_replay(packet, as_of):
    fields(packet, "symbol quote_currency cash quantity_step minimum_quote fee_rate band observations")
    quote = currency(packet["quote_currency"])
    cash = initial = decimal(packet["cash"], "cash", positive=True)
    fee = rate(packet["fee_rate"], "fee_rate")
    band = rate(packet["band"], "band")
    observations = packet["observations"]
    if type(observations) is not list or not 258 <= len(observations) <= 4096:
        raise ValueError("need 258..4096 consecutive daily bid/ask observations")
    bids, asks, times = [], [], []
    for row in observations:
        fields(row, "at bid ask")
        at = instant(row["at"])
        bid = decimal(row["bid"], "bid", positive=True)
        ask = decimal(row["ask"], "ask", positive=True)
        if bid > ask or at > as_of or (times and at - times[-1] != timedelta(days=1)):
            raise ValueError("need uncrossed quotes at consecutive completed daily instants")
        bids.append(bid)
        asks.append(ask)
        times.append(at)
    prices = list(map(float, bids))
    forecasts = ewmac_forecast(prices)
    returns = [cur / prev - 1 for prev, cur in zip(prices, prices[1:])]
    held = fees = turnover = Decimal(0)
    decisions = []
    for i in range(257, len(times)):
        signal = i - 1
        # Return k ends at close k+1. Exclude the signal day's return.
        vol = stdev(returns[signal - 37:signal - 1]) * sqrt(365)
        cost = 1 - bids[signal] / asks[signal] * (1 - fee) ** 2
        sizing = vol_target_position(forecasts[signal], vol, roundtrip_cost_bps=float(cost * 10000))
        weight = max(Decimal(0), Decimal(sizing["weight"]))
        equity = cash + held * bids[i]
        edge = edge_of_band_target(held * bids[i] / equity, weight, band)
        position = {k: packet[k] for k in ("symbol", "quantity_step", "minimum_quote")}
        position.update(held=held, reserved="0", bid=bids[i], ask=asks[i], target_weight=edge["new_weight"])
        plan = rebalance_preview(dict(quote_currency=quote, cash=cash, reserved_cash="0",
                                      fee_rate=fee, positions=[position]))
        legs = plan["legs"] if edge["trade"] else []
        if edge["trade"]:
            cash = Decimal(plan["conditional_remaining_cash"])
            held = Decimal(plan["concentration"][0]["conditional_held"])
            turnover += Decimal(plan["turnover_quote"])
            for leg in legs:
                if leg["status"] == "PLANNED":
                    fees += Decimal(leg["fee_amount"]) * (asks[i] if leg["side"] == "BUY" else 1)
        decisions.append(dict(signal_at=times[signal].isoformat(), execution_at=times[i].isoformat(),
                              forecast=forecasts[signal], prior_annual_vol=vol, sizing=sizing["status"],
                              target_weight=str(weight), band_target=str(edge["new_weight"]), legs=legs,
                              cash=str(cash), held=str(held)))
    equity = cash + held * bids[-1]
    return dict(schema="trend-replay/1", symbol=packet["symbol"], quote_currency=quote,
                decisions=decisions, terminal_bid_equity=str(equity), cash_benchmark=str(initial),
                excess_quote=str(equity - initial), turnover_quote=str(turnover), fees_quote=str(fees),
                registered_trial=False, funded_authority=False)
