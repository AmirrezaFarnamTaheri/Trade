"""Pure domain engines for Track III:
- Idea #5: Cross-sectional BTC/ETH Lead-Lag Diffusion sleeve on 2h bars
- Idea #9: Single-ADMM Cross-Sleeve Netting & Sector Cluster Caps using convex_optimizer.py
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from statistics import median

from .convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from .paper_ledger import SelfFinancingLedger
from .short_and_levered_ignition import LeveredIgnitionResult, _summarize_levered_nav
from .strategy_sleeves import SleeveSignal
from .timeframe_panel import BarPoint

SECTOR_CLUSTERS: dict[str, tuple[str, ...]] = {
    "BTC_MAJOR": ("BTCUSDT",),
    "ETH_DEFI": ("ETHUSDT", "AAVEUSDT", "LINKUSDT", "UNIUSDT"),
    "ALT_L1": ("SOLUSDT", "AVAXUSDT", "NEARUSDT", "ADAUSDT", "ATOMUSDT", "DOTUSDT", "TRXUSDT"),
    "PAYMENTS_MEME": ("XRPUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT", "BNBUSDT", "FILUSDT"),
    "GOLD": ("XAUTUSDT", "PAXGUSDT"),
}


def _trailing_beta(follower_rets: list[float], leader_rets: list[float]) -> float:
    n = min(len(follower_rets), len(leader_rets))
    if n < 18:
        return 1.0
    f, ld = follower_rets[-n:], leader_rets[-n:]
    mf, ml = sum(f) / n, sum(ld) / n
    vl = sum((x - ml) ** 2 for x in ld)
    if vl <= 1e-10:
        return 1.0
    cov = sum((a - mf) * (b - ml) for a, b in zip(f, ld, strict=True))
    return max(0.5, min(2.5, cov / vl))


def _detect_leader_impulse(
    leader_bar: BarPoint | None,
    leader_ret: float,
    prior_rets: list[float],
    prior_vols: list[float],
    *,
    z_min: float = 2.0,
    vol_mult: float = 1.8,
) -> float | None:
    """Return leader_ret if leader prints a clean positive impulse bar, else None."""
    if leader_bar is None or leader_bar.close <= 0 or len(prior_rets) < 36 or len(prior_vols) < 36:
        return None
    mr = sum(prior_rets[-36:]) / 36.0
    sr = math.sqrt(sum((r - mr) ** 2 for r in prior_rets[-36:]) / 35.0)
    mv = median(prior_vols[-36:])
    if mv <= 0 or leader_bar.volume < vol_mult * mv:
        return None
    z = (leader_ret - mr) / max(sr, 1e-4)
    return leader_ret if (z >= z_min and leader_ret > 0.008) else None


def _step_diffusion_exits(
    active: dict[str, dict],
    by_avail: dict[str, dict[datetime, BarPoint]],
    by_start: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    equity: float,
    *,
    leg_cost: float,
    hard_stop_pct: float,
    max_hold_bars: int,
) -> tuple[float, float, int, int, float]:
    """Advance exits on open lead-lag diffusion slots. Returns (equity, fees_added, wins_added, closed_added, hold_h_added)."""
    fees_add, wins_add, closed_add, hold_add = 0.0, 0, 0, 0.0
    for sym in list(active):
        pos = active[sym]
        pos["age"] += 1
        cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
        if cur is not None and cur.close > 0:
            cum_r = (cur.close - pos["entry_px"]) / pos["entry_px"]
            if cum_r >= pos["target_catchup"] or cum_r <= -hard_stop_pct or pos["age"] >= max_hold_bars:
                exit_px = nxt.open if (nxt is not None and nxt.open > 0) else cur.close
                ef = pos["qty"] * exit_px * leg_cost
                pnl = pos["qty"] * (exit_px - pos["entry_px"]) - ef
                equity = max(0.0, equity + pnl)
                fees_add += ef
                closed_add += 1
                hold_add += pos["age"] * 2.0
                if pnl - pos["entry_fee"] > 0:
                    wins_add += 1
                del active[sym]
        elif pos["age"] >= max_hold_bars:
            closed_add += 1
            hold_add += pos["age"] * 2.0
            del active[sym]
    return equity, fees_add, wins_add, closed_add, hold_add


def _open_diffusion_entries(
    best_leader: tuple[str, float],
    symbols: tuple[str, ...],
    leaders: tuple[str, ...],
    bar_rets: dict[str, float],
    ret_hist: dict[str, list[float]],
    day_s1: dict[str, float],
    by_avail: dict[str, dict[datetime, BarPoint]],
    by_start: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    active: dict[str, dict],
    equity: float,
    *,
    min_gap_pct: float,
    max_slots: int,
    slot_frac: float,
    leg_cost: float,
) -> tuple[float, float, int]:
    """Rank lagging healthy followers and open spot convergence slots."""
    ld_sym, ld_ret = best_leader
    cands: list[tuple[float, str]] = []
    for sym in symbols:
        if sym in leaders or sym in active or sym not in bar_rets:
            continue
        cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
        if not (cur and cur.entry_eligible and nxt and nxt.open > 0):
            continue
        if day_s1.get(sym, 0.0) < 0.0:
            continue
        beta = _trailing_beta(ret_hist[sym][-36:], ret_hist[ld_sym][-36:])
        gap = beta * ld_ret - bar_rets[sym]
        if gap >= min_gap_pct and bar_rets[sym] > -0.01:
            cands.append((gap, sym))
    cands.sort(key=lambda x: (-x[0], x[1]))
    fees_add, entries_add = 0.0, 0
    for gap, sym in cands:
        if len(active) >= max_slots:
            break
        nxt = by_start[sym].get(ts)
        if nxt is None or nxt.open <= 0:
            continue
        free_col = max(0.0, equity - sum(p["collateral"] for p in active.values()))
        col = min(equity * slot_frac, free_col)
        if col < 25.0:
            continue
        ef = col * leg_cost
        equity = max(0.0, equity - ef)
        fees_add += ef
        active[sym] = {
            "collateral": col, "qty": col / nxt.open, "entry_px": nxt.open,
            "entry_fee": ef, "target_catchup": min(0.06, gap * 0.85), "age": 0,
        }
        entries_add += 1
    return equity, fees_add, entries_add


def simulate_lead_lag_diffusion(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    daily_s1_by_date: dict[str, dict[str, float]],
    *,
    label: str,
    leaders: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    offset_hours: int = 0,
    leg_cost: float = 0.0016,
    min_gap_pct: float = 0.015,
    max_hold_bars: int = 6,
    hard_stop_pct: float = 0.04,
    max_slots: int = 3,
    slot_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float]]:
    """Spot 1.0x cross-sectional lead-lag diffusion: buy calm healthy followers after BTC/ETH impulse."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed = 0, 0, 0
    hold_h, total_fees = 0.0, 0.0

    for ts in all_ts:
        bar_rets = {
            sym: ((by_avail[sym][ts].close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            for sym in symbols if ts in by_avail[sym] and by_avail[sym][ts].close > 0
        }

        equity, f_ex, w_ex, c_ex, h_ex = _step_diffusion_exits(
            active, by_avail, by_start, ts, equity,
            leg_cost=leg_cost, hard_stop_pct=hard_stop_pct, max_hold_bars=max_hold_bars,
        )
        total_fees += f_ex
        wins += w_ex
        closed += c_ex
        hold_h += h_ex

        best_leader: tuple[str, float] | None = None
        for ld in leaders:
            if ld in bar_rets:
                imp = _detect_leader_impulse(by_avail[ld].get(ts), bar_rets[ld], ret_hist[ld], vol_hist[ld])
                if imp is not None and (best_leader is None or imp > best_leader[1]):
                    best_leader = (ld, imp)

        day_iso = ts.date().isoformat()
        if best_leader is not None and equity > 100.0 and daily_breadth.get(day_iso, 0.0) >= 0.45 and len(active) < max_slots:
            equity, f_en, e_en = _open_diffusion_entries(
                best_leader, symbols, leaders, bar_rets, ret_hist, daily_s1_by_date.get(day_iso, {}),
                by_avail, by_start, ts, active, equity,
                min_gap_pct=min_gap_pct, max_slots=max_slots, slot_frac=slot_frac, leg_cost=leg_cost,
            )
            total_fees += f_en
            entries += e_en

        for sym in symbols:
            cur = by_avail[sym].get(ts)
            if cur is not None and cur.close > 0:
                if sym in prev_close and prev_close[sym] > 0:
                    ret_hist[sym].append(bar_rets[sym])
                prev_close[sym] = cur.close
                vol_hist[sym].append(cur.volume)

        unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[day_iso] = max(0.0, equity + unreal)

    res = _summarize_levered_nav(
        label, "LONG_DIFFUSION", 1.0, len(symbols), offset_hours, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, 0, hold_h, 0.0, total_fees,
    )
    return res, nav_by_date


def _build_cluster_groups(active_syms: tuple[str, ...]) -> dict[str, tuple[int, ...]]:
    idx_map = {s: i for i, s in enumerate(active_syms)}
    groups: dict[str, tuple[int, ...]] = {}
    for cname, members in SECTOR_CLUSTERS.items():
        idxs = tuple(idx_map[m] for m in members if m in idx_map)
        if len(idxs) >= 2:
            groups[cname] = idxs
    return groups


def run_joint_admm_cross_sleeve_netting(
    panel_1h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    slow_symbols: tuple[str, ...],
    sigs_1d: dict[datetime, dict[str, SleeveSignal]],
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]],
    ignition_targets_by_ts: dict[datetime, dict[str, float]],
    *,
    slow_budget: float = 0.70,
    ignition_budget: float = 0.30,
    fee_rate: Decimal = Decimal("0.0016"),
    max_cluster_weight: float = 0.40,
) -> dict:
    """Joint single-ADMM cross-sleeve netting passing active 2h ignition weights & sector cluster caps into ADMM."""
    by_avail = {s: {b.ts_avail: b for b in panel_1h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    cur_slow: dict[str, float] = {s: 0.0 for s in symbols}
    prev_ign: dict[str, float] = {s: 0.0 for s in symbols}
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(20.0)

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                last_mark[sym] = exec_prices[sym]
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
                last_mark[sym] = exec_prices[sym]
            elif sym in last_mark:
                exec_prices[sym] = last_mark[sym]

        ign_now = ignition_targets_by_ts.get(ts, prev_ign)
        ign_changed = any(abs(ign_now.get(s, 0.0) - prev_ign.get(s, 0.0)) > 1e-6 for s in symbols)
        prev_ign = ign_now
        is_daily = ts in cov_h_by_ts and ts in sigs_1d

        if is_daily:
            active_slow, cov_h = cov_h_by_ts[ts]
            day_sigs = sigs_1d[ts]
            # Subtract live 2h ignition holdings from current weights so ADMM nets opposite trades at 0 bps!
            live_w = ledger.current_weights(active_slow, exec_prices)
            ign_active_w = {s: ignition_budget * ign_now.get(s, 0.0) for s in symbols}
            reserved_ign = min(0.45, sum(ign_active_w.values()))
            adj_cur_w = tuple(max(0.0, (lw - ign_active_w.get(s, 0.0)) / max(slow_budget, 1e-6)) for s, lw in zip(active_slow, live_w, strict=True))

            mu_gross = []
            for sym in active_slow:
                sig = day_sigs[sym]
                parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
                raw = sum(parts) / len(parts) if parts else 0.0
                mu_gross.append(
                    forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                )
            prob = OptimizationProblem(
                symbols=active_slow,
                expected_returns=tuple(mu_gross),
                current_weights=adj_cur_w,
                covariance=cov_h,
                l1_fee_costs=(float(fee_rate),) * len(active_slow),
                l2_impact_costs=(0.0020,) * len(active_slow),
                risk_aversion=2.0,
                max_weight=0.30,
                cash_buffer=0.05,
                reserved_open_weight=max(0.0, reserved_ign * 0.5),
                underlying_groups=_build_cluster_groups(active_slow),
                max_underlying_weight=max_cluster_weight,
            )
            solved = solve_convex_portfolio(prob).weights
            cur_slow = {s: 0.0 for s in symbols}
            for s, w in zip(active_slow, solved, strict=True):
                cur_slow[s] = w

        if is_daily or ign_changed:
            raw = {
                s: min(0.35, slow_budget * cur_slow.get(s, 0.0) + ignition_budget * ign_now.get(s, 0.0))
                for s in symbols
            }
            tot = sum(raw.values())
            if tot > 0.95 and tot > 0:
                sc = 0.95 / tot
                raw = {s: w * sc for s, w in raw.items()}
            ledger.rebalance_to_targets(ts, raw, exec_prices, tradable_symbols=tradable)

        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return {
        "nav_by_date": nav_by_date,
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }
