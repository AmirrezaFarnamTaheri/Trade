"""Complexity ratchet (finding E-1): no new function above 20, and no listed function may grow.

The baseline lists the functions still above the ceiling with their current complexity. Lower a number (or drop
the entry) when a function is split; `--update` rewrites the file from the current tree but never raises a
ceiling. Run from gym-core: `python scripts/complexity_ratchet.py`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CEILING = 20
ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "complexity-baseline.json"


def measure() -> dict[str, int]:
    out = subprocess.run(["uvx", "ruff==0.16.9", "check", "--isolated", "--select", "C901", "--config",
                          f"lint.mccabe.max-complexity={CEILING}", "--output-format", "json", "src"],
                         cwd=ROOT, capture_output=True, text=True, check=False).stdout
    found = {}
    for item in json.loads(out or "[]"):
        name, value = re.match(r"`(.+)` is too complex \((\d+) >", item["message"]).groups()
        path = Path(item["filename"]).resolve().relative_to(ROOT).as_posix()
        found[f"{path}::{name}"] = int(value)
    return found


def compare(found: dict[str, int], baseline: dict[str, int]) -> list[str]:
    problems = []
    for key, value in sorted(found.items()):
        if key not in baseline:
            problems.append(f"{key} is {value}, above {CEILING}, and not in the baseline: split it")
        elif value > baseline[key]:
            problems.append(f"{key} grew from {baseline[key]} to {value}")
    return problems


def main(argv: list[str]) -> int:
    found = measure()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    problems = compare(found, baseline)
    if "--update" in argv:
        kept = {k: min(v, baseline.get(k, v)) for k, v in found.items() if k in baseline or not baseline}
        BASELINE.write_text(json.dumps(dict(sorted(kept.items())), indent=2) + "\n", encoding="utf-8", newline="\n")
    for line in problems:
        print("FAIL", line)
    for key in sorted(set(baseline) - set(found)):
        print("improved:", key, "is now at or below", CEILING, "- remove it from the baseline")
    for key, value in sorted(found.items()):
        if key in baseline and value < baseline[key]:
            print("improved:", key, baseline[key], "->", value, "- lower the baseline")
    print(f"{len(found)} functions above {CEILING}; {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
