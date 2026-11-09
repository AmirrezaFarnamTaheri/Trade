"""Differential lookahead and warm-up checks for registered strategies (paper research only).

Three properties a decision at time t must have, each tested by replaying the same strategy twice:

- truncation: a replay that ends at a cut gives the same decisions up to that cut as the full replay;
- future perturbation: repricing every observation available after a cut leaves every decision up to the
  cut byte-identical (snapshot, features and action), which also catches leaks a truncation cannot see,
  such as a strategy or data layer that reads ahead through another path;
- warm-up stability: with a longer prehistory, the long/flat `trend` agrees once indicators have settled.

Fills are not compared up to the cut: an order decided before the cut legitimately fills after it.
Like Freqtrade's lookahead analysis, a clean result covers only the data and decisions exercised.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.bars import BarSpec
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from .data_portal import DataPortal
from .diagnostics import first_divergence
from .paper import run
from .rules import RuleService

DECISION_FIELDS = ("snapshot", "features", "action")


def build_store(path: Path, rows, preset: str | None = "usdt-irt-october-2026", preset_at: datetime | None = None) -> MarketDB:
    db = MarketDB(path)
    for row in rows:
        db.add_book_top(row, None)
    if preset:
        RuleService(db).preset(preset, preset_at or min(r.ts_avail for r in rows) - timedelta(days=30))
    return db


def perturbed(rows, cut: datetime, factor: Decimal = Decimal("1.37")):
    """Every observation available after `cut` repriced; earlier ones untouched."""
    return [replace(r, bid=r.bid * factor, ask=r.ask * factor) if r.ts_avail > cut and r.bid is not None and r.ask is not None
            else r for r in rows]


def replay(db: MarketDB, strategy_id: str, params: dict, symbol: str, t0: datetime, t1: datetime,
           resolution: str, cash: Decimal) -> list[dict]:
    portal, svc = DataPortal(db), RuleService(db)
    strategy = create_strategy(strategy_id, params)
    subscriptions = tuple(dict.fromkeys((resolution, *getattr(strategy, "required_resolutions", ()))))
    instrument = portal.instrument(symbol)
    auxiliary = tuple(strategy.reference_symbols(instrument)) if hasattr(strategy, "reference_symbols") else ()
    result = run(portal, lambda t: svc.load(t)[1], strategy, symbol, t0, t1, resolution, cash, CostModel(),
                 subscriptions, getattr(strategy, "reference_symbol", None), auxiliary)
    return result["decisions"]


def _upto(decisions, cut):
    return [{k: d.get(k) for k in ("t", *DECISION_FIELDS)} for d in decisions if datetime.fromisoformat(d["t"]) <= cut]


def check(db: MarketDB, db_after: dict[datetime, MarketDB], strategy_id: str, params: dict, symbol: str,
          t0: datetime, t1: datetime, resolution: str, cash: Decimal, *, cuts: list[datetime],
          prehistory: timedelta | None = None) -> dict:
    """`db_after[cut]` holds the same observations as `db` with everything after `cut` repriced."""
    full = replay(db, strategy_id, params, symbol, t0, t1, resolution, cash)
    report = {"strategy": strategy_id, "decisions": len(full),
              "acting": sum(not d["action"].startswith("ABSTAIN") for d in full), "truncation": {}, "perturbation": {}}
    for cut in cuts:
        expected = _upto(full, cut)
        report["truncation"][cut.isoformat()] = first_divergence(
            expected, _upto(replay(db, strategy_id, params, symbol, t0, cut, resolution, cash), cut), DECISION_FIELDS)
        if cut in db_after:
            report["perturbation"][cut.isoformat()] = first_divergence(
                expected, _upto(replay(db_after[cut], strategy_id, params, symbol, t0, t1, resolution, cash), cut),
                DECISION_FIELDS)
    if prehistory:
        longer = {d["t"]: d for d in replay(db, strategy_id, params, symbol, t0 - prehistory, t1, resolution, cash)}
        warm = [i for i, d in enumerate(full) if d["action"] != "ABSTAIN_WARMUP"]
        # Settled: three times the strategy's own warm-up after it first acts.
        settle = warm[0] + 2 * (warm[0] + 1) if warm else len(full)
        base = DataPortal(db).instrument(symbol).base
        ours, theirs = _holding(full, base), _holding([longer.get(d["t"], {}) for d in full], base)
        pairs = list(zip(ours[settle:], theirs[settle:]))
        # Position is path-dependent; once both runs hold the same position they must agree from then on.
        aligned = next((i for i, (a, b) in enumerate(pairs) if a == b), None)
        mismatch = None if aligned is None else next((i for i in range(aligned, len(pairs)) if pairs[i][0] != pairs[i][1]), None)
        report["warmup"] = {"compared": 0 if aligned is None else len(pairs) - aligned, "settle_bars": settle,
                            "first_mismatch": ({"index": settle, "reason": "never aligned"} if aligned is None and pairs else
                                               None if mismatch is None else
                                               {"index": settle + mismatch, "long": pairs[mismatch][0],
                                                "long_with_prehistory": pairs[mismatch][1]})}
    report["passed"] = (not any(report["truncation"].values()) and not any(report["perturbation"].values())
                        and not (report.get("warmup") or {}).get("first_mismatch"))
    return report


def _holding(decisions, base: str) -> list[bool | None]:
    """Actual position before each decision, from the recorded balances; None when the run has no such decision."""
    return [None if "balances_before" not in d else Decimal(d["balances_before"].get(base, "0")) > 0 for d in decisions]


def bar_step(resolution: str) -> timedelta:
    return BarSpec(resolution).step
