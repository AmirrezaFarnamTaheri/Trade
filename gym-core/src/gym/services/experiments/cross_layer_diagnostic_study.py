"""Cross-Layer Trading Design Diagnostics Study.

Implements the first high-value diagnostic slice from
docs/architecture/rare-micro-signal-research-design.md and
docs/architecture/cross-layer-trading-design-decisions.md on one frozen post-repair tape:
  1. Exit-specialist vs. incumbent exits (identical ignition entries, thesis-failure & stall exits).
  2. Confirmation price (enter now vs wait-for-confirm vs 50/50 split, scored per original alert).
  3. Intrabar path-ambiguity sensitivity (stop-first adverse vs target-first optimistic bounds).
  4. 2x2 capital-conflict interaction matrix (Neither, Slow A, Ignition B, Both shared capital).
  5. Sample-size & time-to-decision learning horizon for rare signals.
  6. Asset/hour/vol-matched sham-entry control & zero-trade-week diagnostic funnel.
  7. Duplicate-listing underlying-risk invariant.

Strictly read-only against market.db; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.instrument_resolver import InstrumentOffer
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import MultiHorizonBook
from ...domain.rare_micro_signals import MicroSignalIntent, scan_micro_signal_intents
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    resolve_bar_prices,
)


def canonical_underlying(symbol: str) -> str:
    """Map wrapped/duplicate symbol aliases to one canonical underlying so duplicate listings add zero risk."""
    base = symbol.upper().replace("_WRAPPER", "").replace("_DUP", "")
    for suffix in ("USDT", "IRT", "TMN"):
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    aliases = {"WBTC": "BTC", "WETH": "ETH", "PAXG": "GOLD", "XAUT": "GOLD"}
    return aliases.get(base, base)


def deduplicate_intents_by_underlying(intents: list[MicroSignalIntent]) -> list[MicroSignalIntent]:
    """Keep at most one highest-strength intent per (ts_avail, canonical_underlying)."""
    best: dict[tuple[datetime, str], MicroSignalIntent] = {}
    for it in sorted(intents, key=lambda x: (x.ts_avail, -x.strength, x.symbol)):
        key = (it.ts_avail, canonical_underlying(it.symbol))
        if key not in best:
            best[key] = it
    return sorted(best.values(), key=lambda x: (x.ts_avail, -x.strength, x.symbol))


def _replay_exit_policy(
    panel_2h: dict[str, list[BarPoint]],
    intents: list[MicroSignalIntent],
    *,
    policy: str,
    leg_cost: float = 0.0016,
    max_slots: int = 3,
) -> dict:
    """Exit-specialist experiment: identical entry stream, varying only the exit rule."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    by_ts: dict[datetime, list[MicroSignalIntent]] = {}
    for it in deduplicate_intents_by_underlying(intents):
        by_ts.setdefault(it.ts_avail, []).append(it)

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    fills = early_exits = wins = closed = 0
    total_fees = 0.0

    for ts in all_ts:
        for sym in list(active):
            pos = active[sym]
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None:
                continue
            pos["age"] += 1
            if cur.high > pos["peak"]:
                pos["peak"] = cur.high
                pos["bars_since_peak"] = 0
            else:
                pos["bars_since_peak"] += 1

            hit_base = (
                pos["age"] >= 24
                or cur.close <= pos["entry_px"] * 0.96
                or cur.close <= pos["peak"] * (1.0 - 2.5 * pos["bar_vol"])
            )
            hit_early = False
            if policy == "THESIS_FAILURE_4BAR" and pos["age"] >= 4 and cur.close < pos["entry_px"] * 1.0075:
                hit_early = True
            elif policy == "PROFIT_STALL_6BAR" and pos["bars_since_peak"] >= 6:
                hit_early = True

            if hit_base or hit_early:
                ex_px = nxt.open if (nxt and nxt.open > 0) else cur.close
                ex_fee = pos["qty"] * ex_px * leg_cost
                pnl = pos["qty"] * (ex_px - pos["entry_px"]) - pos["entry_fee"] - ex_fee
                equity = max(0.0, equity + pos["col"] + pnl)
                total_fees += pos["entry_fee"] + ex_fee
                closed += 1
                if pnl > 0:
                    wins += 1
                if hit_early and not hit_base:
                    early_exits += 1
                del active[sym]

        for it in by_ts.get(ts, []):
            if it.symbol in active or len(active) >= max_slots or equity <= 100.0:
                continue
            nxt = by_start[it.symbol].get(ts)
            if nxt is None or nxt.open <= 0:
                continue
            col = min(equity * 0.30, equity - 1.0)
            if col < 25.0:
                continue
            ef = col * leg_cost
            equity -= col
            active[it.symbol] = {
                "col": col, "qty": (col - ef) / nxt.open, "entry_px": nxt.open, "entry_fee": ef,
                "peak": nxt.open, "bar_vol": it.bar_vol, "age": 0, "bars_since_peak": 0,
            }
            fills += 1

        mark_u = sum(
            p["col"] + p["qty"] * (by_avail[s][ts].close - p["entry_px"])
            for s, p in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + mark_u)

    m = portfolio_metrics(nav_by_date, starting_nav=1000.0)
    return {
        "policy": policy,
        "fills": fills,
        "early_exits": early_exits,
        "win_rate_pct": round(wins / max(1, closed) * 100.0, 1),
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "fees_usdt": round(total_fees, 2),
    }


