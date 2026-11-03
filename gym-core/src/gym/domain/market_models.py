"""Offline Part D diagnostics. No prices here authorize or construct orders."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import re
from statistics import median

D = Decimal


def decimal(value, name="decimal", *, positive=False):
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(value.as_tuple().exponent) > 64:
            raise ValueError(f"invalid or unbounded {name}")
        value = format(value, "f")
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) or len(value) > 64:
        raise ValueError(f"{name} must be a plain finite decimal string (max 64 characters)")
    result = D(value)
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'} and finite")
    return result


def rate(value, name="rate"):
    result = decimal(value, name)
    if result >= 1:
        raise ValueError(f"{name} must be less than one")
    return result


def instant(value):
    if not isinstance(value, str) or len(value) > 40 or "T" not in value:
        raise ValueError("time must be a zoned ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid ISO time") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("time must have a zone")
    return result.astimezone(timezone.utc)


def fields(obj, names):
    if type(obj) is not dict or set(obj) != set(names.split()):
        raise ValueError(f"expected exactly these fields: {names}")


def rows(value):
    if type(value) is not list or not 1 <= len(value) <= 10000:
        raise ValueError("samples must be a nonempty list of at most 10000 rows")
    return value


def currency(value):
    if value not in ("TMN", "USDT"):
        raise ValueError("quote currency must be TMN or USDT (not IRT)")
    return value


def quote(row):
    fields(row, "at bid ask status qualified")
    at = instant(row["at"])
    bid, ask = decimal(row["bid"], "bid", positive=True), decimal(row["ask"], "ask", positive=True)
    if bid > ask:
        raise ValueError("crossed quote")
    if row["status"] not in ("OPEN", "CLOSED") or type(row["qualified"]) is not bool or not row["qualified"]:
        raise ValueError("unknown market state or unqualified sample")
    return at, bid, ask, row["status"]


def elapsed(start, end):
    delta = end - start
    return D(delta.days * 86400 + delta.seconds) + D(delta.microseconds) / D(1000000)


class LocalLiquidity:
    """EMA surprise standardized under an explicitly assumed independent null."""

    def __init__(self, alpha="0.08", overshoot_probability="0.08", dc_surprise="0.0834", overshoot_surprise="2.5257"):
        self.alpha = decimal(alpha, "alpha", positive=True)
        if self.alpha > 1:
            raise ValueError("alpha must be at most one")
        self.p = rate(overshoot_probability, "overshoot_probability")
        if not self.p:
            raise ValueError("null probability must be positive")
        self.dc = decimal(dc_surprise, "dc_surprise", positive=True)
        self.os = decimal(overshoot_surprise, "overshoot_surprise", positive=True)
        self.h1 = (1 - self.p) * self.dc + self.p * self.os
        self.h2 = (1 - self.p) * (self.dc - self.h1) ** 2 + self.p * (self.os - self.h1) ** 2
        if not self.h2:
            raise ValueError("null surprise variance must be positive")
        self.ema, self.count = self.h1, 0

    def update(self, event):
        if type(event) is not int or event not in (-2, -1, 1, 2):
            raise ValueError("event must be a DC (+/-1) or overshoot (+/-2)")
        self.ema += self.alpha * ((self.dc if abs(event) == 1 else self.os) - self.ema)
        self.count += 1
        variance = self.h2 * self.alpha / (2 - self.alpha) * (1 - (1 - self.alpha) ** (2 * self.count))
        return (self.ema - self.h1) / variance.sqrt()


def liquidity(samples, delta_up, delta_down, overshoot_step, alpha, overshoot_probability, dc_surprise, overshoot_surprise, sigma_per_sqrt_second):
    up, down, step = (decimal(x, positive=True) for x in (delta_up, delta_down, overshoot_step))
    sigma = decimal(sigma_per_sqrt_second, "sigma_per_sqrt_second", positive=True)
    model = LocalLiquidity(alpha, overshoot_probability, dc_surprise, overshoot_surprise)
    direction, extreme, next_step = -1, None, None
    events, previous, first, last, gap = [], None, None, None, False
    observed, open_samples, open_seconds = 0, 0, D(0)
    previous_open = False
    z = None
    for row in rows(samples):
        at, bid, ask, status = quote(row)
        if previous is not None and at <= previous:
            raise ValueError("samples must be strictly chronological")
        if first is None:
            first = at
        last = at
        if status == "OPEN" and previous_open:
            open_seconds += elapsed(previous, at)
        previous, previous_open = at, status == "OPEN"
        observed += 1
        if status == "CLOSED":
            gap = True
            continue
        open_samples += 1
        observed_price = bid if direction < 0 else ask
        if extreme is None:
            extreme = observed_price
        extreme = min(extreme, observed_price) if direction < 0 else max(extreme, observed_price)
        move = (observed_price / extreme).ln()
        event = 1 if direction < 0 and move >= up else -1 if direction > 0 and move <= -down else None
        emitted = []
        if event:
            direction = event
            extreme = ask if direction > 0 else bid
            next_step = extreme * (step * direction).exp()
            emitted.append(event)
        elif next_step is not None:
            # ponytail: cap gap-generated steps at 10000; use an aggregated event representation for larger gaps.
            while (bid >= next_step if direction > 0 else ask <= next_step):
                emitted.append(2 * direction)
                if len(emitted) > 10000:
                    raise ValueError("overshoot step count exceeds bound")
                next_step *= (step * direction).exp()
        for code in emitted:
            z = model.update(code)
            if len(events) >= 10000:
                raise ValueError("total event count exceeds 10000")
            events.append({"at": at.isoformat(), "event": code, "gap": gap})
        gap = False
    symmetric = up == down
    return {"observed_sample_count": observed, "open_sample_count": open_samples, "event_count": len(events),
            "dc_count": sum(abs(e["event"]) == 1 for e in events), "events": events,
            "ema_surprise": model.ema if model.count else None, "z_score": z, "H1": model.h1, "H2": model.h2,
            "alpha": model.alpha, "overshoot_probability": model.p, "dc_surprise": model.dc, "overshoot_surprise": model.os,
            "expected_dc_count": open_seconds * sigma ** 2 / up ** 2 if symmetric else None,
            "model": "driftless continuous log-GBM symmetric DC approximation; discrete quotes, spread and gaps change counts",
            "elapsed_seconds": elapsed(first, last), "observed_open_seconds": open_seconds,
            "null": "assumed independent event types; H2 is surprise variance; not calibrated or certified", "certified": False}


def roundtrip_spacing(spacing, fee_buy, fee_sell, spread, slippage_buy, slippage_sell, quote_currency):
    currency(quote_currency)
    spacing = decimal(spacing, "spacing", positive=True)
    buy, sell, spread, slip_buy, slip_sell = (rate(v) for v in (fee_buy, fee_sell, spread, slippage_buy, slippage_sell))
    modeled_cost = spread + buy + sell + slip_buy + slip_sell
    # Also require multiplicative break-even, with spread modeled as ask/bid - 1.
    break_even = (1 + spread) * (1 + slip_buy) * (1 + buy) / ((1 - slip_sell) * (1 - sell)) - 1
    threshold = max(modeled_cost, break_even)
    if spacing <= threshold:
        raise ValueError("grid/DCA spacing must be strictly greater than modeled ROUND-TRIP cost")
    return {"quote_currency": quote_currency, "spacing": spacing, "additive_roundtrip_cost": modeled_cost,
            "break_even_spacing": break_even, "required_spacing": threshold,
            "fee_buy": buy, "fee_sell": sell, "spread": spread, "slippage_buy": slip_buy, "slippage_sell": slip_sell,
            "fixture": "grid/DCA conversion-workload cost gate; not a funded strategy"}


def implied_fx(pairs, reference, as_of, max_age_seconds, max_skew_seconds):
    now = instant(as_of)
    age_limit, skew_limit = decimal(max_age_seconds), decimal(max_skew_seconds)
    times = []

    def fresh(row):
        at, bid, ask, status = quote(row)
        age = elapsed(at, now)
        if status != "OPEN" or age < 0 or age > age_limit:
            raise ValueError("FX requires fresh, nonfuture, qualified OPEN markets")
        times.append(at)
        return bid, ask

    factors, seen = [], set()
    for pair in rows(pairs):
        fields(pair, "base tmn usdt")
        base = pair["base"]
        if not isinstance(base, str) or not re.fullmatch(r"[A-Z][A-Z0-9]{1,19}", base) or base in {"TMN", "IRT", "USDT"} or base in seen:
            raise ValueError("invalid or duplicate FX base currency")
        seen.add(base)
        tb, ta = fresh(pair["tmn"])
        ub, ua = fresh(pair["usdt"])
        factors.append({"base": base, "implied_tmn_per_usdt": tb / ua, "upper_diagnostic": ta / ub})
    direct = None
    if reference is not None:
        rb, ra = fresh(reference)
        direct = (rb + ra) / 2
    if elapsed(min(times), max(times)) > skew_limit:
        raise ValueError("FX observations are not simultaneous within max_skew_seconds")
    values = [f["implied_tmn_per_usdt"] for f in factors]
    center = median(values)
    return {"factors": factors, "median_tmn_per_usdt": center, "range_dispersion": max(values) - min(values),
            "relative_dispersion": (max(values) - min(values)) / center, "reference_mid": direct,
            "relative_basis": center / direct - 1 if direct is not None else None,
            "reference_status": "OPEN" if direct is not None else "STALE_CLOSED_OR_UNAVAILABLE",
            "executable": False, "diagnostic_only": True}


def financing(product, side, quote_currency, collateral, quantity, borrowed, interest_rate, interest_period_seconds,
              entry_fee, exit_fee, maintenance_ratio, closure_liquidation, samples):
    if product not in ("MARGIN", "TRADE_CREDIT") or side not in ("LONG", "SHORT"):
        raise ValueError("product/side must be MARGIN or TRADE_CREDIT and LONG or SHORT")
    if closure_liquidation not in ("PAUSE", "CONTINUE", "UNKNOWN"):
        raise ValueError("closure_liquidation must be PAUSE, CONTINUE or UNKNOWN")
    currency(quote_currency)
    cash, units, principal = decimal(collateral), decimal(quantity, positive=True), decimal(borrowed)
    interest = decimal(interest_rate)
    period = decimal(interest_period_seconds, positive=True)
    buy_fee, sell_fee, maintenance = rate(entry_fee), rate(exit_fee), rate(maintenance_ratio)
    points = [quote(row) for row in rows(samples)]
    if points[0][3] != "OPEN":
        raise ValueError("paper entry requires an OPEN market")
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError("financing samples must be strictly chronological")
    at, bid, ask, _ = points[0]
    if side == "LONG":
        cost = units * ask * (1 + buy_fee)
        cash += principal - cost
        if cash < 0:
            raise ValueError("collateral plus borrowing cannot fund entry and fee")
    else:
        if principal != units:
            raise ValueError("SHORT must borrow exactly its sold base quantity")
        cash += units * bid * (1 - buy_fee)
        units = D(0)
    debt, accrued, history, liquidated = principal, D(0), [], False
    previous = at
    for at, bid, ask, status in points:
        # Simple interest on outstanding principal; accrued interest is not silently capitalized.
        charge = principal * interest * elapsed(previous, at) / period
        debt += charge
        accrued += charge
        previous = at
        liability = debt if side == "LONG" else debt * ask * (1 + sell_fee)
        assets = cash + units * bid * (1 - sell_fee)
        equity = assets - liability
        gross = units * bid if side == "LONG" else debt * ask
        health = equity / gross if gross else None
        breached = gross > 0 and equity <= gross * maintenance
        action = "HOLD"
        if breached and not liquidated:
            if status == "CLOSED":
                action = "LIQUIDATION_UNKNOWN" if closure_liquidation == "UNKNOWN" else "LIQUIDATION_PAUSED" if closure_liquidation == "PAUSE" else "LIQUIDATION_DUE_UNEXECUTABLE"
            else:
                action, liquidated = "PAPER_LIQUIDATION", True
                if side == "LONG":
                    cash += units * bid * (1 - sell_fee)
                    units = D(0)
                    repaid = min(cash, debt)
                else:
                    covered = min(debt, cash / (ask * (1 + sell_fee)))
                    repaid = covered
                    cash -= covered * ask * (1 + sell_fee)
                old_debt = debt
                if side == "LONG":
                    cash -= repaid
                debt -= repaid
                principal *= debt / old_debt if old_debt else D(0)
                liability = debt if side == "LONG" else debt * ask * (1 + sell_fee)
                assets = cash + units * bid * (1 - sell_fee)
                equity = assets - liability
                gross = units * bid if side == "LONG" else debt * ask
                health = equity / gross if gross else None
        history.append({"at": at.isoformat(), "status": status, "cash": cash, "base_units": units,
                        "debt_units": debt, "liability_quote": liability, "equity_quote": equity,
                        "health_equity_to_gross": health, "maintenance_breached": breached,
                        "action": action, "paper_send_allowed": status == "OPEN", "order_submitted": False})
    return {"product": product, "side": side, "quote_currency": quote_currency,
            "debt_currency": quote_currency if side == "LONG" else "BASE", "interest_accrued_units": accrued,
            "interest_rate": interest, "interest_period_seconds": period, "maintenance_ratio": maintenance,
            "entry_fee": buy_fee, "exit_fee": sell_fee, "closure_liquidation": closure_liquidation,
            "history": history, "venue_terms_verified": False,
            "assumptions": "simple interest on remaining principal; quote fees; mark/close long at bid and short at ask; no top-up; closed markets never send"}


def evaluate_artifact(artifact):
    fields(artifact, "model parameters")
    models = {"liquidity": liquidity, "spacing": roundtrip_spacing, "fx": implied_fx, "financing": financing}
    name = artifact["model"]
    if not isinstance(name, str) or name not in models:
        raise ValueError("unknown paper market model")
    import inspect
    function = models[name]
    fields(artifact["parameters"], " ".join(inspect.signature(function).parameters))
    # Money remains Decimal throughout; transcendental diagnostics alone are rounded by Decimal.
    with localcontext() as context:
        context.prec = 160
        result = function(**artifact["parameters"])
    return {"mode": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
            "model": name, "result": result}
