"""Run Post-Repair Microstructure & Treasury Study (Menu Ideas 1, 6, 11 + Dual-Clock Audit)."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.signal_expiry_cash_and_feed_study import (
    run_signal_expiry_cash_and_feed_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_signal_expiry_cash_and_feed_study(
        wallex_db=repo / "data" / "live" / "market.db",
        multi_venue_db=repo / "data" / "live" / "multi_venue_quotes.sqlite3",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "signal-expiry-cash-and-feed-study.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "signal-expiry-cash-and-feed-receipt.json",
    )
    print("Idea 1 Slow 1d:", [(r["delay_bars"], r["ret_pct"], r["ann_sharpe"]) for r in res["idea_1_signal_expiry_slow_1d"]])
    print("Idea 1 Ign 2h:", [(r["delay_bars"], r["ret_pct"], r["ann_sharpe"], r["entries"], r["missed_or_expired"]) for r in res["idea_1_signal_expiry_ignition_2h"]])
    print("Idea 6 Cash:", [(r["label"], r["ret_pct"], r["ann_sharpe"], r["blocked_ign"], r["blocked_mean_24h_net_pct"]) for r in res["idea_6_cash_option_value"]])
    print("Idea 11 Feed:", [(r["notional_usdt"], r["arm"], r["med_smart_taker_bps"], r["mean_passive_fill_pct"]) for r in res["idea_11_feed_value_ablation"].get("arms", [])])


if __name__ == "__main__":
    main()
