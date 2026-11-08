"""Deterministic, dependency-free Decimal hierarchical risk parity (paper only)."""
from decimal import Decimal, localcontext


def hierarchical_risk_parity(covariance):
    """Single-linkage correlation clustering followed by inverse-variance bisection.

    The returned weights correspond to the original covariance order; leaf
    order records the hierarchy. This is a descriptive target allocator, not
    a validated turnover, market capacity, or live risk optimizer.
    """
    if (type(covariance) is not list or not 2 <= len(covariance) <= 100
            or any(type(row) is not list or len(row) != len(covariance) for row in covariance)):
        raise ValueError("HRP needs a square covariance matrix of 2..100 markets")
    n = len(covariance)
    with localcontext() as context:
        context.prec = 70
        if any(type(value) is not Decimal or not value.is_finite()
               for row in covariance for value in row):
            raise ValueError("HRP covariance values must be finite Decimal")
        if any(covariance[i][i] <= 0 for i in range(n)):
            raise ValueError("HRP requires strictly positive variances")
        if any(covariance[i][j] != covariance[j][i]
               for i in range(n) for j in range(i)):
            raise ValueError("HRP covariance must be symmetric")
        distances = [[Decimal(0) for _ in range(n)] for _ in range(n)]
        for i in range(n):
            for j in range(i):
                corr = covariance[i][j] / (covariance[i][i] * covariance[j][j]).sqrt()
                if not -1 <= corr <= 1:
                    raise ValueError("HRP correlation magnitude exceeds one")
                distances[i][j] = distances[j][i] = ((1 - corr) / 2).sqrt()
        clusters = [(i,) for i in range(n)]
        while len(clusters) > 1:
            candidates = (
                (min(distances[i][j] for i in a for j in b), min(a), min(b), ai, bi)
                for ai, a in enumerate(clusters) for bi, b in enumerate(clusters)
                if ai < bi
            )
            _, _, _, ai, bi = min(candidates)
            a, b = clusters[ai], clusters[bi]
            for index in sorted((ai, bi), reverse=True):
                clusters.pop(index)
            clusters.append(a + b if min(a) < min(b) else b + a)
        order = list(clusters[0])
        weights = [Decimal(1) for _ in range(n)]

        def cluster_variance(indices):
            """Estimate risk using inverse-diagonal allocation inside a cluster."""
            inv = [1 / covariance[i][i] for i in indices]
            total = sum(inv, Decimal(0))
            relative = [value / total for value in inv]
            variance = sum((relative[p] * covariance[i][j] * relative[q]
                            for p, i in enumerate(indices)
                            for q, j in enumerate(indices)), Decimal(0))
            if variance <= 0:
                raise ValueError("HRP cannot allocate a degenerate covariance cluster")
            return variance

        def allocate(indices):
            """Recursively bisect quasi-diagonalized leaves without leverage."""
            if len(indices) == 1:
                return
            cut = len(indices) // 2
            left, right = indices[:cut], indices[cut:]
            lvar, rvar = cluster_variance(left), cluster_variance(right)
            share = rvar / (lvar + rvar)
            for i in left:
                weights[i] *= share
            for i in right:
                weights[i] *= 1 - share
            allocate(left)
            allocate(right)

        allocate(order)
        total = sum(weights, Decimal(0))
        return [+(w / total) for w in weights], order
