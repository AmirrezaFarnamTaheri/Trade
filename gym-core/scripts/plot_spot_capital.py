"""Plot a capital comparison and export residual sizes in their original units."""
import argparse
import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def plot(report, figure_path, quantities_path):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    runs = sorted(report["runs"], key=lambda run: Decimal(run["opening_equity"]))
    if report["schema"] != "spot-capital-comparison/1" or len(runs) < 2:
        raise ValueError("expected at least two comparable capital runs")
    reference = runs[0]
    for run in runs:
        for key in ("archive_digest", "cost", "markets", "observations"):
            if run[key] != reference[key]:
                raise ValueError(f"capital runs differ on {key}")
        for key in ("model", "through_exclusive"):
            if run["post_cutoff_exit"][key] != reference["post_cutoff_exit"][key]:
                raise ValueError(f"exit windows differ on {key}")
    opening = [float(run["opening_equity"]) for run in runs]
    if len(set(opening)) != len(opening):
        raise ValueError("capital runs must have distinct opening equity")
    currency = reference["booked_deployment"]["reporting_currency"]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), layout="constrained")
    deployed, returns, unfilled, exits = axes.flat
    deployed.plot(opening, [float(run["booked_deployment"]["mean_deployed_capital"]) for run in runs], "o-")
    deployed.set(ylabel=f"Mean deployed capital ({currency})")
    returns.plot(opening, [float(run["marked_return"]) for run in runs], "o-")
    returns.yaxis.set_major_formatter(PercentFormatter(1))
    returns.set(ylabel="Marked net return", title="Closing marks may be stale")
    counts = [sum(Decimal(row["quantity"]) > 0 for row in run["known_unfilled_base_by_market_and_side"])
              for run in runs]
    unfilled.plot(opening, counts, "o-")
    unfilled.set(ylabel="Market-side pairs with known unfilled size")
    for axis in (deployed, returns, unfilled):
        axis.set_xlabel(f"Opening equity ({currency})")
    for cash, run in zip(opening, runs, strict=True):
        positions = run["post_cutoff_exit"]["positions"]
        if not positions:
            continue
        times = sorted(p["seconds_to_flat"] for p in positions if p["seconds_to_flat"] is not None)
        end = datetime.fromisoformat(run["post_cutoff_exit"]["through_exclusive"])
        start = datetime.fromisoformat(run["booked_deployment"]["to"])
        horizon = (end - start).total_seconds()
        exits.step([0, *times, horizon], [i / len(positions) for i in range(len(times) + 1)]
                   + [len(times) / len(positions)], where="post", label=f"{cash:,.0f} {currency}")
    exits.set(xlabel="Seconds from exit window open", ylabel="Share of positions fully exited")
    exits.set_xscale("symlog", linthresh=60)
    exits.yaxis.set_major_formatter(PercentFormatter(1))
    exits.legend()
    for axis in axes.flat:
        axis.grid(alpha=0.25)
    fig.suptitle("TradingGYM historical spot capital comparison")
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    with quantities_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("run_id", "opening_equity", "symbol", "side", "known_unfilled_base_quantity"))
        for run in runs:
            for row in run["known_unfilled_base_by_market_and_side"]:
                writer.writerow((run["run_id"], run["opening_equity"], row["symbol"], row["side"], row["quantity"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    parser.add_argument("figure", type=Path)
    parser.add_argument("quantities", type=Path)
    args = parser.parse_args()
    plot(json.loads(args.comparison.read_text(encoding="utf-8")), args.figure, args.quantities)


if __name__ == "__main__":
    main()
