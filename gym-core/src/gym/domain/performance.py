"""Paper-run performance: FIFO trade ledger, risk-adjusted returns and selection-aware Sharpe tests.

Money stays exact (Decimal). Distribution statistics (volatility, Sharpe, skew) use floats, as usual.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from decimal import Decimal, localcontext
from itertools import pairwise
from random import Random
from statistics import NormalDist, fmean, median

from .model import iso, parse_ts

YEAR_SECONDS = 365 * 86400  # crypto venues trade every day
EULER = 0.5772156649015329
_N = NormalDist()


def sampled_drawdown(out):
    """Exact peak-to-trough diagnostic on recorded marks, including initial cash."""
    result = out["result"]
    initial = result.get("start_cash")
    curve = result.get("curve", [])
    if initial is None or not curve:
        return {"status": "UNAVAILABLE", "basis": "RECORDED_MARK_TO_BID"}
    initial = Decimal(initial)
    if not initial.is_finite() or initial <= 0:
        raise ValueError("invalid starting equity")
    start, cutoff = parse_ts(out["inputs"]["from"]), parse_ts(out["inputs"]["to"])
    peak, peak_at, previous = initial, start, start
    worst, peak_time, trough_time = Decimal(0), start, start
    samples = list(curve)
    if result.get("end"):
        samples.append((iso(cutoff), result["end"]["equity"]))
    for timestamp, raw in samples:
        at, equity = parse_ts(timestamp), Decimal(raw)
        if not previous <= at <= cutoff or not equity.is_finite() or equity < 0:
            raise ValueError("invalid recorded equity path")
        previous = at
        if equity > peak:
            peak, peak_at = equity, at
        loss = (peak - equity) / peak
        if loss > worst:
            worst, peak_time, trough_time = loss, peak_at, at
    return {"status": "AVAILABLE", "basis": "RECORDED_MARK_TO_BID", "samples": len(samples),
            "maximum_percent": str((worst * 100).quantize(Decimal("0.00000001"))),
            "peak_at": iso(peak_time), "trough_at": iso(trough_time),
            "peak_to_trough_seconds": (trough_time - peak_time).total_seconds(),
            "continuous_path_verified": False}


def trade_ledger(orders: list[dict], base: str) -> dict:
    """Match filled sells to earlier buys first-in-first-out.

    A buy pays `qty * price` quote and receives `qty - fee` base when its fee is in the base asset.
    A sell gives up `qty` base and receives `qty * price - fee` quote. Each filled sell becomes one
    closed trade with its own cost, proceeds, holding time and return, so scaled entries and partial
    exits are exact.
    """
    with localcontext() as context:
        context.prec = 28  # the simulator's posting precision; a caller's wider context must not split dust
        return _ledger(orders, base)


def _ledger(orders, base):
    lots: deque[list] = deque()  # [base quantity left, quote cost left, opened at]
    trades = []
    held, held_cost = Decimal(0), Decimal(0)  # average-cost view of the same position
    for order in orders:
        if order.get("status") != "FILLED":
            continue
        qty, price, fee = Decimal(order["qty"]), Decimal(order["price"]), Decimal(order["fee"])
        at = parse_ts(order["fill_time"])
        if order["side"] == "BUY":
            # Match the cash book's separate gross-credit and fee-debit postings.
            balance = held + qty
            if order.get("fee_ccy", base) == base:
                balance -= fee
            received = balance - held
            if received > 0:
                lots.append([received, qty * price, at])
                held, held_cost = balance, held_cost + qty * price
            elif lots:
                lots[-1][1] += qty * price
                held_cost += qty * price
            continue
        if qty > held:
            raise ValueError(f"sell {order.get('ref')} exceeds the quantity bought earlier")
        proceeds, left, cost, opened = qty * price - fee, qty, Decimal(0), None
        if qty == held:
            cost = sum((lot[1] for lot in lots), Decimal(0))
            opened = lots[0][2] if lots else None
            lots.clear()
            left = Decimal(0)
        while left > 0 and lots:
            lot = lots[0]
            take = min(lot[0], left)
            # A whole lot moves its exact remaining cost; only a split lot is divided.
            share = lot[1] if take == lot[0] else lot[1] * take / lot[0]
            cost += share
            lot[0] -= take
            lot[1] -= share
            left -= take
            opened = opened or lot[2]
            if lot[0] == 0:
                lots.popleft()
        if left > 0:
            raise ValueError(f"sell {order.get('ref')} exceeds the quantity bought earlier")
        average = held_cost if qty == held else held_cost * qty / held
        held, held_cost = held - qty, held_cost - average
        trades.append({"ref": order.get("ref"), "opened_at": iso(opened), "closed_at": iso(at),
                       "holding_seconds": (at - opened).total_seconds(), "quantity": str(qty),
                       "cost": str(cost), "proceeds": str(proceeds), "pnl": str(proceeds - cost),
                       "return": str((proceeds - cost) / cost) if cost else None,
                       "average_cost_pnl": str(proceeds - average)})
    open_qty = sum((lot[0] for lot in lots), Decimal(0))
    open_cost = sum((lot[1] for lot in lots), Decimal(0))
    return {"trades": trades, "open": {"quantity": str(open_qty), "cost": str(open_cost),
                                       "opened_at": iso(lots[0][2]) if lots else None}}


def _moments(returns: list[float]) -> tuple[float, float, float, float]:
    """Mean, sample standard deviation, skewness and (non-excess) kurtosis."""
    n = len(returns)
    mu = fmean(returns)
    deviations = [r - mu for r in returns]
    var = sum(d * d for d in deviations) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return mu, 0.0, 0.0, 3.0
    m2 = sum(d * d for d in deviations) / n
    skew = sum(d ** 3 for d in deviations) / n / m2 ** 1.5
    kurt = sum(d ** 4 for d in deviations) / n / m2 ** 2
    return mu, sd, skew, kurt


def probabilistic_sharpe(sharpe: float, observations: int, skew: float, kurtosis: float, benchmark: float = 0.0) -> float | None:
    """Probability the true per-period Sharpe exceeds `benchmark` (Bailey & Lopez de Prado, 2012)."""
    if observations < 3:
        return None
    spread = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2
    if spread <= 0:
        return None
    return _N.cdf((sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(spread))


def expected_max_sharpe(trials: int, sharpe_variance: float) -> float:
    """Sharpe the best of `trials` unskilled strategies reaches by luck alone (per period)."""
    if trials < 2 or sharpe_variance <= 0:
        return 0.0
    return math.sqrt(sharpe_variance) * ((1 - EULER) * _N.inv_cdf(1 - 1 / trials)
                                         + EULER * _N.inv_cdf(1 - 1 / (trials * math.e)))


def deflated_sharpe(sharpe: float, observations: int, skew: float, kurtosis: float,
                    trials: int, sharpe_variance: float) -> float | None:
    """Probabilistic Sharpe against the luck threshold of picking the best of `trials` candidates."""
    return probabilistic_sharpe(sharpe, observations, skew, kurtosis, expected_max_sharpe(trials, sharpe_variance))


def _exposure(orders: list[dict], start: datetime, end: datetime, base: str) -> float | None:
    """Share of the window with a nonzero position, from fills alone."""
    span = (end - start).total_seconds()
    if span <= 0:
        return None
    held, since, total = Decimal(0), None, 0.0
    for order in orders:
        if order.get("status") != "FILLED":
            continue
        at = parse_ts(order["fill_time"])
        qty, fee = Decimal(order["qty"]), Decimal(order["fee"])
        change = qty - (fee if order.get("fee_ccy", base) == base else 0) if order["side"] == "BUY" else -qty
        if held <= 0 < held + change:
            since = at
        elif held > 0 >= held + change and since is not None:
            total += (at - since).total_seconds()
            since = None
        held += change
    if held > 0 and since is not None:
        total += (end - since).total_seconds()
    return min(1.0, total / span)


def _bootstrap(returns: list[float], seed: int = 0) -> dict:
    """90% stationary-block bootstrap ranges for per-period Sharpe and compounded return.

    Fixed seed, so a run always shows the same range. Blocks keep short-range dependence; the mean
    block length is the cube root of the sample size.
    """
    n = len(returns)
    sims = max(100, min(500, 400_000 // n))
    block = max(1, round(n ** (1 / 3)))
    rng, sharpes, totals = Random(seed), [], []
    for _ in range(sims):
        sample, index = [], rng.randrange(n)
        for _ in range(n):
            sample.append(returns[index])
            index = rng.randrange(n) if rng.random() < 1 / block else (index + 1) % n
        mu = fmean(sample)
        sd = math.sqrt(sum((r - mu) ** 2 for r in sample) / (n - 1))
        sharpes.append(mu / sd if sd else 0.0)
        totals.append(math.prod(1 + r for r in sample) - 1)
    sharpes.sort()
    totals.sort()
    low, high = int(0.05 * (sims - 1)), int(0.95 * (sims - 1))
    return {"simulations": sims, "mean_block": block, "sharpe_per_period": [sharpes[low], sharpes[high]],
            "total_return": [totals[low], totals[high]]}


def _benchmark(record: dict, periods_per_year: float | None) -> dict | None:
    """Strategy against holding the base asset over the same equity marks (bid at each decision)."""
    bids = {d["t"]: float(d["bid"]) for d in record["result"].get("decisions", []) if d.get("bid")}
    marks = [(t, float(v), bids[t]) for t, v in record["result"].get("curve", []) if t in bids]
    pairs = [(e1 / e0 - 1, b1 / b0 - 1) for (_, e0, b0), (_, e1, b1) in pairwise(marks) if e0 > 0 and b0 > 0]
    if len(pairs) < 3:
        return None
    strat, bench = [p[0] for p in pairs], [p[1] for p in pairs]
    ms, mb = fmean(strat), fmean(bench)
    var_b = sum((b - mb) ** 2 for b in bench) / (len(bench) - 1)
    cov = sum((s - ms) * (b - mb) for s, b in pairs) / (len(pairs) - 1)
    active = [s - b for s, b in pairs]
    tracking = math.sqrt(sum((a - fmean(active)) ** 2 for a in active) / (len(active) - 1))
    sd_s = math.sqrt(sum((s - ms) ** 2 for s in strat) / (len(strat) - 1))
    beta = cov / var_b if var_b else None
    alpha = ms - beta * mb if beta is not None else None
    return {"name": f"hold {record['result'].get('base', 'base asset')}", "periods": len(pairs), "beta": beta,
            "alpha_per_period": alpha,
            "alpha_annualized": alpha * periods_per_year if alpha is not None and periods_per_year else None,
            "correlation": cov / (sd_s * math.sqrt(var_b)) if sd_s and var_b else None,
            "tracking_error_per_period": tracking,
            "information_ratio_per_period": fmean(active) / tracking if tracking else None}


def market_open_annualization(start: datetime, end: datetime, step_seconds: float, skipped: list[dict]) -> dict:
    """Use recorded effective venue closure gaps, never missing-data gaps, for annualization."""
    from .model import parse_ts

    span = (end - start).total_seconds()
    if span <= 0 or step_seconds <= 0 or not math.isfinite(step_seconds):
        return {"status": "UNAVAILABLE"}
    cuts = []
    for row in skipped:
        if row.get("reason") != "VENUE_CLOSED":
            continue
        a, b = parse_ts(row["from"]), parse_ts(row["to"])
        if not a < b:
            raise ValueError("invalid recorded trading closure")
        left, right = max(a, start), min(b, end)
        if left < right:
            cuts.append((left, right))
    cuts.sort()
    merged = []
    for left, right in cuts:
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    closed = sum((right - left).total_seconds() for left, right in merged)
    opened = span - closed
    if opened <= 0:
        return {"status": "NOT_ENOUGH_DATA", "calendar_span_seconds": span,
                "closed_seconds": closed}
    open_share = opened / span
    return {"status": "AVAILABLE", "calendar_span_seconds": span,
            "closed_seconds": closed, "open_seconds": opened,
            "open_share": open_share, "observed_closure_intervals": len(merged),
            "periods_per_year": YEAR_SECONDS * open_share / step_seconds,
            "closure_basis": "Only causally recorded VENUE_CLOSED intervals; missing quote buckets are not closure."}


def minimum_track_record_length(sharpe: float, skew: float, kurtosis: float, *,
                                benchmark: float = 0.0, confidence: float = 0.95) -> float | None:
    """Bailey/Lopez de Prado minimum observations for a one-sided Sharpe claim."""
    if not math.isfinite(sharpe) or sharpe <= benchmark or not 0.5 < confidence < 1:
        return None
    spread = 1 - skew * sharpe + (kurtosis - 1) * sharpe ** 2 / 4
    if not math.isfinite(spread) or spread <= 0:
        return None
    return 1 + spread * (_N.inv_cdf(confidence) / (sharpe - benchmark)) ** 2


def _lo_factor(returns: list[float], periods_per_year: float, max_lags: int = 20) -> tuple[float | None, int]:
    """Lo (2002) long-run variance with measured lags, zero beyond the capped sample."""
    if len(returns) < 3 or periods_per_year <= 0 or max_lags < 1:
        return None, 0
    avg = fmean(returns)
    centered = [r - avg for r in returns]
    total = sum(r * r for r in centered)
    if total <= 0:
        return None, 0
    lags = min(max_lags, len(returns) - 1, max(0, math.ceil(periods_per_year) - 1))
    factor = periods_per_year + 2 * sum(
        (periods_per_year - k) * sum(centered[j] * centered[j - k] for j in range(k, len(centered))) / total
        for k in range(1, lags + 1)
    )
    return (factor if factor > 0 else None), lags


def lo_annualized_sharpe(returns: list[float], periods_per_year: float, max_lags: int = 20) -> float | None:
    """Autocorrelation-adjusted Sharpe; lag truncation is disclosed in enhanced reports."""
    if len(returns) < 3:
        return None
    mu, sd, _, _ = _moments(returns)
    factor, _ = _lo_factor(returns, periods_per_year, max_lags)
    return mu / sd * periods_per_year / math.sqrt(factor) if sd and factor else None


def _sharpe_block(returns: list[float], periods_per_year: float | None, *, enhanced: bool = False) -> dict:
    mu, sd, skew, kurt = _moments(returns)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / len(returns))
    sharpe = mu / sd if sd else None
    scale = math.sqrt(periods_per_year) if periods_per_year else None
    result = {
        "periods": len(returns), "mean_return": mu, "volatility": sd, "skew": skew, "kurtosis": kurt,
        "sharpe_per_period": sharpe,
        "sharpe_annualized": sharpe * scale if sharpe is not None and scale else None,
        "sortino_annualized": mu / downside * scale if downside and scale else None,
        "volatility_annualized": sd * scale if scale else None,
        "probabilistic_sharpe": probabilistic_sharpe(sharpe, len(returns), skew, kurt) if sharpe is not None else None,
    }
    if enhanced:
        minimum = minimum_track_record_length(sharpe, skew, kurt) if sharpe is not None else None
        factor, used = _lo_factor(returns, periods_per_year) if periods_per_year else (None, 0)
        result.update(minimum_track_record=minimum,
                      track_record_status="SUFFICIENT" if minimum is not None and len(returns) >= minimum
                      else "NOT_ENOUGH_DATA",
                      sharpe_annualized_lo=lo_annualized_sharpe(returns, periods_per_year) if periods_per_year else None,
                      lo_lags_used=used, lo_lags_truncated=bool(periods_per_year and used < periods_per_year - 1),
                      lo_method="autocorrelation/20-lag-cap" if factor else "UNAVAILABLE")
    return result


def performance(record: dict, drawdown: dict | None = None, *, enhanced: bool = False) -> dict:
    """Risk, return and trade statistics for one saved paper run."""
    result, inputs = record["result"], record["inputs"]
    if result.get("start_cash") is None:
        return {"status": "UNAVAILABLE", "ledger": []}
    start, end = parse_ts(inputs["from"]), parse_ts(inputs["to"])
    cash = Decimal(result["start_cash"])
    final = result.get("end") if (result.get("end") or {}).get("equity") is not None else None
    out: dict = {"status": "AVAILABLE", "currency": result["quote"], "starting_cash": str(cash), "window_days": (end - start).total_seconds() / 86400}

    # Equity path: starting cash, each recorded mark, then the end mark.
    points = [(start, cash)] + [(parse_ts(t), Decimal(v)) for t, v in result.get("curve", [])]
    if final:
        points.append((parse_ts(final["mark_time"]), Decimal(final["equity"])))
    returns = [float(b / a - 1) for (_, a), (_, b) in pairwise(points) if a > 0]
    gaps = sorted((tb - ta).total_seconds() for (ta, _), (tb, _) in pairwise(points) if tb > ta)
    periods_per_year = YEAR_SECONDS / median(gaps) if gaps else None
    open_calendar = (market_open_annualization(start, end, median(gaps),
                     result.get("session", {}).get("skipped", []))
                     if enhanced and gaps else None)
    if enhanced and open_calendar and open_calendar["status"] == "AVAILABLE":
        periods_per_year = open_calendar["periods_per_year"]
        out["market_open_annualization"] = open_calendar
    if final:
        total = Decimal(final["equity"]) / cash - 1
        out["total_return_pct"] = str((total * 100).quantize(Decimal("0.0001")))
        years = (end - start).total_seconds() / YEAR_SECONDS
        # Compounding a few days to a year exaggerates; report it only for windows of 30+ days.
        out["annualized_return_pct"] = str(round(((1 + float(total)) ** (1 / years) - 1) * 100, 4)) if years >= 30 / 365 and total > -1 else None
    # Annualizing a few days of marks turns noise into extreme ratios; per-period Sharpe and P(Sharpe>0) stay honest.
    long_enough = (end - start).total_seconds() >= 30 * 86400
    out["returns"] = _sharpe_block(returns, periods_per_year if long_enough else None, enhanced=enhanced) if len(returns) >= 3 else None
    if len(returns) >= 20:
        out["returns"]["bootstrap_90"] = _bootstrap(returns)
    out["benchmark"] = _benchmark(record, periods_per_year if long_enough else None)
    if drawdown and drawdown.get("status") == "AVAILABLE":
        out["max_drawdown_pct"] = drawdown["maximum_percent"]
        if out.get("annualized_return_pct") is not None and Decimal(drawdown["maximum_percent"]) > 0:
            out["calmar"] = round(float(out["annualized_return_pct"]) / float(drawdown["maximum_percent"]), 4)

    ledger = trade_ledger(result.get("orders", []), result.get("base") or "")
    trades = ledger["trades"]
    pnls = [Decimal(t["pnl"]) for t in trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins, Decimal(0)), -sum(losses, Decimal(0))
    streak = longest = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        longest = max(longest, streak)
    filled = [o for o in result.get("orders", []) if o.get("status") == "FILLED"]
    turnover = sum((Decimal(o["qty"]) * Decimal(o["price"]) for o in filled), Decimal(0))
    stats = {
        "closed_trades": len(trades), "winning": len(wins), "losing": len(losses),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "average_win": str(gross_win / len(wins)) if wins else None,
        "average_loss": str(-gross_loss / len(losses)) if losses else None,
        "profit_factor": round(float(gross_win / gross_loss), 4) if gross_loss else None,
        "expectancy": str(sum(pnls, Decimal(0)) / len(pnls)) if pnls else None,
        "realized_pnl": str(sum(pnls, Decimal(0))),
        "average_cost_realized_pnl": str(sum((Decimal(t["average_cost_pnl"]) for t in trades), Decimal(0))),
        "average_holding_hours": round(fmean(t["holding_seconds"] for t in trades) / 3600, 3) if trades else None,
        "longest_losing_streak": longest,
        "turnover": str((turnover / cash).quantize(Decimal("0.0001"))),
        "exposure": _exposure(filled, start, end, result.get("base") or ""),
        "open_position": ledger["open"],
    }
    if wins and losses and len(trades) >= 20:
        win_rate, payoff = len(wins) / len(trades), float(gross_win / len(wins)) / float(gross_loss / len(losses))
        stats["kelly_fraction"] = round(max(0.0, win_rate - (1 - win_rate) / payoff), 4)
    out["trades"] = stats
    out["ledger"] = trades
    return out


def selection_check(candidates: dict[str, dict], trials: int | None = None) -> dict | None:
    """Deflated Sharpe for the best of several candidates evaluated on the same data.

    `trials` counts every configuration tried before on this market, not only these candidates; the
    Sharpe dispersion still comes from the candidates measured here.
    """
    usable = {name: p["returns"] for name, p in candidates.items()
              if p.get("returns") and p["returns"]["sharpe_per_period"] is not None}
    if len(usable) < 2:
        return None
    trials = max(len(usable), trials or 0)
    sharpes = [r["sharpe_per_period"] for r in usable.values()]
    variance = sum((s - fmean(sharpes)) ** 2 for s in sharpes) / (len(sharpes) - 1)
    best_name = max(usable, key=lambda name: usable[name]["sharpe_per_period"])
    best = usable[best_name]
    minimum = minimum_track_record_length(best["sharpe_per_period"], best["skew"], best["kurtosis"])
    return {"trials": trials, "compared": len(usable), "best": best_name, "best_sharpe_per_period": best["sharpe_per_period"],
            "luck_threshold_per_period": expected_max_sharpe(trials, variance),
            "minimum_track_record": minimum,
            "track_record_status": "SUFFICIENT" if minimum is not None and best["periods"] >= minimum else "NOT_ENOUGH_DATA",
            "deflated_sharpe": deflated_sharpe(best["sharpe_per_period"], best["periods"], best["skew"],
                                               best["kurtosis"], trials, variance)}
