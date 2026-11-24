"""CLI runner for Track III Ablations (#5 Lead-Lag Diffusion, #9 Joint ADMM Netting, #6 Live Venue Dislocations)."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.diffusion_and_netting_study import (
    run_diffusion_and_netting_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Track III diffusion, joint ADMM netting, and live dislocation study")
    parser.add_argument("--wallex-db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/2026-11-25-diffusion-and-netting-report.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/2026-11-25-diffusion-and-netting.json"))
    args = parser.parse_args()
    res = run_diffusion_and_netting_study(args.wallex_db, args.multi_venue_db, args.report, args.receipt)
    print(f"Wrote {args.report} | diffusion={len(res['idea_5_lead_lag_diffusion'])} netting={len(res['idea_9_joint_admm_netting'])} live_pairs={len(res['idea_6_live_dislocation_rebate'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
