"""Follow-on attribution study: S2 retention band + fast sleeves S3/S4 with +1h UTC offset sensitivity."""
from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.fast_sleeves import compute_fast_sleeves_s3_s4
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket

FAST_COHORT = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT")


def _replay_fast_sleeve(
    panel_6h: dict[str, list[BarPoint]],
    sleeve: str,
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    slot_weight: float = 0.25,
) -> dict:
    """Self-financing next-bar-open replay of S3 or S4 on 6h resampled bars."""
    sig_by_sym = {s: {sig.as_of: sig for sig in compute_fast_sleeves_s3_s4(bars)} for s, bars in panel_6h.items()}
    start_by_sym = {s: {b.ts_start: b for b in bars} for s, bars in panel_6h.items()}
    avail_by_sym = {s: {b.ts_avail: b for b in bars} for s, bars in panel_6h.items()}
    all_ts = sorted({t for d in sig_by_sym.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    nav_by_day: dict[str, float] = {}
    entries = 0

    for t_avail in all_ts:
        prices: dict[str, Decimal] = dict(last_mark)
        tradable: set[str] = set()
        targets: dict[str, float] = {}

        for sym in FAST_COHORT:
            nxt = start_by_sym[sym].get(t_avail)
            cur = avail_by_sym[sym].get(t_avail)
            if nxt is not None and nxt.open > 0:
                px = Decimal(str(nxt.open))
                prices[sym] = px
                last_mark[sym] = px
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                px = Decimal(str(cur.close))
                prices[sym] = px
                last_mark[sym] = px

        for sym in FAST_COHORT:
            sig = sig_by_sym[sym].get(t_avail)
            if sig is None:
                continue
            act = sig.s3_action if sleeve == "S3" else sig.s4_action
            if act == "ENTER_LONG":
                targets[sym] = slot_weight
                entries += 1
            elif act == "HOLD":
                held = ledger.units.get(sym, Decimal(0))
                px = prices.get(sym, Decimal(0))
                nav = ledger.mark_nav(prices) if prices else Decimal("1000")
                targets[sym] = float((held * px) / nav) if (held > 0 and px > 0 and nav > 0) else 0.0
            else:
                targets[sym] = 0.0

        if not prices:
            continue
        ledger.rebalance_to_targets(t_avail, targets, prices, tradable_symbols=tradable)
        nav_by_day[t_avail.date().isoformat()] = float(ledger.mark_nav(prices))

    dates = sorted(nav_by_day)
    if len(dates) < 5:
        return {"days": len(dates), "entries": entries, "ending_nav": 1000.0, "ret_pct": 0.0, "ann_sharpe": 0.0, "max_dd_pct": 0.0}
    navs = [nav_by_day[d] for d in dates]
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / len(rets)
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    return {
        "days": len(dates),
        "entries": entries,
        "fills": len(ledger.fills),
        "ending_nav": round(navs[-1], 2),
        "ret_pct": round((navs[-1] / navs[0] - 1.0) * 100.0, 2),
        "ann_sharpe": round(sr, 3),
        "max_dd_pct": round(max_dd * 100.0, 2),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
    }


def run_fast_sleeve_attribution(db_path: Path) -> dict:
    """Evaluate S3 (Panic Reversion) and S4 (Vol Breakout) at 0h and +1h UTC offsets on Wallex & Nobitex fees."""
    con = open_readonly_market_db(db_path)
    try:
        hourly = {s: load_keyed_candles(con, s, "1h", limit=20000) for s in FAST_COHORT}
    finally:
        con.close()

    panel_off0 = {s: resample_hourly_to_bucket(bars, 6, offset_hours=0) for s, bars in hourly.items()}
    panel_off1 = {s: resample_hourly_to_bucket(bars, 6, offset_hours=1) for s, bars in hourly.items()}

    return {
        "schema": "fast-sleeve-attribution/1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "cohort": list(FAST_COHORT),
        "s3_wallex_offset_0h": _replay_fast_sleeve(panel_off0, "S3", fee_rate=Decimal("0.0013")),
        "s3_wallex_offset_1h": _replay_fast_sleeve(panel_off1, "S3", fee_rate=Decimal("0.0013")),
        "s3_nobitex_cf_offset_0h": _replay_fast_sleeve(panel_off0, "S3", fee_rate=Decimal("0.00091")),
        "s4_wallex_offset_0h": _replay_fast_sleeve(panel_off0, "S4", fee_rate=Decimal("0.0013")),
        "s4_wallex_offset_1h": _replay_fast_sleeve(panel_off1, "S4", fee_rate=Decimal("0.0013")),
        "s4_nobitex_cf_offset_0h": _replay_fast_sleeve(panel_off0, "S4", fee_rate=Decimal("0.00091")),
    }
