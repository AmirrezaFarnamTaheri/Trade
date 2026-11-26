"""Gap taxonomy, leave-one-coin-out FX factor & traded-leg Kalman basis filter (spec §6.1)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median

from .model import BookTop

DUAL_QUOTED_COINS = ("BTC", "ETH", "SOL", "XRP", "XAUT", "PEPE")


def classify_gap(
    dt_seconds: float,
    *,
    shard_connected: bool,
    scheduled_closure: bool = False,
    structural_break: bool = False,
) -> str:
    """Explicit gap taxonomy separating quiet books, venue closures, collector outages & halts."""
    if structural_break:
        return "STRUCTURAL_BREAK"
    if not shard_connected:
        return "CAPTURE_OUTAGE"
    if scheduled_closure:
        return "SCHEDULED_CLOSURE"
    return "ROUTINE_QUIET"


def irregular_decay_alpha(dt_seconds: float, decay_lambda: float) -> float:
    """Continuous-time irregular exponential decay factor: 1 - exp(-lambda * dt)."""
    if dt_seconds <= 0 or decay_lambda <= 0:
        return 0.0
    return 1.0 - math.exp(-decay_lambda * dt_seconds)


@dataclass(frozen=True)
class PeerFxInterval:
    coin: str
    low: Decimal
    high: Decimal
    center: Decimal
    skew_s: float


@dataclass(frozen=True)
class LeaveOneOutFxEstimate:
    target_coin: str
    fx_center: Decimal | None
    peer_count: int
    peers: tuple[PeerFxInterval, ...]
    status: str                           # "OK" | "INSUFFICIENT_PEERS"


def leave_one_out_fx_interval(
    target_coin: str,
    quotes_by_symbol: dict[str, BookTop],
    as_of: datetime,
    *,
    tmn_fee: Decimal = Decimal("0.0025"),
    usdt_fee: Decimal = Decimal("0.0010"),
    max_skew_seconds: float = 5.0,
    min_peers: int = 4,
    universe: tuple[str, ...] = DUAL_QUOTED_COINS,
) -> LeaveOneOutFxEstimate:
    """Compute trimmed-median leave-one-coin-out executable implied-FX reference across dual-quoted pairs."""
    target = target_coin.upper()
    peers: list[PeerFxInterval] = []
    for coin in universe:
        if coin == target:
            continue
        q_tmn = quotes_by_symbol.get(f"{coin}TMN")
        q_usdt = quotes_by_symbol.get(f"{coin}USDT")
        if q_tmn is None or q_usdt is None:
            continue
        if not (q_tmn.bid and q_tmn.ask and q_usdt.bid and q_usdt.ask):
            continue
        if q_tmn.bid <= 0 or q_tmn.ask <= 0 or q_usdt.bid <= 0 or q_usdt.ask <= 0:
            continue
        age_tmn = abs((as_of - q_tmn.ts_avail).total_seconds())
        age_usdt = abs((as_of - q_usdt.ts_avail).total_seconds())
        leg_skew = abs((q_tmn.ts_avail - q_usdt.ts_avail).total_seconds())
        skew = max(age_tmn, age_usdt, leg_skew)
        if skew > max_skew_seconds:
            continue
        low = (q_tmn.bid * (Decimal(1) - tmn_fee)) / (q_usdt.ask * (Decimal(1) + usdt_fee))
        high = (q_tmn.ask * (Decimal(1) + tmn_fee)) / (q_usdt.bid * (Decimal(1) - usdt_fee))
        center = (low + high) / Decimal(2)
        peers.append(PeerFxInterval(coin, low, high, center, skew))

    if len(peers) < min_peers:
        return LeaveOneOutFxEstimate(target, None, len(peers), tuple(peers), "INSUFFICIENT_PEERS")

    centers = sorted(p.center for p in peers)
    # Trimmed median: drop outermost pair when >= 5 peers
    trimmed = centers[1:-1] if len(centers) >= 5 else centers
    fx_center = Decimal(str(median(trimmed)))
    return LeaveOneOutFxEstimate(target, fx_center, len(peers), tuple(peers), "OK")


@dataclass(frozen=True)
class KalmanBasisOutput:
    basis_bps: float
    local_level_bps: float
    residual_bps: float
    z_score: float
    forecast_usdt_leg: float              # [-20, +20]: + when Coin/TMN is rich -> Coin/USDT is cheap
    forecast_tmn_leg: float               # [-20, +20]: - when Coin/TMN is rich -> avoid/sell Coin/TMN
    gap_kind: str


class KalmanBasisFilter:
    """2-state local-level + transient-residual Kalman filter with irregular-time decay & traded-leg sign."""

    def __init__(
        self,
        *,
        level_process_var_per_s: float = 0.02,
        obs_var_bps2: float = 25.0,
        z_entry: float = 1.5,
        usdt_convergence_beta: float = 0.65,
        tmn_convergence_beta: float = 0.35,
        round_trip_usdt_maker_bps: float = 20.0,
        round_trip_tmn_maker_bps: float = 50.0,
    ) -> None:
        self.q_per_s = level_process_var_per_s
        self.r_var = obs_var_bps2
        self.z_entry = z_entry
        self.beta_usdt = usdt_convergence_beta
        self.beta_tmn = tmn_convergence_beta
        self.cost_usdt = round_trip_usdt_maker_bps
        self.cost_tmn = round_trip_tmn_maker_bps
        self._level = 0.0
        self._var = 100.0
        self._last_ts: datetime | None = None
        self._initialized = False

    def update(
        self,
        *,
        as_of: datetime,
        coin_tmn_mid: Decimal,
        coin_usdt_mid: Decimal,
        peer_fx_center: Decimal,
        shard_connected: bool = True,
        scheduled_closure: bool = False,
        structural_break: bool = False,
    ) -> KalmanBasisOutput:
        dt_s = 0.0 if self._last_ts is None else max(0.0, (as_of - self._last_ts).total_seconds())
        gap_kind = classify_gap(
            dt_s,
            shard_connected=shard_connected,
            scheduled_closure=scheduled_closure,
            structural_break=structural_break,
        )
        y_bps = (math.log(float(coin_tmn_mid / coin_usdt_mid)) - math.log(float(peer_fx_center))) * 10000.0

        if structural_break or not self._initialized:
            self._level = y_bps
            self._var = self.r_var
            self._last_ts = as_of
            self._initialized = True
            return KalmanBasisOutput(y_bps, self._level, 0.0, 0.0, 0.0, 0.0, gap_kind)

        # Predict step: inflate variance smoothly over irregular dt_s (bounded so outages don't explode)
        p_pred = self._var + self.q_per_s * min(dt_s, 3600.0)
        innov = y_bps - self._level
        s_var = p_pred + self.r_var
        z_score = innov / math.sqrt(max(s_var, 1e-9))

        if gap_kind != "CAPTURE_OUTAGE":
            k_gain = p_pred / s_var
            self._level = self._level + k_gain * innov
            self._var = (1.0 - k_gain) * p_pred
        else:
            self._var = p_pred
        self._last_ts = as_of

        # Traded-leg sign convention (spec §6.1):
        # +y / +z => Coin/TMN is RICH relative to Coin/USDT => BUY Coin/USDT (+), SELL/skip Coin/TMN (-)
        f_usdt = 0.0
        f_tmn = 0.0
        if abs(z_score) > self.z_entry:
            exp_conv_usdt = self.beta_usdt * abs(innov)
            if exp_conv_usdt > self.cost_usdt:
                scale = min(20.0, (abs(z_score) - self.z_entry) * 8.0)
                f_usdt = scale if z_score > 0 else -scale
            exp_conv_tmn = self.beta_tmn * abs(innov)
            if exp_conv_tmn > self.cost_tmn:
                scale = min(20.0, (abs(z_score) - self.z_entry) * 8.0)
                f_tmn = -scale if z_score > 0 else scale

        return KalmanBasisOutput(y_bps, self._level, innov, z_score, f_usdt, f_tmn, gap_kind)
