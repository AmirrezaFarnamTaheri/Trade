# Wallex tokenised assets against what they track - 2026-11-18

Daily Wallex closes (00:00 UTC) of the tokenised assets divided by the Yahoo Finance close of the asset each token tracks
(New York close, about 21:00 UTC). Descriptive only; no strategy is scored. Reproduce with `gym-core/scripts/token_premium.py`.

| Token | Tracks | Days | Median premium | 10% to 90% of days | Day-to-day persistence | Half-life |
| --- | --- | --- | --- | --- | --- | --- |
| XAUTUSDT | gold futures (GC=F) | 576 | -0.44% | -1.55% to +0.66% | 0.41 | 0.8 days |
| SLVONUSDT | SLV, the iShares Silver Trust | 200 | +0.19% | -1.35% to +2.23% | 0.36 | 0.7 days |
| USOONUSDT | USO, the United States Oil Fund | 174 | +0.14% | -1.31% to +4.03% | 0.33 | 0.6 days |
| COPXONUSDT | COPX, copper-mining stocks | 133 | +0.32% | -2.19% to +4.21% | 0.77 | 2.7 days |
| AAPLXUSDT | Apple (AAPL) | 212 | -1.19% | -16.75% to +327% | 0.96 | 17 days |

## What it means

- The ON tokens track exchange-traded funds, not commodity futures: against silver, oil and copper futures their gaps were
  -9.5%, +53% and +1,187%, which are the funds' own price levels, not mispricing.
- `passive-multi-asset-mix` was registered and scored with futures as stand-ins for silver, oil and copper. Rerun with
  the funds the tokens track (a sensitivity check, not a new score): 3,591 days, +306.6% (15.3% a year), Sharpe 0.98,
  probability 0.999. The registered result holds.
- AAPLX's Wallex daily candles are unusable (a 327% "premium", candles ending 2026-09-25); the mix journal gives it no weight.
- Gaps of 1.5% to 4% that close within a day look tradeable against about 0.4% of round-trip cost, but the closes are
  taken 3 hours apart, which widens the measured gaps. A fair test needs prices observed at the same moment; it is a
  candidate trial, not a finding.
