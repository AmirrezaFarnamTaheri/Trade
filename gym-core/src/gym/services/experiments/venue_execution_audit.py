"""Matched live multi-venue execution-cost audit: Wallex vs Nobitex (-30% discount) for S1+S5 rebalances."""
from __future__ import annotations

import json
from bisect import bisect_left
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from ...adapters.candle_reader import open_readonly_market_db
from ...adapters.nobitex import nobitex_fee_schedule
from ...domain.model import dec, parse_ts
from ...domain.venue_contracts import wallex_l1_fee_schedule


def _depth_usdt_from_json(depth_raw: str | None, bid: Decimal, ask: Decimal, bq: Decimal, aq: Decimal) -> float:
    if depth_raw:
        try:
            d = json.loads(depth_raw)
            if isinstance(d, list) and len(d) == 2 and d[0] and d[1]:
                bid_val = sum((dec(p) * dec(q) for p, q in d[0]), Decimal(0))
                ask_val = sum((dec(p) * dec(q) for p, q in d[1]), Decimal(0))
                return float(min(bid_val, ask_val))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    mid = (bid + ask) / Decimal(2)
    return float(mid * min(bq, aq))


def _spread_bps(bid: Decimal, ask: Decimal) -> float:
    mid = (bid + ask) / Decimal(2)
    return float((ask - bid) / mid * Decimal(10000)) if mid > 0 else 0.0


