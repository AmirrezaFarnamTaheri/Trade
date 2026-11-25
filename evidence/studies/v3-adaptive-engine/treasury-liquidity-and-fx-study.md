# Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10)

- **Generated:** `2026-11-25T21:35:32.878336+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## Idea 7 — Marginal Value of +1 USDT per Venue (Prefunding Sweep, `$1,000` Fixed)

| Split (NBX / WLX) | Normal Exec Cost (bps) | Normal Missed% | 25% NBX-Outage Cost (bps) | 25% Outage Missed% |
| --- | ---: | ---: | ---: | ---: |
| `NBX_0_WLX_1000` | `+39.12` | `38.5%` | `+39.12` | `38.5%` |
| `NBX_250_WLX_750` | `+34.63` | `42.1%` | `+34.63` | `42.1%` |
| `NBX_500_WLX_500` | `+28.76` | `25.9%` | `+28.76` | `25.9%` |
| `NBX_750_WLX_250` | `+24.51` | `21.0%` | `+24.59` | `23.4%` |
| `NBX_1000_WLX_0` | `+23.89` | `3.5%` | `+23.63` | `25.0%` |

## Idea 8 — Gold Token Substitution (`XAUT` vs `PAXG`, 3 Execution Timings + -3% Issuer Shock)
- **Overlap Days (Closed Bars Only):** `841` · **Switches:** `49`
- **Hold Benchmarks:** `XAUT_ONLY=47.45%` · `SPLIT_50_50=47.95%`
- **Switching Timing Sensitivity:** `SAME_CLOSE_UPPER=140.06%` · `CAUSAL_NEXT_OPEN=88.08%` · `CAUSAL_NEXT_CLOSE=48.27%`
- **Under -3% XAUT Issuer Shock (Applied to Execution & Marks):** `{'xaut_only_pct': 43.03, 'split_50_50_pct': 45.74, 'switch_next_open_shocked_pct': 130.03}`

## Idea 9 — Cash Recoverable on Deadline (Net of Fees, Original Portfolio Denominator)

| Book | Notional | Deadline | Net Cash Recovered% | Residual Inv% | Unpriced Inv% | Shortfall (bps) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `5m` | `94.4%` | `5.6%` | `0.0%` | `+24.81` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1h` | `99.8%` | `0.2%` | `0.0%` | `+22.76` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+22.45` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `5m` | `44.7%` | `55.3%` | `0.0%` | `+25.04` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1h` | `88.9%` | `11.1%` | `0.0%` | `+25.04` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+22.76` |
| `ALT_HEAVY_BASKET` | `$10,000` | `5m` | `99.4%` | `0.6%` | `0.0%` | `+56.00` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1h` | `99.8%` | `0.2%` | `0.0%` | `+21.64` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+20.71` |
| `ALT_HEAVY_BASKET` | `$50,000` | `5m` | `40.5%` | `59.5%` | `0.0%` | `+93.94` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1h` | `99.3%` | `0.7%` | `0.0%` | `+68.45` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1d` | `99.8%` | `0.2%` | `0.0%` | `+21.64` |

## Idea 10 — Separating Trading Skill from USDT/TMN FX Exposure
- **Overlap:** `2022-06-01..2026-11-18` (`1632` days)
- **Hold TMN:** `0.00%` · **Buy & Hold USDT (in TMN):** `777.59%` · **USDT Strategy Converted Back to TMN:** `2114.38%`
- **Pure USDT Trading Alpha (FX Stripped):** `152.33%` · **Direct `BTCTMN` Hold:** `1675.41%`
