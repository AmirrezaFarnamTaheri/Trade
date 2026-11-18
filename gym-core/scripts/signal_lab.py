"""Signal lab: blends of causal signals on every capability - spot long, margin long, margin short, leverage, cash.

EXPLORATION ONLY. Runs on Binance daily candles before 2024-01-01 (the ranking period); the 2024-2026 days are
consumed for daily trend and breakout rules and are not touched here. A form worth scoring must be registered in
docs/trial-log.md and tested on new data (Wallex intraday or the forward record).

Each configuration is (blend form, member set, side mode, credit ratio). Every coin-day records a decision:
OPEN_LONG_SPOT, OPEN_LONG_MARGIN, OPEN_SHORT, FLIP, EXIT_SIGNAL, EXIT_MAX_AGE, LIQUIDATED, HOLD, CASH.
A 1x long uses spot (fee and half-spread each side). Margin longs and every short use Wallex's margin costs as in
margin_hold.hold: entry fee, a loan fee per 4 hours prepaid for the first period, exit fee, the 15% equity floor
and the 21-day maximum position age. Positions are marked each close as if closed there.

    uv run --no-sync python scripts/signal_lab.py [--coins N] [--workers N]
"""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from math import sqrt
from pathlib import Path
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binance_archive import liquid, spot_daily, universe  # noqa: E402
from margin_hold import ENTRY_FEE, EXIT_FEE, FLOOR, LOAN_FEE, PERIOD  # noqa: E402

from gym.domain.multiple_testing import bh_q, sign_test_p  # noqa: E402
from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402
from gym.domain.signals import blend  # noqa: E402

SPLIT, DAY, MAX_AGE_DAYS = "2024-01-01", 86400, 21
HALF_SPREAD, SPOT_FEE = 0.001, 0.001
FORMS = ("vote", "confirm", "calm-vote", "regime-switch")
SETS = {"trend5": ("tsmom", "efficiency", "obv", "donchian", "ema-cross"),
        "mixed5": ("tsmom", "efficiency", "obv", "rsi-reversion", "bollinger-reversion"),
        "pair": ("efficiency", "obv"),
        # single members: the baseline a blend has to beat
        **{name: (name,) for name in ("tsmom", "efficiency", "obv", "donchian", "ema-cross")}}
MODES = (("long", 1), ("long", 2), ("long-short", 1), ("long-short", 2), ("long-short", 3), ("long-short", 5))
DECISIONS = ("OPEN_LONG_SPOT", "OPEN_LONG_MARGIN", "OPEN_SHORT", "FLIP", "EXIT_SIGNAL", "EXIT_MAX_AGE", "LIQUIDATED",
             "HOLD", "CASH")


