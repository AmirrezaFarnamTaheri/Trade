"""Rare Micro-Signal Portfolio Weekly Opportunity, Portfolio Fragility & Two-Leg Gold Tape Study.

Implements:
  - Weekly Opportunity Table (docs/architecture/rare-micro-signal-research-design.md):
    Ignition alone, Failed Downside Auction, Peer-Relative Catch-Up, pairs, and all 3 combined.
  - Portfolio Fragility Report (Priority #3 of 2026-11-26 review):
    Replays the actual position-sized portfolio after erasing the top 3 market-shock episodes.
  - Prospective Two-Leg Native Gold-Switching Tape Audit (Priority #4):
    Pairs live Nobitex XAUTUSDT and PAXGUSDT bid/ask quotes within 15s and prices failed second legs.

Strictly read-only against market.db / multi_venue_quotes.sqlite3; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.model import dec, parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.rare_micro_signals import MicroSignalIntent, scan_micro_signal_intents
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .ensemble_study import portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO


def _cluster_episode_id(ts: datetime, episodes: list[datetime], gap_hours: int = 6) -> int:
    if not episodes or (ts - episodes[-1]) > timedelta(hours=gap_hours):
        episodes.append(ts)
    return len(episodes) - 1


def _replay_micro_portfolio(
    panel_2h: dict[str, list[BarPoint]],
    intents: list[MicroSignalIntent],
    *,
    label: str,
    leg_cost: float = 0.0016,
    max_slots: int = 3,
    excluded_episode_ids: set[int] | None = None,
) -> tuple[dict, dict[int, float]]:
    """Replay a fixed-risk-budget paper book on a union of intents; returns (metrics, episode_pnl_usdt)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    if not all_ts:
        return {"label": label, "ending_nav": 1000.0}, {}

    # Assign market-shock episode IDs chronologically across the combined stream
    ep_starts: list[datetime] = []
    intents_by_ts: dict[datetime, list[tuple[MicroSignalIntent, int]]] = {}
    for it in sorted(intents, key=lambda x: (x.ts_avail, -x.strength, x.symbol)):
        ep_id = _cluster_episode_id(it.ts_avail, ep_starts)
        if excluded_episode_ids and ep_id in excluded_episode_ids:
            continue
        intents_by_ts.setdefault(it.ts_avail, []).append((it, ep_id))

    equity = 1000.0
    active: dict[str, dict] = {}
    last_px: dict[str, float] = {}
    stale_mark_steps = 0
    nav_by_date: dict[str, float] = {}
    episode_pnl: dict[int, float] = {}
    trade_net_bps: list[float] = []
    active_weeks: set[tuple[int, int]] = set()
    executed_episodes: set[int] = set()
    fills = misses = 0

    for ts in all_ts:
        for sym in IGNITION_18_CRYPTO:
            b_cur = by_avail[sym].get(ts)
            if b_cur is not None and b_cur.close > 0:
                last_px[sym] = b_cur.close
        # Step exits
        for sym in list(active):
            pos = active[sym]
            cur = by_avail[sym].get(ts)
            nxt = by_start[sym].get(ts)
            if cur is None:
                continue
            pos["age"] += 1
            pos["peak"] = max(pos["peak"], cur.high)
            hit_inv = cur.close <= pos["inv_px"]
            hit_trail = cur.close <= pos["peak"] * (1.0 - 2.5 * pos["bar_vol"])
            if pos["age"] >= pos["max_hold"] or hit_inv or hit_trail:
                ex_px = nxt.open if (nxt and nxt.open > 0) else cur.close
                ex_fee = pos["qty"] * ex_px * leg_cost
                pnl = pos["qty"] * (ex_px - pos["entry_px"]) - pos["entry_fee"] - ex_fee
                equity = max(0.0, equity + pos["col"] + pnl)
                episode_pnl[pos["ep_id"]] = episode_pnl.get(pos["ep_id"], 0.0) + pnl
                trade_net_bps.append((pnl / max(1e-9, pos["col"])) * 10_000.0)
                del active[sym]

        # Step entries
        for it, ep_id in intents_by_ts.get(ts, []):
            if it.symbol in active or len(active) >= max_slots or equity <= 100.0:
                misses += 1
                continue
            nxt = by_start[it.symbol].get(ts)
            if nxt is None or nxt.open <= 0:
                misses += 1
                continue
            col = min(equity * 0.30, equity - 1.0)
            if col < 25.0:
                misses += 1
                continue
            ef = col * leg_cost
            equity -= col
            active[it.symbol] = {
                "col": col, "qty": (col - ef) / nxt.open, "entry_px": nxt.open, "entry_fee": ef,
                "inv_px": it.invalidation_px, "peak": nxt.open, "bar_vol": it.bar_vol,
                "max_hold": it.max_hold_bars, "age": 0, "ep_id": ep_id,
            }
            fills += 1
            iso_cal = ts.isocalendar()
            active_weeks.add((iso_cal[0], iso_cal[1]))
            executed_episodes.add(ep_id)

        mark_u = 0.0
        for s, p in active.items():
            b_m = by_avail[s].get(ts)
            if b_m is not None and b_m.close > 0:
                px_m = b_m.close
            else:
                px_m = last_px.get(s, p["entry_px"])
                stale_mark_steps += 1
            mark_u += p["col"] + p["qty"] * (px_m - p["entry_px"])
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + mark_u)

    # Weekly drought stats
    all_weeks = sorted({(t.isocalendar()[0], t.isocalendar()[1]) for t in all_ts})
    longest_drought = cur_drought = 0
    for wk in all_weeks:
        if wk in active_weeks:
            cur_drought = 0
        else:
            cur_drought += 1
            longest_drought = max(longest_drought, cur_drought)

    m = portfolio_metrics(nav_by_date, starting_nav=1000.0)
    intended = fills + misses
    # Net P&L per intended trade (misses contribute 0 bps)
    net_per_intended = (sum(trade_net_bps) / intended) if intended > 0 else 0.0
    return {
        "label": label,
        "total_weeks": len(all_weeks),
        "active_weeks": len(active_weeks),
        "longest_drought_weeks": longest_drought,
        "unique_episodes": len(executed_episodes),
        "fills": fills,
        "misses": misses,
        "stale_mark_steps": stale_mark_steps,
        "net_bps_per_intended": round(net_per_intended, 2),
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
    }, episode_pnl


