"""Causal Ledoit-Wolf covariance shrinkage toward a constant-correlation target."""
from decimal import Decimal, localcontext
from operator import mul


def ledoit_wolf_constant_correlation(observations):
    """Return sample, target, shrunk covariance and its plug-in shrinkage intensity.

    Input is a time-by-market matrix of synchronized, point-in-time Decimal returns.
    The Ledoit-Wolf pi/rho/gamma plug-in estimates use the MLE covariance; the
    reported matrix uses the unbiased sample covariance used by PortfolioPolicy.
    """
    if (type(observations) not in (tuple, list) or len(observations) < 3
            or type(observations[0]) not in (tuple, list) or len(observations[0]) < 2):
        raise ValueError("shrinkage requires at least three synchronized return rows for two markets")
    n, p = len(observations), len(observations[0])
    if (n * p * p > 1000000 or any(type(row) not in (tuple, list) or len(row) != p
                                  for row in observations)
            or any(type(value) is not Decimal or not value.is_finite()
                   for row in observations for value in row)):
        raise ValueError("invalid synchronized Decimal return matrix")
    with localcontext() as context:
        context.prec = 60
        means = [sum(row[i] for row in observations) / n for i in range(p)]
        centered = [[value - means[i] for i, value in enumerate(row)] for row in observations]
        columns = list(zip(*centered))
        mle = [[Decimal(0)] * p for _ in range(p)]
        for i in range(p):
            for j in range(i + 1):
                mle[i][j] = mle[j][i] = sum(map(mul, columns[i], columns[j])) / n
        if any(mle[i][i] <= 0 for i in range(p)):
            raise ValueError("shrinkage requires positive sample variances")
        sample = [[mle[i][j] * n / (n - 1) for j in range(p)] for i in range(p)]
        mean_corr = sum((mle[i][j] / (mle[i][i] * mle[j][j]).sqrt()
                         for i in range(p) for j in range(i + 1, p)), Decimal(0)) / (p * (p - 1) // 2)
        target = [[sample[i][i] if i == j else mean_corr * (sample[i][i] * sample[j][j]).sqrt()
                   for j in range(p)] for i in range(p)]
        pi = [[Decimal(0)] * p for _ in range(p)]
        for i in range(p):
            for j in range(i + 1):
                pi[i][j] = pi[j][i] = sum((value - mle[i][j]) ** 2
                                         for value in map(mul, columns[i], columns[j])) / n
        cubes = [[value ** 3 for value in column] for column in columns]
        theta = [[sum(map(mul, cubes[i], columns[j])) / n - mle[i][i] * mle[i][j]
                  for j in range(p)] for i in range(p)]
        phi = sum((v for row in pi for v in row), Decimal(0))
        rho = sum((pi[i][i] for i in range(p)), Decimal(0)) + mean_corr * sum(
            ((mle[j][j] / mle[i][i]).sqrt() * theta[i][j]
             for i in range(p) for j in range(p) if i != j), Decimal(0))
        gamma = sum(((mle[i][j] - target[i][j] * (n - 1) / n) ** 2
                     for i in range(p) for j in range(p)), Decimal(0))
        intensity = (min(Decimal(1), max(Decimal(0), (phi - rho) / (n * gamma)))
                     if gamma > 0 else Decimal(0))
        covariance = [[sample[i][j] if i == j else
                       (1 - intensity) * sample[i][j] + intensity * target[i][j]
                       for j in range(p)] for i in range(p)]
        return {"sample": sample, "target": target, "covariance": covariance, "intensity": +intensity}
