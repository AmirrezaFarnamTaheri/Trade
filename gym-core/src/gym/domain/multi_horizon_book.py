"""Pure domain engine for Multi-Horizon Lot-Scoped Portfolio, Online IC Calibration, and RV Pairing.

Addresses structural flaws F1 (fake leverage / slow-core cannibalization), F3 (static 60/40 budgets
and hardcoded ic_prior=0.08), and F6 (naked beta exposure on 2h breakouts in fragile regimes).
Strictly pure (zero filesystem, DB, or network IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .diffusion_and_netting import SECTOR_CLUSTERS
from .instrument_resolver import (
    InstrumentOffer,
    ResolverConfig,
    dd_governor_leverage_cap,
    liquidation_distance_bps,
    max_liquidation_safe_leverage,
)
from .strategy_sleeves import SleeveSignal
from .timeframe_panel import BarPoint
from .venue_leverage_models import NOBITEX_MARGIN_ELIGIBLE_USDT


@dataclass
class OnlineICTracker:
    """Strictly causal exponentially-weighted realized Information Coefficient (IC) tracker.

    Tracks realized alignment between prior forecasts and subsequent realized returns with Bayesian
    shrinkage toward a modest prior so dead/chop regimes shrink forecasts automatically toward 0.
    """

    prior_ic: float = 0.055
    prior_weight: float = 25.0
    decay: float = 0.96
    ic_floor: float = 0.015
    ic_cap: float = 0.14
    _sum_w: float = 0.0
    _sum_xy: float = 0.0
    _sum_x2: float = 0.0
    _sum_y2: float = 0.0

    def update(self, forecast: float, realized_return: float) -> None:
        if not (math.isfinite(forecast) and math.isfinite(realized_return)):
            return
        self._sum_w = self._sum_w * self.decay + 1.0
        self._sum_xy = self._sum_xy * self.decay + forecast * realized_return
        self._sum_x2 = self._sum_x2 * self.decay + forecast * forecast
        self._sum_y2 = self._sum_y2 * self.decay + realized_return * realized_return

    @property
    def realized_ic(self) -> float:
        denom = math.sqrt(max(0.0, self._sum_x2 * self._sum_y2))
        if denom <= 1e-12 or self._sum_w < 5.0:
            return self.prior_ic
        return max(-0.5, min(0.5, self._sum_xy / denom))

    @property
    def shrunk_ic(self) -> float:
        """Posterior IC shrunk toward prior_ic; decays toward ic_floor when recent IC collapses."""
        raw = self.realized_ic
        blend = (self._sum_w * raw + self.prior_weight * self.prior_ic) / (self._sum_w + self.prior_weight)
        return max(self.ic_floor, min(self.ic_cap, blend))


def capital_velocity_score(net_edge_bps: float, horizon_hours: float, vol_ann: float) -> float:
    """Normalize expected net return by holding-time and risk so 16h and 168h theses compete fairly."""
    if net_edge_bps <= 0.0:
        return 0.0
    h = max(2.0, horizon_hours)
    risk_h = max(0.005, vol_ann * math.sqrt(h / 8760.0))
    return (net_edge_bps / (risk_h * 10_000.0)) / math.sqrt(h / 24.0)


@dataclass
class ThesisLot:
    """One isolated thesis lot (slow_core | ignition_2h | rv_hedge) inside the multi-horizon book."""

    lot_key: tuple[str, str]  # (symbol, thesis_id)
    symbol: str
    thesis_id: str
    venue: str
    instrument_type: str  # SPOT | ISOLATED_MARGIN | PERP_FUTURE
    direction: int  # 1 or -1
    leverage: float
    collateral: float
    notional: float
    qty: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    liq_price: float
    entry_ts: datetime
    last_utc_date: str
    entry_bar_vol: float = 0.02
    entry_gru_score: float = 0.0
    peak_price: float = 0.0
    age_bars: int = 0
    pyramided: bool = False
    is_internal_spot_offset: bool = False


@dataclass
class MultiHorizonBook:
    """Exact conservation-verified portfolio holding independent slow Spot and fast Margin lots."""

    free_cash: float = 1000.0
    lots: dict[tuple[str, str], ThesisLot] = field(default_factory=dict)
    total_fees: float = 0.0
    total_borrow: float = 0.0
    total_pool_yield: float = 0.0
    liquidations: int = 0
    stop_outs: int = 0
    oco_profit_exits: int = 0
    early_ml_exits: int = 0
    pyramids: int = 0
    internal_short_offsets: int = 0
    rv_hedges_opened: int = 0
    max_leverage_used: float = 1.0

    def lot_equity(self, lot: ThesisLot, mark_px: float) -> float:
        return lot.collateral + lot.direction * lot.qty * (mark_px - lot.entry_price)

    def mark_equity(self, prices: dict[str, float]) -> float:
        pos_eq = sum(self.lot_equity(lot, prices.get(lot.symbol, lot.entry_price)) for lot in self.lots.values())
        return max(0.0, self.free_cash + pos_eq)

    def accrue_pool_and_borrow(self, ts: datetime, bar_hours: float, *, idle_pool_apr: float, eod_borrow_bps: float) -> None:
        """Accrue Nobitex EOD UTC borrow on borrowed margin notional and idle USDT pool yield on free cash."""
        cur_day = ts.date().isoformat()
        for key in list(self.lots):
            lot = self.lots[key]
            if lot.instrument_type == "SPOT" or lot.is_internal_spot_offset:
                continue
            borrowed = lot.notional if lot.direction < 0 else max(0.0, lot.notional - lot.collateral)
            if borrowed > 0.0 and cur_day != lot.last_utc_date:
                lot.last_utc_date = cur_day
                brw = borrowed * (eod_borrow_bps / 10_000.0)
                lot.collateral -= brw
                self.total_borrow += brw
                if lot.collateral <= 0.0:
                    self.liquidations += 1
                    del self.lots[key]
        if self.free_cash > 0.0 and idle_pool_apr > 0.0:
            yld = self.free_cash * idle_pool_apr * (bar_hours / 8760.0)
            self.free_cash += yld
            self.total_pool_yield += yld

    def close_lot(self, lot_key: tuple[str, str], exit_px: float, fee_bps: float) -> float:
        """Close one thesis lot at exit_px, preserving exact equity conservation."""
        lot = self.lots.pop(lot_key, None)
        if lot is None:
            return 0.0
        exit_fee = (lot.qty * exit_px) * (fee_bps / 10_000.0)
        returned = max(0.0, self.lot_equity(lot, exit_px) - exit_fee)
        self.free_cash += returned
        self.total_fees += exit_fee
        return returned

    def rebalance_slow_spot_targets(
        self,
        targets: dict[str, float],
        prices: dict[str, float],
        tradable: set[str],
        ts: datetime,
        *,
        leg_fee_bps: float,
        min_trade_usdt: float = 4.0,
    ) -> int:
        """Adjust ONLY slow_core Spot lots without ever disturbing active fast 2h margin lots."""
        equity = self.mark_equity(prices)
        if equity < 20.0:
            return 0
        fills = 0
        # 1) Sells/trims first to free cash
        for sym in sorted(set(targets) | {k[0] for k in self.lots if k[1] == "slow_core"}):
            if sym not in tradable or sym not in prices or prices[sym] <= 0:
                continue
            px = prices[sym]
            key = (sym, "slow_core")
            lot = self.lots.get(key)
            cur_val = (lot.qty * px) if lot is not None else 0.0
            tgt_val = max(0.0, targets.get(sym, 0.0)) * equity
            delta = tgt_val - cur_val
            if delta < -min_trade_usdt and lot is not None:
                if tgt_val < min_trade_usdt:
                    self.close_lot(key, px, leg_fee_bps)
                else:
                    frac_keep = max(0.0, min(1.0, tgt_val / max(1e-9, cur_val)))
                    frac_sell = 1.0 - frac_keep
                    fee = (cur_val * frac_sell) * (leg_fee_bps / 10_000.0)
                    returned = max(0.0, self.lot_equity(lot, px) * frac_sell - fee)
                    self.free_cash += returned
                    self.total_fees += fee
                    lot.qty *= frac_keep
                    lot.notional *= frac_keep
                    lot.collateral *= frac_keep
                fills += 1

        # 2) Buys/adds strictly from free_cash (never encroaching on active fast margin lots)
        for sym in sorted(targets):
            if sym not in tradable or sym not in prices or prices[sym] <= 0:
                continue
            px = prices[sym]
            key = (sym, "slow_core")
            lot = self.lots.get(key)
            cur_val = (lot.qty * px) if lot is not None else 0.0
            tgt_val = max(0.0, targets.get(sym, 0.0)) * equity
            delta = tgt_val - cur_val
            if delta <= min_trade_usdt or self.free_cash <= min_trade_usdt + 1.0:
                continue
            spend = min(delta, max(0.0, self.free_cash - 1.0))
            fee = spend * (leg_fee_bps / 10_000.0)
            if spend <= fee + 1.0:
                continue
            net_spend = spend - fee
            self.free_cash -= spend
            self.total_fees += fee
            if lot is None:
                self.lots[key] = ThesisLot(
                    lot_key=key, symbol=sym, thesis_id="slow_core", venue="nobitex",
                    instrument_type="SPOT", direction=1, leverage=1.0,
                    collateral=net_spend, notional=net_spend, qty=net_spend / px,
                    entry_price=px, stop_price=0.0, take_profit_price=0.0, liq_price=0.0,
                    entry_ts=ts, last_utc_date=ts.date().isoformat(), peak_price=px,
                )
            else:
                new_qty = lot.qty + (net_spend / px)
                lot.entry_price = ((lot.qty * lot.entry_price) + net_spend) / max(1e-12, new_qty)
                lot.qty = new_qty
                lot.collateral += net_spend
                lot.notional += net_spend
                lot.peak_price = max(lot.peak_price, px)
            fills += 1
        return fills

    def open_fast_margin_lot(
        self,
        *,
        symbol: str,
        thesis_id: str,
        direction: int,
        leverage: float,
        target_collateral: float,
        entry_px: float,
        stop_bps: float,
        take_profit_bps: float,
        offer: InstrumentOffer,
        ts: datetime,
        entry_bar_vol: float,
        entry_gru_score: float,
        allow_internal_short_offset: bool = True,
    ) -> bool:
        """Open isolated fast Margin lot; for shorts, trims existing Spot inventory first (0% borrow!)."""
        key = (symbol, thesis_id)
        if key in self.lots or entry_px <= 0.0 or target_collateral < 5.0:
            return False

        # Internal zero-borrow shorting: trim existing slow_core Spot lot before borrowing coin!
        if direction < 0 and allow_internal_short_offset:
            spot_key = (symbol, "slow_core")
            spot_lot = self.lots.get(spot_key)
            if spot_lot is not None and spot_lot.qty * entry_px >= 10.0:
                desired_notional = target_collateral * leverage
                spot_val = spot_lot.qty * entry_px
                trim_val = min(spot_val, desired_notional)
                frac_sell = trim_val / spot_val
                frac_keep = 1.0 - frac_sell
                fee = trim_val * (offer.entry_cost_bps / 10_000.0)
                self.free_cash += max(0.0, self.lot_equity(spot_lot, entry_px) * frac_sell - fee)
                self.total_fees += fee
                self.internal_short_offsets += 1
                if frac_keep <= 0.02:
                    del self.lots[spot_key]
                else:
                    spot_lot.qty *= frac_keep
                    spot_lot.notional *= frac_keep
                    spot_lot.collateral *= frac_keep
                rem_notional = desired_notional - trim_val
                if rem_notional < 15.0:
                    return True
                target_collateral = rem_notional / max(1.0, leverage)

        col = min(target_collateral, max(0.0, self.free_cash - 1.0))
        notional = col * leverage
        entry_fee = notional * (offer.entry_cost_bps / 10_000.0)
        if col <= entry_fee + 2.0 or self.free_cash < col:
            return False

        self.free_cash -= col
        self.total_fees += entry_fee
        liq_bps = liquidation_distance_bps(offer, leverage)
        if direction > 0:
            stop_px = entry_px * max(0.05, 1.0 - stop_bps / 10_000.0)
            tp_px = entry_px * (1.0 + take_profit_bps / 10_000.0) if take_profit_bps > 0 else 0.0
            liq_px = entry_px * max(0.0, 1.0 - liq_bps / 10_000.0) if leverage > 1.0 else 0.0
        else:
            stop_px = entry_px * (1.0 + stop_bps / 10_000.0)
            tp_px = entry_px * max(0.05, 1.0 - take_profit_bps / 10_000.0) if take_profit_bps > 0 else 0.0
            liq_px = entry_px * (1.0 + liq_bps / 10_000.0)

        self.lots[key] = ThesisLot(
            lot_key=key, symbol=symbol, thesis_id=thesis_id, venue=offer.venue,
            instrument_type=offer.instrument_type if leverage > 1.0 or direction < 0 else "SPOT",
            direction=direction, leverage=leverage, collateral=col - entry_fee,
            notional=notional, qty=notional / entry_px, entry_price=entry_px,
            stop_price=stop_px, take_profit_price=tp_px, liq_price=liq_px,
            entry_ts=ts, last_utc_date=ts.date().isoformat(),
            entry_bar_vol=entry_bar_vol, entry_gru_score=entry_gru_score, peak_price=entry_px,
        )
        self.max_leverage_used = max(self.max_leverage_used, leverage)
        if thesis_id == "rv_hedge":
            self.rv_hedges_opened += 1
        return True

    def pyramid_lot_on_house_money(
        self,
        lot_key: tuple[str, str],
        cur_px: float,
        add_fraction: float,
        entry_fee_bps: float,
    ) -> bool:
        """Ratchet stop to breakeven+fee (zero downside on original equity) and add +add_fraction notional."""
        lot = self.lots.get(lot_key)
        if lot is None or lot.pyramided or cur_px <= 0.0:
            return False
        upnl_pct = lot.direction * (cur_px - lot.entry_price) / lot.entry_price
        if upnl_pct < 0.015:
            return False
        add_col = min(lot.collateral * add_fraction, max(0.0, self.free_cash - 1.0))
        add_notional = add_col * lot.leverage
        fee = add_notional * (entry_fee_bps / 10_000.0)
        if add_col <= fee + 2.0 or self.free_cash < add_col:
            return False

        self.free_cash -= add_col
        self.total_fees += fee
        new_qty = lot.qty + (add_notional / cur_px)
        # Keep exact equity conservation: old_eq + (add_col - fee) == new_col + dir * new_qty * (cur_px - new_entry)
        old_eq = self.lot_equity(lot, cur_px)
        lot.entry_price = cur_px
        lot.collateral = old_eq + (add_col - fee)
        lot.notional = new_qty * cur_px
        lot.qty = new_qty
        # Ratchet stop to lock breakeven cushion against the newly blended entry
        if lot.direction > 0:
            lot.stop_price = max(lot.stop_price, cur_px * (1.0 - 0.012))
        else:
            lot.stop_price = min(lot.stop_price, cur_px * (1.0 + 0.012))
        lot.pyramided = True
        self.pyramids += 1
        return True


def select_rv_laggard_hedge(
    leader_sym: str,
    day_sigs: dict[str, SleeveSignal],
    ret_24h_by_sym: dict[str, float],
    breadth: float,
    *,
    margin_eligible: frozenset[str] = NOBITEX_MARGIN_ELIGIBLE_USDT,
    breadth_ceiling: float = 0.45,
) -> tuple[str, float] | None:
    """In fragile/choppy breadth (<0.45), find the weakest cross-sectional laggard to pair-hedge a breakout."""
    if breadth >= breadth_ceiling:
        return None
    # Prefer same-sector or weakest crypto laggard with clear negative 1d trend + weak 24h momentum
    leader_sector = next((m for m in SECTOR_CLUSTERS.values() if leader_sym in m), ())
    best_sym: str | None = None
    best_score = 0.0
    for sym, sig in day_sigs.items():
        if sym == leader_sym or sym not in margin_eligible or sym in {"XAUTUSDT", "PAXGUSDT", "SLVONUSDT"}:
            continue
        if sig.s1_trend is None or sig.s1_trend > -0.25:
            continue
        r24 = ret_24h_by_sym.get(sym, 0.0)
        if r24 > 0.005:
            continue
        sector_bonus = 0.15 if sym in leader_sector else 0.0
        weakness = abs(sig.s1_trend) + min(0.5, abs(min(0.0, r24)) * 5.0) + sector_bonus
        if weakness > best_score:
            best_score = weakness
            best_sym = sym
    if best_sym is None or best_score < 0.40:
        return None
    return best_sym, best_score


def resolve_safe_ignition_leverage(
    offer: InstrumentOffer,
    stop_bps: float,
    conformal_rank: float,
    current_dd_pct: float,
    cfg: ResolverConfig,
) -> float:
    """Resolve moment-specific leverage (1x..5x) respecting tight-stop survival + DD governor + conviction."""
    dd_cap = dd_governor_leverage_cap(current_dd_pct, cfg)
    if conformal_rank >= 0.85 and stop_bps <= 550.0:
        conv_cap = min(cfg.max_venue_leverage, dd_cap)
    elif conformal_rank >= 0.67:
        conv_cap = min(2.5, dd_cap)
    elif conformal_rank >= 0.45:
        conv_cap = min(1.5, dd_cap)
    else:
        conv_cap = 1.0
    return max(1.0, max_liquidation_safe_leverage(offer, stop_bps, cfg, conv_cap))


def check_lot_intrabar_exit(
    lot: ThesisLot,
    bar: BarPoint,
    *,
    taker_exit_bps: float,
    oco_maker_exit_bps: float,
    use_oco_maker_tp: bool,
) -> tuple[str | None, float, float]:
    """Evaluate exact intra-bar high/low liquidation, hard stop, and resting OCO maker profit target."""
    if lot.direction > 0:
        if lot.liq_price > 0.0 and bar.low <= lot.liq_price:
            return "LIQ", lot.liq_price, 0.0
        if lot.stop_price > 0.0 and bar.low <= lot.stop_price:
            px = min(bar.open, lot.stop_price) if bar.open < lot.stop_price else lot.stop_price
            return "STOP", px, taker_exit_bps + 8.0
        if use_oco_maker_tp and lot.take_profit_price > 0.0 and bar.high >= lot.take_profit_price:
            px = max(bar.open, lot.take_profit_price) if bar.open > lot.take_profit_price else lot.take_profit_price
            return "OCO_TP", px, oco_maker_exit_bps
    else:
        if lot.liq_price > 0.0 and bar.high >= lot.liq_price:
            return "LIQ", lot.liq_price, 0.0
        if lot.stop_price > 0.0 and bar.high >= lot.stop_price:
            px = max(bar.open, lot.stop_price) if bar.open > lot.stop_price else lot.stop_price
            return "STOP", px, taker_exit_bps + 8.0
        if use_oco_maker_tp and lot.take_profit_price > 0.0 and bar.low <= lot.take_profit_price:
            px = min(bar.open, lot.take_profit_price) if bar.open < lot.take_profit_price else lot.take_profit_price
            return "OCO_TP", px, oco_maker_exit_bps
    return None, 0.0, 0.0
