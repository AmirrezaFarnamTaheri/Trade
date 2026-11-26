"""Pure domain quantitative v3.1 risk, microstructure, and fragility gates (zero I/O).

Implements the verified orthogonal Iranian-microstructure and statistical fragility upgrades:
  - compute_ofi_toxicity: trailing signed-volume order-flow imbalance (OFI/VPIN proxy)
  - pre_trade_implementation_shortfall_gate: net expected edge >= k * total execution costs
  - compute_leave_k_out_fragility: automated Leave-K-Out (K=1..max_k) episode-deletion curve
  - compute_local_fx_basis_stress: log local TMN/USDT vs global USDT basis dislocation
  - compute_pool_crowding_veto: Nobitex USDT pool APR & Wallex margin-ratio short-squeeze veto
"""
from __future__ import annotations

import math
from statistics import mean, stdev


def compute_ofi_toxicity(trades: list[tuple[str, float]]) -> tuple[float, float]:
    """Compute signed-volume imbalance in [-1, +1] and unsigned toxicity ratio |OFI| in [0, 1].

    Each item in `trades` is `(aggressor, qty)` where aggressor is 'BUY' or 'SELL'.
    """
    buy_vol = 0.0
    sell_vol = 0.0
    for side, qty in trades:
        if not math.isfinite(qty) or qty <= 0.0:
            continue
        s = side.upper()
        if s == "BUY":
            buy_vol += qty
        elif s == "SELL":
            sell_vol += qty
    total = buy_vol + sell_vol
    if total <= 0.0:
        return 0.0, 0.0
    ofi = (buy_vol - sell_vol) / total
    return round(ofi, 6), round(abs(ofi), 6)


def pre_trade_implementation_shortfall_gate(
    expected_edge_bps: float,
    *,
    spread_bps: float,
    l2_walk_bps: float = 0.0,
    fee_bps: float = 16.0,
    adverse_selection_bps: float = 0.0,
    borrow_bps: float = 0.0,
    margin_multiple: float = 1.5,
) -> tuple[bool, float, float]:
    """Admit trade only when expected gross edge clears margin_multiple * all-in execution cost."""
    total_cost = max(0.0, spread_bps) + max(0.0, l2_walk_bps) + max(0.0, fee_bps) + max(0.0, adverse_selection_bps) + max(0.0, borrow_bps)
    hurdle = max(1.0, margin_multiple) * total_cost
    net_edge = expected_edge_bps - total_cost
    return (expected_edge_bps >= hurdle), round(net_edge, 4), round(hurdle, 4)


def compute_leave_k_out_fragility(
    episode_returns_bps: list[float],
    *,
    max_k: int = 5,
) -> list[dict]:
    """Drop the top K winning episodes (K=0..max_k) and report remaining mean, sum, and per-episode Sharpe."""
    cleaned = [float(x) for x in episode_returns_bps if math.isfinite(x)]
    ranked = sorted(cleaned, reverse=True)
    out: list[dict] = []
    for k in range(min(max_k, len(ranked)) + 1):
        rem = ranked[k:]
        if not rem:
            out.append({"k_removed": k, "remaining": 0, "sum_bps": 0.0, "mean_bps": 0.0, "ep_sharpe": 0.0})
            continue
        m = mean(rem)
        sd = stdev(rem) if len(rem) >= 2 else 0.0
        sh = (m / sd) if sd > 1e-9 else 0.0
        out.append({
            "k_removed": k,
            "remaining": len(rem),
            "sum_bps": round(sum(rem), 2),
            "mean_bps": round(m, 2),
            "ep_sharpe": round(sh, 4),
        })
    return out


def compute_local_fx_basis_stress(
    local_tmn_px: float,
    usdt_tmn_px: float,
    global_usdt_px: float,
) -> float | None:
    """Compute log basis ln((local_tmn_px / usdt_tmn_px) / global_usdt_px) in bps."""
    if any(not math.isfinite(v) or v <= 0.0 for v in (local_tmn_px, usdt_tmn_px, global_usdt_px)):
        return None
    implied_usdt = local_tmn_px / usdt_tmn_px
    return round(math.log(implied_usdt / global_usdt_px) * 10_000.0, 2)


def compute_pool_crowding_veto(
    pool_apr_pct: float | None,
    margin_ratio: float | None,
    *,
    max_apr_pct: float = 35.0,
    max_margin_ratio: float = 0.85,
) -> tuple[bool, list[str]]:
    """Return (veto_active, reasons) when Nobitex pool APR or Wallex margin ratio signals short-squeeze crowding."""
    reasons: list[str] = []
    if pool_apr_pct is not None and math.isfinite(pool_apr_pct) and pool_apr_pct >= max_apr_pct:
        reasons.append(f"pool_apr_high:{pool_apr_pct:.1f}%")
    if margin_ratio is not None and math.isfinite(margin_ratio) and margin_ratio >= max_margin_ratio:
        reasons.append(f"margin_ratio_high:{margin_ratio:.2f}")
    return bool(reasons), reasons