class Position:
    """Equity on 1 unit of collateral, updated one daily bar at a time (same formulas as margin_hold.hold)."""

    def __init__(self, side, ratio, close):
        self.side, self.ratio, self.age, self.liquidated = side, ratio, 0, False
        self.spot = side > 0 and ratio == 1
        if self.spot:
            self.units = (1 - SPOT_FEE) / (close * (1 + HALF_SPREAD))
            return
        entry = close * (1 + HALF_SPREAD * side)
        long = side > 0
        self.units = ratio / entry * (1 - ENTRY_FEE) if long else ratio / entry
        self.cash = 1 - ratio * LOAN_FEE if long else 1 + ratio * (1 - ENTRY_FEE) - ratio * LOAN_FEE
        self.debt = ratio if long else 0.0

    def _raw(self, price):
        carry = self.ratio * LOAN_FEE * (self.age // PERIOD)
        return self.cash - carry + self.units * price - self.debt if self.side > 0 else self.cash - carry - self.units * price

    def step(self, low, high, close):
        """Advance one day; return equity if closed at this close (FLOOR if liquidated on the way)."""
        if self.spot:
            return self.units * close * (1 - HALF_SPREAD) * (1 - SPOT_FEE)
        self.age += DAY
        if self._raw(low if self.side > 0 else high) <= FLOOR:
            self.liquidated = True
            return FLOOR
        exit_price = close * (1 - HALF_SPREAD * self.side)
        carry = self.ratio * LOAN_FEE * (self.age // PERIOD)
        worth = self.units * exit_price * (1 - EXIT_FEE) if self.side > 0 else -self.units * exit_price * (1 + EXIT_FEE)
        return self.cash - carry + worth - self.debt


def run_coin(bars, counted, positions, ratio):
    """Daily returns on counted days, decision counts, and the coin's compounded strategy and hold returns."""
    out, counts, trade, before = [], dict.fromkeys(DECISIONS, 0), None, 1.0
    strat = hold = 1.0
    c, lo, hi = bars["close"], bars["low"], bars["high"]
    for j in range(1, len(c)):
        if not counted[j]:
            trade = None
            continue
        r = 0.0
        if trade:
            equity = trade.step(lo[j], hi[j], c[j])
            r = equity / before - 1
            before = equity
        want, decision = positions[j] or 0, None  # exactly one decision per coin-day
        if trade and trade.liquidated:
            decision, trade = "LIQUIDATED", None
        elif trade and want != trade.side:
            decision, trade = ("FLIP" if want else "EXIT_SIGNAL"), None
        elif trade and not trade.spot and trade.age >= MAX_AGE_DAYS * DAY:
            decision, trade = "EXIT_MAX_AGE", None
        if trade is None and want and decision != "LIQUIDATED":
            trade, before = Position(want, ratio, c[j]), 1.0
            opened = "OPEN_SHORT" if want < 0 else "OPEN_LONG_SPOT" if trade.spot else "OPEN_LONG_MARGIN"
            decision = decision or opened
            if decision != opened:  # a flip or an age-out reopens: count the new side as well
                counts[opened] += 1
        counts[decision or ("HOLD" if trade else "CASH")] += 1
        out.append((bars["days"][j], r))
        strat *= 1 + r
        hold *= c[j] / c[j - 1]
    return out, counts, strat - 1, hold - 1


def coin_job(job):
    symbol, configs = job
    bars = spot_daily(symbol)
    cut = sum(d < SPLIT for d in bars["days"])
    bars = {k: v[:cut] for k, v in bars.items()}
    if cut < 120:
        return symbol, None
    counted = liquid(bars["volume"])
    results = {}
    for key in configs:
        form, set_name, mode, ratio = key
        names = SETS[set_name]
        # one member: follow its own sign (enter at +-1, leave at 0), not a consensus band
        band = {"enter_pct": 100, "exit_pct": 0} if len(names) == 1 else {"enter_pct": 60, "exit_pct": 20}
        positions = blend(bars, names, form=form, long_only=mode == "long", **band)
        results[key] = run_coin(bars, counted, positions, ratio)
    return symbol, results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", type=int, default=0, help="first N coins of the universe (0 = all)")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--sets", help="comma-separated member sets (default: all)")
    parser.add_argument("--modes", help="comma-separated mode:ratio pairs, e.g. long:1,long-short:1 (default: all)")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / ".pi" / "signal-lab.json"))
    args = parser.parse_args()
    sets = args.sets.split(",") if args.sets else list(SETS)
    modes = [(m, int(r)) for m, r in (x.split(":") for x in args.modes.split(","))] if args.modes else MODES
    # a single member gives the same position under every form: run it once, as "vote"
    configs = [(f, s, m, r) for f in FORMS for s in sets for m, r in modes if len(SETS[s]) > 1 or f == "vote"]
    coins = universe()[: args.coins or None]
    pooled = {k: {} for k in configs}
    league = {k: [0, 0] for k in configs}
    decisions = {k: dict.fromkeys(DECISIONS, 0) for k in configs}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for _symbol, results in pool.map(coin_job, [(s, configs) for s in coins], chunksize=4):
            if not results:
                continue
            for key, (series, counts, strat, hold) in results.items():
                for day, r in series:
                    pooled[key].setdefault(day, []).append(r)
                for name, n in counts.items():
                    decisions[key][name] += n
                if counts["OPEN_LONG_SPOT"] + counts["OPEN_LONG_MARGIN"] + counts["OPEN_SHORT"]:
                    bench = max(hold, 0.0)
                    league[key][0 if strat > bench else 1] += strat != bench
    cells = []
    for key in configs:
        values = [fmean(pooled[key][d]) for d in sorted(pooled[key])]
        if len(values) < 30:
            continue
        mean, sd, skew, kurt = _moments(values)
        total = 1.0
        peak, drawdown = 1.0, 0.0
        for v in values:
            total *= 1 + v
            peak = max(peak, total)
            drawdown = max(drawdown, 1 - total / peak)
        wins, losses = league[key]
        cells.append({"form": key[0], "members": key[1], "mode": key[2], "ratio": key[3], "days": len(values),
                      "total_pct": 100 * (total - 1), "yearly_sharpe": mean / sd * sqrt(365) if sd else 0.0,
                      "max_drawdown_pct": 100 * drawdown, "sharpe": mean / sd if sd else 0.0, "moments": (skew, kurt),
                      "coins_won": wins, "coins_lost": losses, "sign_p": sign_test_p(wins, wins + losses),
                      "decisions": decisions[key]})
    variance = pvariance([c["sharpe"] for c in cells])
    q = bh_q({i: c["sign_p"] for i, c in enumerate(cells)})
    for i, c in enumerate(cells):
        c["deflated"] = deflated_sharpe(c["sharpe"], c["days"], *c.pop("moments"), len(cells), variance) or 0.0
        c["sign_q"] = q[i]
    cells.sort(key=lambda c: -c["deflated"])
    print(f"signal lab, EXPLORATION before {SPLIT}: {len(coins)} coins, {len(cells)} configurations "
          f"(deflated Sharpe corrects for all of them; coin league vs max(hold, cash), BH q)")
    for c in cells[:15] + [None] + cells[-5:]:
        if c is None:
            print("  ...")
            continue
        d = c["decisions"]
        print(f"  {c['form']:<13} {c['members']:<10} {c['mode']:<10} {c['ratio']}x  total {c['total_pct']:9.1f}%  "
              f"Sharpe/yr {c['yearly_sharpe']:5.2f}  maxDD {c['max_drawdown_pct']:5.1f}%  deflated {c['deflated']:.3f}  "
              f"coins {c['coins_won']:>3}-{c['coins_lost']:<3} q {c['sign_q']:.3f}  opens L{d['OPEN_LONG_SPOT'] + d['OPEN_LONG_MARGIN']}"
              f"/S{d['OPEN_SHORT']} flips {d['FLIP']} liq {d['LIQUIDATED']} age-outs {d['EXIT_MAX_AGE']}")
    Path(args.out).write_text(json.dumps(cells, indent=1), "utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
