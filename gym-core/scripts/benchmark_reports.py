"""Measure benchmark-report arithmetic on deterministic synthetic data.

Run from gym-core: uv run --no-sync python scripts/benchmark_reports.py.
Timings cover calculation only; byte counts describe the JSON input.
"""
import json
import platform
import sys
import time
from statistics import median

from gym.domain.performance import _benchmark


def main():
    repeats = 5
    metrics = {
        "schema": "report-benchmark/1",
        "dataset": "synthetic: equity=1000+i*.04+(i%11)*.01; bid=100+i*.01+(i%7)*.003",
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "repeats": repeats,
        "statistic": "median_seconds",
    }
    for count in (1000, 3000, 6000):
        record = {"result": {
            "base": "BTC",
            "decisions": [{"t": str(i), "bid": str(100 + i * .01 + (i % 7) * .003)}
                          for i in range(count)],
            "curve": [(str(i), str(1000 + i * .04 + (i % 11) * .01)) for i in range(count)],
        }}
        elapsed = []
        for _ in range(repeats):
            started = time.perf_counter()
            _benchmark(record, None)
            elapsed.append(time.perf_counter() - started)
        metrics[f"benchmark_{count}_seconds"] = median(elapsed)
        metrics[f"benchmark_{count}_input_bytes"] = len(json.dumps(record).encode("utf-8"))
    print(json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
