# Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10)

- **Generated:** `2026-11-26T08:34:45.156251+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## Idea 7 — Marginal Value of +1 USDT per Venue (Prefunding Sweep, `$1,000` Fixed)

| Split (NBX / WLX) | Normal Exec Cost (bps) | Normal Missed% | 25% NBX-Outage Cost (bps) | 25% Outage Missed% |
| --- | ---: | ---: | ---: | ---: |
| `NBX_0_WLX_1000` | `+38.50` | `80.6%` | `+38.50` | `80.6%` |
| `NBX_250_WLX_750` | `+34.23` | `82.0%` | `+35.49` | `82.7%` |
| `NBX_500_WLX_500` | `+29.37` | `81.0%` | `+31.07` | `83.3%` |
| `NBX_750_WLX_250` | `+25.08` | `81.4%` | `+26.35` | `85.2%` |
| `NBX_1000_WLX_0` | `+22.88` | `79.8%` | `+22.81` | `86.3%` |

## Idea 8 — Gold Token Substitution (`XAUT` vs `PAXG`, 3 Execution Timings + -3% Issuer Shock)
- **Overlap Days (Closed Bars Only):** `842` · **Switches:** `49`
- **Hold Benchmarks:** `XAUT_ONLY=48.84%` · `SPLIT_50_50=48.16%`
- **Switching Timing Sensitivity:** `SAME_CLOSE_UPPER=138.49%` · `CAUSAL_NEXT_OPEN=86.85%` · `CAUSAL_NEXT_CLOSE=47.29%`
- **Under -3% XAUT Issuer Shock (Applied to Execution & Marks):** `{'xaut_only_pct': 44.37, 'split_50_50_pct': 45.92, 'switch_next_open_shocked_pct': 132.54}`

## Idea 9 — Cash Recoverable on Deadline (Net of Fees, Original Portfolio Denominator)

| Book | Notional | Deadline | Net Cash Recovered% | Residual Inv% | Unpriced Inv% | Shortfall (bps) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `5m` | `74.7%` | `25.3%` | `0.0%` | `+28.51` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1h` | `99.8%` | `0.2%` | `0.0%` | `+21.39` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+20.58` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `5m` | `36.1%` | `63.9%` | `0.0%` | `+28.60` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1h` | `67.8%` | `32.2%` | `0.0%` | `+28.51` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+21.39` |
| `ALT_HEAVY_BASKET` | `$10,000` | `5m` | `92.2%` | `7.8%` | `0.0%` | `+24.09` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1h` | `99.8%` | `0.2%` | `0.0%` | `+21.95` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+18.84` |
| `ALT_HEAVY_BASKET` | `$50,000` | `5m` | `27.5%` | `72.5%` | `0.0%` | `+44.74` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1h` | `86.7%` | `13.3%` | `0.0%` | `+24.28` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+21.95` |

## Idea 10 — Separating Trading Skill from USDT/TMN FX Exposure
- **Overlap:** `2022-06-01..2026-11-18` (`1632` days)
- **Hold TMN:** `0.00%` · **Buy & Hold USDT (in TMN):** `777.59%` · **USDT Strategy Converted Back to TMN:** `2114.38%`
- **Pure USDT Trading Alpha (FX Stripped):** `152.33%` · **Direct `BTCTMN` Hold:** `1675.41%`
