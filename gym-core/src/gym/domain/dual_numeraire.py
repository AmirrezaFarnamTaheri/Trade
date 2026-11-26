"""Corrected executable dual-numeraire accounting & return decomposition (spec §4.6)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FxQuote:
    bid: Decimal                      # TMN received per 1 USDT sold
    ask: Decimal                      # TMN paid per 1 USDT bought
    taker_fee_rate: Decimal = Decimal("0.0030")

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("FxQuote requires 0 < bid <= ask")


def tmn_to_executable_usdt(tmn_amount: Decimal, fx: FxQuote) -> Decimal:
    """Convert TMN asset/liability to executable USDT using exact bid/ask side rules.

    - Positive TMN balance -> divide by USDTTMN.ask (buying USDT costs ask + fee).
    - Negative TMN liability -> divide by USDTTMN.bid (covering TMN debt by selling USDT receives bid - fee).
    """
    if tmn_amount == 0:
        return Decimal(0)
    if tmn_amount > 0:
        return (tmn_amount / fx.ask) * (Decimal(1) - fx.taker_fee_rate)
    return (tmn_amount / fx.bid) / (Decimal(1) - fx.taker_fee_rate)


def usdt_to_executable_tmn(usdt_amount: Decimal, fx: FxQuote) -> Decimal:
    """Convert USDT asset/liability to executable TMN using exact bid/ask side rules.

    - Positive USDT balance -> multiply by USDTTMN.bid (selling USDT receives bid - fee).
    - Negative USDT liability -> multiply by USDTTMN.ask (buying USDT to cover debt costs ask + fee).
    """
    if usdt_amount == 0:
        return Decimal(0)
    if usdt_amount > 0:
        return usdt_amount * fx.bid * (Decimal(1) - fx.taker_fee_rate)
    return usdt_amount * fx.ask / (Decimal(1) - fx.taker_fee_rate)


@dataclass(frozen=True)
class DualNumeraireSnapshot:
    booked_usdt: Decimal
    booked_tmn: Decimal
    executable_liquidation_usdt: Decimal
    executable_liquidation_tmn: Decimal
    unliquidated_residual_usdt: Decimal
    incremental_operating_cost_usdt: Decimal
    net_profit_usdt: Decimal
    net_profit_tmn: Decimal


def build_dual_numeraire_snapshot(
    *,
    initial_usdt_equity: Decimal,
    initial_tmn_equity: Decimal,
    booked_usdt: Decimal,
    booked_tmn: Decimal,
    liquidation_proceeds_usdt: Decimal,
    unliquidated_residual_usdt: Decimal,
    fx: FxQuote,
    incremental_operating_cost_usdt: Decimal = Decimal(0),
) -> DualNumeraireSnapshot:
    """Report native balances, executable liquidation proceeds, residual inventory & net profit after costs."""
    exec_usdt = booked_usdt + tmn_to_executable_usdt(booked_tmn, fx) + liquidation_proceeds_usdt - incremental_operating_cost_usdt
    exec_tmn = booked_tmn + usdt_to_executable_tmn(booked_usdt + liquidation_proceeds_usdt - incremental_operating_cost_usdt, fx)
    return DualNumeraireSnapshot(
        booked_usdt=booked_usdt,
        booked_tmn=booked_tmn,
        executable_liquidation_usdt=exec_usdt,
        executable_liquidation_tmn=exec_tmn,
        unliquidated_residual_usdt=unliquidated_residual_usdt,
        incremental_operating_cost_usdt=incremental_operating_cost_usdt,
        net_profit_usdt=exec_usdt - initial_usdt_equity,
        net_profit_tmn=exec_tmn - initial_tmn_equity,
    )


@dataclass(frozen=True)
class TmnReturnDecomposition:
    r_usdt: Decimal
    r_fx: Decimal
    cross_term: Decimal
    r_tmn: Decimal


def decompose_tmn_return(r_usdt: Decimal, r_fx: Decimal) -> TmnReturnDecomposition:
    """Exact identity: R_TMN = (1 + R_USDT)(1 + R_FX) - 1 = R_USDT + R_FX + R_USDT * R_FX."""
    cross = r_usdt * r_fx
    return TmnReturnDecomposition(r_usdt=r_usdt, r_fx=r_fx, cross_term=cross, r_tmn=r_usdt + r_fx + cross)
