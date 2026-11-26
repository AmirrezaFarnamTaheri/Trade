"""Pure domain model for Calm Daily & CTA Volatility-Targeted Bear-Majors + Gold (XAUT) Short Sleeves.

Symmetric downside mirror of the 1d Slow Long Core (S1 trend + 2nd-order acceleration + inverse-vol risk parity)
applied strictly to liquid Nobitex isolated-margin majors (BTC, ETH, SOL, BNB) and orthogonal Gold (XAUTUSDT),
with optional institutional CTA 20d volatility targeting, 14d Kaufman Efficiency Ratio trend-persistence scaling,
and 4h fast squeeze-cut defense. Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .instrument_resolver import liquidation_distance_bps
from .multi_horizon_book import MultiHorizonBook
from .optimal_exits import trim_lot_fraction
from .timeframe_panel import BarPoint

BEAR_MAJORS_4: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
BEAR_MAJORS_6: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT")
BEAR_MAJORS_4_PLUS_GOLD: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XAUTUSDT")


@dataclass(frozen=True)
class BearMajorsConfig:
    """Configuration for calm daily bear-regime shorting on liquid isolated-margin majors."""

    label: str = "S1_BEAR_MAJORS4"
    symbols: tuple[str, ...] = BEAR_MAJORS_4
    breadth_max: float = 0.30
    s1_max: float = -0.25
    use_inv_vol: bool = True
    use_accel_vbottom_exit: bool = True
    accel_exit_max: float = 0.12
    gross_short_budget: float = 1.00
    margin_leverage: float = 2.0
    stop_bps: float = 1500.0
    rebal_band: float = 0.08
    leg_fee_bps: float = 16.0
    max_single_weight: float = 0.90


@dataclass(frozen=True)
class CtaBearVolConfig:
    """Configuration for CTA Vol-Targeted Cross-Asset Bear Short (Liquid Crypto Majors + Gold XAUT)."""

    label: str = "CTA_VOLTGT80_M4_XAUT"
    crypto_symbols: tuple[str, ...] = BEAR_MAJORS_4
    gold_symbol: str = "XAUTUSDT"
    breadth_max: float = 0.30
    deep_bear_breadth: float = 0.05
    crypto_s1_max: float = -0.25
    crypto_accel_max: float = 0.12
    gold_s1_max: float = -0.30
    gold_deep_s1: float = -0.55
    gold_accel_max: float = 0.10
    target_ann_vol: float = 0.80
    max_crypto_gross: float = 2.40
    min_crypto_gross: float = 0.40
    max_gold_gross: float = 1.10
    gold_vol_share: float = 0.32
    use_kaufman_er: bool = False
    use_4h_squeeze_guard: bool = False
    squeeze_retain_frac: float = 0.40
    margin_leverage: float = 3.0
    stop_bps: float = 1200.0
    rebal_band: float = 0.10
    leg_fee_bps: float = 16.0
    max_single_weight: float = 1.15


def compute_daily_vol_and_kaufman_er(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    vol_window: int = 20,
    er_window: int = 14,
) -> tuple[dict[str, dict[datetime, float]], dict[str, dict[datetime, float]]]:
    """Compute strictly causal 20d annualized realized volatility and 14d Kaufman Efficiency Ratio."""
    ann_vol: dict[str, dict[datetime, float]] = {}
    kaufman_er: dict[str, dict[datetime, float]] = {}
    sqrt_yr = math.sqrt(365.0)
    for sym in symbols:
        bars = panel_1d.get(sym, [])
        cs = [b.close for b in bars]
        rets = [0.0] + [(cs[i] / cs[i - 1] - 1.0) if cs[i - 1] > 0 else 0.0 for i in range(1, len(cs))]
        v_map: dict[datetime, float] = {}
        er_map: dict[datetime, float] = {}
        for i, b in enumerate(bars):
            if i >= vol_window:
                win = rets[i - vol_window + 1 : i + 1]
                mu = sum(win) / vol_window
                sd = math.sqrt(sum((r - mu) ** 2 for r in win) / max(1, vol_window - 1))
                v_map[b.ts_avail] = max(0.10, sd * sqrt_yr)
            if i >= er_window:
                net_chg = abs(cs[i] - cs[i - er_window])
                path_len = sum(abs(cs[j] - cs[j - 1]) for j in range(i - er_window + 1, i + 1))
                er_map[b.ts_avail] = net_chg / max(path_len, 1e-9)
        ann_vol[sym] = v_map
        kaufman_er[sym] = er_map
    return ann_vol, kaufman_er


def compute_calm_bear_majors_targets(
    day_sigs: dict,
    day_accel: dict[str, float],
    daily_breadth: float,
    cfg: BearMajorsConfig,
) -> dict[str, float]:
    """Compute signed negative target notional weights for calm daily bear-regime shorting on majors."""
    if daily_breadth > cfg.breadth_max or cfg.gross_short_budget <= 0.0:
        return {}
    raw: dict[str, float] = {}
    for sym in cfg.symbols:
        sig = day_sigs.get(sym)
        if sig is None or sig.s1_trend is None or sig.s1_trend > cfg.s1_max:
            continue
        if cfg.use_accel_vbottom_exit and (day_accel.get(sym, 0.0) or 0.0) > cfg.accel_exit_max:
            continue
        if cfg.use_inv_vol:
            yz = max(0.015, float(sig.yang_zhang_vol))
            raw[sym] = abs(float(sig.s1_trend)) / yz
        else:
            raw[sym] = 1.0
    if not raw:
        return {}
    tot = sum(raw.values())
    denom_scale = max(1.0, min(3.0, float(len(cfg.symbols))))
    eff_gross = cfg.gross_short_budget * min(1.0, len(raw) / denom_scale)
    return {sym: -eff_gross * (val / tot) for sym, val in raw.items()}


def compute_cta_vol_targeted_bear_targets(
    day_sigs: dict,
    day_accel: dict[str, float],
    daily_breadth: float,
    ann_vol_now: dict[str, float],
    kaufman_er_now: dict[str, float],
    cfg: CtaBearVolConfig,
    *,
    btc_4h_squeezing: bool = False,
    gold_4h_squeezing: bool = False,
) -> dict[str, float]:
    """Compute signed negative targets for CTA Vol-Targeted Crypto Majors + Orthogonal Gold (XAUT) Short."""
    out: dict[str, float] = {}

    # 1) Crypto Majors Sleeve (gated by macro crypto breadth + S1 + accel V-bottom filter)
    if daily_breadth <= cfg.breadth_max and cfg.max_crypto_gross > 0.0:
        raw: dict[str, float] = {}
        for sym in cfg.crypto_symbols:
            sig = day_sigs.get(sym)
            if sig is None or sig.s1_trend is None or sig.s1_trend > cfg.crypto_s1_max:
                continue
            if (day_accel.get(sym, 0.0) or 0.0) > cfg.crypto_accel_max:
                continue
            raw[sym] = abs(float(sig.s1_trend)) / max(0.015, float(sig.yang_zhang_vol))
        if raw:
            avg_vol = sum(ann_vol_now.get(s, 0.65) for s in cfg.crypto_symbols) / len(cfg.crypto_symbols)
            tier_m = 1.15 if daily_breadth <= cfg.deep_bear_breadth else 0.72
            er_m = 1.0
            if cfg.use_kaufman_er:
                avg_er = sum(kaufman_er_now.get(s, 0.25) for s in cfg.crypto_symbols) / len(cfg.crypto_symbols)
                er_m = 1.20 if avg_er >= 0.32 else (0.95 if avg_er >= 0.20 else 0.55)
            gross = max(cfg.min_crypto_gross, min(cfg.max_crypto_gross, (cfg.target_ann_vol * tier_m * er_m) / max(0.25, avg_vol)))
            denom = max(1.0, min(3.0, float(len(cfg.crypto_symbols))))
            eff_gross = gross * min(1.0, len(raw) / denom)
            if cfg.use_4h_squeeze_guard and btc_4h_squeezing:
                eff_gross *= cfg.squeeze_retain_frac
            tot = sum(raw.values())
            for sym, val in raw.items():
                out[sym] = -min(cfg.max_single_weight, eff_gross * (val / tot))

    # 2) Orthogonal Gold (XAUTUSDT) Macro Breakdown Short Sleeve (independent of crypto breadth!)
    if cfg.gold_symbol and cfg.max_gold_gross > 0.0:
        gsig = day_sigs.get(cfg.gold_symbol)
        gac = day_accel.get(cfg.gold_symbol, 0.0) or 0.0
        if gsig is not None and gsig.s1_trend is not None and gsig.s1_trend <= cfg.gold_s1_max and gac <= cfg.gold_accel_max:
            gvol = ann_vol_now.get(cfg.gold_symbol, 0.20)
            ger_m = 1.0
            if cfg.use_kaufman_er:
                ger = kaufman_er_now.get(cfg.gold_symbol, 0.25)
                ger_m = 1.15 if ger >= 0.30 else 0.70
            g_gross = max(0.35, min(cfg.max_gold_gross, (cfg.target_ann_vol * cfg.gold_vol_share * ger_m) / max(0.10, gvol)))
            if gsig.s1_trend > cfg.gold_deep_s1:
                g_gross *= 0.55
            if cfg.use_4h_squeeze_guard and gold_4h_squeezing:
                g_gross *= cfg.squeeze_retain_frac
            out[cfg.gold_symbol] = -min(cfg.max_single_weight, g_gross)

    return out


def _resolve_liquidation_safe_short_leverage(offer, requested_lev: float, stop_bps: float) -> float:
    """Guarantee hard stop lies strictly inside liquidation distance (>= 1.30x cushion) for zero gap liqs."""
    max_lev = max(offer.allowed_leverages) if offer.allowed_leverages else 1.0
    lev = max(1.0, min(requested_lev, max_lev))
    while lev > 1.0 and liquidation_distance_bps(offer, lev) < stop_bps * 1.30:
        lev = max(1.0, round(lev - 0.5, 1))
    return lev


def rebalance_slow_short_lots(
    book: MultiHorizonBook,
    targets: dict[str, float],
    prices: dict[str, float],
    tradable: set[str],
    offers_by_sym: dict,
    ts: datetime,
    *,
    cfg: BearMajorsConfig | CtaBearVolConfig,
    thesis_id: str = "slow_bear_short",
    min_trade_usdt: float = 6.0,
) -> int:
    """Rebalance calm/CTA isolated-margin short lots inside MultiHorizonBook with exact equity conservation."""
    equity = book.mark_equity(prices)
    if equity < 20.0:
        return 0
    fills = 0
    fee_bps = cfg.leg_fee_bps
    max_single_w = cfg.max_single_weight
    held_syms = {k[0] for k in book.lots if k[1] == thesis_id}

    # 1) Cover / trim reduced shorts first so collateral returns to free_cash before opening/adding
    for sym in sorted(held_syms | set(targets)):
        if sym not in tradable or sym not in prices or prices[sym] <= 0.0:
            continue
        px = prices[sym]
        key = (sym, thesis_id)
        lot = book.lots.get(key)
        tgt_notional = min(max_single_w, max(0.0, -targets.get(sym, 0.0))) * equity
        if lot is None:
            continue
        cur_notional = lot.qty * px
        diff_w = abs(tgt_notional - cur_notional) / equity
        if tgt_notional < min_trade_usdt:
            book.close_lot(key, px, fee_bps)
            fills += 1
        elif tgt_notional < cur_notional and diff_w >= cfg.rebal_band:
            frac_keep = max(0.0, min(1.0, tgt_notional / max(1e-9, cur_notional)))
            trim_lot_fraction(book, key, frac_keep, px, fee_bps)
            fills += 1

    # 2) Open or add shorts strictly from free_cash (never disturbing Slow Core or active 2h Ignition)
    for sym in sorted(targets):
        if sym not in tradable or sym not in prices or prices[sym] <= 0.0:
            continue
        px = prices[sym]
        tgt_notional = min(max_single_w, max(0.0, -targets.get(sym, 0.0))) * equity
        if tgt_notional < min_trade_usdt or book.free_cash < min_trade_usdt:
            continue
        key = (sym, thesis_id)
        lot = book.lots.get(key)
        matched = [
            o for o in offers_by_sym.get(sym, ())
            if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == -1
        ]
        if not matched:
            continue
        offer = matched[0]
        lev = _resolve_liquidation_safe_short_leverage(offer, cfg.margin_leverage, cfg.stop_bps)
        if lot is None:
            tgt_col = min(tgt_notional / lev, max(0.0, book.free_cash - 2.0))
            if book.open_fast_margin_lot(
                symbol=sym, thesis_id=thesis_id, direction=-1, leverage=lev,
                target_collateral=tgt_col, entry_px=px, stop_bps=cfg.stop_bps,
                take_profit_bps=0.0, offer=offer, ts=ts, entry_bar_vol=0.02,
                entry_gru_score=0.0, allow_internal_short_offset=True,
            ):
                fills += 1
        else:
            cur_notional = lot.qty * px
            add_notional = tgt_notional - cur_notional
            if add_notional / equity < cfg.rebal_band:
                continue
            add_col = min(add_notional / lev, max(0.0, book.free_cash - 2.0))
            actual_add_notional = add_col * lev
            fee = actual_add_notional * (fee_bps / 10_000.0)
            if add_col <= fee + 2.0 or book.free_cash < add_col:
                continue
            old_eq = book.lot_equity(lot, px)
            book.free_cash -= add_col
            book.total_fees += fee
            new_qty = lot.qty + (actual_add_notional / px)
            lot.entry_price = px
            lot.collateral = old_eq + (add_col - fee)
            lot.notional = new_qty * px
            lot.qty = new_qty
            lot.stop_price = px * (1.0 + cfg.stop_bps / 10_000.0)
            lot.liq_price = px * (1.0 + liquidation_distance_bps(offer, lev) / 10_000.0)
            fills += 1
    return fills
