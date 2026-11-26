"""Size a prospective paired portfolio study under declared independent-block assumptions."""
import argparse
import json
import math
from statistics import NormalDist


def plan(*, threshold_bps, alternative_bps, block_sd_bps, block_days, comparisons, alpha=0.05, power=0.8):
    """Plan a one-sided test of mean paired uplift above the economic threshold."""
    gap = alternative_bps - threshold_bps
    if (not all(map(math.isfinite, (threshold_bps, alternative_bps, block_sd_bps))) or gap <= 0 or block_sd_bps <= 0
            or type(block_days) is not int or block_days < 1 or type(comparisons) is not int or comparisons < 1
            or not 0 < alpha < 0.5 or not 0.5 < power < 1):
        raise ValueError("invalid prospective power assumptions")
    tail = alpha / comparisons
    normal = NormalDist()
    critical, target = -normal.inv_cdf(tail), normal.inv_cdf(power)
    blocks = math.ceil(((critical + target) * block_sd_bps / gap) ** 2)
    return {"method": "one-sided normal approximation with Bonferroni adjustment",
            "economic_threshold_bps": threshold_bps, "design_alternative_bps": alternative_bps,
            "assumed_paired_block_sd_bps": block_sd_bps, "family_comparisons": comparisons,
            "family_alpha": alpha, "per_comparison_alpha": tail, "power_target": power,
            "independent_blocks_required": blocks, "calendar_days_if_complete": blocks * block_days,
            "block_days": block_days}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("threshold-bps", "alternative-bps", "block-sd-bps"):
        parser.add_argument("--" + name, required=True, type=float)
    for name in ("block-days", "comparisons"):
        parser.add_argument("--" + name, required=True, type=int)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.8)
    print(json.dumps(plan(**vars(parser.parse_args())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
