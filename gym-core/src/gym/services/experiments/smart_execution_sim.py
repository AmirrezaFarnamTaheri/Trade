"""Side-asymmetric smart execution simulator comparing Wallex taker, Nobitex taker, smart taker router, and asymmetric passive-BUY / taker-SELL routing."""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from ...adapters.candle_reader import open_readonly_market_db
from ...adapters.nobitex import nobitex_fee_schedule
from ...domain.model import dec, parse_ts
from ...domain.venue_contracts import wallex_l1_fee_schedule


def _parse_levels(depth_raw: str | None, bid: float, ask: float, bq: float, aq: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if depth_raw:
        try:
            d = json.loads(depth_raw)
            if isinstance(d, list) and len(d) == 2 and d[0] and d[1]:
                bids = [(float(p), float(q)) for p, q in d[0] if float(p) > 0 and float(q) > 0]
                asks = [(float(p), float(q)) for p, q in d[1] if float(p) > 0 and float(q) > 0]
                if bids and asks:
                    return bids, asks
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return ([(bid, max(bq, 1e-9))], [(ask, max(aq, 1e-9))])


def walk_orderbook_vwap(levels: list[tuple[float, float]], notional_quote: float) -> tuple[float, float]:
    """Walk displayed depth levels to fill notional_quote. Returns (vwap_price, fill_fraction)."""
    if not levels or notional_quote <= 0:
        return 0.0, 0.0
    rem = notional_quote
    spent = 0.0
    qty_total = 0.0
    for px, qty in levels:
        lvl_val = px * qty
        take_val = min(rem, lvl_val)
        take_qty = take_val / px
        spent += take_val
        qty_total += take_qty
        rem -= take_val
        if rem <= 1e-9:
            break
    if qty_total <= 0:
        return levels[0][0], 0.0
    return spent / qty_total, min(1.0, spent / notional_quote)


def _taker_cost_bps(levels: list[tuple[float, float]], mid: float, side: str, notional: float, fee_bps: float) -> tuple[float, float]:
    """Compute walked all-in slippage + fee in bps vs common mid. Unfilled residual gets 25 bps penalty."""
    vwap, fill_frac = walk_orderbook_vwap(levels, notional)
    if mid <= 0 or vwap <= 0:
        return fee_bps + 50.0, 0.0
    slip = ((vwap - mid) / mid * 10000.0) if side == "BUY" else ((mid - vwap) / mid * 10000.0)
    unfilled_pen = (1.0 - fill_frac) * 25.0
    return slip + fee_bps + unfilled_pen, fill_frac


def _evaluate_symbol_orders(
    matched: list[dict],
    *,
    symbol: str,
    notional: float,
    w_maker_bps: float,
    w_taker_bps: float,
    n_maker_bps: float,
    n_taker_bps: float,
    passive_horizon_s: float = 300.0,
) -> dict:
    """Evaluate all 4 execution policies over matched live Wallex+Nobitex snapshots for one symbol."""
    stats: dict[str, dict[str, list[float]]] = {
        side: {k: [] for k in ("wlx_taker", "nbx_taker", "smart_taker", "asym_router", "wlx_fill", "nbx_fill", "passive_filled")}
        for side in ("BUY", "SELL")
    }
    nbx_win_count = {"BUY": 0, "SELL": 0}
    epochs = [m["epoch"] for m in matched]

    for idx, m in enumerate(matched):
        common_mid = 0.5 * (m["w_mid"] + m["n_mid"])
        # BUY side
        wb_c, wb_f = _taker_cost_bps(m["w_asks"], common_mid, "BUY", notional, w_taker_bps)
        nb_c, nb_f = _taker_cost_bps(m["n_asks"], common_mid, "BUY", notional, n_taker_bps)
        sb_c = min(wb_c, nb_c)
        if nb_c <= wb_c:
            nbx_win_count["BUY"] += 1

        # Passive BUY limit: post at Nobitex best bid; check causal future Nobitex snapshots within horizon.
        post_px = m["n_bids"][0][0]
        filled_passive = False
        had_later_snapshot = False
        fallback_idx = idx
        j = idx + 1
        while j < len(matched) and epochs[j] - epochs[idx] <= passive_horizon_s:
            had_later_snapshot = True
            fallback_idx = j
            if matched[j]["n_asks"][0][0] <= post_px:
                filled_passive = True
                break
            j += 1

        stats["BUY"]["wlx_taker"].append(wb_c)
        stats["BUY"]["nbx_taker"].append(nb_c)
        stats["BUY"]["smart_taker"].append(sb_c)
        stats["BUY"]["wlx_fill"].append(wb_f * 100.0)
        stats["BUY"]["nbx_fill"].append(nb_f * 100.0)
        if had_later_snapshot:
            if filled_passive:
                asym_buy = ((post_px - common_mid) / common_mid * 10000.0) + n_maker_bps
            else:
                fm = matched[fallback_idx]
                fw_c, _ = _taker_cost_bps(fm["w_asks"], common_mid, "BUY", notional, w_taker_bps)
                fn_c, _ = _taker_cost_bps(fm["n_asks"], common_mid, "BUY", notional, n_taker_bps)
                asym_buy = min(fw_c, fn_c)
            stats["BUY"]["asym_router"].append(asym_buy)
            stats["BUY"]["passive_filled"].append(100.0 if filled_passive else 0.0)

        # SELL side: immediate smart taker sweep (avoids passive SELL adverse selection)
        ws_c, ws_f = _taker_cost_bps(m["w_bids"], common_mid, "SELL", notional, w_taker_bps)
        ns_c, ns_f = _taker_cost_bps(m["n_bids"], common_mid, "SELL", notional, n_taker_bps)
        ss_c = min(ws_c, ns_c)
        if ns_c <= ws_c:
            nbx_win_count["SELL"] += 1

        stats["SELL"]["wlx_taker"].append(ws_c)
        stats["SELL"]["nbx_taker"].append(ns_c)
        stats["SELL"]["smart_taker"].append(ss_c)
        stats["SELL"]["asym_router"].append(ss_c)
        stats["SELL"]["wlx_fill"].append(ws_f * 100.0)
        stats["SELL"]["nbx_fill"].append(ns_f * 100.0)
        stats["SELL"]["passive_filled"].append(0.0)

    n = len(matched)
    passive_covered = len(stats["BUY"]["passive_filled"])
    out = {
        "symbol": symbol,
        "notional_quote": notional,
        "samples": n,
        "passive_covered_samples": passive_covered,
        "passive_uncovered_deadlines": n - passive_covered,
    }
    for side in ("BUY", "SELL"):
        s = stats[side]
        asym_med = median(s["asym_router"]) if s["asym_router"] else median(s["smart_taker"])
        out[side.lower()] = {
            "wallex_taker_bps": round(median(s["wlx_taker"]), 2),
            "nobitex_taker_bps": round(median(s["nbx_taker"]), 2),
            "smart_taker_bps": round(median(s["smart_taker"]), 2),
            "asym_router_bps": round(asym_med, 2),
            "saving_smart_vs_wallex_bps": round(median(s["wlx_taker"]) - median(s["smart_taker"]), 2),
            "saving_asym_vs_wallex_bps": round(median(s["wlx_taker"]) - asym_med, 2),
            "nobitex_cheaper_pct": round(nbx_win_count[side] / max(1, n) * 100.0, 1),
            "wallex_depth_fill_pct": round(mean(s["wlx_fill"]), 1),
            "nobitex_depth_fill_pct": round(mean(s["nbx_fill"]), 1),
            "passive_buy_fill_pct": round(mean(s["passive_filled"]), 1) if s["passive_filled"] else 0.0,
        }
    return out


def run_smart_execution_simulation(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
    *,
    notional_usdt: float = 250.0,
    max_skew_s: float = 15.0,
) -> dict:
    """Compare Wallex taker, Nobitex taker, Smart Taker Router, and Side-Asymmetric Router on live matched books."""
    if not wallex_db.exists() or not multi_venue_db.exists():
        return {"status": "MISSING_DB", "rows": []}

    now = datetime.now(UTC)
    w_usdt_m, w_usdt_t = wallex_l1_fee_schedule("USDT").effective_rates(now)
    n_usdt_m, n_usdt_t = nobitex_fee_schedule("USDT", permanent_discount=Decimal("0.30")).effective_rates(now)

    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    rows: list[dict] = []
    try:
        nbx_raw = mcon.execute(
            "SELECT symbol, ts_avail, bid, ask, bid_qty, ask_qty, depth_json "
            "FROM venue_quotes WHERE venue = 'nobitex' AND symbol LIKE '%USDT' ORDER BY ts_avail ASC"
        ).fetchall()
        by_sym: dict[str, list] = {}
        for rec in nbx_raw:
            by_sym.setdefault(rec[0], []).append(rec)

        for sym, n_list in sorted(by_sym.items()):
            inst = wcon.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if inst is None:
                continue
            min_ts = (parse_ts(n_list[0][1]) - timedelta(seconds=max_skew_s)).isoformat().replace("+00:00", "Z")
            w_raw = wcon.execute(
                "SELECT ts_avail, bid, ask, bid_qty, ask_qty, depth "
                "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? "
                "AND bid IS NOT NULL AND ask IS NOT NULL ORDER BY ts_avail ASC",
                (inst[0], min_ts),
            ).fetchall()
            if not w_raw:
                continue
            w_epochs = [parse_ts(r[0]).timestamp() for r in w_raw]
            matched: list[dict] = []
            for _, ts_s, nb, na, nbq, naq, ndepth in n_list:
                t_ep = parse_ts(ts_s).timestamp()
                # Strictly causal pairing: latest Wallex quote observable at or before t_ep.
                cand = bisect_right(w_epochs, t_ep) - 1
                if cand < 0 or (t_ep - w_epochs[cand]) > max_skew_s:
                    continue
                best_i = cand
                _, wb_s, wa_s, wbq_s, waq_s, wdepth = w_raw[best_i]
                wb, wa = float(dec(wb_s)), float(dec(wa_s))
                nb_f, na_f = float(dec(nb)), float(dec(na))
                w_bids, w_asks = _parse_levels(wdepth, wb, wa, float(dec(wbq_s or "0")), float(dec(waq_s or "0")))
                n_bids, n_asks = _parse_levels(ndepth, nb_f, na_f, float(dec(nbq or "0")), float(dec(naq or "0")))
                matched.append({
                    "epoch": t_ep,
                    "w_mid": 0.5 * (wb + wa),
                    "n_mid": 0.5 * (nb_f + na_f),
                    "w_bids": w_bids,
                    "w_asks": w_asks,
                    "n_bids": n_bids,
                    "n_asks": n_asks,
                })
            if len(matched) < 5:
                continue
            rows.append(
                _evaluate_symbol_orders(
                    matched,
                    symbol=sym,
                    notional=notional_usdt,
                    w_maker_bps=float(w_usdt_m * Decimal(10000)),
                    w_taker_bps=float(w_usdt_t * Decimal(10000)),
                    n_maker_bps=float(n_usdt_m * Decimal(10000)),
                    n_taker_bps=float(n_usdt_t * Decimal(10000)),
                )
            )
    finally:
        wcon.close()
        mcon.close()

    payload = {
        "generated_at": now.isoformat(),
        "notional_usdt": notional_usdt,
        "max_skew_s": max_skew_s,
        "rows": rows,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Side-Asymmetric Smart Execution Audit (Walked L2 Depth + Live Passive BUY Fill Check)",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        f"- **Order Size Evaluated:** `${p['notional_usdt']:.0f}` USDT per leg (walking up to 5 displayed book levels)",
        "- **Policy:** `SIDE_ASYMMETRIC_ROUTER` posts passive limit `BUY` at Nobitex best bid (300s causal live-book fill check, fallback to `SMART_TAKER_ROUTER`), and sweeps immediately on `SELL` via `SMART_TAKER_ROUTER`.",
        "",
        "| Symbol | Samples | Side | Wallex Taker (bps) | Nobitex Taker (bps) | Smart Taker (bps) | Asym Router (bps) | Saving vs Wallex | Nobitex Cheaper% | WLX/NBX 5L Fill% | Passive BUY Fill% |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for r in p["rows"]:
        for side in ("buy", "sell"):
            s = r[side]
            lines.append(
                f"| `{r['symbol']}` | `{r['samples']}` | `{side.upper()}` | "
                f"`{s['wallex_taker_bps']:+.2f}` | `{s['nobitex_taker_bps']:+.2f}` | "
                f"`{s['smart_taker_bps']:+.2f}` | `{s['asym_router_bps']:+.2f}` | "
                f"`{s['saving_asym_vs_wallex_bps']:+.2f} bps` | `{s['nobitex_cheaper_pct']:.1f}%` | "
                f"`{s['wallex_depth_fill_pct']:.0f}% / {s['nobitex_depth_fill_pct']:.0f}%` | "
                f"`{s['passive_buy_fill_pct']:.1f}%` |"
            )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
