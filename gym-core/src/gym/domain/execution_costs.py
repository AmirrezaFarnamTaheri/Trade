"""Bounded, opt-in square-root public-print impact and intraday cost assumptions.

Public prints can estimate a price-impact *proxy*, never actual authenticated
execution quality. No model is silently enabled in a paper replay.
"""
import re
from datetime import datetime
from decimal import Decimal, localcontext
from statistics import median

from .model import TEHRAN, parse_ts

_SOURCE = "PUBLIC_TRADE_VS_PRIOR_MID_PROXY"


def _number(value, label, *, positive=False):
    """Parse a finite, nonnegative Decimal, with optional strict positivity."""
    if type(value) not in (str, Decimal, int):
        raise ValueError("invalid " + label)
    try:
        number = Decimal(value)
    except (ValueError, ArithmeticError):
        raise ValueError("invalid " + label) from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError("invalid " + label)
    return number


def _regression(rows):
    """Fit bounded nonnegative linear coefficients from explanatory observations."""
    xx = xz = zz = xy = zy = Decimal(0)
    for x, z, y in rows:
        xx += x * x
        xz += x * z
        zz += z * z
        xy += x * y
        zy += z * y
    determinant = xx * zz - xz * xz
    if determinant <= Decimal("1e-36"):
        return None
    a, b = (xy * zz - zy * xz) / determinant, (zy * xx - xy * xz) / determinant
    candidates = [(max(a, Decimal(0)), max(b, Decimal(0))),
                  (max(xy / xx, Decimal(0)), Decimal(0)) if xx else (Decimal(0), Decimal(0)),
                  (Decimal(0), max(zy / zz, Decimal(0))) if zz else (Decimal(0), Decimal(0))]
    return min(candidates, key=lambda p: sum(((y - p[0] * x - p[1] * z) ** 2 for x, z, y in rows), Decimal(0)))


def fit_square_root_impact(symbol, samples, *, trained_until: datetime):
    """Fit nonnegative a,b from pre-cutoff independent public trade-print proxies.

    Split chronologically 80/20; the last 20% is *never* used in fitting.
    A nonidentifiable design or too few samples returns an unavailable status.
    """
    if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
            or trained_until.tzinfo is None or type(samples) not in (list, tuple)
            or len(samples) > 100000):
        raise ValueError("invalid impact calibration request")
    if len(samples) < 30:
        return {"status": "INSUFFICIENT_DATA", "sample_count": len(samples),
                "symbol": symbol, "source": _SOURCE}
    with localcontext() as context:
        context.prec = 60
        rows = []
        for sample in samples:
            if type(sample) is not dict:
                raise ValueError("invalid independent impact sample")
            spread = _number(sample["spread_bps"], "spread")
            sigma = _number(sample["volatility_bps"], "volatility", positive=True)
            qty = _number(sample["quantity"], "quantity", positive=True)
            volume = _number(sample["volume_base"], "historical base volume", positive=True)
            cost = Decimal(sample["observed_cost_bps"])
            if not cost.is_finite() or qty > volume:
                raise ValueError("invalid independent impact sample")
            rows.append((spread / 2, sigma * (qty / volume).sqrt(), cost,
                         qty, volume, sigma))
        count = len(rows)
        train_count = count * 4 // 5
        train = [row[:3] for row in rows[:train_count]]
        estimate = _regression(train)
        if estimate is None:
            return {"status": "UNIDENTIFIABLE", "sample_count": count, "symbol": symbol,
                    "source": _SOURCE}
        a, b = estimate
        if max(a, b) > 100:
            return {"status": "OUT_OF_RANGE", "sample_count": count, "symbol": symbol,
                    "source": _SOURCE}
        rmse = lambda subset: (sum(((y - a * x - b * z) ** 2 for x, z, y in subset),
                                   Decimal(0)) / len(subset)).sqrt()
        fit_error = rmse(train)
        holdout_error = rmse([row[:3] for row in rows[train_count:]])
        return {"status": "AVAILABLE", "schema": "sqrt-impact/1", "symbol": symbol,
                "a": str(+a), "b": str(+b),
                "volatility_bps": str(+median([r[5] for r in rows[:train_count]])),
                "volume_base": str(+median([r[4] for r in rows[:train_count]])),
                "fit_rmse_bps": str(+fit_error), "holdout_rmse_bps": str(+holdout_error),
                "sample_count": count, "train_samples": train_count,
                "trained_until": trained_until.isoformat(),
                "source": _SOURCE, "funded_authority": False,
                "limitations": ["Fitted public aggressor prints relative to a prior public quote, not independently verified funded fills.",
                               "The holdout evaluates residual fit error, not profitability or fill probability.",
                               "Parameters are historical assumptions, not contemporaneous executable liquidity."]}


def validate_impact_models(models):
    """Validate user-supplied impact models and normalize malformed input errors."""
    try:
        _validate_impact_models(models)
    except (KeyError, TypeError):
        raise ValueError("invalid impact profiles") from None


def _validate_impact_models(models):
    """Apply strict schema, symbol, timestamp, and coefficient bounds."""
    if models is None:
        return
    if type(models) is not dict or not 1 <= len(models) <= 20:
        raise ValueError("invalid impact profiles")
    for symbol, row in models.items():
        if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                or type(row) is not dict or row.get("schema") != "sqrt-impact/1"
                or row.get("source") != _SOURCE or row.get("symbol") != symbol
                or type(row.get("sample_count")) is not int or row["sample_count"] < 30):
            raise ValueError("invalid impact profiles")
        parse_ts(row["trained_until"])
        for name, positive in (("a", False), ("b", False), ("volume_base", True),
                               ("volatility_bps", True), ("fit_rmse_bps", False),
                               ("holdout_rmse_bps", False)):
            val = _number(row[name], name, positive=positive)
            if name in ("a", "b") and val > 100:
                raise ValueError("unbounded impact coefficient")


