# Portfolio lab exploration (2026-11-19)

These tables record the original exploration, not current model output. The lab now excludes a coin from the breadth calculation unless it has a complete daily price window. The first full window counts. The change does not alter the registered Wallex forward rule or its score.

Exploration, not a trial. Binance daily candles before 2024-01-01, 279 coins with 120 or more days of history,
2,328 days. The 2024-2026 days were not read. Script: `gym-core/scripts/portfolio_lab.py`; output
`.pi/portfolio-lab.json`. All books share one simulator: spot cost for long exposure up to 1x, margin cost for shorts
and leverage, the 4-hourly loan fee on borrowed notional, liquidation at the 15% equity floor, a 5% no-trade band, and
one logged decision per coin-day.

## Why these ideas

Every single-coin price rule failed (trial log). The ideas here use information one coin's chart does not carry:
market breadth (the cross-section), the held coins' volatility, relative strength across coins, and the correlation
between strategies.

## Results

| Book | Total | Sharpe/yr | Max DD | Deflated (9 books) |
| --- | ---: | ---: | ---: | ---: |
| Trend blend + breadth gate (trade only while most coins are above their 50-day mean) | +3,173% | 1.54 | 37.0% | 0.923 |
| Trend + breadth + ex-ante volatility target (40%/yr, cap 3x) | +705% | 1.36 | 30.7% | 0.843 |
| Trend blend alone (five members, equal sleeves) | +1,903% | 1.29 | 49.2% | 0.802 |
| Strategy blend: breadth trend + cross-sectional momentum (inverse volatility) | +628% | 1.05 | 59.7% | 0.606 |
| Hold every liquid coin, equal weight | +20% | 0.51 | 89.5% | 0.145 |
| Cross-sectional momentum, long only (top decile, weekly) | +14% | 0.48 | 94.8% | 0.129 |
| Cross-sectional momentum, long-short (top/bottom decile on margin) | -54% | -0.21 | 71.9% | 0.002 |

- The breadth gate is the clearest improvement found so far: Sharpe 1.29 to 1.54, drawdown 49% to 37%.
- Volatility targeting lowered drawdown again, to 30.7%, but cost Sharpe; crypto volatility kept it below 1x.
- Cross-sectional momentum loses on crypto at weekly rebalancing, long-short worst (10 liquidations). It is nearly
  uncorrelated with trend (+0.10), but a diversifier with a negative return lowers any blend.
- Not significant: deflated 0.923 against these nine books, lower against everything tried this week.

## Defects found and fixed while building it

- Volatility targeting first scaled by the book's own past returns, which read near zero while it sat in cash and
  sent it to the 3x cap exactly at re-entry. It now uses the held coins' trailing covariance, sqrt(w'Sw).
- Unlevered books were charged as borrowing: costs and banded drift pushed long weights a little above 1. Costs now
  come out of the positions.

## Execution clock (Wallex, 2026-11-11 to 18, 13.3M quotes)

Median spread by Tehran hour is lowest at 15:00 (203 bps across all markets, 26 bps on the ten most liquid) and
highest at 05:00 to 07:00 (266 to 275 bps; 38 bps). Rebalancing at 15:00 instead of 06:00 cuts spread cost by
26 to 32%. The forward journals fill at 03:45 (245 and 36 bps); their registered protocol stays unchanged, and new
forward trials should register a 15:00 fill.

## Next

Register a forward record for the breadth-gated trend blend on Wallex coins with a 15:00 Tehran fill, so the
strongest exploration result meets data it has not seen.
