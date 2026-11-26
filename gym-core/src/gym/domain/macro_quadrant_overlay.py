"""Pure domain models for the 4-Quadrant Macro Bidirectional Overlay (Crypto Majors + Levered Gold XAUT)
and 20-window decorrelated multi-regime target scoring.

Implements:
- Causal 4h ATR-Supertrend direction detector for agreement/disagreement defense.
- 4-Quadrant Macro Bidirectional CTA Vol-Targeted target generator (Reflation, Risk-On,
  Flight-to-Safety, Synchronized Liquidity Crunch) on liquid Nobitex 5x isolated-margin majors & XAUT.
- Exact-conservation bidirectional margin lot rebalancer inside MultiHorizonBook with liquidation-safe
  dynamic leverage stepping (stop strictly inside liquidation distance).
- Exact 5-criteria 7-day window target scorer (C1 >=3% 1d, C2 >=2% x2d, C3 >=1% x3d, C4 >=8% 3d, C5 >=18% 7d).
Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .bear_majors_sleeve import BEAR_MAJORS_4
from .instrument_resolver import liquidation_distance_bps
from .multi_horizon_book import MultiHorizonBook
from .optimal_exits import trim_lot_fraction
from .timeframe_panel import BarPoint


@dataclass(frozen=True)
class MacroQuadrantConfig:
    """Configuration for 4-Quadrant Bidirectional Crypto Majors + Levered Gold (XAUT) overlay."""

    label: str = "MACRO_4QUAD_BALANCED"
    crypto_symbols: tuple[str, ...] = BEAR_MAJORS_4
    gold_symbol: str = "XAUTUSDT"
    bull_breadth_min: float = 0.50
    bull_assist_breadth_min: float = 0.35
    bear_breadth_max: float = 0.32
    crypto_vol_target: float = 0.85
    gold_long_vol_target: float = 0.45
    gold_short_vol_target: float = 0.30
    max_crypto_gross: float = 2.40
    max_gold_long_gross: float = 2.50
    max_gold_short_gross: float = 1.50
    use_4h_agreement_gate: bool = False
    disagree_retain_frac: float = 0.35
    margin_leverage: float = 3.0
    stop_bps: float = 1150.0
    rebal_band: float = 0.12
    leg_fee_bps: float = 16.0
    max_single_weight: float = 2.50
    overlay_scale: float = 1.00


def compute_4h_supertrend_direction(
    bars_4h: list[BarPoint],
    *,
    atr_window: int = 10,
    atr_mult: float = 2.6,
) -> dict[datetime, int]:
    """Compute strictly causal 4h ATR-Supertrend regime direction (+1 bullish, -1 bearish)."""
    if len(bars_4h) <= atr_window + 2:
        return {}
    cs = [b.close for b in bars_4h]
    trs = [0.0] + [
        max(bars_4h[i].high - bars_4h[i].low, abs(bars_4h[i].high - cs[i - 1]), abs(bars_4h[i].low - cs[i - 1]))
        for i in range(1, len(bars_4h))
    ]
    out: dict[datetime, int] = {}
    cdir = 1
    ub_prev, lb_prev = 1e18, 0.0
    for i, b in enumerate(bars_4h):
        if i < atr_window + 2:
            continue
        atr = sum(trs[i - atr_window + 1 : i + 1]) / float(atr_window)
        mid = 0.5 * (b.high + b.low)
        ub, lb = mid + atr_mult * atr, mid - atr_mult * atr
        ub_prev = min(ub, ub_prev) if (i > atr_window + 2 and cs[i - 1] <= ub_prev) else ub
        lb_prev = max(lb, lb_prev) if (i > atr_window + 2 and cs[i - 1] >= lb_prev) else lb
        if cdir == 1 and b.close < lb_prev:
            cdir = -1
        elif cdir == -1 and b.close > ub_prev:
            cdir = 1
        out[b.ts_avail] = cdir
    return out


def compute_macro_quadrant_targets(
    day_sigs: dict,
    day_accel: dict[str, float],
    daily_breadth: float,
    ann_vol_now: dict[str, float],
    st_dir_4h_now: dict[str, int],
    cfg: MacroQuadrantConfig,
) -> dict[str, float]:
    """Compute signed target notional weights across all 4 Crypto x Gold macro quadrants."""
    out: dict[str, float] = {}
    avg_c_vol = sum(ann_vol_now.get(s, 0.60) for s in cfg.crypto_symbols) / max(1, len(cfg.crypto_symbols))
    btc_st = st_dir_4h_now.get("BTCUSDT", 0)

    # 1) Crypto Majors Directional Leg (Bull Long vs Bear Short)
    if daily_breadth >= cfg.bull_breadth_min or (daily_breadth >= cfg.bull_assist_breadth_min and btc_st > 0):
        raw = {
            s: abs(float(day_sigs[s].s1_trend)) / max(0.015, float(day_sigs[s].yang_zhang_vol))
            for s in cfg.crypto_symbols
            if s in day_sigs and day_sigs[s].s1_trend is not None and day_sigs[s].s1_trend > 0.15
        }
        if raw:
            tier = 1.15 if daily_breadth >= 0.75 else 0.85
            gross = max(0.50, min(cfg.max_crypto_gross, (cfg.crypto_vol_target * tier) / max(0.25, avg_c_vol)))
            tot = sum(raw.values())
            for sym, val in raw.items():
                mult = 1.0 if (not cfg.use_4h_agreement_gate or st_dir_4h_now.get(sym, 1) > 0) else cfg.disagree_retain_frac
                out[sym] = min(cfg.max_single_weight, gross * (val / tot) * mult * cfg.overlay_scale)
    elif daily_breadth <= cfg.bear_breadth_max:
        raw = {
            s: abs(float(day_sigs[s].s1_trend)) / max(0.015, float(day_sigs[s].yang_zhang_vol))
            for s in cfg.crypto_symbols
            if (
                s in day_sigs
                and day_sigs[s].s1_trend is not None
                and day_sigs[s].s1_trend < -0.22
                and (day_accel.get(s, 0.0) or 0.0) <= 0.12
            )
        }
        if raw:
            tier = 1.15 if daily_breadth <= 0.05 else 0.76
            gross = max(0.45, min(cfg.max_crypto_gross, (cfg.crypto_vol_target * tier) / max(0.25, avg_c_vol)))
            denom = max(1.0, min(3.0, float(len(cfg.crypto_symbols))))
            eff_gross = gross * min(1.0, len(raw) / denom)
            tot = sum(raw.values())
            for sym, val in raw.items():
                mult = 1.0 if (not cfg.use_4h_agreement_gate or st_dir_4h_now.get(sym, -1) < 0) else cfg.disagree_retain_frac
                out[sym] = -min(cfg.max_single_weight, eff_gross * (val / tot) * mult * cfg.overlay_scale)

    # 2) Orthogonal Gold (XAUTUSDT) Bidirectional Levered Leg (Long in Q1/Q3, Short in Q2/Q4)
    if cfg.gold_symbol:
        gsig = day_sigs.get(cfg.gold_symbol)
        g_s1 = float(gsig.s1_trend) if (gsig is not None and gsig.s1_trend is not None) else 0.0
        g_ac = float(day_accel.get(cfg.gold_symbol, 0.0) or 0.0)
        g_vol = max(0.10, ann_vol_now.get(cfg.gold_symbol, 0.18))
        g_st = st_dir_4h_now.get(cfg.gold_symbol, 0)
        if g_s1 >= 0.20 and g_ac >= -0.12:
            xg = max(0.50, min(cfg.max_gold_long_gross, cfg.gold_long_vol_target / g_vol))
            mult = 1.0 if (not cfg.use_4h_agreement_gate or g_st > 0) else cfg.disagree_retain_frac
            out[cfg.gold_symbol] = min(cfg.max_single_weight, xg * mult * cfg.overlay_scale)
        elif g_s1 <= -0.25 and g_ac <= 0.10:
            xg = max(0.40, min(cfg.max_gold_short_gross, cfg.gold_short_vol_target / g_vol))
            mult = 1.0 if (not cfg.use_4h_agreement_gate or g_st < 0) else cfg.disagree_retain_frac
            out[cfg.gold_symbol] = -min(cfg.max_single_weight, xg * mult * cfg.overlay_scale)

    return out


def _safe_margin_leverage(offer, requested_lev: float, stop_bps: float) -> float:
    max_l = max(offer.allowed_leverages) if offer.allowed_leverages else 1.0
    lev = max(1.0, min(requested_lev, max_l))
    while lev > 1.0 and liquidation_distance_bps(offer, lev) < stop_bps * 1.30:
        lev = max(1.0, round(lev - 0.5, 1))
    return lev


def rebalance_bidirectional_margin_lots(
    book: MultiHorizonBook,
    targets: dict[str, float],
    prices: dict[str, float],
    tradable: set[str],
    offers_by_sym: dict,
    ts: datetime,
    *,
    cfg: MacroQuadrantConfig,
    thesis_id: str = "macro_4quad",
    min_trade_usdt: float = 8.0,
) -> int:
    """Rebalance signed Long/Short isolated-margin overlay lots inside MultiHorizonBook with exact conservation."""
    equity = book.mark_equity(prices)
    if equity < 25.0:
        return 0
    fills = 0
    fee_bps = cfg.leg_fee_bps
    held = {k[0] for k in book.lots if k[1] == thesis_id}

    # 1) Close flipped / exited / reduced lots first to free collateral cleanly
    for sym in sorted(held | set(targets)):
        if sym not in tradable or sym not in prices or prices[sym] <= 0.0:
            continue
        px = prices[sym]
        key = (sym, thesis_id)
        lot = book.lots.get(key)
        if lot is None:
            continue
        tw = max(-cfg.max_single_weight, min(cfg.max_single_weight, targets.get(sym, 0.0)))
        cur_signed = (lot.direction * lot.qty * px) / equity
        if abs(tw) * equity < min_trade_usdt or (tw * lot.direction < 0):
            book.close_lot(key, px, fee_bps)
            fills += 1
        elif abs(tw) < abs(cur_signed) and abs(tw - cur_signed) >= cfg.rebal_band:
            frac_keep = max(0.0, min(1.0, abs(tw) / max(1e-9, abs(cur_signed))))
            trim_lot_fraction(book, key, frac_keep, px, fee_bps)
            fills += 1

    # 2) Open new or add to existing same-direction margin lots strictly from free_cash
    for sym in sorted(targets):
        if sym not in tradable or sym not in prices or prices[sym] <= 0.0:
            continue
        px = prices[sym]
        tw = max(-cfg.max_single_weight, min(cfg.max_single_weight, targets[sym]))
        tgt_notional = abs(tw) * equity
        if tgt_notional < min_trade_usdt or book.free_cash < min_trade_usdt:
            continue
        tdir = 1 if tw > 0 else -1
        key = (sym, thesis_id)
        lot = book.lots.get(key)
        matched = [
            o for o in offers_by_sym.get(sym, ())
            if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == tdir
        ]
        if not matched:
            continue
        offer = matched[0]
        lev = _safe_margin_leverage(offer, cfg.margin_leverage, cfg.stop_bps)
        if lot is None:
            col = min(tgt_notional / lev, max(0.0, book.free_cash - 2.0))
            if book.open_fast_margin_lot(
                symbol=sym, thesis_id=thesis_id, direction=tdir, leverage=lev,
                target_collateral=col, entry_px=px, stop_bps=cfg.stop_bps, take_profit_bps=0.0,
                offer=offer, ts=ts, entry_bar_vol=0.02, entry_gru_score=0.0,
                allow_internal_short_offset=False,
            ):
                fills += 1
        elif lot.direction == tdir:
            cur_notional = lot.qty * px
            add_notional = tgt_notional - cur_notional
            if add_notional / equity < cfg.rebal_band:
                continue
            add_col = min(add_notional / lev, max(0.0, book.free_cash - 2.0))
            actual_add = add_col * lev
            fee = actual_add * (fee_bps / 10_000.0)
            if add_col <= fee + 2.0 or book.free_cash < add_col:
                continue
            old_eq = book.lot_equity(lot, px)
            book.free_cash -= add_col
            book.total_fees += fee
            new_qty = lot.qty + (actual_add / px)
            lot.entry_price = px
            lot.collateral = old_eq + (add_col - fee)
            lot.notional = new_qty * px
            lot.qty = new_qty
            liq_bps = liquidation_distance_bps(offer, lev)
            if tdir > 0:
                lot.stop_price = px * max(0.05, 1.0 - cfg.stop_bps / 10_000.0)
                lot.liq_price = px * max(0.0, 1.0 - liq_bps / 10_000.0)
            else:
                lot.stop_price = px * (1.0 + cfg.stop_bps / 10_000.0)
                lot.liq_price = px * (1.0 + liq_bps / 10_000.0)
            fills += 1
    return fills


def score_7d_window_targets(
    nav_ts: dict[datetime, float],
    windows: list[dict],
    *,
    max_staleness_hours: float = 24.0,
) -> dict:
    """Evaluate exact 5 Northstar criteria across a list of 7-day windows using O(log N) causal backward lookup.

    C1: >=3% in >=1 day | C2: >=2% in >=2 days | C3: >=1% in >=3 days | C4: >=8% in >=1 3d | C5: >=18% in 7d.
    """
    from bisect import bisect_right

    if len(nav_ts) < 2 or not windows:
        return {
            "mean_7d": 0.0, "med_7d": 0.0, "pos_wins": 0, "scored_windows": 0, "unscored_windows": len(windows),
            "c1_3pct_1d": 0, "c2_2pct_2d": 0, "c3_1pct_3d": 0, "c4_8pct_3d": 0, "c5_18pct_7d": 0,
            "full_5of5_hits": 0, "per_window": [],
        }
    ts_list = sorted(nav_ts)
    max_stale_s = max_staleness_hours * 3600.0
    per_w = []
    c1_n = c2_n = c3_n = c4_n = c5_n = full_n = pos_n = unscored = 0
    rets_7d: list[float] = []
    for w in windows:
        t0 = datetime.fromisoformat(w["start"])
        pts: list[float] = []
        valid = True
        for d in range(8):
            target = t0 + timedelta(days=d)
            pos = bisect_right(ts_list, target) - 1
            if pos < 0 or (target - ts_list[pos]).total_seconds() > max_stale_s:
                valid = False
                break
            pts.append(nav_ts[ts_list[pos]])
        if not valid:
            unscored += 1
            continue
        d_rets = [((pts[d + 1] / pts[d]) - 1.0) * 100.0 if pts[d] > 0 else 0.0 for d in range(7)]
        r3_list = [((pts[d + 3] / pts[d]) - 1.0) * 100.0 if pts[d] > 0 else 0.0 for d in range(5)]
        ret_7d = ((pts[7] / pts[0]) - 1.0) * 100.0 if pts[0] > 0 else 0.0
        max_1d = max(d_rets)
        d_ge_2 = sum(1 for r in d_rets if r >= 2.0)
        d_ge_1 = sum(1 for r in d_rets if r >= 1.0)
        max_3d = max(r3_list)
        c1, c2, c3, c4, c5 = (max_1d >= 3.0), (d_ge_2 >= 2), (d_ge_1 >= 3), (max_3d >= 8.0), (ret_7d >= 18.0)
        c1_n += int(c1)
        c2_n += int(c2)
        c3_n += int(c3)
        c4_n += int(c4)
        c5_n += int(c5)
        full_n += int(c1 and c2 and c3 and c4 and c5)
        pos_n += int(ret_7d > 0.0)
        rets_7d.append(ret_7d)
        per_w.append({
            "wid": w["wid"],
            "regime": w["regime"],
            "ret_7d": round(ret_7d, 2),
            "max_1d": round(max_1d, 2),
            "d_ge_2": d_ge_2,
            "d_ge_1": d_ge_1,
            "max_3d": round(max_3d, 2),
            "criteria_met": int(c1) + int(c2) + int(c3) + int(c4) + int(c5),
            "hit_all": (c1 and c2 and c3 and c4 and c5),
        })
    return {
        "mean_7d": round(sum(rets_7d) / len(rets_7d), 2) if rets_7d else 0.0,
        "med_7d": round(median(rets_7d), 2) if rets_7d else 0.0,
        "pos_wins": pos_n,
        "scored_windows": len(rets_7d),
        "unscored_windows": unscored,
        "c1_3pct_1d": c1_n,
        "c2_2pct_2d": c2_n,
        "c3_1pct_3d": c3_n,
        "c4_8pct_3d": c4_n,
        "c5_18pct_7d": c5_n,
        "full_5of5_hits": full_n,
        "per_window": per_w,
    }