def _run_confirmation_price(
    panel_2h: dict[str, list[BarPoint]],
    intents: list[MicroSignalIntent],
    *,
    leg_cost: float = 0.0016,
) -> dict:
    """Confirmation-price experiment: score enter-now, wait-1b-confirm, and 50/50 split per ORIGINAL alert."""
    by_sym_ts = {s: {b.ts_start: i for i, b in enumerate(panel_2h.get(s, []))} for s in IGNITION_18_CRYPTO}
    rt_fee = 2.0 * leg_cost
    now_bps, wait_bps, split_bps = [], [], []
    confirmed = missed_winners = 0

    for it in deduplicate_intents_by_underlying(intents):
        bars = panel_2h.get(it.symbol, [])
        i0 = by_sym_ts.get(it.symbol, {}).get(it.ts_avail)
        if i0 is None or i0 + 13 >= len(bars):
            continue
        b0, b1, b_ex = bars[i0], bars[i0 + 1], bars[i0 + 12]
        if b0.open <= 0 or b1.open <= 0 or b_ex.open <= 0:
            continue
        r_now = ((b_ex.open - b0.open) / b0.open - rt_fee) * 10_000.0
        is_conf = b0.close > b0.open  # confirmation bar closes green
        if is_conf:
            confirmed += 1
            r_wait = ((b_ex.open - b1.open) / b1.open - rt_fee) * 10_000.0
            r_split = 0.5 * r_now + 0.5 * r_wait
        else:
            r_wait = 0.0
            r_split = 0.5 * r_now
            if r_now > 0:
                missed_winners += 1
        now_bps.append(r_now)
        wait_bps.append(r_wait)
        split_bps.append(r_split)

    return {
        "original_alerts": len(now_bps),
        "confirmed_count": confirmed,
        "unconfirmed_runaway_winners": missed_winners,
        "enter_now_mean_bps_per_alert": round(mean(now_bps), 2) if now_bps else 0.0,
        "wait_confirm_mean_bps_per_alert": round(mean(wait_bps), 2) if wait_bps else 0.0,
        "split_50_50_mean_bps_per_alert": round(mean(split_bps), 2) if split_bps else 0.0,
    }


