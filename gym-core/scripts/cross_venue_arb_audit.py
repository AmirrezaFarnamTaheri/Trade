"""Wallex <-> Nobitex pre-funded capital-day arbitrage audit on matched live timestamps (spec §8.1).

Reads read-only Wallex data/live/market.db and Nobitex data/live/multi_venue_quotes.sqlite3,
matches quotes within max_skew_s, and reports gross cross-venue spreads and net repeatable
proceeds per capital-day under Nobitex -30% discount vs Wallex Level-1 fees.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.adapters.candle_reader import open_readonly_market_db
from gym.adapters.nobitex import (
    evaluate_prefunded_arb_capital_day,
    nobitex_fee_schedule,
)
from gym.domain.model import dec, parse_ts


def run_cross_venue_arb_audit(
    wallex_db: Path,
    multi_venue_db: Path,
    *,
    max_skew_s: float = 15.0,
    nobitex_discount: Decimal = Decimal("0.30"),
    replenishment_transfer_fee_usdt: Decimal = Decimal("1.0"),
) -> dict:
    if not wallex_db.exists() or not multi_venue_db.exists():
        return {"status": "MISSING_DB", "symbols": []}

    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    try:
        nbx_rows = mcon.execute(
            "SELECT symbol, ts_avail, bid, ask, bid_qty, ask_qty "
            "FROM venue_quotes WHERE venue = 'nobitex' ORDER BY ts_avail ASC"
        ).fetchall()
        if not nbx_rows:
            return {"status": "NO_NOBITEX_ROWS", "symbols": []}

        by_sym: dict[str, list[tuple[datetime, Decimal, Decimal]]] = {}
        for sym, ts_s, bid, ask, _, _ in nbx_rows:
            by_sym.setdefault(sym, []).append((parse_ts(ts_s), dec(bid), dec(ask)))

        now = datetime.now(UTC)
        _, nbx_usdt_taker = nobitex_fee_schedule("USDT", permanent_discount=nobitex_discount).effective_rates(now)
        _, nbx_tmn_taker = nobitex_fee_schedule("TMN", permanent_discount=nobitex_discount).effective_rates(now)

        summary_rows: list[dict] = []
        for sym, quotes in sorted(by_sym.items()):
            inst = wcon.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if not inst:
                continue
            inst_id = inst[0]
            min_ts = quotes[0][0].isoformat().replace("+00:00", "Z")
            w_rows = wcon.execute(
                "SELECT ts_avail, bid, ask FROM book_top "
                "WHERE instrument_id = ? AND ts_avail >= ? AND bid IS NOT NULL AND ask IS NOT NULL "
                "ORDER BY ts_avail ASC",
                (inst_id, min_ts),
            ).fetchall()
            w_parsed = [(parse_ts(t), dec(b), dec(a)) for t, b, a in w_rows]
            if not w_parsed:
                continue

            is_tmn = sym.endswith("TMN")
            nbx_fee = nbx_tmn_taker if is_tmn else nbx_usdt_taker
            wlx_fee = Decimal("0.0030") if is_tmn else Decimal("0.0013")

            matched = 0
            positive_net = 0
            max_gap_bps = Decimal("-999999")
            sum_gap_bps = Decimal("0")
            best_net_per_cap_day = Decimal("-999999")

            w_idx = 0
            for n_ts, n_bid, n_ask in quotes:
                while w_idx + 1 < len(w_parsed) and abs((w_parsed[w_idx + 1][0] - n_ts).total_seconds()) <= abs((w_parsed[w_idx][0] - n_ts).total_seconds()):
                    w_idx += 1
                w_ts, w_bid, w_ask = w_parsed[w_idx]
                if abs((w_ts - n_ts).total_seconds()) > max_skew_s:
                    continue
                matched += 1
                g1 = (w_bid - n_ask) / n_ask * Decimal(10000)
                g2 = (n_bid - w_ask) / w_ask * Decimal(10000)
                gap = max(g1, g2)
                sum_gap_bps += gap
                if gap > max_gap_bps:
                    max_gap_bps = gap

                buy_px, sell_px = (n_ask, w_bid) if g1 >= g2 else (w_ask, n_bid)
                b_fee, s_fee = (nbx_fee, wlx_fee) if g1 >= g2 else (wlx_fee, nbx_fee)
                lot_notional = Decimal("1000")
                qty = lot_notional / buy_px
                arb = evaluate_prefunded_arb_capital_day(
                    buy_venue_ask=buy_px,
                    sell_venue_bid=sell_px,
                    leg1_filled_qty=qty,
                    leg2_filled_qty=qty,
                    buy_fee_rate=b_fee,
                    sell_fee_rate=s_fee,
                    replenishment_transfer_fee_usdt=replenishment_transfer_fee_usdt if not is_tmn else Decimal("0"),
                    residual_unwind_slippage_bps=Decimal("0"),
                    total_prefunded_capital_usdt=lot_notional * Decimal("2"),
                    cycle_days=Decimal("1"),
                )
                if arb.net_proceeds_usdt > 0:
                    positive_net += 1
                if arb.net_usdt_per_capital_day > best_net_per_cap_day:
                    best_net_per_cap_day = arb.net_usdt_per_capital_day

            if matched > 0:
                summary_rows.append(
                    {
                        "symbol": sym,
                        "matched_snapshots": matched,
                        "mean_raw_gap_bps": round(float(sum_gap_bps / matched), 2),
                        "max_raw_gap_bps": round(float(max_gap_bps), 2),
                        "positive_net_count": positive_net,
                        "best_net_per_capital_day_bps": round(float(best_net_per_cap_day * Decimal(10000)), 2),
                    }
                )
    finally:
        wcon.close()
        mcon.close()

    return {"status": "OK", "generated_at": datetime.now(UTC).isoformat(), "symbols": summary_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit matched Wallex <-> Nobitex cross-venue arb opportunities")
    parser.add_argument("--wallex-db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("D:/Github/Trade/data/live/multi_venue_quotes.sqlite3"))
    args = parser.parse_args()
    res = run_cross_venue_arb_audit(args.wallex_db, args.multi_venue_db)
    print(f"Cross-venue audit status={res['status']} symbols={len(res['symbols'])}")
    for row in res["symbols"]:
        print(
            f"  {row['symbol']}: matched={row['matched_snapshots']} mean_gap={row['mean_raw_gap_bps']}bps "
            f"max_gap={row['max_raw_gap_bps']}bps pos_net={row['positive_net_count']} best_cap_day={row['best_net_per_capital_day_bps']}bps"
        )


if __name__ == "__main__":
    main()
