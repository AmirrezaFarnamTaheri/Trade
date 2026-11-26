"""Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10).

Implements four treasury & execution-economics paper experiments from
docs/architecture/2026-11-25-last-42-commits-review.md:
  - Idea 7: Marginal value of +1 USDT per venue (prefunding sweep + one-venue outage stress).
  - Idea 8: Gold token substitution (XAUT-only vs 50/50 split vs cost-aware switch + -3% issuer shock).
  - Idea 9: Cash recoverable on deadline (5m / 1h / 1d liquidation under live walked L2 depth).
  - Idea 10: Separating trading skill from USDT/TMN FX exposure on matched TMN capital.

Strictly read-only against market.db / multi_venue_quotes.sqlite3; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.model import dec, parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.strategy_sleeves import compute_slow_sleeves
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import portfolio_metrics
from .smart_execution_sim import _parse_levels, _taker_cost_bps, walk_orderbook_vwap
from .unified_book_helpers import resolve_bar_prices


def _load_matched_live_books(
    wallex_db: Path,
    multi_venue_db: Path,
    symbols: tuple[str, ...],
    *,
    max_skew_s: float = 15.0,
) -> dict[str, list[dict]]:
    if not wallex_db.exists() or not multi_venue_db.exists():
        return {}
    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    out: dict[str, list[dict]] = {}
    try:
        for sym in symbols:
            n_list = mcon.execute(
                "SELECT ts_avail, bid, ask, bid_qty, ask_qty, depth_json "
                "FROM venue_quotes WHERE venue = 'nobitex' AND symbol = ? ORDER BY ts_avail ASC",
                (sym,),
            ).fetchall()
            inst = wcon.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if not n_list or inst is None:
                continue
            min_ts = (parse_ts(n_list[0][0]) - timedelta(seconds=max_skew_s)).isoformat().replace("+00:00", "Z")
            w_raw = wcon.execute(
                "SELECT ts_avail, bid, ask, bid_qty, ask_qty, depth "
                "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? "
                "AND bid IS NOT NULL AND ask IS NOT NULL ORDER BY ts_avail ASC",
                (inst[0], min_ts),
            ).fetchall()
            if not w_raw:
                continue
            w_ep = [parse_ts(r[0]).timestamp() for r in w_raw]
            matched: list[dict] = []
            for ts_s, nb, na, nbq, naq, ndepth in n_list:
                t_ep = parse_ts(ts_s).timestamp()
                cand = bisect_right(w_ep, t_ep) - 1
                if cand < 0 or (t_ep - w_ep[cand]) > max_skew_s:
                    continue
                _, wb_s, wa_s, wbq_s, waq_s, wdepth = w_raw[cand]
                wb, wa = float(dec(wb_s)), float(dec(wa_s))
                nb_f, na_f = float(dec(nb)), float(dec(na))
                matched.append({
                    "symbol": sym,
                    "epoch": t_ep,
                    "w_mid": 0.5 * (wb + wa),
                    "n_mid": 0.5 * (nb_f + na_f),
                    "w_bids": _parse_levels(wdepth, wb, wa, float(dec(wbq_s or "0")), float(dec(waq_s or "0")))[0],
                    "w_asks": _parse_levels(wdepth, wb, wa, float(dec(wbq_s or "0")), float(dec(waq_s or "0")))[1],
                    "n_bids": _parse_levels(ndepth, nb_f, na_f, float(dec(nbq or "0")), float(dec(naq or "0")))[0],
                    "n_asks": _parse_levels(ndepth, nb_f, na_f, float(dec(nbq or "0")), float(dec(naq or "0")))[1],
                })
            if matched:
                out[sym] = matched
    finally:
        wcon.close()
        mcon.close()
    return out


def _sim_prefund_split(
    snaps: list[dict],
    nbx_init: float,
    wlx_init: float,
    *,
    order_usdt: float = 125.0,
    outage_nbx_frac: float = 0.0,
    sides: list[str] | None = None,
    settlement_steps: int = 1,
) -> dict:
    """Strict (venue, symbol) inventory & settlement ledger in chronological order; never mixes assets across symbols."""
    ordered = sorted(snaps, key=lambda x: x["epoch"]) if sides is None else snaps
    cash = {"nobitex": float(nbx_init), "wallex": float(wlx_init)}
    units: dict[tuple[str, str], float] = {}  # (venue, symbol) -> units
    last_mid_by_sym: dict[str, float] = {}
    pending_cash: list[tuple[int, str, float]] = []  # (settle_idx, venue, amount)
    costs_bps: list[float] = []
    missed = 0
    executed = 0
    total = 0
    outage_start = int((1.0 - outage_nbx_frac) * len(ordered)) if outage_nbx_frac > 0 else len(ordered)

    for idx, m in enumerate(ordered):
        still_pending = []
        for s_idx, ven, amt in pending_cash:
            if s_idx <= idx:
                cash[ven] += amt
            else:
                still_pending.append((s_idx, ven, amt))
        pending_cash = still_pending

        total += 1
        sym = str(m.get("symbol", "BTCUSDT"))
        mid = 0.5 * (m["w_mid"] + m["n_mid"])
        last_mid_by_sym[sym] = mid
        side = sides[idx] if (sides is not None and idx < len(sides)) else ("BUY" if idx % 2 == 0 else "SELL")
        nbx_up = idx < outage_start

        if side == "BUY":
            wc, wf = _taker_cost_bps(m["w_asks"], mid, "BUY", order_usdt, 25.0)
            nc, nf = _taker_cost_bps(m["n_asks"], mid, "BUY", order_usdt, 16.0)
            order_venues = ("nobitex", "wallex") if (nbx_up and nc <= wc) else ("wallex", "nobitex")
            filled = False
            for ven in order_venues:
                if ven == "nobitex" and not nbx_up:
                    continue
                c_bps, f_frac = (nc, nf) if ven == "nobitex" else (wc, wf)
                if cash[ven] >= order_usdt and f_frac > 0:
                    spent = order_usdt * f_frac
                    cash[ven] -= spent
                    eff_px = mid * (1.0 + c_bps / 10_000.0)
                    units[(ven, sym)] = units.get((ven, sym), 0.0) + (spent / max(1e-9, eff_px))
                    costs_bps.append(c_bps)
                    executed += 1
                    filled = True
                    break
            if not filled:
                missed += 1
        else:
            wc, wf = _taker_cost_bps(m["w_bids"], mid, "SELL", order_usdt, 25.0)
            nc, nf = _taker_cost_bps(m["n_bids"], mid, "SELL", order_usdt, 16.0)
            order_venues = ("nobitex", "wallex") if (nbx_up and nc <= wc) else ("wallex", "nobitex")
            filled = False
            for ven in order_venues:
                if ven == "nobitex" and not nbx_up:
                    continue
                held_u = units.get((ven, sym), 0.0)
                if held_u * mid >= order_usdt * 0.25:
                    c_bps, f_frac = (nc, nf) if ven == "nobitex" else (wc, wf)
                    sell_u = min(held_u, (order_usdt * f_frac) / max(1e-9, mid))
                    if sell_u > 0:
                        units[(ven, sym)] = held_u - sell_u
                        proceeds = sell_u * mid * (1.0 - c_bps / 10_000.0)
                        pending_cash.append((idx + max(1, settlement_steps), ven, proceeds))
                        costs_bps.append(c_bps)
                        executed += 1
                        filled = True
                        break
            if not filled:
                missed += 1

    settled_total = cash["nobitex"] + cash["wallex"] + sum(a for _, _, a in pending_cash)
    inv_val = sum(u * last_mid_by_sym.get(sym, 0.0) for (_, sym), u in units.items())
    return {
        "nbx_init_usdt": nbx_init,
        "wlx_init_usdt": wlx_init,
        "orders": total,
        "executed": executed,
        "missed": missed,
        "missed_pct": round(missed / max(1, total) * 100.0, 1),
        "mean_exec_cost_bps": round(mean(costs_bps), 2) if costs_bps else 0.0,
        "ending_cash_usdt": round(cash["nobitex"] + cash["wallex"], 2),
        "ending_equity_usdt": round(settled_total + inv_val, 2),
    }


def _run_idea_7_venue_prefunding(matched_books: dict[str, list[dict]]) -> list[dict]:
    """Idea 7: Sweep initial Nobitex/Wallex USDT split under normal and 25% Nobitex-outage conditions."""
    snaps = matched_books.get("BTCUSDT", []) + matched_books.get("ETHUSDT", [])
    if not snaps:
        return []
    rows = []
    for nbx_init in (0.0, 250.0, 500.0, 750.0, 1000.0):
        wlx_init = 1000.0 - nbx_init
        norm = _sim_prefund_split(snaps, nbx_init, wlx_init, outage_nbx_frac=0.0)
        out = _sim_prefund_split(snaps, nbx_init, wlx_init, outage_nbx_frac=0.25)
        rows.append({
            "split_label": f"NBX_{int(nbx_init)}_WLX_{int(wlx_init)}",
            "normal_cost_bps": norm["mean_exec_cost_bps"],
            "normal_missed_pct": norm["missed_pct"],
            "outage_cost_bps": out["mean_exec_cost_bps"],
            "outage_missed_pct": out["missed_pct"],
        })
    return rows


def _run_idea_8_gold_substitution(con, *, as_of: datetime | None = None) -> dict:
    """Idea 8: Compare XAUT-only, 50/50 split, and switching under 3 explicit execution timings (same-close, next-open, next-close)."""
    cutoff = as_of or datetime.now(UTC)
    x_bars = {b.ts_avail.date().isoformat(): b for b in load_keyed_candles(con, "XAUTUSDT", "1d", limit=2500, as_of=cutoff)}
    p_bars = {b.ts_avail.date().isoformat(): b for b in load_keyed_candles(con, "PAXGUSDT", "1d", limit=2500, as_of=cutoff)}
    days = sorted(d for d in (set(x_bars) & set(p_bars)) if d >= "2024-01-01")
    if len(days) < 30:
        return {"status": "INSUFFICIENT_GOLD_OVERLAP", "days": len(days)}

    rt_fee = 0.0032
    shock_idx = len(days) // 2

    def _sim_switch(mode: str, *, apply_shock: bool = False) -> tuple[dict[str, float], int]:
        nav: dict[str, float] = {}
        held = "XAUT"
        qty = 1000.0 / x_bars[days[0]].close
        switches = 0
        for i, d in enumerate(days):
            sh = 0.97 if (apply_shock and i >= shock_idx) else 1.0
            px_x = x_bars[d].close * sh
            px_p = p_bars[d].close
            nav[d] = qty * (px_x if held == "XAUT" else px_p)
            if i + 1 >= len(days) and mode != "same_close":
                continue
            ratio = (px_p - px_x) / px_x
            want = "PAXG" if (held == "XAUT" and ratio < -0.006) else ("XAUT" if (held == "PAXG" and ratio > 0.006) else None)
            if want is not None:
                sh_ex = 0.97 if (apply_shock and (i if mode == "same_close" else i + 1) >= shock_idx) else 1.0
                if mode == "same_close":
                    ex_x, ex_p = px_x, px_p
                elif mode == "next_open":
                    ex_x, ex_p = x_bars[days[i + 1]].open * sh_ex, p_bars[days[i + 1]].open
                else:
                    ex_x, ex_p = x_bars[days[i + 1]].close * sh_ex, p_bars[days[i + 1]].close
                if want == "PAXG":
                    qty = (qty * ex_x * (1.0 - rt_fee)) / ex_p
                else:
                    qty = (qty * ex_p * (1.0 - rt_fee)) / ex_x
                held = want
                switches += 1
        return nav, switches

    nav_x = {d: (1000.0 / x_bars[days[0]].close) * x_bars[d].close for d in days}
    nav_sp = {d: (500.0 / x_bars[days[0]].close) * x_bars[d].close + (500.0 / p_bars[days[0]].close) * p_bars[d].close for d in days}
    nav_x_s = {d: (1000.0 / x_bars[days[0]].close) * x_bars[d].close * (0.97 if i >= shock_idx else 1.0) for i, d in enumerate(days)}
    nav_sp_s = {d: (500.0 / x_bars[days[0]].close) * x_bars[d].close * (0.97 if i >= shock_idx else 1.0) + (500.0 / p_bars[days[0]].close) * p_bars[d].close for i, d in enumerate(days)}

    nav_sc, sw_sc = _sim_switch("same_close")
    nav_no, sw_no = _sim_switch("next_open")
    nav_nc, sw_nc = _sim_switch("next_close")
    nav_no_s, _ = _sim_switch("next_open", apply_shock=True)

    return {
        "days": len(days),
        "switches": sw_no,
        "xaut_only": portfolio_metrics(nav_x, starting_nav=1000.0),
        "split_50_50": portfolio_metrics(nav_sp, starting_nav=1000.0),
        "switch_same_close_upper_bound": portfolio_metrics(nav_sc, starting_nav=1000.0),
        "switch_causal_next_open": portfolio_metrics(nav_no, starting_nav=1000.0),
        "switch_causal_next_close": portfolio_metrics(nav_nc, starting_nav=1000.0),
        "issuer_shock_3pct_ret": {
            "xaut_only_pct": portfolio_metrics(nav_x_s, starting_nav=1000.0)["ret_pct"],
            "split_50_50_pct": portfolio_metrics(nav_sp_s, starting_nav=1000.0)["ret_pct"],
            "switch_next_open_shocked_pct": portfolio_metrics(nav_no_s, starting_nav=1000.0)["ret_pct"],
        },
    }


def _run_idea_9_liquidation_deadlines(matched_books: dict[str, list[dict]]) -> list[dict]:
    """Idea 9: Rank portfolios by net spendable USDT recovered against the ORIGINAL portfolio (never dropping missing books)."""
    books = {
        "BTC_ETH_XAUT_CORE": {"BTCUSDT": 0.40, "ETHUSDT": 0.30, "XAUTUSDT": 0.30},
        "ALT_HEAVY_BASKET": {"SOLUSDT": 0.35, "XRPUSDT": 0.35, "ADAUSDT": 0.30},
    }
    deadlines = (("5m", 1.0), ("1h", 4.0), ("1d", 20.0))
    rows = []
    for book_name, weights in books.items():
        orig_w = sum(weights.values())
        for notional in (10_000.0, 50_000.0):
            for dl_name, depth_mult in deadlines:
                net_cash_w = 0.0
                unpriced_w = 0.0
                shortfalls = []
                covered_w = 0.0
                for sym, w in weights.items():
                    snaps = matched_books.get(sym, [])
                    if not snaps:
                        unpriced_w += w
                        continue
                    covered_w += w
                    m = snaps[-1]
                    leg_n = notional * (w / orig_w)
                    comb_bids = sorted(
                        [(p, q * depth_mult) for p, q in (m["n_bids"] + m["w_bids"])],
                        key=lambda x: x[0],
                        reverse=True,
                    )
                    mid = 0.5 * (m["n_mid"] + m["w_mid"])
                    vwap, fill_f = walk_orderbook_vwap(comb_bids, leg_n)
                    fee_frac = 0.0016
                    sf = ((mid - vwap) / mid * 10_000.0 + 16.0) if (mid > 0 and vwap > 0) else 50.0
                    # Net spendable cash after slippage & 16 bps taker fee relative to decision mid
                    net_cash_w += w * fill_f * max(0.0, (vwap / mid) * (1.0 - fee_frac)) if (mid > 0 and vwap > 0) else 0.0
                    shortfalls.append(w * sf)
                rec_pct = (net_cash_w / orig_w) * 100.0 if orig_w > 0 else 0.0
                unpriced_pct = (unpriced_w / orig_w) * 100.0 if orig_w > 0 else 0.0
                sf_bps = (sum(shortfalls) / max(1e-9, covered_w)) if covered_w > 0 else 0.0
                rows.append({
                    "book": book_name,
                    "notional_usdt": notional,
                    "deadline": dl_name,
                    "cash_recovered_pct": round(rec_pct, 1),
                    "residual_inventory_pct": round(max(0.0, 100.0 - rec_pct), 1),
                    "unpriced_inventory_pct": round(unpriced_pct, 1),
                    "shortfall_bps": round(sf_bps, 2),
                })
    return rows


def _run_idea_10_tmn_fx_separation(con) -> dict:
    """Idea 10: Separate trading alpha from USDT/TMN FX depreciation starting from 100M TMN."""
    usdt_tmn = {b.ts_avail.date().isoformat(): b.close for b in load_keyed_candles(con, "USDTTMN", "1d", limit=2500)}
    btc_tmn = {b.ts_avail.date().isoformat(): b.close for b in load_keyed_candles(con, "BTCTMN", "1d", limit=2500)}
    panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))

    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0016"), fee_in_received_asset=True)
    nav_usdt: dict[str, float] = {}
    last_px: dict[str, float] = {}
    for ts in sorted(daily_targets):
        ef, tr = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        ep = {s: Decimal(str(p)) for s, p in ef.items()}
        ledger.rebalance_to_targets(ts, daily_targets[ts], ep, tradable_symbols=tr)
        nav_usdt[ts.date().isoformat()] = float(ledger.mark_nav(ep))

    days = sorted(set(usdt_tmn) & set(nav_usdt))
    if len(days) < 30:
        return {"status": "INSUFFICIENT_TMN_OVERLAP", "days": len(days)}

    d0, d1 = days[0], days[-1]
    fx0, fx1 = usdt_tmn[d0], usdt_tmn[d1]
    conv_fee = 0.0025  # 25 bps TMN<->USDT conversion each way
    hold_usdt_tmn_ret = ((fx1 / fx0) * ((1.0 - conv_fee) ** 2) - 1.0) * 100.0
    strat_usdt_mult = nav_usdt[d1] / nav_usdt[d0]
    strat_tmn_ret = (strat_usdt_mult * (fx1 / fx0) * ((1.0 - conv_fee) ** 2) - 1.0) * 100.0
    btc_tmn_ret = (
        ((btc_tmn[d1] / btc_tmn[d0]) * ((1.0 - conv_fee) ** 2) - 1.0) * 100.0
        if (d0 in btc_tmn and d1 in btc_tmn and btc_tmn[d0] > 0)
        else None
    )
    return {
        "overlap_days": len(days),
        "start_date": d0,
        "end_date": d1,
        "hold_tmn_ret_pct": 0.0,
        "buy_hold_usdt_in_tmn_ret_pct": round(hold_usdt_tmn_ret, 2),
        "usdt_strategy_converted_tmn_ret_pct": round(strat_tmn_ret, 2),
        "strategy_pure_usdt_alpha_pct": round((strat_usdt_mult - 1.0) * 100.0, 2),
        "direct_btctmn_hold_ret_pct": round(btc_tmn_ret, 2) if btc_tmn_ret is not None else None,
    }


def run_treasury_liquidity_and_fx_study(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Execute Menu Ideas 7, 8, 9, and 10 on live data and corrected accounting."""
    matched = _load_matched_live_books(
        wallex_db, multi_venue_db, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "XAUTUSDT"),
    )
    con = open_readonly_market_db(wallex_db)
    try:
        idea8 = _run_idea_8_gold_substitution(con)
        idea10 = _run_idea_10_tmn_fx_separation(con)
    finally:
        con.close()

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "idea_7_prefunding_sweep": _run_idea_7_venue_prefunding(matched),
        "idea_8_gold_substitution": idea8,
        "idea_9_liquidation_deadlines": _run_idea_9_liquidation_deadlines(matched),
        "idea_10_tmn_fx_separation": idea10,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10)",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "",
        "## Idea 7 — Marginal Value of +1 USDT per Venue (Prefunding Sweep, `$1,000` Fixed)",
        "",
        "| Split (NBX / WLX) | Normal Exec Cost (bps) | Normal Missed% | 25% NBX-Outage Cost (bps) | 25% Outage Missed% |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in p["idea_7_prefunding_sweep"]:
        lines.append(
            f"| `{r['split_label']}` | `{r['normal_cost_bps']:+.2f}` | `{r['normal_missed_pct']:.1f}%` | `{r['outage_cost_bps']:+.2f}` | `{r['outage_missed_pct']:.1f}%` |"
        )
    i8 = p["idea_8_gold_substitution"]
    lines.extend([
        "",
        "## Idea 8 — Gold Token Substitution (`XAUT` vs `PAXG`, 3 Execution Timings + -3% Issuer Shock)",
        f"- **Overlap Days (Closed Bars Only):** `{i8.get('days')}` · **Switches:** `{i8.get('switches', 0)}`",
        f"- **Hold Benchmarks:** `XAUT_ONLY={i8.get('xaut_only', {}).get('ret_pct')}%` · `SPLIT_50_50={i8.get('split_50_50', {}).get('ret_pct')}%`",
        f"- **Switching Timing Sensitivity:** `SAME_CLOSE_UPPER={i8.get('switch_same_close_upper_bound', {}).get('ret_pct')}%` · `CAUSAL_NEXT_OPEN={i8.get('switch_causal_next_open', {}).get('ret_pct')}%` · `CAUSAL_NEXT_CLOSE={i8.get('switch_causal_next_close', {}).get('ret_pct')}%`",
        f"- **Under -3% XAUT Issuer Shock (Applied to Execution & Marks):** `{i8.get('issuer_shock_3pct_ret')}`",
        "",
        "## Idea 9 — Cash Recoverable on Deadline (Net of Fees, Original Portfolio Denominator)",
        "",
        "| Book | Notional | Deadline | Net Cash Recovered% | Residual Inv% | Unpriced Inv% | Shortfall (bps) |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ])
    for r in p["idea_9_liquidation_deadlines"]:
        lines.append(
            f"| `{r['book']}` | `${r['notional_usdt']:,.0f}` | `{r['deadline']}` | `{r['cash_recovered_pct']:.1f}%` | `{r['residual_inventory_pct']:.1f}%` | `{r['unpriced_inventory_pct']:.1f}%` | `{r['shortfall_bps']:+.2f}` |"
        )
    i10 = p["idea_10_tmn_fx_separation"]
    lines.extend([
        "",
        "## Idea 10 — Separating Trading Skill from USDT/TMN FX Exposure",
        f"- **Overlap:** `{i10.get('start_date')}..{i10.get('end_date')}` (`{i10.get('overlap_days')}` days)",
        f"- **Hold TMN:** `0.00%` · **Buy & Hold USDT (in TMN):** `{i10.get('buy_hold_usdt_in_tmn_ret_pct')}%` · **USDT Strategy Converted Back to TMN:** `{i10.get('usdt_strategy_converted_tmn_ret_pct')}%`",
        f"- **Pure USDT Trading Alpha (FX Stripped):** `{i10.get('strategy_pure_usdt_alpha_pct')}%` · **Direct `BTCTMN` Hold:** `{i10.get('direct_btctmn_hold_ret_pct')}%`",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
