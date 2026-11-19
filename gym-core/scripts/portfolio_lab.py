"""Portfolio lab: strategies that see every coin at once, on every capability, priced by one simulator.

EXPLORATION ONLY: Binance daily candles before 2024-01-01 (ranking period). The 2024-2026 days are not read.

Ideas tested, each built on information a single coin's chart does not carry:
  breadth gate      trade only while most liquid coins close above their 50-day mean (cross-section)
  vol target        exposure = target volatility / realized volatility of the strategy itself, capped at 3x:
                    leverage only when calm, the opposite of constant leverage
  xs momentum       long the strongest decile on spot, short the weakest on margin, weekly: market neutral
  strategy blend    causal inverse-volatility weights across strategies' own return streams, netted into one
                    book; it pays only if the streams are not correlated, so correlations are printed

Every strategy is a signed weight matrix W[day, coin] set at the close and earning the next day's return.
Costs: turnover at the spot rate for long exposure up to 1x and at the margin rate for shorts and leverage;
the 4-hourly loan fee on borrowed notional. Liquidation uses a fresh one-day margin position at the book's
leverage as a proxy. It does not track entry collateral or accrued carry across days.

    uv run --no-sync python scripts/portfolio_lab.py [--coins N]
"""
import argparse
import json
import sys
from math import sqrt
from pathlib import Path
from statistics import pvariance

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binance_archive import liquid, spot_daily, universe  # noqa: E402
from margin_hold import ENTRY_FEE, FLOOR, LOAN_FEE, PERIOD  # noqa: E402
from signal_lab import Position  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402
from gym.domain.signals import blend  # noqa: E402

SPLIT, YEAR = "2024-01-01", 365
SPOT_COST, MARGIN_COST = 0.002, 0.001 + ENTRY_FEE  # half-spread plus fee per unit traded
BORROW_PER_DAY = LOAN_FEE * 86400 / PERIOD
EPS = 1e-9  # float noise: weights summing to 1.0000000002 are not leverage
TREND = ("tsmom", "efficiency", "obv", "donchian", "ema-cross")
DECISIONS = ("OPEN_LONG", "OPEN_SHORT", "FLIP", "RESIZE", "CLOSE", "HOLD", "LIQUIDATED", "LEVERED_DAYS", "CASH_DAYS")


def load_panel(coins):
    series = {}
    for symbol in coins:
        bars = spot_daily(symbol)
        cut = sum(d < SPLIT for d in bars["days"])
        if cut >= 120:
            series[symbol] = ({k: v[:cut] for k, v in bars.items()}, liquid(bars["volume"][:cut]))
    days = sorted({d for bars, _ in series.values() for d in bars["days"]})
    index = {d: i for i, d in enumerate(days)}
    shape = (len(days), len(series))
    panel = {k: np.full(shape, np.nan) for k in ("close", "high", "low")}
    panel["liquid"] = np.zeros(shape, bool)
    panel["trend"] = np.zeros(shape)
    for j, (bars, flags) in enumerate(series.values()):
        rows = [index[d] for d in bars["days"]]
        for k in ("close", "high", "low"):
            panel[k][rows, j] = bars[k]
        panel["liquid"][rows, j] = flags
        panel["trend"][rows, j] = [p or 0 for p in blend(bars, TREND, enter_pct=60, exit_pct=20, long_only=True)]
    panel["days"], panel["coins"] = days, list(series)
    return panel


def _breached(side, ratio, entry_close, low, high, close):
    """Check the floor for a fresh position using the same fees as the single-position lab."""
    position = Position(side, ratio, entry_close)
    position.step(low, high, close)
    return position.liquidated


