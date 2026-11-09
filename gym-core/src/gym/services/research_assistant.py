"""Model-assisted research: a model proposes strategy configurations, the paper engine tests them.

The model only writes proposals. Every proposal is validated against the strategy registry, already-tried
configurations are skipped, the trial budget is enforced here, and each tested configuration becomes a
saved run, so the deflated-Sharpe check counts it as a trial. Nothing reaches an order path.
"""
import json
import re
from datetime import datetime
from decimal import Decimal

from ..adapters.run_store import list_runs, save_run
from ..domain.registry import catalog, create_strategy
from ..domain.sim import CostModel
from .research import compare, tried_before

MAX_BUDGET = 4  # one matched comparison holds at most four candidates


def prompt(symbol: str, resolution: str, history: list[dict], budget: int) -> str:
    strategies = [{"id": entry["id"], "parameters": entry["parameters"]["properties"], "constraints": entry["constraints"]}
                  for entry in catalog()]
    return ("You are helping design PAPER-ONLY trading research. Propose strategy configurations to test next.\n"
            f"Market: {symbol}. Decision close: {resolution}.\n"
            f"Available strategies and parameter schemas (JSON): {json.dumps(strategies)}\n"
            f"Already tested here, newest first, with net result (JSON): {json.dumps(history[:30])}\n"
            f"Reply with ONLY a JSON array of at most {budget} objects: "
            '{"strategy": <id>, "params": {...}, "rationale": <one sentence>}. Prefer configurations unlike the tested ones.')


REPAIR = ("Your previous reply did not contain a valid JSON array. Reply again with ONLY the JSON array, "
          "no prose and no code fences.")


def extract_array(text: str) -> list | None:
    """The first complete JSON array in the reply, wherever it starts; brackets in surrounding prose do not break it."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    return None


def parse_proposals(text: str, budget: int, tried: frozenset) -> list[dict]:
    """First JSON array in the reply; invalid, duplicate and already-tried configurations are dropped."""
    items = extract_array(text) or []
    proposals, seen = [], set(tried)
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("params", {}), dict):
            continue
        try:
            strategy = create_strategy(item.get("strategy"), item.get("params") or {})
        except (ValueError, TypeError):
            continue
        if strategy.config_hash in seen:
            continue
        seen.add(strategy.config_hash)
        proposals.append({"strategy": strategy.name, "params": strategy.params,
                          "rationale": str(item.get("rationale", ""))[:300]})
        if len(proposals) == budget:
            break
    return proposals


async def assist(complete, db, runs, symbol: str, start: datetime, end: datetime, *, preset: str, budget: int,
                 resolution: str = "15min", cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), store: str = "live") -> dict:
    """`complete` is the model gateway call: (action, value) -> result with "text"."""
    if type(budget) is not int or not 2 <= budget <= MAX_BUDGET:
        raise ValueError(f"budget must be 2..{MAX_BUDGET} configurations")
    history = [{"strategy": row["inputs"].get("strategy"), "params": row["inputs"].get("params"), "net": (row.get("end") or {}).get("net")}
               for row in list_runs(runs, limit=200, symbol=symbol) if row["inputs"].get("resolution") == resolution]
    request = prompt(symbol, resolution, history, budget)
    reply = await complete("complete", {"preset": preset, "prompt": request})
    usage, attempts = [reply.get("usage")], 1
    if extract_array(str(reply.get("text", ""))) is None:  # one repair retry, then give up and say why
        reply = await complete("complete", {"preset": preset, "prompt": request + "\n\n" + REPAIR})
        usage.append(reply.get("usage"))
        attempts = 2
    text = str(reply.get("text", ""))
    proposals = parse_proposals(text, budget, tried_before(runs, symbol, resolution))
    report = {"mode": "PAPER_ONLY", "symbol": symbol, "budget": budget, "proposals": proposals,
              "usage": usage[0] if attempts == 1 else usage, "model": reply.get("model"),
              "reply_attempts": attempts, "reply_valid": extract_array(text) is not None}
    if not report["reply_valid"]:
        return {**report, "status": "INVALID_MODEL_REPLY"}
    if len(proposals) < 2:
        return {**report, "status": "TOO_FEW_NEW_PROPOSALS"}
    result = compare(db, symbol, start, end, [{"strategy": p["strategy"], "params": p["params"]} for p in proposals],
                     resolution=resolution, cash=cash, cost=cost, store=store, prior_configs=tried_before(runs, symbol, resolution))
    for record in result["runs"]:
        save_run(record, runs)
    return {**report, "status": "TESTED", "comparison_id": result["comparison_id"], "selection": result["selection"],
            "results": [{"run_id": r["run_id"], "strategy": r["inputs"]["strategy"], "params": r["inputs"]["params"],
                         "net": r["result"]["end"]["net"] if r["result"]["end"] else None,
                         "sharpe_per_period": ((result["performance"][r["run_id"]].get("returns") or {}).get("sharpe_per_period"))}
                        for r in result["runs"]]}
