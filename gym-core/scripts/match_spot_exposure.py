"""Choose a constant EMA cap on a training segment, then replay it unchanged."""

import argparse
import asyncio
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from gym.adapters.run_store import load_verified_run, save_run
from gym.adapters.store import MarketDB
from gym.domain.market_models import decimal
from gym.domain.model import iso, parse_ts
from gym.domain.sim import CostModel
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.market_watchlists import save_watchlist
from gym.services.research_ledger import ResearchLedger
from gym.services.research_process import calculate
from scripts.audit_shared_portfolio import _fx_mid
from scripts.spot_capital_exposure import spot_capital_exposure


def _job_options(run):
    inputs = run["inputs"]
    cash = inputs.get("cash_by_currency")
    if (not cash or inputs.get("strategy") != "ema-trend" or not inputs.get("rank_gate")
            or inputs.get("rules_mode") != "point-in-time"
            or {"funding_legs", "fx_rebalance", "margin_positions", "policy"} & inputs.keys()):
        raise ValueError("target must be a point-in-time ranked spot EMA portfolio")
    cost = inputs["cost"]
    if cost.get("max_fraction") is not None:
        raise ValueError("target already has a fraction cap")
    options = {"fee_rate": cost["fee_rate"]}
    if "max_participation" in cost:
        options["max_participation"] = cost["max_participation"]
    if cost != CostModel(**{k: Decimal(v) for k, v in options.items()}).describe():
        raise ValueError("target costs cannot be reproduced by the scheduler")
    options.update(every_seconds=86400, resolution=inputs["resolution"], cash="1000", cash_by_currency=cash)
    for key in ("venue", "valuation_symbol", "dynamic_routes"):
        if key in inputs:
            options[key] = inputs[key]
    selection = inputs.get("universe_selection")
    if selection is None:
        options["portfolio_symbols"] = inputs["symbols"]
    elif selection.get("schema") not in ("whole-spot-universe/1", "whole-spot-universe/2", "watchlist-spot-universe/1"):
        raise ValueError("target universe is unavailable in the scheduler")
    return options


def _exposure(db, run, **window):
    inputs = run["inputs"]
    portal = DataPortal(db, venue=inputs.get("venue", "wallex"))
    fx = run["result"]["valuation"]["conversion"]
    rate = _fx_mid(portal, fx["start_at"], fx["pair"], explicit="valuation_symbol" in inputs)
    return Decimal(spot_capital_exposure(run, rate, **window)["mean_deployed_share_of_opening_equity"])


async def _replay(archive, output, target, options, cap, through, *, store):
    inputs = target["inputs"]
    begin = parse_ts(inputs["from"])
    job = {**options, "lookback_seconds": int((through - begin).total_seconds()), "first_at": iso(through),
           "max_fraction": str(cap)}
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix="spot-exposure-") as temporary:
        root = Path(temporary)
        os.link(archive, root / "market.db")
        watchlist = (inputs.get("universe_selection") or {}).get("watchlist")
        if watchlist:
            job["watchlist_id"] = save_watchlist(
                root, {key: watchlist[key] for key in ("name", "symbols", "effective_from")})["watchlist_id"]
        with ResearchLedger(root / "research.sqlite3") as ledger:
            saved = ledger.register({"symbol": sorted(inputs["symbols"])[0], "strategy": inputs["strategy"],
                                     "params": inputs["params"]})
            ledger.schedule({**job, "hypothesis_id": saved["hypothesis_id"]})
        outcome = await calculate(root, "tick", at=iso(through), store=store)
        if outcome["failed"]:
            raise ValueError(f"scheduled exposure comparison failed: {outcome['failed']}")
        completed, = outcome["completed"]
        run = load_verified_run(root / "runs" / "portfolios", completed["run_id"], store=store)
        save_run(run, output / "runs")
        return run


def _later(db, run, cutoff):
    result = run["result"]
    split = next((amount for stamp, amount in result["curve"] if parse_ts(stamp) == cutoff), None)
    end = result["end"]
    marked = (Decimal(end["equity"]) / Decimal(split) - 1) * 10000 if split and Decimal(split) > 0 else None
    return {"run_id": run["run_id"], "digest": run["outputs_digest"], "split_equity": split,
            "end_equity": end["equity"], "valuation_status": end["valuation_status"],
            "marked_return_bps": str(marked) if marked is not None else None,
            "exposure_share": str(_exposure(db, run, start=cutoff))}