def simulate(panel, weights):
    """Daily book returns after costs, plus the decision log. weights[t] is held from close t to close t+1."""
    close, high, low = panel["close"], panel["high"], panel["low"]
    w = np.nan_to_num(weights)
    returns, counts = np.zeros(len(close)), dict.fromkeys(DECISIONS, 0)
    held = np.zeros(close.shape[1])
    for t in range(len(close) - 1):
        # No-trade band: a position within 5% of its target is left as it drifted; a zero target always closes.
        target = np.where((w[t] != 0) & (np.abs(w[t] - held) <= 0.05 * np.abs(w[t])), held, w[t])
        banded_longs = target.clip(min=0).sum()
        if w[t].clip(min=0).sum() <= 1 + EPS < banded_longs:  # kept drift must not lever an unlevered book
            target = np.where(target > 0, target / banded_longs, target)
        gross = np.abs(target).sum()
        longs = target.clip(min=0).sum()
        delta = np.abs(target - held)
        spot_part = min(longs, 1.0) / longs if longs > EPS else 1.0
        cost = (delta * np.where(target > 0, spot_part * SPOT_COST + (1 - spot_part) * MARGIN_COST, MARGIN_COST)).sum()
        borrowed = max(longs - 1 - EPS, 0.0) + (-target.clip(max=0)).sum()
        move = np.nan_to_num(close[t + 1] / close[t] - 1)
        levered = gross > 1 + EPS
        ratio = gross if levered else 1.0
        burst = np.array([bool(w_c) and (w_c < 0 or levered) and not np.isnan(close[t + 1, c]) and _breached(
            1 if w_c > 0 else -1, ratio, close[t, c], low[t + 1, c], high[t + 1, c], close[t + 1, c])
            for c, w_c in enumerate(target)])
        pnl = np.where(burst, -np.abs(target) / ratio * (1 - FLOOR), target * move)
        returns[t + 1] = pnl.sum() - cost - borrowed * BORROW_PER_DAY
        for prev, now, b in zip(held, target, burst, strict=True):
            if b:
                counts["LIQUIDATED"] += 1
            elif prev == 0 and now != 0:
                counts["OPEN_LONG" if now > 0 else "OPEN_SHORT"] += 1
            elif prev != 0 and now == 0:
                counts["CLOSE"] += 1
            elif prev * now < 0:
                counts["FLIP"] += 1
            elif prev != now:
                counts["RESIZE"] += 1
            elif now != 0:
                counts["HOLD"] += 1
        if levered:
            counts["LEVERED_DAYS"] += 1
        elif gross <= EPS:
            counts["CASH_DAYS"] += 1
        held = np.where(burst, 0.0, target * (1 + move) / max(1 + returns[t + 1], 1e-9))
        drifted = held.clip(min=0).sum()
        if w[t].clip(min=0).sum() <= 1 + EPS < drifted:  # an unlevered book pays its costs out of its positions
            held = np.where(held > 0, held / drifted, held)
    return returns, counts


def equal_hold(panel):
    live = panel["liquid"] & ~np.isnan(panel["close"])
    return live / np.maximum(live.sum(1, keepdims=True), 1)


def trend_sleeves(panel):
    live = panel["liquid"] & ~np.isnan(panel["close"])
    return live * panel["trend"] / np.maximum(live.sum(1, keepdims=True), 1)


def breadth(panel, lookback=50):
    close = panel["close"]
    mean = np.full_like(close, np.nan)
    for t in range(lookback, len(close)):
        mean[t] = np.nanmean(close[t - lookback + 1:t + 1], axis=0)
    live = panel["liquid"] & ~np.isnan(mean)
    above = (close > mean) & live
    return above.sum(1) / np.maximum(live.sum(1), 1)


def breadth_gated(panel, weights, level=0.5):
    return weights * (breadth(panel) > level)[:, None]


def vol_target(panel, weights, target=0.40, cap=3.0, lookback=30):
    """Scale the book to `target` yearly volatility, estimated ex ante from the coins it holds now.

    Project trailing asset returns onto today's weights before computing volatility, equivalent to sqrt(w' S w).
    A book's own past returns would
    read near zero while it sat in cash and send it to the cap exactly when it re-enters: that was the bug here.
    """
    close = panel["close"]
    rets = np.vstack([np.zeros(close.shape[1]), close[1:] / close[:-1] - 1])
    out = np.zeros_like(weights)
    for t in range(lookback, len(close)):
        held = np.flatnonzero(weights[t])
        if not len(held):
            continue
        window = np.nan_to_num(rets[t - lookback + 1:t + 1][:, held])
        vol = float(np.std(window @ weights[t, held], ddof=1)) * sqrt(YEAR)
        out[t] = weights[t] * (min(cap, target / vol) if vol > 0 else 0.0)
    return out