def run_venue_execution_cost_audit(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
    *,
    max_skew_s: float = 15.0,
    annual_turnover_multiple: float = 12.4,
) -> dict:
    """Compare matched live Wallex vs Nobitex spreads, 5-level depth, and all-in rebalance costs."""
    if not wallex_db.exists() or not multi_venue_db.exists():
        return {"status": "MISSING_DB", "symbols": []}

    now = datetime.now(UTC)
    w_usdt_m, w_usdt_t = wallex_l1_fee_schedule("USDT").effective_rates(now)
    w_tmn_m, w_tmn_t = wallex_l1_fee_schedule("TMN").effective_rates(now)
    n_usdt_m, n_usdt_t = nobitex_fee_schedule("USDT", permanent_discount=Decimal("0.30")).effective_rates(now)
    n_tmn_m, n_tmn_t = nobitex_fee_schedule("TMN", permanent_discount=Decimal("0.30")).effective_rates(now)

    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    rows_out: list[dict] = []
    try:
        nbx_raw = mcon.execute(
            "SELECT symbol, ts_avail, bid, ask, bid_qty, ask_qty, depth_json "
            "FROM venue_quotes WHERE venue = 'nobitex' ORDER BY ts_avail ASC"
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
            w_spreads, n_spreads = [], []
            w_depths, n_depths = [], []
            matched_epochs = []

            for _, ts_s, nb, na, nbq, naq, ndepth in n_list:
                t_ep = parse_ts(ts_s).timestamp()
                pos = bisect_left(w_epochs, t_ep)
                best_i = None
                best_dt = max_skew_s + 1.0
                for cand in (pos - 1, pos):
                    if 0 <= cand < len(w_epochs):
                        dt = abs(w_epochs[cand] - t_ep)
                        if dt < best_dt:
                            best_dt = dt
                            best_i = cand
                if best_i is None or best_dt > max_skew_s:
                    continue
                _, wb_s, wa_s, wbq_s, waq_s, wdepth = w_raw[best_i]
                wb, wa = dec(wb_s), dec(wa_s)
                nb_d, na_d = dec(nb), dec(na)
                w_spreads.append(_spread_bps(wb, wa))
                n_spreads.append(_spread_bps(nb_d, na_d))
                w_depths.append(_depth_usdt_from_json(wdepth, wb, wa, dec(wbq_s or "0"), dec(waq_s or "0")))
                n_depths.append(_depth_usdt_from_json(ndepth, nb_d, na_d, dec(nbq or "0"), dec(naq or "0")))
                matched_epochs.append(t_ep)

            if not matched_epochs:
                continue

            is_usdt = sym.endswith("USDT")
            w_taker_bps = float((w_usdt_t if is_usdt else w_tmn_t) * Decimal(10000))
            n_taker_bps = float((n_usdt_t if is_usdt else n_tmn_t) * Decimal(10000))
            w_maker_bps = float((w_usdt_m if is_usdt else w_tmn_m) * Decimal(10000))
            n_maker_bps = float((n_usdt_m if is_usdt else n_tmn_m) * Decimal(10000))

            w_med_sp = median(w_spreads)
            n_med_sp = median(n_spreads)
            w_allin_taker = 0.5 * w_med_sp + w_taker_bps
            n_allin_taker = 0.5 * n_med_sp + n_taker_bps
            saving_oneway = w_allin_taker - n_allin_taker
            ann_drag_saving_pct = (saving_oneway / 10000.0) * annual_turnover_multiple * 100.0

            rows_out.append(
                {
                    "symbol": sym,
                    "matched_pairs": len(matched_epochs),
                    "elapsed_hours": round((max(matched_epochs) - min(matched_epochs)) / 3600.0, 2),
                    "wallex_median_spread_bps": round(w_med_sp, 2),
                    "nobitex_median_spread_bps": round(n_med_sp, 2),
                    "spread_ratio_w_over_n": round(w_med_sp / max(n_med_sp, 0.01), 2),
                    "wallex_median_depth_quote": round(median(w_depths), 2),
                    "nobitex_median_depth_quote": round(median(n_depths), 2),
                    "wallex_allin_taker_bps": round(w_allin_taker, 2),
                    "nobitex_allin_taker_bps": round(n_allin_taker, 2),
                    "oneway_taker_saving_bps": round(saving_oneway, 2),
                    "maker_fee_saving_bps": round(w_maker_bps - n_maker_bps, 2),
                    "est_annual_s1_s5_drag_saving_pct": round(ann_drag_saving_pct, 2),
                }
            )
    finally:
        wcon.close()
        mcon.close()

    summary = {
        "generated_at": now.isoformat(),
        "max_skew_s": max_skew_s,
        "annual_turnover_multiple": annual_turnover_multiple,
        "symbols": rows_out,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_report(report_path, summary)
    return summary


def _write_report(report_path: Path, summary: dict) -> None:
    lines = [
        "# Multi-Venue Execution-Cost Audit: Wallex L1 vs. Nobitex (-30% Discount)",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Timestamp Match Tolerance:** `±{summary['max_skew_s']}s`",
        f"- **Annualized Turnover Basis (`S1 + S5` Leader):** `{summary['annual_turnover_multiple']}x/yr` (`55.5x` over `4.49` years)",
        "",
        "| Symbol | Matched | Hours | Wallex Med Spread (bps) | Nobitex Med Spread (bps) | Ratio (W/N) | Wallex 5L Depth | Nobitex 5L Depth | Wallex All-In Taker (bps) | Nobitex All-In Taker (bps) | One-Way Saving (bps) | Est. Annual S1+S5 Drag Saving |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in summary["symbols"]:
        lines.append(
            f"| `{r['symbol']}` | `{r['matched_pairs']}` | `{r['elapsed_hours']:.2f}` | "
            f"`{r['wallex_median_spread_bps']:.2f}` | `{r['nobitex_median_spread_bps']:.2f}` | `{r['spread_ratio_w_over_n']:.2f}x` | "
            f"`{r['wallex_median_depth_quote']:,.0f}` | `{r['nobitex_median_depth_quote']:,.0f}` | "
            f"`{r['wallex_allin_taker_bps']:.2f}` | `{r['nobitex_allin_taker_bps']:.2f}` | "
            f"`{r['oneway_taker_saving_bps']:+.2f}` | `{r['est_annual_s1_s5_drag_saving_pct']:+.2f}%/yr` |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
