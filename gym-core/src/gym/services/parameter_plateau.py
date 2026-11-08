"""Neighbour-smoothed, pointwise parameter-grid scores for exploratory rankings."""
from decimal import Decimal


def parameter_plateau(params: list[dict], scores: list[str | None]) -> dict:
    """Rank the mean of each cell and adjacent (not diagonally adjacent) grid cells."""
    if len(params) != len(scores) or not 2 <= len(params) <= 64:
        raise ValueError("invalid parameter score grid")
    if type(params[0]) is not dict:
        return {"status": "NOT_GRID"}
    names = sorted(params[0])
    if not 1 <= len(names) <= 2 or any(type(p) is not dict or sorted(p) != names for p in params):
        return {"status": "NOT_GRID"}
    try:
        coords = [tuple(Decimal(str(p[k])) for k in names) for p in params]
        numeric = [None if score is None else Decimal(str(score)) for score in scores]
    except (ArithmeticError, ValueError, TypeError):
        return {"status": "NOT_GRID"}
    if (any(not coordinate.is_finite() for point in coords for coordinate in point)
            or any(value is not None and not value.is_finite() for value in numeric)
            or len(set(coords)) != len(coords)):
        return {"status": "NOT_GRID"}
    axes = [{v: i for i, v in enumerate(sorted({coordinate[j] for coordinate in coords}))}
            for j in range(len(names))]
    scaled = [tuple(axes[j][coordinate[j]] for j in range(len(names))) for coordinate in coords]
    cells = []
    for i, here in enumerate(scaled):
        neighbors = [j for j, there in enumerate(scaled)
                     if sum(abs(a - b) for a, b in zip(here, there)) <= 1 and numeric[j] is not None]
        score = sum((numeric[j] for j in neighbors), Decimal(0)) / len(neighbors) if neighbors else None
        cells.append({"trial": i, "score": str(score) if score is not None else None,
                      "neighbors_including_self": len(neighbors)})
    ranked = sorted((cell for cell in cells if cell["score"] is not None),
                    key=lambda cell: (-Decimal(cell["score"]), cell["trial"]))
    return {"status": "AVAILABLE" if ranked else "INSUFFICIENT_DATA", "parameters": names,
            "cells": cells, "ranked_trials": [row["trial"] for row in ranked],
            "basis": "USDT-equivalent net after modeled costs; axis-adjacent configurations only."}


def scorecard_plateau(definition, rows):
    """Aggregate comparable trial net-USDT results before smoothing parameter choices."""
    trials = definition["trials"]
    by_trial = {i: [] for i in range(len(trials))}
    for row in rows:
        by_trial[row["trial"]].append(row)
    scores = []
    for i in range(len(trials)):
        entries = by_trial[i]
        if not entries or any(entry["run"] is None for entry in entries):
            scores.append(None)
            continue
        values = []
        for entry in entries:
            run = entry["run"]
            net = run.get("net_usdt_equivalent")
            if net is None and run.get("quote") == "USDT":
                net = run.get("net_quote")
            if net is None or run["valuation"]["status"] != "CURRENT":
                break
            values.append(Decimal(net))
        else:
            scores.append(str(sum(values, Decimal(0)) / len(values)))
            continue
        scores.append(None)
    return parameter_plateau(trials, scores)