def xs_momentum(panel, lookback=28, decile=0.1, every=7, long_only=False):
    close = panel["close"]
    w = np.zeros_like(close)
    for t in range(lookback, len(close)):
        if t % every:
            w[t] = w[t - 1]
            continue
        ret = close[t] / close[t - lookback] - 1
        ok = np.flatnonzero(panel["liquid"][t] & ~np.isnan(ret))
        if len(ok) < 20:
            continue
        ranked = ok[np.argsort(ret[ok])]
        k = max(1, int(len(ok) * decile))
        if long_only:
            w[t, ranked[-k:]] = 1 / k
        else:
            w[t, ranked[-k:]], w[t, ranked[:k]] = 0.5 / k, -0.5 / k
    return w


def strategy_blend(panel, books, lookback=60):
    """Net several books with causal inverse-volatility weights from each book's own past returns."""
    streams = [simulate(panel, b)[0] for b in books]
    out = np.zeros_like(books[0])
    for t in range(len(out)):
        if t < lookback:
            continue
        inv = np.array([1 / v if (v := np.std(s[t - lookback + 1:t + 1])) > 0 else 0.0 for s in streams])
        if inv.sum() > 0:
            out[t] = sum(a * b[t] for a, b in zip(inv / inv.sum(), books, strict=True))
    return out


def stats(returns, counts, start):
    r = returns[start:]
    mean, sd, skew, kurt = _moments(list(r))
    curve = np.cumprod(np.r_[1.0, 1 + r])
    return {"total_pct": 100 * (curve[-1] - 1), "yearly_sharpe": mean / sd * sqrt(YEAR) if sd else 0.0,
            "max_drawdown_pct": 100 * float(np.max(1 - curve / np.maximum.accumulate(curve))),
            "sharpe": mean / sd if sd else 0.0, "moments": (skew, kurt), "days": len(r), "decisions": counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", type=int, default=0)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / ".pi" / "portfolio-lab.json"))
    args = parser.parse_args()
    panel = load_panel(universe()[: args.coins or None])
    trend = trend_sleeves(panel)
    gated = breadth_gated(panel, trend)
    xs = xs_momentum(panel)
    books = {
        "hold equal weight": equal_hold(panel),
        "trend blend sleeves": trend,
        "trend + breadth gate": gated,
        "trend + vol target": vol_target(panel, trend),
        "trend + breadth + vol target": vol_target(panel, gated),
        "xs momentum long-short": xs,
        "xs momentum long-only": xs_momentum(panel, long_only=True),
        "xs momentum long-short + vol target": vol_target(panel, xs),
        "strategy blend: breadth trend + xs long-short": strategy_blend(panel, [gated, xs]),
    }
    start = 120  # every book's warm-up is over
    results, streams = {}, {}
    for name, w in books.items():
        r, counts = simulate(panel, w)
        results[name], streams[name] = stats(r, counts, start), r[start:]
    variance = pvariance([s["sharpe"] for s in results.values()])
    for s in results.values():
        s["deflated"] = deflated_sharpe(s["sharpe"], s["days"], *s.pop("moments"), len(results), variance) or 0.0
    print(f"portfolio lab, EXPLORATION before {SPLIT}: {len(panel['coins'])} coins, {len(panel['days'])} days, "
          f"{len(books)} books (deflated over these {len(books)} only)")
    for name, s in sorted(results.items(), key=lambda kv: -kv[1]["yearly_sharpe"]):
        d = s["decisions"]
        print(f"  {name:<46} total {s['total_pct']:10.1f}%  Sharpe/yr {s['yearly_sharpe']:5.2f}  "
              f"maxDD {s['max_drawdown_pct']:5.1f}%  deflated {s['deflated']:.3f}  opens L{d['OPEN_LONG']}/S{d['OPEN_SHORT']} "
              f"liq {d['LIQUIDATED']} levered days {d['LEVERED_DAYS']} cash days {d['CASH_DAYS']}")
    names = ["trend + breadth gate", "xs momentum long-short", "hold equal weight"]
    corr = np.corrcoef([streams[n] for n in names])
    print("  correlation of daily returns: " + "; ".join(f"{a} / {b}: {corr[i, j]:+.2f}"
                                                         for i, a in enumerate(names) for j, b in enumerate(names) if i < j))
    Path(args.out).write_text(json.dumps(results, indent=1, default=float), "utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