def _audit_live_gold_two_leg_tape(multi_venue_db: Path, *, max_skew_s: float = 15.0) -> dict:
    """Priority #4: Evaluate native Nobitex XAUTUSDT <-> PAXGUSDT executable bid/ask pairs & failed-second-leg risk."""
    if not multi_venue_db.is_file():
        return {"status": "MISSING_DB"}
    con = open_readonly_market_db(multi_venue_db)
    try:
        x_rows = con.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty FROM venue_quotes "
            "WHERE venue = 'nobitex' AND symbol = 'XAUTUSDT' ORDER BY ts_avail ASC"
        ).fetchall()
        p_rows = con.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty FROM venue_quotes "
            "WHERE venue = 'nobitex' AND symbol = 'PAXGUSDT' ORDER BY ts_avail ASC"
        ).fetchall()
    finally:
        con.close()
    if not x_rows or not p_rows:
        return {"status": "INSUFFICIENT_NATIVE_GOLD_QUOTES", "xaut_rows": len(x_rows), "paxg_rows": len(p_rows)}

    p_ep = [parse_ts(r[0]).timestamp() for r in p_rows]
    rt_fee = 0.0032
    paired = 0
    positive_net_events = 0
    best_net_bps = -1e9
    net_edges_bps: list[float] = []
    unwind_costs_bps: list[float] = []

    for ts_s, xb_s, xa_s, _xbq_s, _xaq_s in x_rows:
        t_ep = parse_ts(ts_s).timestamp()
        pos = bisect_right(p_ep, t_ep) - 1
        if pos < 0 or (t_ep - p_ep[pos]) > max_skew_s:
            continue
        _, pb_s, pa_s, pbq_s, paq_s = p_rows[pos]
        xb, xa = float(dec(xb_s)), float(dec(xa_s))
        pb, pa = float(dec(pb_s)), float(dec(pa_s))
        if min(xb, xa, pb, pa) <= 0:
            continue
        paired += 1
        # Sell XAUT at bid, buy PAXG at ask (and vice versa), after 32 bps two-leg fees
        x_to_p = ((xb / pa) * (1.0 - rt_fee) - 1.0) * 10_000.0
        p_to_x = ((pb / xa) * (1.0 - rt_fee) - 1.0) * 10_000.0
        best_dir = max(x_to_p, p_to_x)
        best_net_bps = max(best_net_bps, best_dir)
        # Cost of unwinding if second leg fails = own spread + 32 bps round-trip
        own_sp = ((xa - xb) / xb * 10_000.0) if x_to_p >= p_to_x else ((pa - pb) / pb * 10_000.0)
        if best_dir > 0.0:
            positive_net_events += 1
            net_edges_bps.append(best_dir)
            unwind_costs_bps.append(own_sp + 32.0)

    return {
        "status": "OK",
        "xaut_quotes": len(x_rows),
        "paxg_quotes": len(p_rows),
        "paired_within_15s": paired,
        "positive_net_switch_events": positive_net_events,
        "best_executable_net_bps": round(best_net_bps, 2) if paired > 0 else None,
        "mean_positive_edge_bps": round(mean(net_edges_bps), 2) if net_edges_bps else 0.0,
        "mean_failed_second_leg_unwind_bps": round(mean(unwind_costs_bps), 2) if unwind_costs_bps else 0.0,
    }


