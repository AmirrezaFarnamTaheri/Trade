"""Shared paired-comparison core over one SQLite read snapshot (breaks research <-> temporal_validation cycle)."""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from ..domain.performance import performance, selection_check
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .paper import paper, ranking
from .reports import sampled_drawdown


def compare_in_snapshot(
    db,
    symbol,
    t0,
    t1,
    candidates,
    *,
    resolution="15min",
    cash=Decimal(1000),
    cost=CostModel(),
    rules_mode="point-in-time",
    store="live",
    subscriptions=(),
    prior_configs=frozenset(),
    ledger_trials=0,
):
    if not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid market symbol")
    if not t0 < t1 or t1 - t0 > timedelta(days=31):
        raise ValueError("comparison window must be positive and at most 31 days")
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 4:
        raise ValueError("compare requires two to four candidates")
    if any(not isinstance(c, dict) or c.keys() - {"strategy", "params"} for c in candidates):
        raise ValueError("invalid comparison candidate")
    strategies = [create_strategy(c.get("strategy"), c.get("params")) for c in candidates]
    resolutions = tuple(
        dict.fromkeys((resolution, *subscriptions, *(r for s in strategies for r in getattr(s, "required_resolutions", ()))))
    )
    references = {s.reference_symbol for s in strategies if hasattr(s, "reference_symbol")}
    if len(references) > 1:
        raise ValueError("paired comparison supports one common reference asset")
    reference = next(iter(references), None)
    from .data_portal import DataPortal

    instrument = DataPortal(db).instrument(symbol)
    auxiliary_symbols = tuple(
        sorted(
            {
                aux
                for strategy in strategies
                for aux in (strategy.reference_symbols(instrument) if hasattr(strategy, "reference_symbols") else ())
            }
        )
    )
    runs = [
        paper(
            db,
            symbol,
            t0,
            t1,
            resolution=resolution,
            cash=cash,
            cost=cost,
            rules_mode=rules_mode,
            store=store,
            subscriptions=resolutions,
            strategy_id=s.name,
            params=s.params,
            reference_symbol=reference,
            auxiliary_symbols=auxiliary_symbols,
        )
        for s in strategies
    ]
    if len({(r["inputs"]["data"], r["inputs"]["snapshots"]) for r in runs}) != 1:
        raise ValueError("comparison data or decision snapshots diverged")
    labels = [f"{chr(65 + i)}: {r['inputs']['strategy']}" for i, r in enumerate(runs)]
    ranked = ranking(
        runs[0]["result"],
        {**{label: r["result"] for label, r in zip(labels[1:], runs[1:])}, **runs[0]["baselines"]},
        labels[0],
    )
    shared = {
        k: runs[0]["inputs"][k]
        for k in (
            "engine", "symbol", "from", "to", "resolution", "subscriptions",
            "cash", "cost", "rules_mode", "store", "data", "snapshots", "reference_symbol",
        )
    }
    measured = {label: performance(r, sampled_drawdown(r), enhanced=True) for label, r in zip(labels, runs)}
    new = {r["inputs"]["config_hash"] for r in runs}
    return {
        "comparison_id": digest({"shared": shared, "runs": [r["run_id"] for r in runs]})[:16],
        "mode": "COMPARE",
        "authority": "PAPER_ONLY",
        "shared_inputs": shared,
        "runs": runs,
        "ranking": ranked,
        "selection": selection_check(measured, max(len(prior_configs | new), ledger_trials)),
        # Kept beside, never inside, saved run records so identical reruns stay byte-identical.
        "performance": {
            r["run_id"]: {k: v for k, v in measured[label].items() if k != "ledger"}
            for label, r in zip(labels, runs)
        },
        "limitation": "Independent paper accounts; one traded asset with optional reference signal, not a shared portfolio or execution proposals.",
    }
