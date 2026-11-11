"""Causal Decimal research statistics for premium and paired-spread models.

The AR(1) fit is descriptive and fitted from historical observations only.
It is not a forecast calibration, transferable arbitrage proof or execution authority.
"""
from decimal import Decimal, localcontext


def ar1_half_life(values):
    """Fit an AR(1) with intercept and return the mean-reversion half-life in bars.

    The input must be an ordered historical series available at the fit cutoff.
    The stationary half-life is meaningful only for 0 < phi < 1.
    """
    if type(values) not in (list, tuple) or not 12 <= len(values) <= 5000:
        raise ValueError("AR(1) requires 12..5000 sequential historical values")
    if any(type(x) is not Decimal or not x.is_finite() for x in values):
        raise ValueError("AR(1) requires finite exact Decimal observations")
    with localcontext() as context:
        context.prec = 90
        prior, later = values[:-1], values[1:]
        n = Decimal(len(prior))
        mx, my = sum(prior, Decimal(0)) / n, sum(later, Decimal(0)) / n
        xx = sum(((x - mx) ** 2 for x in prior), Decimal(0))
        if xx <= 0:
            return {"status": "UNIDENTIFIABLE", "phi": None, "half_life_bars": None,
                    "observations": len(values)}
        phi = sum(((a - mx) * (b - my) for a, b in zip(prior, later)), Decimal(0)) / xx
        if not 0 < phi < 1:
            return {"status": "UNIDENTIFIABLE", "phi": str(+phi),
                    "half_life_bars": None, "observations": len(values)}
        half = -Decimal(2).ln() / phi.ln()
        return {"status": "IDENTIFIED", "phi": str(+phi),
                "half_life_bars": str(+half), "observations": len(values)}


class CausalPremiumMoments:
    """Fixed-alpha EWMA of past observed discounts, never including the scored point.

    This is a descriptive z-score for a paper long/flat hypothesis. A warmup and
    strictly positive historical variance are required before any z-score exists.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Discard a stale or discontinuous discount history."""
        self.mean = None
        self.variance = Decimal(0)
        self.count = 0

    def score(self, current):
        """Score a fresh discount using only statistics from earlier bars."""
        if type(current) is not Decimal or not current.is_finite():
            raise ValueError("premium score requires finite Decimal")
        if self.count < 20 or self.variance <= 0:
            return None
        with localcontext() as context:
            context.prec = 90
            return +(current - self.mean) / self.variance.sqrt()

    def observe(self, current):
        """Advance mean and variance after the signal at this bar is formed."""
        if type(current) is not Decimal or not current.is_finite():
            raise ValueError("premium observation requires finite Decimal")
        alpha = Decimal("0.08")
        with localcontext() as context:
            context.prec = 90
            if self.mean is None:
                self.mean = current
            else:
                delta = current - self.mean
                self.mean += alpha * delta
                self.variance = (1 - alpha) * (self.variance + alpha * delta * delta)
            self.count += 1