def run_rare_micro_signal_portfolio_study(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Execute the Weekly Opportunity Table, Position-Sized Portfolio Fragility Report, and Gold Two-Leg Tape Audit."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    daily_breadth = extract_daily_breadth(sigs_13)
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO if panel_1h[s]}

    by_mech = scan_micro_signal_intents(panel_2h, IGNITION_18_CRYPTO, daily_breadth)
    combos = (
        ("IGNITION_ONLY", by_mech["MOMENTUM_IGNITION"]),
        ("FAILED_AUCTION_ONLY", by_mech["FAILED_DOWNSIDE_AUCTION"]),
        ("PEER_CATCHUP_ONLY", by_mech["PEER_RELATIVE_CATCHUP"]),
        ("IGNITION_PLUS_FAILED_AUCTION", by_mech["MOMENTUM_IGNITION"] + by_mech["FAILED_DOWNSIDE_AUCTION"]),
        ("IGNITION_PLUS_PEER_CATCHUP", by_mech["MOMENTUM_IGNITION"] + by_mech["PEER_RELATIVE_CATCHUP"]),
        ("ALL_THREE_COMBINED", by_mech["MOMENTUM_IGNITION"] + by_mech["FAILED_DOWNSIDE_AUCTION"] + by_mech["PEER_RELATIVE_CATCHUP"]),
    )

    rows = []
    ign_active_weeks = 0
    for lbl, intents in combos:
        base_m, ep_pnl = _replay_micro_portfolio(panel_2h, intents, label=lbl)
        if lbl == "IGNITION_ONLY":
            ign_active_weeks = base_m["active_weeks"]
        top3_eps = {ep for ep, _ in sorted(ep_pnl.items(), key=lambda kv: kv[1], reverse=True)[:3]}
        ex3_m, _ = _replay_micro_portfolio(panel_2h, intents, label=f"{lbl}_EX_TOP3", excluded_episode_ids=top3_eps)
        rows.append({
            **base_m,
            "addl_active_weeks_vs_ign": base_m["active_weeks"] - ign_active_weeks,
            "ex_top3_ret_pct": ex3_m["ret_pct"],
            "ex_top3_sharpe": ex3_m["ann_sharpe"],
            "ex_top3_max_dd_pct": ex3_m["max_dd_pct"],
        })

    gold_tape = _audit_live_gold_two_leg_tape(multi_venue_db)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "raw_intent_counts": {k: len(v) for k, v in by_mech.items()},
        "weekly_opportunity_table": rows,
        "live_gold_two_leg_tape": gold_tape,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Rare Micro-Signal Portfolio — Weekly Opportunity Table, Position-Sized Fragility & Native Gold Two-Leg Tape",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        f"- **Raw Causal 2h Intents:** `{p['raw_intent_counts']}`",
        "",
        "## 1. Weekly Opportunity Table & Position-Sized Episode Fragility (`16 bps/side`, Equal Risk Budget)",
        "",
        "| Combination | Active Weeks (+vs Ign) | Longest Drought | Unique Episodes | Fills / Misses | Net bps / Intended | Full Ret | Sharpe | MaxDD | Ex-Top-3 Ret (Sharpe) |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["weekly_opportunity_table"]:
        lines.append(
            f"| `{r['label']}` | `{r['active_weeks']}/{r['total_weeks']}` (`{r['addl_active_weeks_vs_ign']:+d}`) | `{r['longest_drought_weeks']}w` | `{r['unique_episodes']}` | `{r['fills']} / {r['misses']}` | `{r['net_bps_per_intended']:+.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['ex_top3_ret_pct']:+.2f}%` (`{r['ex_top3_sharpe']:.3f}`) |"
        )
    gt = p["live_gold_two_leg_tape"]
    lines.extend([
        "",
        "## 2. Prospective Native Two-Leg Gold-Switching Tape (`XAUTUSDT` ↔ `PAXGUSDT`, Nobitex Live Quotes)",
        f"- **Status:** `{gt.get('status')}` · **XAUT / PAXG Quotes:** `{gt.get('xaut_quotes', 0)}` / `{gt.get('paxg_quotes', 0)}` · **Paired (`<=15s`):** `{gt.get('paired_within_15s', 0)}`",
        f"- **Positive Executable Net Switch Events (`>32 bps` RT fee):** `{gt.get('positive_net_switch_events', 0)}` · **Best Net Edge:** `{gt.get('best_executable_net_bps')} bps`",
        f"- **Mean Positive Edge:** `{gt.get('mean_positive_edge_bps', 0):+.2f} bps` · **Mean Failed-Second-Leg Unwind Cost:** `{gt.get('mean_failed_second_leg_unwind_bps', 0):.2f} bps`",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
