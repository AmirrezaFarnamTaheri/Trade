"""Pure domain model for the Calm Daily S1 + 2nd-Order Acceleration Bear-Majors Short Sleeve.

Symmetric mirror of the 1d Slow Long Core (S1 trend + 2nd-order acceleration + inverse-vol risk parity)
applied strictly to liquid Nobitex isolated-margin majors during confirmed macro bear regimes.
Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .instrument_resolver import liquidation_distance_bps
from .multi_horizon_book import MultiHorizonBook
from .optimal_exits import trim_lot_fraction

BEAR_MAJORS_4: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
BEAR_MAJORS_6: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT")


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


def rebalance_slow_short_lots(
    book: MultiHorizonBook,
    targets: dict[str, float],
    prices: dict[str, float],
    tradable: set[str],
    offers_by_sym: dict,
    ts: datetime,
    *,
    cfg: BearMajorsConfig,
    thesis_id: str = "slow_bear_short",
    min_trade_usdt: float = 6.0,
) -> int:
    """Rebalance calm isolated-margin short lots inside MultiHorizonBook with exact equity conservation."""
    equity = book.mark_equity(prices)
    if equity < 20.0:
        return 0
    fills = 0
    fee_bps = cfg.leg_fee_bps
    held_syms = {k[0] for k in book.lots if k[1] == thesis_id}

    # 1) Cover / trim reduced shorts first so collateral returns to free_cash before opening/adding
    for sym in sorted(held_syms | set(targets)):
        if sym not in tradable or sym not in prices or prices[sym] <= 0.0:
            continue
        px = prices[sym]
        key = (sym, thesis_id)
        lot = book.lots.get(key)
        tgt_notional = max(0.0, -targets.get(sym, 0.0)) * equity
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
        tgt_notional = max(0.0, -targets.get(sym, 0.0)) * equity
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
        max_lev = max(offer.allowed_leverages) if offer.allowed_leverages else 1.0
        lev = max(1.0, min(cfg.margin_leverage, max_lev))
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
            liq_bps = liquidation_distance_bps(offer, lev)
            lot.liq_price = px * (1.0 + liq_bps / 10_000.0)
            fills += 1
    return fills