async def compare(archive, output, target, cutoff, caps, tolerance, *, store):
    start, end = map(parse_ts, (target["inputs"]["from"], target["inputs"]["to"]))
    if not start < cutoff < end or cutoff.microsecond or start.microsecond or end.microsecond:
        raise ValueError("training cutoff must be a whole second strictly inside the replay")
    if not 60 <= (cutoff - start).total_seconds() or (end - start).total_seconds() > 2678400:
        raise ValueError("comparison requires 60 seconds to 31 days")
    if (not 1 <= len(caps) <= 8 or len(set(caps)) != len(caps)
            or any(not 0 < cap <= 1 for cap in caps) or not 0 <= tolerance <= 1):
        raise ValueError("provide 1..8 unique size caps and a tolerance at most one")
    wal = archive.with_name(archive.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("comparison requires a closed archive snapshot")
    options = _job_options(target)
    output.mkdir(parents=True)
    db = MarketDB(archive, readonly=True)
    try:
        target_training = _exposure(db, target, end=cutoff)
        manifest = {"scope": "CHRONOLOGICAL_DEVELOPMENT_SPLIT", "target_run": target["run_id"],
                    "target_outputs": target["outputs_digest"], "target_inputs": digest(target["inputs"]),
                    "portfolio_data_digest": target["inputs"]["data"], "train_to": iso(cutoff),
                    "caps": [str(cap) for cap in caps], "tolerance": str(tolerance),
                    "target_training_share": str(target_training), "job": options,
                    "selection_rule": "Smallest absolute training exposure gap, then smallest cap."}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        training = []
        attempts = output / "training.jsonl"
        for cap in caps:
            try:
                run = await _replay(archive, output, target, options, cap, cutoff, store=store)
                share = _exposure(db, run)
                difference = abs(share - target_training)
            except (ValueError, RuntimeError, OSError) as error:
                with attempts.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"cap": str(cap), "status": "FAILED", "reason": str(error)}) + "\n")
                raise
            training.append((difference, cap, run["run_id"], share))
            with attempts.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"cap": str(cap), "run_id": run["run_id"], "status": "COMPLETED",
                                         "share": str(share), "gap": str(difference)}) + "\n")
        gap, cap, _, selected_share = min(training)
        candidate = await _replay(archive, output, target, options, cap, end, store=store)
        checks = ("data", "fx_data", "metadata", "symbols", "universe_selection")
        if (any(candidate["inputs"].get(key) != target["inputs"].get(key) for key in checks)
                or candidate["result"]["start_cash"] != target["result"]["start_cash"]):
            raise ValueError("target and comparator do not cover the same full tape")
        if abs(_exposure(db, candidate, end=cutoff) - selected_share) > Decimal("1e-26"):
            raise ValueError("evaluation suffix changed the training exposure")
        later = {"target": _later(db, target, cutoff), "constant_cap": _later(db, candidate, cutoff)}
        later_gap = abs(Decimal(later["target"]["exposure_share"]) - Decimal(later["constant_cap"]["exposure_share"]))
        fully_scored = all(row["valuation_status"] == "CURRENT" and row["marked_return_bps"] is not None for row in later.values())
        report = {"manifest_id": digest(manifest),
                  "training": [{"run_id": rid, "cap": str(c), "share": str(s), "gap": str(g)} for g, c, rid, s in training],
                  "selected_cap": str(cap), "training_match": gap <= tolerance, "later_match": later_gap <= tolerance,
                  "later_absolute_exposure_gap": str(later_gap), "later": later,
                  "status": "DEVELOPMENT_COMPARISON" if gap <= tolerance and later_gap <= tolerance and fully_scored else "INCONCLUSIVE"}
        (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        db.c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--train-to", type=parse_ts, required=True)
    parser.add_argument("--caps", nargs="+", required=True)
    parser.add_argument("--tolerance", required=True)
    parser.add_argument("--store", choices=("live", "demo"), default="live")
    args = parser.parse_args()
    caps = [decimal(cap, "cap", positive=True) for cap in args.caps]
    target = load_verified_run(args.target.parent, args.target.stem, store=args.store)
    report = asyncio.run(compare(args.archive, args.output, target, args.train_to, caps,
                                 decimal(args.tolerance, "tolerance"), store=args.store))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
