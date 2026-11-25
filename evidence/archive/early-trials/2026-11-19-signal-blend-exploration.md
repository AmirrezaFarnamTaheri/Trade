# Signal blends on every capability: exploration (2026-11-19)

Exploration, not a trial. Binance daily candles before 2024-01-01 (the ranking period), 474 coins, liquid days only.
The 2024-2026 days were not used. Script: `gym-core/scripts/signal_lab.py`; outputs `.pi/signal-lab.json` (72
configurations) and `.pi/signal-lab-vs-singles.json` (26 configurations: blends against their own members).

## What was run

Seven causal signals (`gym-core/src/gym/domain/signals.py`): ema-cross, tsmom, donchian, efficiency (Kaufman ratio),
obv (volume), rsi-reversion, bollinger-reversion. Four blend forms: vote (consensus band), confirm (one member times,
others agree), calm-vote (weight 1/(1+recent flips)), regime-switch (trend members when the 20-bar efficiency ratio
is at least 0.3, reversion members otherwise). Side modes: long only, long and short. Credit ratios 1, 2, 3 and 5.
A 1x long is spot. Margin longs and every short pay Wallex's margin costs (entry fee, loan fee per 4 hours, exit
fee). They are liquidated at the 15% equity floor and closed at the 21-day maximum age. The incremental position
matches `scripts/margin_hold.hold` to 1e-12 (`tests/test_signal_lab.py`). Every coin-day records one decision.

## Results (pooled equal-weight daily returns, 2019 to 2023)

| Configuration (long only, 1x) | Total | Sharpe/yr | Max DD | Opens |
| --- | ---: | ---: | ---: | ---: |
| vote, five trend members | +4,241% | 1.52 | 48.9% | 2,960 |
| donchian alone | +4,834% | 1.46 | 57.4% | 2,315 |
| ema-cross alone | +4,204% | 1.43 | 58.9% | 3,161 |
| vote, efficiency + obv | +887% | 1.42 | 30.9% | 1,733 |
| tsmom alone | +3,413% | 1.38 | 60.5% | 6,668 |

- Blending raised Sharpe a little, cut maximum drawdown by 9 to 30 points and halved trading against tsmom. It did
  not create an edge from members without one: blends with reversion members ended near zero or below.
- Shorts lowered every Sharpe (best long-short 1.17, donchian). Leverage made every form worse: 2x long had 109
  liquidations and an 85.5% drawdown; 5x long-short had 128 liquidations.
- Only 95 of 267 coins beat the better of holding the coin and holding cash; the pooled gain leans on 2020-21.
- Deflated Sharpe of the best blend: 0.973 against this run's 26 configurations, about 0.81 against the 82 tried in
  total. Not significant.

## Next

The held-out Binance days are consumed for daily trend rules, so a trend blend needs new data: a registered forward
record (as `btc-daily-trend` has) or Wallex intraday quotes. The spot `signal-blend` strategy runs in the paper
engine and sweep; on BTCUSDT 15min for 2026-11-11 to 18 it traded 3 times (5.9x turnover) against 9 (18.2x) for
`ema-trend` alone.