def _run_intrabar_ambiguity_bounds(
    panel_2h: dict[str, list[BarPoint]],
    intents: list[MicroSignalIntent],
    *,
    stop_pct: float = 0.04,
    tp_pct: float = 0.08,
    leg_cost: float = 0.0016,
) -> dict:
    """Cross-layer #1: Measure intrabar stop-vs-target ambiguity and compare optimistic vs adverse bounds."""
    by_sym_ts = {s: {b.ts_start: i for i, b in enumerate(panel_2h.get(s, []))} for s in IGNITION_18_CRYPTO}
    rt_fee = 2.0 * leg_cost
    opt_rets, adv_rets = [], []
    ambiguous = 0

    for it in deduplicate_intents_by_underlying(intents):
        bars = panel_2h.get(it.symbol, [])
        i0 = by_sym_ts.get(it.symbol, {}).get(it.ts_avail)
        if i0 is None or i0 + 24 >= len(bars):
            continue
        ent = bars[i0].open
        if ent <= 0:
            continue
        stop_px, tp_px = ent * (1.0 - stop_pct), ent * (1.0 + tp_pct)
        r_opt = r_adv = None
        for k in range(i0, i0 + 24):
            bk = bars[k]
            hit_s, hit_t = (bk.low <= stop_px), (bk.high >= tp_px)
            if hit_s and hit_t:
                ambiguous += 1
                r_opt = tp_pct - rt_fee
                r_adv = -stop_pct - rt_fee
                break
            if hit_t:
                r_opt = r_adv = tp_pct - rt_fee
                break
            if hit_s:
                r_opt = r_adv = -stop_pct - rt_fee
                break
        if r_opt is None:
            r_opt = r_adv = (bars[i0 + 24].open - ent) / ent - rt_fee
        opt_rets.append(r_opt * 10_000.0)
        adv_rets.append(r_adv * 10_000.0)

    n = max(1, len(opt_rets))
    return {
        "trades_evaluated": len(opt_rets),
        "ambiguous_trades": ambiguous,
        "ambiguous_pct": round(ambiguous / n * 100.0, 2),
        "optimistic_target_first_mean_bps": round(mean(opt_rets), 2) if opt_rets else 0.0,
        "adverse_stop_first_mean_bps": round(mean(adv_rets), 2) if adv_rets else 0.0,
        "ambiguity_gap_bps": round((mean(opt_rets) - mean(adv_rets)), 2) if opt_rets else 0.0,
        "sign_flips_under_adverse": bool(opt_rets and (mean(opt_rets) > 0) != (mean(adv_rets) > 0)),
    }


