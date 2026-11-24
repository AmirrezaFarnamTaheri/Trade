"""Sprint 0 / Experiment 0 empirical feasibility & execution-economics harness (spec §7.1).

Runs read-only against data/live/market.db and outputs a reproducible decision packet:
1. 40-market coverage matrix (two-sided quote uptime, L2 depth presence, print/aggressor counts).
2. Constrained hindsight DP ceiling on BTCUSDT + 6 dual-quoted TMN/USDT triangles + USDTTMN.
3. Fixed-size, fixed-offset passive maker replay vs immediate taker vs cash across
   optimistic / deduplicated / adversarial_lower_bound print modes with forced flat unwind.
4. Execution-timing overlay (IMMEDIATE vs FIXED_PASSIVE vs OPPORTUNISTIC_RECOVERY) on real windows.
5. Leave-one-coin-out 6-triangle FX factor & Kalman basis summary.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.domain.execution_schedule import compare_execution_timing_arms
from gym.domain.kalman_models import (
    DUAL_QUOTED_COINS,
    KalmanBasisFilter,
    leave_one_out_fx_interval,
)
from gym.domain.model import BookTop, TradeTick, dec, parse_ts
from gym.domain.passive_execution import (
    DUPLICATE_MODES,
    PassiveOrderSpec,
    simulate_passive_orders,
)
from gym.domain.quote_hazard import hindsight_dp_ceiling
from gym.domain.tca_markout import FillRecord, compute_fill_markouts
from gym.domain.venue_contracts import wallex_l1_fee_schedule

CORE_TRIANGLE_SYMBOLS = (
    "BTCUSDT", "BTCTMN",
    "ETHUSDT", "ETHTMN",
    "SOLUSDT", "SOLTMN",
    "XRPUSDT", "XRPTMN",
    "XAUTUSDT", "XAUTTMN",
    "PEPEUSDT", "PEPETMN",
    "USDTTMN",
)


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)


def _load_symbol_window(
    con: sqlite3.Connection,
    symbol: str,
    since_iso: str,
    *,
    max_books: int = 8000,
    max_trades: int = 12000,
) -> tuple[list[BookTop], list[TradeTick]]:
    row = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return [], []
    inst_id = row[0]
    b_rows = con.execute(
        "SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags, depth "
        "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? "
        "ORDER BY ts_avail DESC LIMIT ?",
        (inst_id, since_iso, max_books),
    ).fetchall()
    b_rows.reverse()
    books: list[BookTop] = []
    for ts_a, bid, ask, bq, aq, flags_raw, depth_raw in b_rows:
        depth = json.loads(depth_raw) if depth_raw else None
        flags = frozenset(f.strip() for f in str(flags_raw).split(",") if f.strip()) if flags_raw else frozenset()
        books.append(
            BookTop(
                symbol=symbol,
                ts_avail=parse_ts(ts_a),
                bid=dec(bid) if bid is not None else None,
                ask=dec(ask) if ask is not None else None,
                bid_qty=dec(bq) if bq is not None else None,
                ask_qty=dec(aq) if aq is not None else None,
                flags=flags,
                depth=depth,
            )
        )

    t_rows = con.execute(
        "SELECT ts_event, ts_avail, price, qty, aggressor "
        "FROM trades WHERE instrument_id = ? AND ts_avail >= ? "
        "ORDER BY ts_avail DESC LIMIT ?",
        (inst_id, since_iso, max_trades),
    ).fetchall()
    t_rows.reverse()
    trades: list[TradeTick] = []
    for ts_e, ts_a, px, qty, agg in t_rows:
        if px is None or qty is None:
            continue
        trades.append(
            TradeTick(
                symbol=symbol,
                ts_event=parse_ts(ts_e),
                ts_avail=parse_ts(ts_a),
                price=dec(px),
                qty=dec(qty),
                aggressor=str(agg),
            )
        )
    return books, trades


def _coverage_matrix(con: sqlite3.Connection, since_iso: str) -> list[dict]:
    rows = con.execute(
        "SELECT i.symbol, "
        "COUNT(b.ts_avail) AS n_books, "
        "SUM(CASE WHEN b.bid IS NOT NULL AND b.ask IS NOT NULL THEN 1 ELSE 0 END) AS two_sided, "
        "SUM(CASE WHEN b.depth IS NOT NULL THEN 1 ELSE 0 END) AS with_depth "
        "FROM instruments i LEFT JOIN book_top b ON b.instrument_id = i.instrument_id AND b.ts_avail >= ? "
        "GROUP BY i.symbol HAVING n_books > 0 ORDER BY n_books DESC LIMIT 40",
        (since_iso,),
    ).fetchall()
    trade_counts = dict(
        con.execute(
            "SELECT i.symbol, COUNT(t.ts_avail) FROM instruments i "
            "JOIN trades t ON t.instrument_id = i.instrument_id AND t.ts_avail >= ? GROUP BY i.symbol",
            (since_iso,),
        ).fetchall()
    )
    out = []
    for sym, n_b, two_s, w_d in rows:
        out.append(
            {
                "symbol": sym,
                "book_rows": int(n_b),
                "two_sided_pct": round((two_s / n_b) * 100.0, 2) if n_b else 0.0,
                "depth_rows": int(w_d or 0),
                "trade_rows": int(trade_counts.get(sym, 0)),
            }
        )
    return out


def _passive_experiment_0(
    symbol: str,
    books: list[BookTop],
    trades: list[TradeTick],
    *,
    lot_notional_usdt: Decimal = Decimal("100"),
    offset_bps: Decimal = Decimal("0"),
    window_s: float = 300.0,
    max_attempts: int = 30,
) -> dict[str, dict]:
    """Run fixed-size, fixed-offset passive BUY + compulsory deadline flat unwind across all 3 print modes."""
    sched = wallex_l1_fee_schedule("USDT" if symbol.endswith("USDT") else "TMN")
    valid = [b for b in books if b.bid is not None and b.ask is not None and b.bid > 0 and b.ask > 0]
    if len(valid) < 10:
        return {}
    step = max(1, (len(valid) - 2) // max_attempts)
    entry_tops = valid[::step][:max_attempts]

    out: dict[str, dict] = {}
    for mode in DUPLICATE_MODES:
        specs: list[PassiveOrderSpec] = []
        entry_mids: dict[str, Decimal] = {}
        for idx, top in enumerate(entry_tops):
            assert top.bid is not None and top.ask is not None
            mid = (top.bid + top.ask) / Decimal(2)
            qty = (lot_notional_usdt / mid).quantize(Decimal("0.000001"))
            if qty <= 0:
                continue
            lim = top.bid * (Decimal(1) - offset_bps / Decimal(10000))
            oid = f"{symbol}-{idx}"
            specs.append(PassiveOrderSpec(oid, symbol, "BUY", qty, lim, top.ts_avail, post_only=True, max_wait_s=window_s))
            entry_mids[oid] = mid

        results = simulate_passive_orders(specs, valid, trades, sched, duplicate_print_mode=mode)
        intended_notional = Decimal(0)
        filled_notional = Decimal(0)
        ambig_notional = Decimal(0)
        total_fees_quote = Decimal(0)
        exit_proceeds = Decimal(0)
        residual_inv = Decimal(0)
        net_usdt = Decimal(0)
        fill_records: list[FillRecord] = []

        for spec, res in zip(specs, results, strict=True):
            mid0 = entry_mids[spec.order_id]
            intended_notional += spec.qty * mid0
            if res.filled_qty <= 0 or res.avg_fill_price is None:
                continue
            filled_notional += res.filled_qty * res.avg_fill_price
            ambig_notional += res.ambiguous_filled_qty * res.avg_fill_price
            entry_fee_q = res.total_fee_quote + res.total_fee_base * res.avg_fill_price
            total_fees_quote += entry_fee_q
            # Compulsory flat unwind at deadline (or last available quote)
            unwind_top = next((b for b in reversed(valid) if b.ts_avail <= res.completed_at + timedelta(seconds=window_s)), valid[-1])
            assert unwind_top.bid is not None
            net_base = res.filled_qty - res.total_fee_base
            _, taker_rate = sched.effective_rates(unwind_top.ts_avail)
            avail_bid_q = unwind_top.bid_qty or Decimal(0)
            sold_base = min(net_base, avail_bid_q) if avail_bid_q > 0 else Decimal(0)
            rem_base = net_base - sold_base
            exit_gross = sold_base * unwind_top.bid
            exit_fee_q = exit_gross * taker_rate
            total_fees_quote += exit_fee_q
            proceeds = exit_gross - exit_fee_q
            exit_proceeds += proceeds
            residual_inv += rem_base * unwind_top.bid
            cost_basis = res.filled_qty * res.avg_fill_price
            net_usdt += proceeds + rem_base * unwind_top.bid - cost_basis

            for fl in res.fills:
                fill_records.append(
                    FillRecord(
                        symbol=symbol,
                        side="BUY",
                        ts_fill=fl.ts_fill,
                        fill_price=fl.price,
                        qty=fl.qty,
                        decision_mid=mid0,
                        arrival_mid=mid0,
                        fee_quote_equiv=fl.fee_amount * fl.price if fl.fee_asset == "BASE" else fl.fee_amount,
                    )
                )

        mk_rep = compute_fill_markouts(fill_records, {symbol: valid}, horizons_s=(300,))
        ambig_share = float(ambig_notional / filled_notional) if filled_notional > 0 else 0.0
        out[mode] = {
            "attempts": len(specs),
            "intended_notional": round(float(intended_notional), 2),
            "filled_notional": round(float(filled_notional), 2),
            "ambiguous_fill_share": round(ambig_share, 4),
            "total_fees": round(float(total_fees_quote), 4),
            "markout_5m_coverage": round(mk_rep.coverage_by_horizon.get(300, 0.0), 4),
            "deadline_residual": round(float(residual_inv), 4),
            "conservative_exit_proceeds": round(float(exit_proceeds), 2),
            "net_incremental": round(float(net_usdt), 4),
        }
    return out


def run_experiment_0(db_path: Path, report_path: Path, *, lookback_hours: int = 72) -> dict:
    con = _open_ro(db_path)
    try:
        latest_row = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()
        latest_ts = parse_ts(latest_row[0]) if latest_row and latest_row[0] else datetime.now(UTC)
        since_iso = (latest_ts - timedelta(hours=lookback_hours)).isoformat().replace("+00:00", "Z")

        coverage = _coverage_matrix(con, since_iso)
        books_map: dict[str, list[BookTop]] = {}
        trades_map: dict[str, list[TradeTick]] = {}
        ceilings: list[dict] = []
        passive_rows: dict[str, dict] = {}
        overlay_rows: list[dict] = []

        for sym in CORE_TRIANGLE_SYMBOLS:
            b, t = _load_symbol_window(con, sym, since_iso)
            books_map[sym] = b
            trades_map[sym] = t
            if not b:
                continue
            quote = "USDT" if sym.endswith("USDT") else "TMN"
            sched = wallex_l1_fee_schedule(quote)
            init_cash = Decimal("1000") if quote == "USDT" else Decimal("100000000")
            c_res = hindsight_dp_ceiling(b, initial_cash_quote=init_cash, fee_schedule=sched)
            ceilings.append(
                {
                    "symbol": sym,
                    "quote": quote,
                    "quotes": c_res.evaluated_quotes,
                    "trades": c_res.trade_count,
                    "ceiling_bps": round(float(c_res.net_return_bps), 2),
                    "beats_hurdle": c_res.beats_cash_hurdle,
                }
            )
            if quote == "USDT":
                passive_rows[sym] = _passive_experiment_0(sym, b, t)
                valid = [x for x in b if x.bid and x.ask]
                if len(valid) >= 30:
                    spreads = sorted(float(x.spread_bps) for x in valid if x.spread_bps is not None)
                    p35 = Decimal(str(round(spreads[int(0.35 * len(spreads))], 2))) if spreads else Decimal("15")
                    mid_idx = len(valid) // 2
                    t0 = valid[mid_idx].ts_avail
                    qty = (Decimal("250") / ((valid[mid_idx].bid + valid[mid_idx].ask) / Decimal(2))).quantize(Decimal("0.000001"))
                    comp = compare_execution_timing_arms(sym, "BUY", qty, t0, 300.0, valid, t, sched, p35_spread_bps=p35)
                    overlay_rows.append(
                        {
                            "symbol": sym,
                            "p35_spread_bps": float(p35),
                            "immediate_cost_bps": round(float(comp.immediate.total_cost_bps), 2),
                            "fixed_passive_cost_bps": round(float(comp.fixed_passive.total_cost_bps), 2),
                            "opportunistic_cost_bps": round(float(comp.opportunistic_recovery.total_cost_bps), 2),
                            "overlay_savings_bps": round(float(comp.immediate.total_cost_bps - comp.opportunistic_recovery.total_cost_bps), 2),
                        }
                    )

        # Leave-one-coin-out 6-triangle FX basis check at latest aligned snapshot
        latest_quotes = {sym: rows[-1] for sym, rows in books_map.items() if rows}
        fx_basis_rows = []
        for coin in DUAL_QUOTED_COINS:
            est = leave_one_out_fx_interval(coin, latest_quotes, latest_ts, max_skew_seconds=120.0)
            kf_z = None
            basis_bps = None
            q_tmn = latest_quotes.get(f"{coin}TMN")
            q_usdt = latest_quotes.get(f"{coin}USDT")
            if est.fx_center is not None and q_tmn and q_usdt and q_tmn.bid and q_tmn.ask and q_usdt.bid and q_usdt.ask:
                kf = KalmanBasisFilter()
                out = kf.update(
                    as_of=latest_ts,
                    coin_tmn_mid=(q_tmn.bid + q_tmn.ask) / Decimal(2),
                    coin_usdt_mid=(q_usdt.bid + q_usdt.ask) / Decimal(2),
                    peer_fx_center=est.fx_center,
                )
                basis_bps = round(out.basis_bps, 2)
                kf_z = round(out.z_score, 2)
            fx_basis_rows.append(
                {
                    "coin": coin,
                    "status": est.status,
                    "peers": est.peer_count,
                    "peer_fx_center": str(est.fx_center.quantize(Decimal("0.01"))) if est.fx_center else None,
                    "basis_bps": basis_bps,
                    "kf_z": kf_z,
                }
            )
    finally:
        con.close()

    summary = {
        "latest_ts": latest_ts.isoformat(),
        "lookback_hours": lookback_hours,
        "coverage_count": len(coverage),
        "ceilings": ceilings,
        "passive_rows": passive_rows,
        "overlay_rows": overlay_rows,
        "fx_basis_rows": fx_basis_rows,
    }
    _write_markdown_report(report_path, summary, coverage)
    return summary


def _write_markdown_report(report_path: Path, summary: dict, coverage: list[dict]) -> None:
    lines = [
        "# Sprint 0 / Experiment 0 Empirical Feasibility Report",
        "",
        f"**Data cutoff (UTC):** `{summary['latest_ts']}` · **Lookback:** `{summary['lookback_hours']}h` · **Source:** `data/live/market.db` (read-only)",
        "",
        "## 1. Constrained Hindsight DP Ceiling (Exact Wallex L1 Received-Asset Fees)",
        "",
        "| Symbol | Quote | Quotes Evaluated | Optimal Trades | Hindsight Ceiling (bps) | Beats Cash Hurdle |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for r in summary["ceilings"]:
        lines.append(f"| `{r['symbol']}` | {r['quote']} | {r['quotes']} | {r['trades']} | {r['ceiling_bps']} | `{r['beats_hurdle']}` |")

    lines += [
        "",
        "## 2. Passive Maker Replay vs. Forced Deadline Unwind (3 Print Modes)",
        "",
        "| Symbol | Mode | Intended ($) | Filled ($) | Ambig. Share | Fees ($) | 5m Markout Cov. | Residual ($) | Net Incr. ($) | Verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for sym, modes in summary["passive_rows"].items():
        for mode, m in modes.items():
            verdict = "PASS_ADVERSARIAL" if (mode == "adversarial_lower_bound" and m["net_incremental"] > 0) else ("RETIRE" if mode == "adversarial_lower_bound" else "DIAGNOSTIC")
            lines.append(
                f"| `{sym}` | `{mode}` | {m['intended_notional']} | {m['filled_notional']} | {m['ambiguous_fill_share']} | {m['total_fees']} | {m['markout_5m_coverage']} | {m['deadline_residual']} | {m['net_incremental']} | **{verdict}** |"
            )

    lines += [
        "",
        "## 3. Execution-Timing Overlay (`IMMEDIATE` vs `FIXED_PASSIVE` vs `OPPORTUNISTIC_RECOVERY`)",
        "",
        "| Symbol | p35 Spread (bps) | Immediate Cost (bps) | Fixed Passive (bps) | Opportunistic (bps) | Overlay Savings (bps) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in summary["overlay_rows"]:
        lines.append(
            f"| `{r['symbol']}` | {r['p35_spread_bps']} | {r['immediate_cost_bps']} | {r['fixed_passive_cost_bps']} | {r['opportunistic_cost_bps']} | {r['overlay_savings_bps']} |"
        )

    lines += [
        "",
        "## 4. Leave-One-Coin-Out 6-Triangle FX Factor Snapshot",
        "",
        "| Coin | Status | Fresh Peers | Peer FX Center (TMN/USDT) | Basis vs Peer FX (bps) |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for r in summary["fx_basis_rows"]:
        lines.append(f"| `{r['coin']}` | `{r['status']}` | {r['peers']} | {r['peer_fx_center']} | {r['basis_bps']} |")

    lines += [
        "",
        f"## 5. Top Active Markets Coverage Matrix (`{len(coverage)}` symbols observed)",
        "",
        "| Symbol | Book Rows | Two-Sided (%) | L2 Depth5 Rows | Trade Prints |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for c in coverage[:20]:
        lines.append(f"| `{c['symbol']}` | {c['book_rows']} | {c['two_sided_pct']}% | {c['depth_rows']} | {c['trade_rows']} |")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Sprint 0 / Experiment 0 on read-only market.db")
    parser.add_argument("--db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("D:/Github/Trade/evidence/2026-11-24-experiment-0-report.md"))
    parser.add_argument("--hours", type=int, default=72)
    args = parser.parse_args()
    summary = run_experiment_0(args.db, args.report, lookback_hours=args.hours)
    print(f"Wrote {args.report} (cutoff={summary['latest_ts']}, ceilings={len(summary['ceilings'])}, overlays={len(summary['overlay_rows'])})")


if __name__ == "__main__":
    main()
