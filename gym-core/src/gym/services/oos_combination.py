"""Item 28: chronological inverse-error combination of matched USDT paper curves.

The error proxy is a strategy's squared realized return relative to a
zero-return USDT cash benchmark. Weights use only *earlier* OOS marks. This
does not model shared-cash fills or prove predictive forecast calibration.
"""
from decimal import Decimal, localcontext

from ..domain.model import parse_ts
from ..domain.strategy import digest


def _number(value, label, *, positive=False):
    """Accept finite exact decimals only; never silent floats or NaNs."""
    if type(value) not in (str, int, Decimal):
        raise ValueError("invalid OOS " + label)
    try:
        out = Decimal(value)
    except (ValueError, ArithmeticError):
        raise ValueError("invalid OOS " + label) from None
    if not out.is_finite() or out < 0 or positive and out == 0:
        raise ValueError("invalid OOS " + label)
    return out


def combine_oos_curves(components, *, lookback=6, rebalance_cost_bps=None):
    """Compare 2..4 already-matched paper paths with a past-only risk/error rule.

    Caller is responsible for independently verifying source file identities.
    Even verified local prospective curves do not establish independent custody.
    """
    if (type(components) is not list or not 2 <= len(components) <= 4
            or type(lookback) is not int or not 3 <= lookback <= 100):
        raise ValueError("invalid OOS combination size or lookback")
    if rebalance_cost_bps is not None:
        charge = _number(rebalance_cost_bps, "rebalance cost", positive=True)
        if charge > 500:
            raise ValueError("OOS combination rebalance cost exceeds bound")
    else:
        charge = None
    ids, names, marks, stamps = [], [], [], None
    with localcontext() as context:
        context.prec = 90
        opening = None
        for component in components:
            if (type(component) is not dict or set(component) != {"run_id", "strategy", "marks"}
                    or type(component["run_id"]) is not str or not 1 <= len(component["run_id"]) <= 64
                    or type(component["strategy"]) is not str
                    or not 1 <= len(component["strategy"]) <= 64
                    or type(component["marks"]) is not list
                    or not lookback + 3 <= len(component["marks"]) <= 1000):
                raise ValueError("invalid OOS source curve")
            times, values = [], []
            for row in component["marks"]:
                if type(row) is not dict or set(row) != {"at", "equity_usdt"} or type(row["at"]) is not str:
                    raise ValueError("invalid OOS curve mark")
                times.append(parse_ts(row["at"]))
                values.append(_number(row["equity_usdt"], "equity", positive=True))
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("OOS curves must be strictly chronological")
            if stamps is None:
                stamps = times
                opening = values[0]
            elif stamps != times or values[0] != opening:
                raise ValueError("OOS curves require identical timestamps and opening USDT cash")
            ids.append(component["run_id"])
            names.append(component["strategy"])
            marks.append(values)
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError("OOS candidates must have distinct run and strategy identities")
        returns = [[None] + [current / before - 1 for before, current in zip(curve, curve[1:])]
                   for curve in marks]
        gross, modeled = opening, opening
        previous = None
        records, weights = [], []
        floor = Decimal("0.0000000001")
        for i in range(lookback + 1, len(stamps)):
            # Excludes returns[i] itself, whose bar had not yet closed when the
            # weights were chosen. A later change cannot affect earlier weights.
            errors = [sum((r * r for r in row[i-lookback:i]), Decimal(0)) /
                      lookback for row in returns]
            inverse = [Decimal(1) / (e + floor) for e in errors]
            total = sum(inverse, Decimal(0))
            allocation = [w / total for w in inverse]
            realized = sum((allocation[j] * returns[j][i]
                            for j in range(len(names))), Decimal(0))
            gross *= 1 + realized
            turnover = (Decimal(1) if previous is None else
                        sum((abs(x - y) for x, y in zip(allocation, previous)), Decimal(0)) / 2)
            if charge is not None:
                modeled *= (1 + realized) * (1 - turnover * charge / 10000)
            previous = allocation
            weights.append({"at": stamps[i].isoformat(),
                            **{name: str(+w) for name, w in zip(names, allocation)}})
            records.append({"at": stamps[i].isoformat(),
                            "gross_usdt_equity": str(+gross),
                            "modeled_net_usdt_equity": str(+modeled) if charge is not None else None,
                            "modeled_rebalance_fraction": str(+turnover)})
        comps = [{"strategy": name, "run_id": key,
                  "net_usdt_from_common_active_window": str(
                      +(opening * (curve[-1] / curve[lookback] - 1)))}
                 for name, key, curve in zip(names, ids, marks)]
        result = {"schema": "oos-strategy-combination/1",
                  "status": "MODELED_PROXY_ONLY" if charge is not None else "COST_UNAVAILABLE",
                  "source_run_ids": ids, "lookback": lookback,
                  "error_definition": "PAST_SQUARED_NET_RETURN_VS_CASH_BENCHMARK",
                  "rebalance_cost_bps": str(+charge) if charge is not None else None,
                  "weights": weights, "curve": records, "components": comps,
                  "gross_combination_net_usdt": str(+(gross - opening)),
                  "modeled_combination_net_usdt": str(+(modeled - opening)) if charge is not None else None,
                  "funded_authority": False, "automatic_application": False,
                  "independent_custody": False, "paper_proxy_only": True,
                  "limits": ["Rolling weights use only prior observations from matched local prospective histories.",
                             "Squared net return versus a zero-return benchmark is a descriptive error/risk proxy, not a trained prediction error.",
                             "Rebalancing cost is an explicit assumption, not a simulated shared-cash venue fill.",
                             "No prediction, capacity, funded authority or automatic allocation is established."]}
        result["report_id"] = digest(result)[:16]
        return result
