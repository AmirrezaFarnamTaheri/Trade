"""Feed-anomaly classifier: the first learned component (M-2 step 2). Advisory; it never trades or sizes.

It scores each stored quote for "looks corrupt" from point-in-time features of that quote and the previous quote
of the same market only (no later data). Labels come from faults injected into real clean quotes (price spikes,
decimal shifts, stale gaps, spread blowouts) plus rows the collector already flagged, so no human labelling is
needed. The model is a logistic regression fitted in pure Python (no dependency), evaluated on a later time split
against a no-model rule baseline, stored as a JSON artifact in the content-addressed registry, and every fit is
recorded first as a `model-fit` trial. Scoring ABSTAINs when the artifact is missing, corrupt, expired or built for
a different feature schema.
"""
from __future__ import annotations

import math
import random
from datetime import timedelta
from decimal import Decimal

FEATURES = ("log_spread_bps", "abs_return_pct", "log_gap_seconds", "abs_log_qty_change", "magnitude_jump")
SCHEMA = {"model": "feed-anomaly", "features": list(FEATURES), "version": 1}
COST_DIGEST = "0" * 64  # not a trading model: no cost model applies
FAULTS = ("spike", "decimal_shift", "stale", "spread_blowout")


def _f(x) -> float:
    return float(x) if x is not None else float("nan")


def features(prev, top) -> list[float]:
    """Five numbers from this quote and the previous quote of the same market; all point-in-time."""
    bid, ask = _f(top["bid"]), _f(top["ask"])
    valid = bid > 0 and ask > 0 and math.isfinite(bid) and math.isfinite(ask)
    mid = (bid + ask) / 2 if valid else float("nan")
    spread_bps = (ask - bid) / mid * 1e4 if valid else 1e6
    if prev is None:
        return [math.log1p(max(spread_bps, 0.0)), 0.0, 0.0, 0.0, 0.0]
    pbid, pask = _f(prev["bid"]), _f(prev["ask"])
    pmid = (pbid + pask) / 2 if pbid > 0 and pask > 0 else float("nan")
    ratio = mid / pmid if valid and pmid > 0 else float("nan")
    ret = abs(math.log(ratio)) * 100 if ratio > 0 else 100.0
    gap = max(0.0, (top["t"] - prev["t"]).total_seconds())
    pq, q = _f(prev["bid_qty"]), _f(top["bid_qty"])
    qty = abs(math.log(q / pq)) if q > 0 and pq > 0 else 0.0
    jump = abs(round(math.log10(ratio))) if ratio > 0 else 3.0
    return [math.log1p(max(spread_bps, 0.0)), min(ret, 100.0), math.log1p(gap), min(qty, 20.0), float(min(jump, 3))]


def inject(row, rng: random.Random):
    """One synthetic fault on a copy of a clean quote; returns (row, fault)."""
    fault = rng.choice(FAULTS)
    out = dict(row)
    bid, ask = Decimal(row["bid"]), Decimal(row["ask"])
    if fault == "spike":
        k = Decimal(str(round(rng.uniform(1.08, 1.6), 4))) ** rng.choice((1, -1))
        out["bid"], out["ask"] = bid * k, ask * k
    elif fault == "decimal_shift":
        k = Decimal(10) ** rng.choice((1, -1))
        out["bid"], out["ask"] = bid * k, ask * k
    elif fault == "stale":
        out["t"] = row["t"] + timedelta(minutes=rng.uniform(15, 240))
    else:
        out["ask"] = ask + (ask - bid + ask * Decimal("0.002")) * Decimal(str(round(rng.uniform(5, 40), 2)))
    return out, fault


def build_dataset(series: dict[str, list[dict]], *, rate: float = 0.08, seed: int = 0):
    """(t, x, y) rows over every market; injected faults are labelled 1, untouched quotes 0, flagged quotes 1."""
    rng, rows = random.Random(seed), []
    for symbol in sorted(series):
        prev = None
        for top in series[symbol]:
            flagged = bool(top.get("flags"))
            if not flagged and prev is not None and rng.random() < rate:
                bad, _ = inject(top, rng)
                rows.append((top["t"], features(prev, bad), 1))
            rows.append((top["t"], features(prev, top), 1 if flagged else 0))
            prev = top
    rows.sort(key=lambda r: r[0])
    return rows


def _standardise(xs):
    n = len(xs)
    means = [sum(x[i] for x in xs) / n for i in range(len(FEATURES))]
    scales = [math.sqrt(sum((x[i] - means[i]) ** 2 for x in xs) / n) or 1.0 for i in range(len(FEATURES))]
    return means, scales


def _sigmoid(z):
    return 1 / (1 + math.exp(-z)) if z > -60 else 0.0


def fit(rows, *, epochs: int = 200, rate: float = 0.5, l2: float = 1e-3) -> dict:
    """Full-batch logistic regression with class weights; returns the JSON artifact."""
    xs = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    means, scales = _standardise(xs)
    zs = [[(x[i] - means[i]) / scales[i] for i in range(len(FEATURES))] for x in xs]
    pos = sum(ys) or 1
    w_pos, w_neg = len(ys) / (2 * pos), len(ys) / (2 * max(1, len(ys) - pos))
    w, b = [0.0] * len(FEATURES), 0.0
    for _ in range(epochs):
        gw, gb = [0.0] * len(FEATURES), 0.0
        for z, y in zip(zs, ys):
            err = (_sigmoid(b + sum(wi * zi for wi, zi in zip(w, z))) - y) * (w_pos if y else w_neg)
            gb += err
            for i, zi in enumerate(z):
                gw[i] += err * zi
        n = len(zs)
        w = [wi - rate * (g / n + l2 * wi) for wi, g in zip(w, gw)]
        b -= rate * gb / n
    return {"kind": "logistic", "schema": SCHEMA, "means": means, "scales": scales, "weights": w, "bias": b}