def _run_2x2_capital_conflict(
    panel_2h: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    ign_intents: list[MicroSignalIntent],
) -> dict:
    """Cross-layer #2: Four-way (Neither, Slow A, Ignition B, Both) interaction on identical $1,000 capital."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in all_syms}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in all_syms}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    sig_dates = sorted(daily_targets)
    ign_by_ts: dict[datetime, list[MicroSignalIntent]] = {}
    for it in deduplicate_intents_by_underlying(ign_intents):
        ign_by_ts.setdefault(it.ts_avail, []).append(it)

    def _sim(use_slow: bool, use_fast: bool) -> dict:
        book = MultiHorizonBook(free_cash=1000.0)
        last_px: dict[str, float] = {}
        last_sig: datetime | None = None
        nav_ts: dict[datetime, float] = {}
        displaced = 0
        for ts in all_ts:
            exec_px, tradable = resolve_bar_prices(all_syms, by_start, by_avail, ts, last_px)
            for key in list(book.lots):
                if key[1] != "ignition_2h":
                    continue
                lot = book.lots[key]
                lot.age_bars += 1
                px = exec_px.get(lot.symbol, lot.entry_price)
                lot.peak_price = max(lot.peak_price, px)
                if lot.age_bars >= 24 or px <= lot.stop_price or px <= lot.peak_price * (1.0 - 2.5 * lot.entry_bar_vol):
                    book.close_lot(key, px, 16.0)
            if use_slow:
                cur_sig = latest_signal_date(sig_dates, ts)
                if cur_sig is not None and cur_sig != last_sig:
                    last_sig = cur_sig
                    book.rebalance_slow_spot_targets(daily_targets[cur_sig], exec_px, tradable, ts, leg_fee_bps=16.0)
            if use_fast:
                act_n = sum(1 for k in book.lots if k[1] == "ignition_2h")
                eq_now = book.mark_equity(exec_px)
                for it in ign_by_ts.get(ts, []):
                    if act_n >= 3 or (it.symbol, "ignition_2h") in book.lots:
                        continue
                    px = exec_px.get(it.symbol, 0.0)
                    if px <= 0:
                        continue
                    req = 0.20 * eq_now
                    if book.free_cash < max(25.0, req * 0.5):
                        displaced += 1
                        continue
                    offer = InstrumentOffer(
                        venue="nobitex", symbol=it.symbol, instrument_type="SPOT", direction=1,
                        allowed_leverages=(1.0,), entry_cost_bps=16.0, exit_cost_bps=16.0,
                        carry_model="NONE", carry_rate_bps=0.0,
                    )
                    if book.open_fast_margin_lot(
                        symbol=it.symbol, thesis_id="ignition_2h", direction=1, leverage=1.0,
                        target_collateral=req, entry_px=px, stop_bps=400.0, take_profit_bps=0.0,
                        offer=offer, ts=ts, entry_bar_vol=it.bar_vol, entry_gru_score=0.0,
                        allow_internal_short_offset=False,
                    ):
                        act_n += 1
            nav_ts[ts] = book.mark_equity(exec_px)
        m = portfolio_metrics(nav_ts_to_daily(nav_ts), starting_nav=1000.0)
        return {"ending_nav": m["ending_nav"], "ret_pct": m["ret_pct"], "ann_sharpe": m["ann_sharpe"], "displaced_fast": displaced}

    w_0 = _sim(False, False)
    w_a = _sim(True, False)
    w_b = _sim(False, True)
    w_ab = _sim(True, True)
    interaction_usdt = round(w_ab["ending_nav"] - w_a["ending_nav"] - w_b["ending_nav"] + w_0["ending_nav"], 2)
    return {
        "neither_cash": w_0,
        "slow_a_only": w_a,
        "ignition_b_only": w_b,
        "both_shared": w_ab,
        "interaction_usdt": interaction_usdt,
    }


def _run_time_to_decision(
    panel_2h: dict[str, list[BarPoint]],
    by_mech: dict[str, list[MicroSignalIntent]],
) -> list[dict]:
    """Cross-layer #3: Estimate independent episodes/month and calendar months to 80% power (alpha=0.05)."""
    by_sym_ts = {s: {b.ts_start: i for i, b in enumerate(panel_2h.get(s, []))} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({b.ts_avail for bars in panel_2h.values() for b in bars})
    total_months = max(1.0, (all_ts[-1] - all_ts[0]).days / 30.4375) if len(all_ts) >= 2 else 1.0
    rows = []
    for mech, intents in by_mech.items():
        ep_rets: list[float] = []
        last_ep: datetime | None = None
        cur_vals: list[float] = []
        for it in deduplicate_intents_by_underlying(intents):
            bars = panel_2h.get(it.symbol, [])
            i0 = by_sym_ts.get(it.symbol, {}).get(it.ts_avail)
            if i0 is None or i0 + 12 >= len(bars) or bars[i0].open <= 0:
                continue
            r_bps = ((bars[i0 + 12].open - bars[i0].open) / bars[i0].open - 0.0032) * 10_000.0
            if last_ep is not None and (it.ts_avail - last_ep) > timedelta(hours=6) and cur_vals:
                ep_rets.append(mean(cur_vals))
                cur_vals = []
            cur_vals.append(r_bps)
            last_ep = it.ts_avail
        if cur_vals:
            ep_rets.append(mean(cur_vals))
        ep_per_mo = len(ep_rets) / total_months
        sd_bps = stdev(ep_rets) if len(ep_rets) >= 2 else 500.0
        # Two-sided alpha=0.05, power=0.80 => z_sum = 1.96 + 0.84 = 2.80 => n = (2.80 * sd / mde)^2
        n_for_50bp = math.ceil((2.80 * sd_bps / 50.0) ** 2)
        n_for_100bp = math.ceil((2.80 * sd_bps / 100.0) ** 2)
        mo_50 = round(n_for_50bp / max(0.1, ep_per_mo), 1)
        mo_100 = round(n_for_100bp / max(0.1, ep_per_mo), 1)
        disp = "TEST_NOW" if mo_100 <= 6.0 else ("POOL_MARKETS" if mo_100 <= 18.0 else "PARK_TOO_SLOW")
        rows.append({
            "mechanism": mech,
            "independent_episodes": len(ep_rets),
            "episodes_per_month": round(ep_per_mo, 2),
            "episode_std_bps": round(sd_bps, 1),
            "episodes_needed_100bp": n_for_100bp,
            "months_to_decide_100bp": mo_100,
            "months_to_decide_50bp": mo_50,
            "disposition": disp,
        })
    return rows


def _run_sham_control_and_funnel(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    ign_intents: list[MicroSignalIntent],
) -> dict:
    """Cross-layer #4 + Operator Funnel: Asset/UTC-hour matched sham entries & zero-trade-week root causes."""
    rng = random.Random(42)
    by_sym_ts = {s: {b.ts_start: i for i, b in enumerate(panel_2h.get(s, []))} for s in IGNITION_18_CRYPTO}
    real_bps, sham_bps = [], []
    trig_set = {(it.symbol, it.ts_avail) for it in ign_intents}

    for it in deduplicate_intents_by_underlying(ign_intents):
        bars = panel_2h.get(it.symbol, [])
        i0 = by_sym_ts.get(it.symbol, {}).get(it.ts_avail)
        if i0 is None or i0 + 12 >= len(bars) or bars[i0].open <= 0:
            continue
        real_bps.append(((bars[i0 + 12].open - bars[i0].open) / bars[i0].open - 0.0032) * 10_000.0)
        # Match same symbol & same UTC hour on non-trigger eligible bars
        cands = [
            j for j in range(72, len(bars) - 13)
            if bars[j].ts_avail.hour == it.ts_avail.hour and (it.symbol, bars[j].ts_avail) not in trig_set and bars[j].open > 0
        ]
        if cands:
            j = rng.choice(cands)
            sham_bps.append(((bars[j + 12].open - bars[j].open) / bars[j].open - 0.0032) * 10_000.0)

    # Zero-trade-week funnel
    all_ts = sorted({b.ts_avail for bars in panel_2h.values() for b in bars})
    all_weeks = sorted({(t.isocalendar()[0], t.isocalendar()[1]) for t in all_ts})
    trig_weeks = {(it.ts_avail.isocalendar()[0], it.ts_avail.isocalendar()[1]) for it in ign_intents}
    breadth_ok_weeks = {
        (t.isocalendar()[0], t.isocalendar()[1]) for t in all_ts if daily_breadth.get(t.date().isoformat(), 0.0) >= 0.45
    }
    zero_weeks = [w for w in all_weeks if w not in trig_weeks]
    no_breadth_weeks = sum(1 for w in zero_weeks if w not in breadth_ok_weeks)
    no_signal_weeks = len(zero_weeks) - no_breadth_weeks

    return {
        "real_ignition_mean_24h_net_bps": round(mean(real_bps), 2) if real_bps else 0.0,
        "matched_sham_mean_24h_net_bps": round(mean(sham_bps), 2) if sham_bps else 0.0,
        "real_minus_sham_bps": round((mean(real_bps) - mean(sham_bps)), 2) if (real_bps and sham_bps) else 0.0,
        "total_weeks": len(all_weeks),
        "active_weeks": len(trig_weeks),
        "zero_trade_weeks": len(zero_weeks),
        "zero_weeks_due_to_low_breadth": no_breadth_weeks,
        "zero_weeks_due_to_no_breakout_signal": no_signal_weeks,
    }


def run_cross_layer_diagnostic_study(
    wallex_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Run all cross-layer design diagnostics on one frozen post-repair tape."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in all_syms if panel_1h[s]}

    by_mech = scan_micro_signal_intents(panel_2h, IGNITION_18_CRYPTO, daily_breadth)
    ign_intents = by_mech["MOMENTUM_IGNITION"]

    exit_arms = [
        _replay_exit_policy(panel_2h, ign_intents, policy=pol)
        for pol in ("INCUMBENT_EXIT", "THESIS_FAILURE_4BAR", "PROFIT_STALL_6BAR")
    ]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "exit_specialist_comparison": exit_arms,
        "confirmation_price": _run_confirmation_price(panel_2h, ign_intents),
        "intrabar_ambiguity_bounds": _run_intrabar_ambiguity_bounds(panel_2h, ign_intents),
        "capital_conflict_2x2": _run_2x2_capital_conflict(panel_2h, daily_targets, ign_intents),
        "time_to_decision": _run_time_to_decision(panel_2h, by_mech),
        "sham_control_and_funnel": _run_sham_control_and_funnel(panel_2h, daily_breadth, ign_intents),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Cross-Layer Trading Design Diagnostics (Exit Specialist, Confirmation Price, Ambiguity, 2×2 Conflict, Time-to-Decision & Sham Control)",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "",
        "## 1. Exit Specialist vs. Incumbent Exits (Identical `MOMENTUM_IGNITION` Entries)",
        "",
        "| Exit Policy | Fills | Early Exits | Win% | Ending NAV | Return | Sharpe | MaxDD | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["exit_specialist_comparison"]:
        lines.append(
            f"| `{r['policy']}` | `{r['fills']}` | `{r['early_exits']}` | `{r['win_rate_pct']:.1f}%` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `${r['fees_usdt']:.2f}` |"
        )
    cp = p["confirmation_price"]
    amb = p["intrabar_ambiguity_bounds"]
    c22 = p["capital_conflict_2x2"]
    sc = p["sham_control_and_funnel"]
    lines.extend([
        "",
        "## 2. Confirmation Price (Scored Per Original Alert, Including Runaway Winners)",
        f"- **Alerts:** `{cp['original_alerts']}` · **Confirmed:** `{cp['confirmed_count']}` · **Unconfirmed Runaway Winners:** `{cp['unconfirmed_runaway_winners']}`",
        f"- **Enter Now (100%):** `{cp['enter_now_mean_bps_per_alert']:+.2f} bps` · **Wait 1b Confirm:** `{cp['wait_confirm_mean_bps_per_alert']:+.2f} bps` · **Split 50/50:** `{cp['split_50_50_mean_bps_per_alert']:+.2f} bps`",
        "",
        "## 3. Intrabar Path-Ambiguity Bounds (Stop `-4%` vs Target `+8%`)",
        f"- **Evaluated Trades:** `{amb['trades_evaluated']}` · **Ambiguous Bars:** `{amb['ambiguous_trades']}` (`{amb['ambiguous_pct']:.2f}%`)",
        f"- **Optimistic (Target First):** `{amb['optimistic_target_first_mean_bps']:+.2f} bps` · **Adverse (Stop First):** `{amb['adverse_stop_first_mean_bps']:+.2f} bps` · **Gap:** `{amb['ambiguity_gap_bps']:.2f} bps` · **Sign Flips:** `{amb['sign_flips_under_adverse']}`",
        "",
        "## 4. 2×2 Capital-Conflict Interaction (`$1,000` Shared Capital)",
        f"- **Neither (Cash):** `${c22['neither_cash']['ending_nav']:.2f}` · **Slow A Only:** `${c22['slow_a_only']['ending_nav']:.2f}` · **Ignition B Only:** `${c22['ignition_b_only']['ending_nav']:.2f}` · **Both Shared:** `${c22['both_shared']['ending_nav']:.2f}` (displaced fast=`{c22['both_shared']['displaced_fast']}`)",
        f"- **Interaction Term `W(AB) - W(A) - W(B) + W(0)`:** **`${c22['interaction_usdt']:+.2f}`**",
        "",
        "## 5. Time-to-Decision Learning Horizon (80% Power, `alpha=0.05`)",
        "",
        "| Mechanism | Indep. Episodes | Episodes/Mo | Ep. Std (bps) | Needed (`100bp`) | Months (`100bp`) | Months (`50bp`) | Disposition |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in p["time_to_decision"]:
        lines.append(
            f"| `{r['mechanism']}` | `{r['independent_episodes']}` | `{r['episodes_per_month']:.2f}` | `{r['episode_std_bps']:.1f}` | `{r['episodes_needed_100bp']}` | `{r['months_to_decide_100bp']:.1f}m` | `{r['months_to_decide_50bp']:.1f}m` | `{r['disposition']}` |"
        )
    lines.extend([
        "",
        "## 6. Matched Sham-Entry Control & Zero-Trade-Week Diagnostic Funnel",
        f"- **Real Ignition 24h Net:** `{sc['real_ignition_mean_24h_net_bps']:+.2f} bps` · **Asset/Hour-Matched Sham:** `{sc['matched_sham_mean_24h_net_bps']:+.2f} bps` · **Real − Sham:** **`{sc['real_minus_sham_bps']:+.2f} bps`**",
        f"- **Zero-Trade Weeks:** `{sc['zero_trade_weeks']} / {sc['total_weeks']}` (`{sc['zero_weeks_due_to_low_breadth']}` due to low breadth `< 0.45`; `{sc['zero_weeks_due_to_no_breakout_signal']}` due to no breakout signal in eligible breadth weeks)",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
