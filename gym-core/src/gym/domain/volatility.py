"""One strictly causal, Decimal-valued high-low EWMA volatility estimator.

The Parkinson bar variance uses only a closed bar's known high and low.
It is a model of diffusion, not a forecast or an executable order price.
"""
from decimal import Decimal, localcontext

DEFAULT_DECAY = Decimal("0.94")


class ParkinsonEWMA:
    """Exponentially smooth causal Parkinson variances; return per-bar sigma."""

    def __init__(self, decay=DEFAULT_DECAY):
        if type(decay) is not Decimal or not decay.is_finite() or not 0 <= decay < 1:
            raise ValueError("Parkinson decay must be a Decimal in [0, 1)")
        self.decay = decay
        self.variance = None
        self.count = 0

    def update(self, high, low):
        """Accept one fully available positive high-low pair, with no future data."""
        with localcontext() as context:
            context.prec = 60
            high, low = Decimal(high), Decimal(low)
            if not high.is_finite() or not low.is_finite() or not 0 < low <= high:
                raise ValueError("Parkinson volatility requires finite high >= low > 0")
            bar = ((high / low).ln() ** 2) / (4 * Decimal(2).ln())
            self.variance = bar if self.variance is None else self.decay * self.variance + (1 - self.decay) * bar
            self.count += 1
            return +self.variance.sqrt()


def parkinson_ewma(ranges, *, decay=DEFAULT_DECAY):
    """Return sigma from closed bars in receipt order; None when no bars exist."""
    estimator = ParkinsonEWMA(decay)
    result = None
    for high, low in ranges:
        result = estimator.update(high, low)
    return result
