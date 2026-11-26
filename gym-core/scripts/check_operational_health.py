"""CLI entrypoint for the TradingGYM read-only operational health & data-freshness watchdog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.operational_health import run_operational_health_check


def main() -> int:
    parser = argparse.ArgumentParser(description="Check TradingGYM collector, multi-venue quote, journal, and model health")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("../evidence"))
    parser.add_argument("--out", type=Path, default=Path("../evidence/forward/operational-health.json"))
    args = parser.parse_args()
    res = run_operational_health_check(args.data_dir, args.evidence_dir, report_path=args.out)
    print(json.dumps(res, indent=2))
    return 0 if res["overall_status"] != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