def score(artifact: dict, x) -> float:
    z = [(x[i] - artifact["means"][i]) / artifact["scales"][i] for i in range(len(FEATURES))]
    return _sigmoid(artifact["bias"] + sum(w * zi for w, zi in zip(artifact["weights"], z)))


def baseline(x) -> float:
    """No-model rule: a 5% move, an order-of-magnitude jump, a 10-minute gap or a 100 bps spread."""
    return 1.0 if x[1] > 5 or x[4] >= 1 or x[2] > math.log1p(600) or x[0] > math.log1p(100) else 0.0


def auroc(scores, labels) -> float | None:
    pairs = sorted(zip(scores, labels))
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        rank_sum += sum(1 for k in range(i, j) if pairs[k][1]) * (i + j + 1) / 2
        i = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def evaluate(artifact, rows, threshold: float = 0.5) -> dict:
    labels = [r[2] for r in rows]
    model = [score(artifact, r[1]) for r in rows]
    rule = [baseline(r[1]) for r in rows]

    def at(scores, cut):
        tp = sum(1 for s, y in zip(scores, labels) if s >= cut and y)
        fp = sum(1 for s, y in zip(scores, labels) if s >= cut and not y)
        fn = sum(1 for s, y in zip(scores, labels) if s < cut and y)
        return {"precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None}

    return {"rows": len(rows), "anomalies": sum(labels),
            "model": {"auroc": round(auroc(model, labels) or 0, 4), **at(model, threshold)},
            "baseline": {"auroc": round(auroc(rule, labels) or 0, 4), **at(rule, 0.5)}}


def load_series(db, symbols, start, end, limit_per_market: int = 20000) -> dict[str, list[dict]]:
    from ..domain.model import iso, parse_ts
    out = {}
    for symbol in symbols:
        rows = db.c.execute("SELECT ts_avail, bid, ask, bid_qty, flags FROM book_top WHERE instrument_id=? "
                            "AND ts_avail>=? AND ts_avail<? ORDER BY ts_avail LIMIT ?",
                            (f"wallex:{symbol}", iso(start), iso(end), limit_per_market)).fetchall()
        out[symbol] = [{"t": parse_ts(t), "bid": b, "ask": a, "bid_qty": q, "flags": f or ""} for t, b, a, q, f in rows]
    return out


def train(root, db, symbols, start, end, *, now, seed: int = 0) -> dict:
    """Fit on the first 70% of the window, evaluate on the last 30%, record the fit as a trial, register it."""
    from .model_artifacts import ArtifactRegistry
    from .trial_ledger import TrialLedger
    rows = build_dataset(load_series(db, symbols, start, end), seed=seed)
    if len(rows) < 200 or sum(r[2] for r in rows) < 20:
        raise ValueError("not enough quotes or anomalies to fit; widen the window or add markets")
    cut = int(len(rows) * 0.7)
    artifact = fit(rows[:cut])
    report = evaluate(artifact, rows[cut:])
    with TrialLedger(root) as ledger, ArtifactRegistry(root) as registry:
        trial = ledger.record(symbol="ALL", start=start, end=end, hypothesis="feed-anomaly logistic v1",
                              source="model-fit", config_hash=f"feed-anomaly-{seed}-{len(symbols)}")
        sha = registry.register(artifact, kind="logistic", feature_schema=SCHEMA, cost_digest=COST_DIGEST,
                                trial_ledger=ledger, trial_attempt=trial["attempt_id"], now=now,
                                expires_at=now + timedelta(days=30))
    return {"artifact": sha, "trial": trial["attempt_id"], "trials_for_question": trial["trials"],
            "train_rows": cut, "test": report, "advisory_only": True}


def scan(root, db, symbol, start, end, artifact_sha: str, *, now, threshold: float = 0.5) -> dict:
    """Score a market's quotes with a registered artifact; ABSTAIN if the artifact is unusable."""
    from .model_artifacts import ArtifactRegistry
    with ArtifactRegistry(root) as registry:
        loaded = registry.load(artifact_sha, feature_schema=SCHEMA, cost_digest=COST_DIGEST, now=now)
    if loaded["status"] != "READY":
        return {"status": "ABSTAIN", "reason": loaded["reason"], "flagged": []}
    series = load_series(db, [symbol], start, end)[symbol]
    flagged, prev = [], None
    for top in series:
        p = score(loaded["artifact"], features(prev, top))
        if p >= threshold:
            flagged.append({"t": top["t"].isoformat(), "probability": round(p, 4), "bid": top["bid"], "ask": top["ask"]})
        prev = top
    return {"status": "SCORED", "quotes": len(series), "flagged": flagged[:500], "flagged_count": len(flagged),
            "advisory_only": True}
