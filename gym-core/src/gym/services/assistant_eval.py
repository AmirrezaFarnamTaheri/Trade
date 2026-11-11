"""Offline evaluation of the research assistant's model against a no-model baseline.

A model earns a place in the assistant only if it beats random sampling from the strategy catalogue on a fixed
prompt set. The set is deterministic (markets x resolutions x earlier-test histories) and uses the assistant's
real prompt and parser. Measured per run: share of replies that hold a JSON array, share of proposals that are
valid registry configurations, share that repeat an earlier test in the prompt's own history, and p95 latency.
No paper replay runs here and nothing is saved; this measures proposal quality only.
"""
from __future__ import annotations

import json
import random
import time

from ..domain.registry import STRATEGIES, catalog, create_strategy
from .research_assistant import extract_array, parse_proposals, prompt

SYMBOLS = ("BTCUSDT", "ETHUSDT", "USDTTMN", "BTCTMN", "SOLUSDT")
RESOLUTIONS = ("15min", "1h")
BUDGET = 3


def cases(count: int = 30, seed: int = 11) -> list[dict]:
    """Deterministic prompts; each history lists earlier tests the model should not repeat."""
    rng, out = random.Random(seed), []
    names = sorted(STRATEGIES)
    for i in range(count):
        symbol, resolution = SYMBOLS[i % len(SYMBOLS)], RESOLUTIONS[(i // len(SYMBOLS)) % len(RESOLUTIONS)]
        history = []
        for _ in range(rng.randint(0, 6)):
            strategy = create_strategy(rng.choice(names), {})
            history.append({"strategy": strategy.name, "params": strategy.params, "net": str(rng.randint(-50, 50))})
        tried = frozenset(create_strategy(h["strategy"], h["params"]).config_hash for h in history)
        out.append({"id": f"case-{i:02d}", "symbol": symbol, "resolution": resolution,
                    "prompt": prompt(symbol, resolution, history, BUDGET), "tried": tried})
    return out


def baseline_reply(seed: int):
    """A no-model 'reply': BUDGET random catalogue entries with parameters drawn inside each schema."""
    rng, entries = random.Random(seed), catalog()

    def draw(spec):
        if spec["type"] == "integer":
            return rng.randint(spec["minimum"], min(spec["maximum"], spec["minimum"] + 200))
        return rng.choice(spec["enum"]) if "enum" in spec else spec["default"]
    picks = []
    for entry in rng.sample(entries, BUDGET):
        params = {k: draw(v) for k, v in entry["parameters"]["properties"].items()
                  if k != "regime_gate" and v.get("type") in ("integer", "string")}
        picks.append({"strategy": entry["id"], "params": params, "rationale": "random catalogue sample"})
    return json.dumps(picks)


def evaluate(complete, prompt_set: list[dict]) -> dict:
    """`complete(prompt) -> text`. Returns per-metric rates over the prompt set."""
    valid_json = proposals = valid = repeats = 0
    latencies = []
    for case in prompt_set:
        started = time.monotonic()
        text = complete(case["prompt"])
        latencies.append(time.monotonic() - started)
        items = extract_array(text)
        if items is None:
            continue
        valid_json += 1
        proposals += min(len(items), BUDGET)
        fresh = parse_proposals(text, BUDGET, case["tried"])
        everything = parse_proposals(text, BUDGET, frozenset())
        valid += len(everything)
        repeats += len(everything) - len(fresh)
    n = len(prompt_set)
    latencies.sort()
    return {"cases": n, "json_valid_rate": round(valid_json / n, 3),
            "valid_proposal_rate": round(valid / proposals, 3) if proposals else 0.0,
            "repeat_rate": round(repeats / valid, 3) if valid else 0.0,
            "p95_seconds": round(latencies[max(0, int(0.95 * n) - 1)], 3) if latencies else None}


def baseline(prompt_set: list[dict]) -> dict:
    counter = iter(range(10**6))
    return evaluate(lambda _prompt: baseline_reply(next(counter)), prompt_set)


def verdict(model: dict, base: dict) -> dict:
    """Thresholds fixed before any model is run: the model must be at least as valid and repeat less."""
    passes = (model["json_valid_rate"] >= 0.95 and model["valid_proposal_rate"] >= base["valid_proposal_rate"]
              and model["repeat_rate"] <= base["repeat_rate"])
    return {"model": model, "baseline": base, "adopt": passes,
            "thresholds": "json_valid_rate >= 0.95, valid_proposal_rate >= baseline, repeat_rate <= baseline"}
