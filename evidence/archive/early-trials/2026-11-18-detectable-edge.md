# Smallest edge each trial could have detected - 2026-11-18

`gym-core/scripts/detectable_edge.py` took each trial's winning return series, removed its average (keeping its real
noise, streaks and tails), planted a known edge, resampled it in 20-day blocks (trades: one at a time) and applied the
trial's registered pass test 200 times. The smallest detectable edge is the smallest planted edge passed 80% of the time.
This scores no strategy and selects nothing.

| Trial | Stage | Periods | Average of its series | Smallest detectable edge |
| --- | --- | --- | --- | --- |
| `btc-daily-trend` | ranking | 2,278 days | 18.9 bps a day | 20 bps a day (about 107% a year) |
| `implied-toman-rate` | ranking | 7 trades | 135 bps a trade | 300 bps a trade |
| `trend-with-short-side` | ranking | 1,188 days | 46 bps a day | 100 bps a day |
| `rule-selector-with-cash` | ranking | 1,704 days | 30 bps a day | 50 bps a day |
| `book-imbalance` | ranking | 3,518 trades | -43 bps a trade | 50 bps a trade |
| `strongest-coin-or-cash` | ranking | 2,146 days | 35 bps a day | 50 bps a day |
| `strongest-coin-or-cash` | held out | 1,574 days | 1.3 bps a day | 20 bps a day (about 107% a year) |
| `funding-crowding-filter` | ranking | 1,089 days | 3.3 bps a day | 15 bps a day (about 73% a year) |
| `margin-breakout-long-short` | ranking | 1,089 days | 8.2 bps a day | 30 bps a day |
| `spot-breakout-long` | held out | 1,035 days | -0.7 bps a day | 10 bps a day (about 44% a year) |
| `funding-confirmed-trend` | held out | 1,035 days | 2.6 bps a day | 10 bps a day (about 44% a year) |

## What it means

- A realistic edge for a daily rule is 5 to 20% a year, about 1.3 to 5 bps a day. No daily test here could detect less
  than 10 bps a day. Their FAIL results say "not proven", not "no edge".
- `funding-confirmed-trend` averaged 2.6 bps a day on its held-out days; its test needed 10. A real edge of that size
  would usually fail.
- The averages include market movement (coins rose in the ranking years), so they are not pure edge.
- Not covered: the first five quote-based screens, `otc-against-book` and `logistic-entry-gate`, whose pass tests are
  counts or calibration marks rather than return series.

## Consequence for trial design

A daily rule needs many more independent days to detect a realistic edge: pooled coins scored per coin-day, intraday
bars, or a long forward record checked with a test that allows looking every day. Register the detectable edge with
each new trial, before running it, so an underpowered design is visible up front.
