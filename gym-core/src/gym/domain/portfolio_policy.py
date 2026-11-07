"""Exact, causal paper allocation targets and entry-blocking loss latches."""
import itertools
from decimal import ROUND_DOWN, Decimal, localcontext

from .market_models import decimal
from .model import TEHRAN


class PortfolioPolicy:
    def __init__(self, value, symbols):
        defaults = {"method": "equal", "lookback": 20, "rebalance_seconds": 60, "max_weight": "1",
                    "cash_buffer": "0", "correlation_limit": None, "correlation_cap": "1",
                    "max_drawdown": None, "daily_loss_limit": None, "rebalance": False, "rebalance_threshold": "0.01"}
        if type(value) is not dict or value.keys() - defaults.keys():
            raise ValueError("invalid portfolio policy fields")
        self.description = {**defaults, **value}
        self.symbols = symbols
        if type(self.description["rebalance"]) is not bool:
            raise ValueError("rebalance must be boolean")
        if self.description["method"] not in ("equal", "inverse-volatility", "risk-parity"):
            raise ValueError("invalid portfolio weighting method")
        for key, low, high in (("lookback", 3, 500), ("rebalance_seconds", 60, 604800)):
            if type(self.description[key]) is not int or not low <= self.description[key] <= high:
                raise ValueError(f"invalid portfolio {key}")
        if (self.description["method"] != "equal" or self.description["correlation_limit"] is not None) and len(symbols) ** 2 * self.description["lookback"] > 1000000:
            raise ValueError("covariance calculation budget exceeded; reduce lookback or use equal weights without correlation grouping")
        self.rates = {}
        for key in ("max_weight", "cash_buffer", "correlation_limit", "correlation_cap", "max_drawdown", "daily_loss_limit", "rebalance_threshold"):
            raw = self.description[key]
            if raw is not None:
                number = decimal(raw, key)
                if (number > 1 or (number == 1 and key not in ("max_weight", "correlation_cap"))
                        or (not number and key not in ("cash_buffer", "correlation_limit", "rebalance_threshold"))):
                    raise ValueError(f"invalid portfolio {key}")
                self.rates[key] = number
        self.peak = self.daily_start = self.day = self.previous_at = None
        self.drawdown_latched = self.daily_latched = False

    def observe(self, at, equity):
        if at.tzinfo is None or not equity.is_finite() or equity < 0 or self.previous_at and at < self.previous_at:
            raise ValueError("portfolio risk requires chronological finite equity observations")
        self.previous_at = at
        day = at.astimezone(TEHRAN).date()
        if day != self.day:
            self.day, self.daily_start, self.daily_latched = day, equity, False
        self.peak = equity if self.peak is None else max(self.peak, equity)
        if self.rates.get("max_drawdown") is not None and self.peak > 0:
            self.drawdown_latched |= (self.peak - equity) / self.peak >= self.rates["max_drawdown"]
        if self.rates.get("daily_loss_limit") is not None and self.daily_start > 0:
            self.daily_latched |= (self.daily_start - equity) / self.daily_start >= self.rates["daily_loss_limit"]
        return "DRAWDOWN" if self.drawdown_latched else "DAILY_LOSS" if self.daily_latched else None

    def weights(self, observations):
        n, count = len(self.symbols), self.description["lookback"]
        zero = {s: "0" for s in self.symbols}
        result = {"status": "READY", "weights": zero, "risk_contribution_error": None}
        need_history = self.description["method"] != "equal" or self.description["correlation_limit"] is not None
        with localcontext() as context:
            context.prec = 60
            covariance = None
            if need_history:
                series = [observations.get(s, [])[-(count + 1):] for s in self.symbols]
                if (any(len(row) < count + 1 for row in series)
                        or any([at for at, _ in row] != [at for at, _ in series[0]] for row in series[1:])):
                    return {**result, "status": "WARMING_UP"}
                if any(any(not value.is_finite() or value <= 0 for _, value in row) for row in series):
                    raise ValueError("allocation requires positive finite closed prices")
                if any(b[0] <= a[0] for a, b in zip(series[0], series[0][1:])):
                    raise ValueError("allocation prices must be chronological")
                if len({b[0] - a[0] for a, b in itertools.pairwise(series[0])}) != 1:
                    return {**result, "status": "GAPPED_HISTORY"}
                returns = [[b[1] / a[1] - 1 for a, b in itertools.pairwise(row)] for row in series]
                means = [sum(row) / count for row in returns]
                covariance = [[sum((returns[i][k] - means[i]) * (returns[j][k] - means[j]) for k in range(count)) / (count - 1)
                               for j in range(n)] for i in range(n)]
                if any(covariance[i][i] <= 0 for i in range(n)):
                    return {**result, "status": "ZERO_VARIANCE"}
            weights = [Decimal(1) / n] * n
            if self.description["method"] != "equal":
                weights = [1 / covariance[i][i].sqrt() for i in range(n)]
            if self.description["method"] == "risk-parity":
                for _ in range(100):
                    for i in range(n):
                        a = covariance[i][i]
                        b = sum(covariance[i][j] * weights[j] for j in range(n) if j != i)
                        weights[i] = (-b + (b * b + 4 * a / n).sqrt()) / (2 * a)
                    contributions = [weights[i] * sum(covariance[i][j] * weights[j] for j in range(n)) for i in range(n)]
                    total_risk = sum(contributions)
                    if total_risk <= 0:
                        return {**result, "status": "DEGENERATE_COVARIANCE"}
                    error = max(abs(value / total_risk - Decimal(1) / n) for value in contributions)
                    if error <= Decimal("0.0001"):
                        break
                else:
                    return {**result, "status": "NO_CONVERGENCE"}
                result["risk_contribution_error"] = str(error)
            total = sum(weights)
            weights = [min(self.rates["max_weight"], value / total * (1 - self.rates["cash_buffer"])) for value in weights]
            if self.description["correlation_limit"] is not None:
                groups = [{i} for i in range(n)]
                for i in range(n):
                    for j in range(i):
                        corr = covariance[i][j] / (covariance[i][i] * covariance[j][j]).sqrt()
                        if corr >= self.rates["correlation_limit"]:
                            joined = groups[i] | groups[j]
                            for k in joined:
                                groups[k] = joined
                for group in {frozenset(group) for group in groups}:
                    total = sum(weights[i] for i in group)
                    if total > self.rates["correlation_cap"]:
                        for i in group:
                            weights[i] *= self.rates["correlation_cap"] / total
            result["weights"] = {s: str(value.quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN)) for s, value in zip(self.symbols, weights)}
            if self.description["method"] == "risk-parity":
                actual = [Decimal(result["weights"][s]) for s in self.symbols]
                contributions = [actual[i] * sum(covariance[i][j] * actual[j] for j in range(n)) for i in range(n)]
                total_risk = sum(contributions)
                result["risk_contribution_error"] = str(max(abs(value / total_risk - Decimal(1) / n) for value in contributions)) if total_risk > 0 else None
                result["risk_basis"] = "Realized target risk contributions after weight/correlation caps and rounding; constraints can prevent equal risk."
            return result