def validate_hourly_costs(models):
    """Validate user-supplied hourly cost models as bounded, causal receipts."""
    try:
        _validate_hourly_costs(models)
    except (KeyError, TypeError):
        raise ValueError("invalid time-of-day cost profiles") from None


def _validate_hourly_costs(models):
    """Enforce recorded hourly spreads, sample counts, and fee provenance."""
    if models is None:
        return
    if type(models) is not dict or not 1 <= len(models) <= 20:
        raise ValueError("invalid time-of-day cost profiles")
    for symbol, model in models.items():
        if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                or type(model) is not dict or model.get("schema") != "hourly-costs/1"
                or model.get("symbol") != symbol
                or type(model.get("hours")) is not dict or len(model["hours"]) > 24):
            raise ValueError("invalid time-of-day cost profiles")
        cutoff = parse_ts(model["trained_until"])
        for hour, row in model["hours"].items():
            if type(hour) is not str or hour not in {str(h) for h in range(24)} or type(row) is not dict:
                raise ValueError("invalid time-of-day hour")
            if type(row.get("quote_samples")) is not int or row["quote_samples"] < 20:
                raise ValueError("hourly spread needs 20 observed quotes")
            if _number(row["spread_bps"], "hourly spread") > 10000:
                raise ValueError("invalid hourly spread")
            for fee in ("taker_fee_rate", "maker_fee_rate"):
                if row.get(fee) is not None and _number(row[fee], fee) >= 1:
                    raise ValueError("invalid hourly fee rate")
            observed = row.get("fee_observed_at")
            if observed is not None and parse_ts(observed) > cutoff:
                raise ValueError("future hourly fee observation")


def validate_postfill_costs(models):
    """Normalize malformed paper receipts to the existing validation-error contract."""
    try:
        _validate_postfill_costs(models)
    except (KeyError, TypeError):
        raise ValueError("invalid paper postfill costs") from None


def _validate_postfill_costs(models):
    """Validate exact schema, sample count, bounded penalty and recorded cutoff."""
    if models is None:
        return
    if type(models) is not dict or not 1 <= len(models) <= 20:
        raise ValueError("invalid paper postfill costs")
    for symbol, row in models.items():
        if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                or type(row) is not dict
                or set(row) != {"schema", "symbol", "trained_until", "penalty_bps", "sample_count", "source"}
                or row["schema"] != "postfill-adverse/1" or row["symbol"] != symbol
                or row["source"] != "PAPER_MARKOUT_DIAGNOSTIC"
                or type(row["sample_count"]) is not int or row["sample_count"] < 30
                or _number(row["penalty_bps"], "postfill penalty") > 200):
            raise ValueError("invalid paper postfill costs")
        parse_ts(row["trained_until"])


def check_causal_costs(impact_models, hourly_costs, at, postfill_costs=None):
    """Reject models fitted after the paper replay's initial knowledge cutoff."""
    if at.tzinfo is None:
        raise ValueError("replay needs an aware start time")
    for models in (impact_models, hourly_costs, postfill_costs):
        for row in (models or {}).values():
            if parse_ts(row["trained_until"]) > at:
                raise ValueError("future execution cost calibration is not available at replay start")


def modeled_execution_cost(cost, symbol, at, quantity, bid, ask, *, maker=False):
    """Return a conservative price uplift on an already-spread-bearing public quote.

    Observed half-spread is already in the bid/ask. Model adds *only* the
    excess of fitted total cost above that baseline, never double counts it.
    """
    impact = (cost.impact_models or {}).get(symbol)
    model = (cost.hourly_costs or {}).get(symbol)
    postfill = (cost.postfill_costs or {}).get(symbol)
    if impact is None and model is None and postfill is None:
        return None
    with localcontext() as context:
        context.prec = 60
        mid = (bid + ask) / 2
        observed = (ask - bid) / mid * 10000
        hour = str(at.astimezone(TEHRAN).hour)
        group = model["hours"].get(hour) if model else None
        spread = max(observed, Decimal(group["spread_bps"])) if group else observed
        spread_add = (spread - observed) / 2 if not maker else Decimal(0)
        impact_add = Decimal(0)
        if impact and not maker and quantity > 0:
            q, volume = quantity, Decimal(impact["volume_base"])
            total = Decimal(impact["a"]) * spread / 2 + Decimal(impact["b"]) * Decimal(
                impact["volatility_bps"]) * (q / volume).sqrt()
            impact_add = max(Decimal(0), total - spread / 2)
        fee = (cost.maker_fee if maker else cost.fee_rate)
        label = "maker_fee_rate" if maker else "taker_fee_rate"
        if group and group.get(label) is not None:
            fee = Decimal(group[label])
        extra = Decimal(postfill["penalty_bps"]) if postfill is not None and not maker else Decimal(0)
        return {"uplift_bps": spread_add + impact_add + extra, "fee_rate": fee,
                "pricing": {**({"postfill_adverse_bps": str(+extra)} if postfill is not None and not maker else {}),
                            "observed_spread_bps": str(+observed),
                            "modeled_spread_bps": str(+spread),
                            "spread_uplift_bps": str(+spread_add),
                            "impact_extra_bps": str(+impact_add),
                            "applied_fee_rate": str(fee),
                            "impact_model": impact and "sqrt-impact/1",
                            "hourly_cost_model": model and "hourly-costs/1"}}
