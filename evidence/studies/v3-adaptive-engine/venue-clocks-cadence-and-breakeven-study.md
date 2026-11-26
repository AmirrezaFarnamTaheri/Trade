# Post-Repair Cross-Venue Clocks, Cadence, Blind Bake-Off & Cost Break-Even Study (Menu Ideas 12, 13, 14 + Review #3)

- **Generated:** `2026-11-25T21:35:50.615977+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## Idea 12 — Cross-Venue Price Discovery (With 1-Step Delay & Swapped-Label Controls)

| Symbol | Samples | WLX→NBX Hit% (bps) | NBX→WLX Hit% (bps) | WLX Delayed +1 Step (bps) | Swapped Placebo (bps) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `BTCUSDT` | `727` | `56.8%` (`+1.46`) | `53.9%` (`+2.38`) | `-0.77` | `+0.09` |
| `ETHUSDT` | `590` | `54.1%` (`+1.55`) | `62.7%` (`+4.40`) | `-0.07` | `+0.16` |
| `SOLUSDT` | `954` | `51.9%` (`+0.76`) | `51.5%` (`+3.04`) | `+0.06` | `+0.51` |
| `XRPUSDT` | `622` | `53.1%` (`+0.89`) | `57.4%` (`+3.33`) | `-0.37` | `-0.15` |

## Idea 13 — Event-Driven vs. Fixed-Cadence Engine Runs (Measured CPU & Missed-Trigger Cost)
- **Evaluations:** `13002` fixed → `7143` event (`45.1%` fewer evals)
- **Measured Process CPU:** `468.8 ms` → `390.6 ms` (**`16.7%` CPU saved**) · **p95 Bar Latency:** `0.1298 ms` vs `0.1290 ms`
- **Triggers Captured:** `266 / 267` (`99.63%`) · **Missed Trigger 24h Net P&L (bps):** `[-61.22]`

## Idea 14 — Blind Prospective Paper Bake-Off Manifest (Concealed Salt, Key Outside Git)
- **Sealed Key SHA-256 Commitment:** `67ec03c38fb5c5dbc4fdcee0e24e370844d200aa8839424bceec9fbf20dfd49c`

| Blinded Alias | Identity Hash | Status |
| --- | --- | --- |
| `BLIND_ARM_A` | `b564918bd6bc` | `PENDING_PROSPECTIVE_WINDOW` |
| `BLIND_ARM_B` | `c109bc881578` | `PENDING_PROSPECTIVE_WINDOW` |
| `BLIND_ARM_C` | `e9dcf5db7d36` | `PENDING_PROSPECTIVE_WINDOW` |
| `BLIND_ARM_D` | `ece9239a89ce` | `PENDING_PROSPECTIVE_WINDOW` |

## Review Priority #3 & F11 — Cost/Missed-Fill Break-Even Sweep & `SLOW_40PCT_PLUS_CASH` Control

| Arm | Fee (bps) | Missed Fills% | Ending NAV | Return | Ann. Sharpe | MaxDD | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FIXED_SLOW_S1_S5_100PCT` | `8.5` | `0%` | `$2577.52` | `+157.75%` | `1.013` | `22.19%` | `$42.66` |
| `FIXED_SLOW_S1_S5_100PCT` | `8.5` | `25%` | `$2511.01` | `+151.10%` | `0.988` | `23.17%` | `$41.58` |
| `FIXED_SLOW_S1_S5_100PCT` | `16.0` | `0%` | `$2522.43` | `+152.24%` | `0.993` | `22.35%` | `$79.23` |
| `FIXED_SLOW_S1_S5_100PCT` | `16.0` | `25%` | `$2458.65` | `+145.87%` | `0.968` | `23.33%` | `$77.28` |
| `FIXED_SLOW_S1_S5_100PCT` | `25.0` | `0%` | `$2458.67` | `+145.87%` | `0.968` | `22.66%` | `$121.94` |
| `FIXED_SLOW_S1_S5_100PCT` | `25.0` | `25%` | `$2400.28` | `+140.03%` | `0.945` | `23.49%` | `$119.12` |
| `FIXED_SLOW_S1_S5_100PCT` | `40.0` | `0%` | `$2356.15` | `+135.61%` | `0.928` | `23.05%` | `$190.17` |
| `FIXED_SLOW_S1_S5_100PCT` | `40.0` | `25%` | `$2301.03` | `+130.10%` | `0.905` | `23.93%` | `$185.88` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `8.5` | `0%` | `$1523.35` | `+52.33%` | `1.028` | `9.32%` | `$11.95` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `8.5` | `25%` | `$1500.19` | `+50.02%` | `0.991` | `9.74%` | `$11.82` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `16.0` | `0%` | `$1510.07` | `+51.01%` | `1.008` | `9.40%` | `$22.40` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `16.0` | `25%` | `$1487.60` | `+48.76%` | `0.972` | `9.82%` | `$22.13` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `25.0` | `0%` | `$1494.34` | `+49.43%` | `0.984` | `9.47%` | `$34.77` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `25.0` | `25%` | `$1472.43` | `+47.24%` | `0.948` | `9.88%` | `$34.31` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `40.0` | `0%` | `$1469.27` | `+46.93%` | `0.945` | `9.62%` | `$55.12` |
| `SLOW_40PCT_PLUS_CASH_CONTROL` | `40.0` | `25%` | `$1446.99` | `+44.70%` | `0.908` | `10.03%` | `$54.35` |
