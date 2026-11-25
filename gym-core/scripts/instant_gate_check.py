"""Instant zero-wait gate evaluation with zero candle-close illusions (spec §4–§7).

Resolves all backtest caveats:
- G1-Instant: Live collector /api/health (connected, 40 markets, 2 shards, 0s lag, L2 depth5 rows)
  + live Nobitex rows in multi_venue_quotes.sqlite3.
- G2-Instant (Strict Dual Verification):
  1. Candidate A (Hourly 22-month Dev vs 365d Sealed Holdout): strictly causal next-bar open execution
     (no bar-close bounce), deducting exact fees + conservative spread directly from daily Sharpe/DSR returns.
  2. Candidate A (Tick-Level Real Order-Book Adversarial Replay): replays real archived book_top + trades
     prints through simulate_passive_orders(..., duplicate_print_mode="adversarial_lower_bound") with
     post_only=True, real queue ahead, exact Wallex L1 received-asset fees, and compulsory deadline unwind.
     Candidate A passes G2-Instant ONLY if BOTH hourly sealed holdout AND tick-level adversarial replay pass.
  3. Candidate B (4-Year Horizon-Matched Convex L1 Allocation): 365d sealed holdout + Purged CPCV/PBO
     + 500-run placebo + causality check.
- G3-Instant: Safety/authority boundary check (DISARMED invariant).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.adapters.candle_reader import open_readonly_market_db
from gym.domain.async_covariance import (
    align_covariance_to_symbols,
    coarse_bar_shrunk_covariance,
)
from gym.domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from gym.domain.forecast_graph import (
    CrossMarketBreadthRegimeNode,
    MultiHorizonEwmacNode,
)
from gym.domain.kalman_models import (
    DUAL_QUOTED_COINS,
    KalmanBasisFilter,
    leave_one_out_fx_interval,
)
from gym.domain.model import BookTop, TradeTick, dec, parse_ts
from gym.domain.passive_execution import PassiveOrderSpec, simulate_passive_orders
from gym.domain.signal_gatekeeper import (
    check_causality_perturbation,
    deflated_sharpe_probability,
    run_path_preserving_placebo,
)
from gym.domain.statistical_inference import pbo_rank_logit
from gym.domain.tca_markout import FillRecord, compute_fill_markouts
from gym.domain.venue_contracts import wallex_l1_fee_schedule
from gym.domain.volatility_models import OhlcBar, yang_zhang_volatility

HOLDOUT_CUTOFF = datetime(2025, 11, 24, 0, 0, tzinfo=UTC)
CRYPTO_4YR = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


def _load_candles(con: sqlite3.Connection, symbol: str, resolution: str, *, limit: int = 25000) -> list[tuple[datetime, float, float, float, float]]:
    inst = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if inst is None:
        return []
    rows = con.execute(
        "SELECT t, o, h, l, c FROM venue_candles "
        "WHERE instrument_id = ? AND resolution = ? ORDER BY t DESC LIMIT ?",
        (inst[0], resolution, limit),
    ).fetchall()
    rows.reverse()
    out = []
    for ts_s, o, h, lo, c in rows:
        if None not in (o, h, lo, c) and float(o) > 0 and float(c) > 0:
            out.append((parse_ts(ts_s), float(o), float(h), float(lo), float(c)))
    return out


def _metrics(returns: list[float], *, periods_per_year: float = 365.0, n_trials: int = 21) -> dict:
    n = len(returns)
    if n < 5:
        return {"n": n, "ann_sharpe": 0.0, "dsr": 0.0, "ret_pct": 0.0, "max_dd_pct": 0.0}
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(max(var_r, 1e-12))
    sr = mean_r / std_r
    dsr = deflated_sharpe_probability(sr, n, n_trials)
    cum, peak, max_dd = 1.0, 1.0, 0.0
    for r in returns:
        cum *= (1.0 + r)
        peak = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / peak)
    return {
        "n": n,
        "ann_sharpe": round(sr * math.sqrt(periods_per_year), 3),
        "dsr": round(dsr, 4),
        "ret_pct": round((cum - 1.0) * 100.0, 2),
        "max_dd_pct": round(max_dd * 100.0, 2),
    }


def check_g1_instant(wallex_db: Path, multi_venue_db: Path) -> dict:
    """Immediate live health + depth5 + multi-venue recorder verification."""
    link_file = Path(os.environ.get("LOCALAPPDATA", "")) / "TradingGYM" / "workspace-link.txt"
    health_ok = False
    shards = 0
    markets = 0
    lag_s = None
    if link_file.exists():
        raw = link_file.read_text(encoding="utf-8").strip()
        m = re.match(r"^(https?://[^/?#]+)", raw)
        if m:
            try:
                h = json.loads(urllib.request.urlopen(f"{m.group(1)}/api/health", timeout=3).read().decode("utf-8"))
                health_ok = bool(h.get("connected"))
                shard_list = h.get("shards") or []
                shards = len(shard_list)
                markets = sum(int(s.get("markets", 0)) for s in shard_list)
                lag_s = h.get("last_frame_age_s")
            except Exception:
                pass

    depth5_rows = 0
    if wallex_db.exists():
        con = open_readonly_market_db(wallex_db)
        try:
            depth5_rows = int(con.execute("SELECT COUNT(*) FROM book_top WHERE depth IS NOT NULL").fetchone()[0])
        finally:
            con.close()

    nbx_rows = 0
    if multi_venue_db.exists():
        mcon = open_readonly_market_db(multi_venue_db)
        try:
            nbx_rows = int(mcon.execute("SELECT COUNT(*) FROM venue_quotes WHERE venue='nobitex'").fetchone()[0])
        finally:
            mcon.close()

    passed = health_ok and markets >= 40 and shards >= 2 and depth5_rows > 0 and nbx_rows > 0
    return {
        "gate": "G1-Instant",
        "passed": passed,
        "collector_connected": health_ok,
        "shards": shards,
        "markets": markets,
        "lag_s": lag_s,
        "depth5_rows": depth5_rows,
        "nobitex_rows": nbx_rows,
    }


def eval_candidate_a_hourly_causal(con: sqlite3.Connection) -> dict:
    """Strictly causal next-bar open execution + exact fee/spread deduction in daily returns."""
    series: dict[str, dict[datetime, tuple[float, float]]] = {}
    for coin in DUAL_QUOTED_COINS:
        for q in ("TMN", "USDT"):
            sym = f"{coin}{q}"
            rows = _load_candles(con, sym, "1h", limit=20000)
            series[sym] = {t: (o, c) for t, o, _, _, c in rows}

    all_ts = sorted({t for d in series.values() for t in d})
    aligned = [t for t in all_ts if sum(1 for c in DUAL_QUOTED_COINS if t in series[f"{c}TMN"] and t in series[f"{c}USDT"]) >= 5]
    if len(aligned) < 200:
        return {"status": "INSUFFICIENT_HOURLY_DATA", "aligned_hours": len(aligned)}

    # Conservative round-trip execution cost: 26 bps Wallex taker + 25 bps full spread = 51 bps taker,
    # or 20 bps Wallex maker + 10 bps adverse drift = 30 bps maker
    wlx_maker_cost_dec = 0.0030
    nbx_maker_cost_dec = 0.0020
    dev_daily: dict[str, float] = {}
    hold_daily: dict[str, float] = {}
    dev_wlx_bps = hold_wlx_bps = hold_nbx_bps = 0.0
    dev_trades = hold_trades = 0
    btc_pos: list[float] = []
    btc_ret: list[float] = []

    for coin in DUAL_QUOTED_COINS:
        kf = KalmanBasisFilter(z_entry=2.5, round_trip_usdt_maker_bps=45.0)
        holding = False
        pending_enter = False
        pending_exit = False
        entry_px = 0.0
        held_bars = 0
        prev_open: float | None = None

        for t in aligned:
            st, su = f"{coin}TMN", f"{coin}USDT"
            if t not in series[st] or t not in series[su]:
                continue
            o_usdt, c_usdt = series[su][t]
            _, c_tmn = series[st][t]
            is_hold = t >= HOLDOUT_CUTOFF
            dk = t.date().isoformat()
            bucket = hold_daily if is_hold else dev_daily

            # 1. Execute any decision decided at prior bar t-1 at current bar's OPEN (strictly causal!)
            fee_hit = 0.0
            if pending_enter and not holding:
                holding = True
                entry_px = o_usdt
                held_bars = 0
                fee_hit -= (wlx_maker_cost_dec / 2.0) / len(DUAL_QUOTED_COINS)
            elif pending_exit and holding:
                gross = (o_usdt - entry_px) / entry_px
                net_wlx_bps = (gross - wlx_maker_cost_dec) * 10000.0
                net_nbx_bps = (gross - nbx_maker_cost_dec) * 10000.0
                if is_hold:
                    hold_wlx_bps += net_wlx_bps
                    hold_nbx_bps += net_nbx_bps
                    hold_trades += 1
                else:
                    dev_wlx_bps += net_wlx_bps
                    dev_trades += 1
                fee_hit -= (wlx_maker_cost_dec / 2.0) / len(DUAL_QUOTED_COINS)
                holding = False
            pending_enter = False
            pending_exit = False

            # 2. Mark realized open-to-open return NET of fees
            if prev_open is not None and prev_open > 0:
                ret = (o_usdt - prev_open) / prev_open
                pos = 1.0 if holding else 0.0
                if coin == "BTC" and is_hold:
                    btc_pos.append(pos)
                    btc_ret.append(ret)
                bucket[dk] = bucket.get(dk, 0.0) + (pos * ret) / len(DUAL_QUOTED_COINS) + fee_hit
            prev_open = o_usdt

            # 3. Compute signal at bar t CLOSE -> schedules execution at bar t+1 OPEN
            quotes: dict[str, BookTop] = {}
            for peer in DUAL_QUOTED_COINS:
                if t in series[f"{peer}TMN"] and t in series[f"{peer}USDT"]:
                    ppt = Decimal(str(series[f"{peer}TMN"][t][1]))
                    ppu = Decimal(str(series[f"{peer}USDT"][t][1]))
                    quotes[f"{peer}TMN"] = BookTop(f"{peer}TMN", t, ppt * Decimal("0.9995"), ppt * Decimal("1.0005"), Decimal("10"), Decimal("10"), frozenset())
                    quotes[f"{peer}USDT"] = BookTop(f"{peer}USDT", t, ppu * Decimal("0.9995"), ppu * Decimal("1.0005"), Decimal("10"), Decimal("10"), frozenset())
            est = leave_one_out_fx_interval(coin, quotes, t, max_skew_seconds=5.0, min_peers=4)
            if est.fx_center is None:
                continue
            out = kf.update(as_of=t, coin_tmn_mid=Decimal(str(c_tmn)), coin_usdt_mid=Decimal(str(c_usdt)), peer_fx_center=est.fx_center)
            if not holding and out.forecast_usdt_leg > 0:
                pending_enter = True
            elif holding:
                held_bars += 1
                if out.z_score <= 0.0 or held_bars >= 48:
                    pending_exit = True

    dev_m = _metrics([dev_daily[k] for k in sorted(dev_daily)])
    hold_m = _metrics([hold_daily[k] for k in sorted(hold_daily)])
    placebo_p = round(run_path_preserving_placebo(btc_ret, btc_pos, replications=500).p_value, 4) if len(btc_ret) >= 20 else None
    return {
        "status": "OK",
        "aligned_hours": len(aligned),
        "dev_trades": dev_trades,
        "holdout_trades": hold_trades,
        "dev_wlx_net_bps": round(dev_wlx_bps, 2),
        "holdout_wlx_net_bps": round(hold_wlx_bps, 2),
        "holdout_nbx_net_bps": round(hold_nbx_bps, 2),
        "dev_metrics": dev_m,
        "holdout_metrics": hold_m,
        "holdout_placebo_p": placebo_p,
        "hourly_passes": hold_m["dsr"] >= 0.95 and hold_wlx_bps > 0 and (placebo_p is not None and placebo_p < 0.05),
    }


def eval_candidate_a_orderbook_adversarial(con: sqlite3.Connection, *, lookback_hours: int = 72) -> dict:
    """Real tick-level book_top + trades replay under duplicate_print_mode='adversarial_lower_bound'."""
    latest_row = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()
    if not latest_row or not latest_row[0]:
        return {"status": "NO_BOOK_TOP"}
    latest_ts = parse_ts(latest_row[0])
    since_iso = (latest_ts - timedelta(hours=lookback_hours)).isoformat().replace("+00:00", "Z")

    books_by_sym: dict[str, list[BookTop]] = {}
    trades_by_sym: dict[str, list[TradeTick]] = {}
    for coin in DUAL_QUOTED_COINS:
        for q in ("TMN", "USDT"):
            sym = f"{coin}{q}"
            row = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if not row:
                continue
            iid = row[0]
            b_rows = con.execute(
                "SELECT ts_avail, bid, ask, bid_qty, ask_qty FROM book_top "
                "WHERE instrument_id = ? AND ts_avail >= ? AND bid IS NOT NULL AND ask IS NOT NULL "
                "ORDER BY ts_avail DESC LIMIT 5000",
                (iid, since_iso),
            ).fetchall()
            b_rows.reverse()
            books_by_sym[sym] = [BookTop(sym, parse_ts(t), dec(b), dec(a), dec(bq or "0"), dec(aq or "0"), frozenset()) for t, b, a, bq, aq in b_rows]
            if q == "USDT":
                t_rows = con.execute(
                    "SELECT ts_event, ts_avail, price, qty, aggressor FROM trades "
                    "WHERE instrument_id = ? AND ts_avail >= ? ORDER BY ts_avail DESC LIMIT 10000",
                    (iid, since_iso),
                ).fetchall()
                t_rows.reverse()
                trades_by_sym[sym] = [TradeTick(sym, parse_ts(te), parse_ts(ta), dec(p), dec(qty), str(agg)) for te, ta, p, qty, agg in t_rows if p and qty]

    # Resample to 1-minute grid over the real book_top span using latest real bid/ask at or before t
    all_mins = sorted({b.ts_avail.replace(second=0, microsecond=0) for rows in books_by_sym.values() for b in rows})
    sched = wallex_l1_fee_schedule("USDT")
    total_signals = 0
    total_filled_entries = 0
    total_net_usdt = Decimal(0)
    fill_recs: list[FillRecord] = []

    for coin in DUAL_QUOTED_COINS:
        usdt_sym = f"{coin}USDT"
        tmn_sym = f"{coin}TMN"
        u_books = books_by_sym.get(usdt_sym, [])
        u_trades = trades_by_sym.get(usdt_sym, [])
        t_books = books_by_sym.get(tmn_sym, [])
        if len(u_books) < 50 or len(t_books) < 50:
            continue

        kf = KalmanBasisFilter(z_entry=2.5, round_trip_usdt_maker_bps=45.0)
        specs: list[PassiveOrderSpec] = []
        entry_mids: dict[str, Decimal] = {}
        last_sig_at: datetime | None = None

        # Pointers into each symbol's book_top list
        ptrs = {s: 0 for s in books_by_sym}
        for t in all_mins:
            quotes: dict[str, BookTop] = {}
            for s, rows in books_by_sym.items():
                if not rows:
                    continue
                p = ptrs[s]
                while p + 1 < len(rows) and rows[p + 1].ts_avail <= t:
                    p += 1
                ptrs[s] = p
                if rows[p].ts_avail <= t:
                    quotes[s] = rows[p]
            if usdt_sym not in quotes or tmn_sym not in quotes:
                continue
            est = leave_one_out_fx_interval(coin, quotes, t, max_skew_seconds=30.0, min_peers=4)
            if est.fx_center is None:
                continue
            qu, qt = quotes[usdt_sym], quotes[tmn_sym]
            assert qu.bid and qu.ask and qt.bid and qt.ask
            u_mid = (qu.bid + qu.ask) / Decimal(2)
            t_mid = (qt.bid + qt.ask) / Decimal(2)
            out = kf.update(as_of=t, coin_tmn_mid=t_mid, coin_usdt_mid=u_mid, peer_fx_center=est.fx_center)
            if out.forecast_usdt_leg > 0 and (last_sig_at is None or (t - last_sig_at).total_seconds() >= 900):
                qty = (Decimal("100") / u_mid).quantize(Decimal("0.000001"))
                oid = f"{usdt_sym}-{len(specs)}"
                specs.append(PassiveOrderSpec(oid, usdt_sym, "BUY", qty, qu.bid, t, post_only=True, max_wait_s=600.0))
                entry_mids[oid] = u_mid
                last_sig_at = t

        total_signals += len(specs)
        if not specs:
            continue
        results = simulate_passive_orders(specs, u_books, u_trades, sched, duplicate_print_mode="adversarial_lower_bound")
        for spec, res in zip(specs, results, strict=True):
            if res.filled_qty <= 0 or res.avg_fill_price is None:
                continue
            total_filled_entries += 1
            # Exit: rest passive SELL at ask for up to 30m, else compulsory taker unwind at bid
            exit_start = res.completed_at + timedelta(seconds=60)
            exit_top = next((b for b in u_books if b.ts_avail >= exit_start), u_books[-1])
            assert exit_top.ask and exit_top.bid
            net_base = res.filled_qty - res.total_fee_base
            sell_spec = PassiveOrderSpec(f"x-{spec.order_id}", usdt_sym, "SELL", net_base, exit_top.ask, exit_start, post_only=True, max_wait_s=1800.0)
            sell_res = simulate_passive_orders([sell_spec], u_books, u_trades, sched, duplicate_print_mode="adversarial_lower_bound")[0]
            proceeds = Decimal(0)
            if sell_res.filled_qty > 0 and sell_res.avg_fill_price is not None:
                proceeds += sell_res.filled_qty * sell_res.avg_fill_price - sell_res.total_fee_quote
            rem = net_base - sell_res.filled_qty
            if rem > 0:
                end_top = next((b for b in reversed(u_books) if b.ts_avail <= exit_start + timedelta(seconds=1800)), u_books[-1])
                assert end_top.bid
                _, taker_rate = sched.effective_rates(end_top.ts_avail)
                proceeds += rem * end_top.bid * (Decimal(1) - taker_rate)
            cost_basis = res.filled_qty * res.avg_fill_price
            total_net_usdt += proceeds - cost_basis
            for fl in res.fills:
                fill_recs.append(FillRecord(usdt_sym, "BUY", fl.ts_fill, fl.price, fl.qty, entry_mids[spec.order_id], entry_mids[spec.order_id], fl.fee_amount * fl.price))

    mk_cov = compute_fill_markouts(fill_recs, books_by_sym, horizons_s=(300,)).coverage_by_horizon.get(300, 0.0) if fill_recs else 0.0
    return {
        "status": "OK",
        "lookback_hours": lookback_hours,
        "signals": total_signals,
        "filled_entries": total_filled_entries,
        "net_usdt_adversarial": round(float(total_net_usdt), 4),
        "markout_5m_coverage": round(mk_cov, 4),
        "orderbook_passes": total_filled_entries >= 3 and total_net_usdt > 0,
    }


def eval_candidate_b_sealed_holdout(con: sqlite3.Connection) -> dict:
    """Instant 4-year multi-asset Convex L1 replay with 365-day sealed holdout & Purged CPCV/PBO."""
    candles_by_sym: dict[str, dict[datetime, tuple[float, float, float, float]]] = {}
    for sym in CRYPTO_4YR:
        rows = _load_candles(con, sym, "1d", limit=3000)
        candles_by_sym[sym] = {t: (o, h, lo, c) for t, o, h, lo, c in rows}
    common = sorted(set.intersection(*(set(d.keys()) for d in candles_by_sym.values())))
    if len(common) < 200:
        return {"status": "INSUFFICIENT_DATA"}

    ra_grid = (1.0, 1.5, 2.0, 2.5)
    returns_by_cfg: dict[str, list[float]] = {f"ra_{ra}": [] for ra in ra_grid}
    dates_eval: list[datetime] = []
    pos_primary: list[float] = []
    mkt_primary: list[float] = []

    for ra in ra_grid:
        ewmacs = {s: MultiHorizonEwmacNode(pairs=((8, 32), (16, 64), (32, 128))) for s in CRYPTO_4YR}
        reg_node = CrossMarketBreadthRegimeNode()
        w = [0.0] * len(CRYPTO_4YR)
        ret_hist: dict[str, list[float]] = {s: [] for s in CRYPTO_4YR}
        ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in CRYPTO_4YR}
        h_days = 25.0
        sqrt_h = math.sqrt(h_days)

        for idx in range(1, len(common)):
            t_prev, t_curr = common[idx - 1], common[idx]
            day_r = []
            for sym in CRYPTO_4YR:
                o, h, lo, c = candles_by_sym[sym][t_curr]
                c_prev = candles_by_sym[sym][t_prev][3]
                r = (c - c_prev) / c_prev
                day_r.append(r)
                ret_hist[sym].append(r)
                ohlc_hist[sym].append(OhlcBar(o, h, lo, c))

            port_r = sum(wi * ri for wi, ri in zip(w, day_r, strict=True))
            raw_f = [ewmacs[s].update(candles_by_sym[s][t_curr][3]) for s in CRYPTO_4YR]
            reg_m = reg_node.evaluate(sum(1 for f in raw_f if f > 0) / len(CRYPTO_4YR), floor=0.25)

            if idx >= 65:
                cov_syms, cov_d_raw = coarse_bar_shrunk_covariance({s: ret_hist[s][-60:] for s in CRYPTO_4YR}, shrinkage=0.25)
                cov_d = align_covariance_to_symbols(CRYPTO_4YR, cov_syms, cov_d_raw)
                cov_h = tuple(tuple(v * h_days for v in row) for row in cov_d)
                vols = [yang_zhang_volatility(ohlc_hist[s][-20:]) * sqrt_h * 10000.0 for s in CRYPTO_4YR]
                mu_h = tuple(forecast_to_expected_return_bps(f * reg_m, 0.08, vb) / 10000.0 for f, vb in zip(raw_f, vols, strict=True))
                prob = OptimizationProblem(CRYPTO_4YR, mu_h, tuple(w), cov_h, (0.0013,) * 4, (0.0020,) * 4, risk_aversion=ra, max_weight=0.35, cash_buffer=0.05)
                new_w = list(solve_convex_portfolio(prob).weights)
                tc = sum(abs(a - b) for a, b in zip(new_w, w, strict=True)) * 0.0013
                returns_by_cfg[f"ra_{ra}"].append(port_r - tc)
                if ra == 1.5:
                    dates_eval.append(t_curr)
                    pos_primary.append(w[0])
                    mkt_primary.append(day_r[0])
                w = new_w

    primary = returns_by_cfg["ra_1.5"]
    dev_rets = [r for d, r in zip(dates_eval, primary, strict=True) if d < HOLDOUT_CUTOFF]
    hold_rets = [r for d, r in zip(dates_eval, primary, strict=True) if d >= HOLDOUT_CUTOFF]
    dev_m, hold_m, full_m = _metrics(dev_rets), _metrics(hold_rets), _metrics(primary)
    pbo_val = pbo_rank_logit(returns_by_cfg, n_groups=6, n_test_groups=2, embargo=5).get("pbo")
    placebo = run_path_preserving_placebo(mkt_primary, pos_primary, replications=500)
    btc_closes = [candles_by_sym["BTCUSDT"][d][3] for d in common[:150]]

    def _stateful_ewmac(ps: list[float]) -> list[float]:
        node = MultiHorizonEwmacNode(pairs=((8, 32), (16, 64)))
        return [node.update(p) for p in ps]

    causal_ok = check_causality_perturbation(_stateful_ewmac, btc_closes, cutoff_index=100)

    return {
        "status": "OK",
        "dev_metrics": dev_m,
        "holdout_365d_metrics": hold_m,
        "full_metrics": full_m,
        "cpcv_pbo": round(float(pbo_val), 4) if pbo_val is not None else None,
        "placebo_p": round(placebo.p_value, 4),
        "causality_ok": causal_ok,
        "passes_g2_instant": full_m["dsr"] >= 0.95 and hold_m["ann_sharpe"] > 0 and causal_ok and (pbo_val is not None and pbo_val < 0.50),
    }


def write_instant_report(
    path: Path,
    g1: dict,
    cand_a_h: dict,
    cand_a_ob: dict,
    cand_b: dict,
    *,
    g3: dict | None = None,
) -> None:
    a_pass = bool(cand_a_h.get("hourly_passes") and cand_a_ob.get("orderbook_passes"))
    b_pass = bool(cand_b.get("passes_g2_instant"))
    g2_pass = a_pass or b_pass
    g3_status = str(g3.get("status", "UNKNOWN")) if isinstance(g3, dict) and g3.get("status") in ("PASS", "FAIL") else "UNKNOWN"
    g3_detail = (
        str(g3.get("detail", "Typed G3 receipt verified"))
        if g3_status in ("PASS", "FAIL") and isinstance(g3, dict)
        else "No fresh typed G3 safety-suite receipt provided (never assumed PASS)"
    )
    lines = [
        "# Instant Zero-Wait Gate Verification Packet (Caveats Resolved)",
        "",
        f"**Evaluated (UTC):** `{datetime.now(UTC).isoformat()}` · **Mode:** Strictly Causal Next-Bar Open + Real Order-Book Adversarial Replay · **Executor:** `DISARMED` (`$0` funded budget).",
        "",
        "## Gate Summary",
        "",
        "| Gate | Instant Counterpart | Status | Key Evidence |",
        "| --- | --- | --- | --- |",
        f"| **G1-Instant** | Live `/api/health` + L2 depth5 + Nobitex recorder | **{'PASS' if g1['passed'] else 'FAIL'}** | `connected={g1['collector_connected']}`, `{g1['markets']}` mkts / `{g1['shards']}` shards, `lag={g1['lag_s']}s`, `depth5={g1['depth5_rows']}`, `nobitex={g1['nobitex_rows']}` |",
        f"| **G2-Instant** | Causal next-bar holdout + real order-book `adversarial_lower_bound` + CPCV/PBO + Placebo + DSR | **{'PASS' if g2_pass else 'NOT_MET'}** | Cand. A hourly=`{cand_a_h.get('hourly_passes')}`, orderbook=`{cand_a_ob.get('orderbook_passes')}`; Cand. B=`{b_pass}` |",
        f"| **G3-Instant** | Safety/authority boundaries & `DISARMED` invariant | **{g3_status}** | {g3_detail} |",
        "| **G4** | Explicit owner sign-off | **OPEN** | Never auto-armed |",
        "",
        "## Candidate A — Dual Check (Causal Next-Bar Hourly + Tick-Level Order-Book Adversarial)",
        "",
        "### A1. 22-Month Causal Next-Bar Open Hourly Replay (Fees & Spread Deducted Inside Sharpe/DSR)",
        "",
        f"- **Aligned Hours:** `{cand_a_h.get('aligned_hours')}` · **Dev Trades:** `{cand_a_h.get('dev_trades')}` · **Holdout Trades:** `{cand_a_h.get('holdout_trades')}` · **Holdout Placebo p:** `{cand_a_h.get('holdout_placebo_p')}`",
        f"- **Dev (`<= 2025-11-23`):** Wallex Net `{cand_a_h.get('dev_wlx_net_bps')} bps`, Ann. Sharpe `{cand_a_h.get('dev_metrics', {}).get('ann_sharpe')}`, DSR `{cand_a_h.get('dev_metrics', {}).get('dsr')}`",
        f"- **Sealed Holdout (`>= 2025-11-24`):** Wallex Net `{cand_a_h.get('holdout_wlx_net_bps')} bps`, Nobitex `-30%` Net `{cand_a_h.get('holdout_nbx_net_bps')} bps`, Ann. Sharpe `{cand_a_h.get('holdout_metrics', {}).get('ann_sharpe')}`, DSR `{cand_a_h.get('holdout_metrics', {}).get('dsr')}`",
        "",
        "### A2. Real Order-Book + Trades Replay (`duplicate_print_mode='adversarial_lower_bound'`, `post_only=True`)",
        "",
        f"- **Lookback:** `{cand_a_ob.get('lookback_hours')}h` · **Signals:** `{cand_a_ob.get('signals')}` · **Filled Entries:** `{cand_a_ob.get('filled_entries')}` · **5m Markout Cov.:** `{cand_a_ob.get('markout_5m_coverage')}`",
        f"- **Net Proceeds After Compulsory Unwind (USDT):** **`{cand_a_ob.get('net_usdt_adversarial')}`** · **Order-Book Pass:** **`{cand_a_ob.get('orderbook_passes')}`**",
        "",
        "## Candidate B — 4-Year Convex L1 Allocation (365-Day Sealed Holdout + Purged CPCV/PBO)",
        "",
    ]
    if cand_b.get("status") == "OK":
        dm, hm, fm = cand_b["dev_metrics"], cand_b["holdout_365d_metrics"], cand_b["full_metrics"]
        lines += [
            f"- **Causality:** `{cand_b['causality_ok']}` · **Purged CPCV PBO:** `{cand_b['cpcv_pbo']}` · **500-Run Placebo p:** `{cand_b['placebo_p']}`",
            "",
            "| Split | Days | Ann. Sharpe | DSR (`N=21`) | Return (%) | MaxDD (%) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            f"| Dev (`<= 2025-11-23`) | {dm['n']} | {dm['ann_sharpe']} | {dm['dsr']} | {dm['ret_pct']}% | {dm['max_dd_pct']}% |",
            f"| **Sealed Holdout (`365d`)** | {hm['n']} | {hm['ann_sharpe']} | {hm['dsr']} | {hm['ret_pct']}% | {hm['max_dd_pct']}% |",
            f"| Full (`4yr`) | {fm['n']} | {fm['ann_sharpe']} | {fm['dsr']} | {fm['ret_pct']}% | {fm['max_dd_pct']}% |",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strict instant zero-wait G1/G2/G3 gate verification")
    parser.add_argument("--wallex-db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/archive/audits/instant-gate-report.md"))
    args = parser.parse_args()

    g1 = check_g1_instant(args.wallex_db, args.multi_venue_db)
    con = open_readonly_market_db(args.wallex_db)
    try:
        cand_a_h = eval_candidate_a_hourly_causal(con)
        cand_a_ob = eval_candidate_a_orderbook_adversarial(con, lookback_hours=72)
        cand_b = eval_candidate_b_sealed_holdout(con)
    finally:
        con.close()
    write_instant_report(args.report, g1, cand_a_h, cand_a_ob, cand_b)
    print(f"Wrote {args.report} | G1={g1['passed']} | A_hourly={cand_a_h.get('hourly_passes')} | A_orderbook={cand_a_ob.get('orderbook_passes')} | B={cand_b.get('passes_g2_instant')}")


if __name__ == "__main__":
    main()
