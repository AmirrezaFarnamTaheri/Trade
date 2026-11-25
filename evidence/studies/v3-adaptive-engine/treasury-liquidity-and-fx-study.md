# Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10)

- **Generated:** `2026-11-25T20:55:41.596203+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## Idea 7 — Marginal Value of +1 USDT per Venue (Prefunding Sweep, `$1,000` Fixed)

| Split (NBX / WLX) | Normal Exec Cost (bps) | Normal Missed% | 25% NBX-Outage Cost (bps) | 25% Outage Missed% |
| --- | ---: | ---: | ---: | ---: |
| `NBX_0_WLX_1000` | `+41.83` | `31.9%` | `+41.83` | `31.9%` |
| `NBX_250_WLX_750` | `+36.81` | `33.7%` | `+36.81` | `33.7%` |
| `NBX_500_WLX_500` | `+25.07` | `2.6%` | `+25.07` | `2.6%` |
| `NBX_750_WLX_250` | `+21.84` | `0.0%` | `+21.72` | `20.8%` |
| `NBX_1000_WLX_0` | `+22.44` | `0.0%` | `+21.69` | `25.0%` |

## Idea 8 — Gold Token Substitution (`XAUT` vs `PAXG`, +3% Issuer-Discount Stress)
- **Overlap Days:** `842` · **Cost-Aware Switches:** `49`
- **Unstressed Return:** `XAUT_ONLY=46.08%` · `SPLIT_50_50=46.78%` · `COST_AWARE_SWITCH=138.49%`
- **Under -3% XAUT Issuer Shock:** `{'xaut_only_pct': 41.7, 'split_50_50_pct': 44.59, 'cost_aware_switch_pct': 138.49}`

## Idea 9 — Cash Recoverable on Deadline (Live Walked L2 Depth)

| Book | Notional | Deadline | Cash Recovered% | Residual Inv% | Shortfall (bps) |
| --- | ---: | --- | ---: | ---: | ---: |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `5m` | `100.0%` | `0.0%` | `+26.12` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1h` | `100.0%` | `0.0%` | `+22.03` |
| `BTC_ETH_XAUT_CORE` | `$10,000` | `1d` | `100.0%` | `0.0%` | `+20.14` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `5m` | `92.2%` | `7.8%` | `+28.96` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1h` | `100.0%` | `0.0%` | `+26.45` |
| `BTC_ETH_XAUT_CORE` | `$50,000` | `1d` | `100.0%` | `0.0%` | `+22.03` |
| `ALT_HEAVY_BASKET` | `$10,000` | `5m` | `79.8%` | `20.2%` | `+41.42` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1h` | `100.0%` | `0.0%` | `+31.01` |
| `ALT_HEAVY_BASKET` | `$10,000` | `1d` | `100.0%` | `0.0%` | `+26.63` |
| `ALT_HEAVY_BASKET` | `$50,000` | `5m` | `22.2%` | `77.8%` | `+45.97` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1h` | `75.6%` | `24.4%` | `+42.49` |
| `ALT_HEAVY_BASKET` | `$50,000` | `1d` | `100.0%` | `0.0%` | `+31.01` |

## Idea 10 — Separating Trading Skill from USDT/TMN FX Exposure
- **Overlap:** `2022-06-01..2026-11-18` (`1632` days)
- **Hold TMN:** `0.00%` · **Buy & Hold USDT (in TMN):** `777.59%` · **USDT Strategy Converted Back to TMN:** `2114.38%`
- **Pure USDT Trading Alpha (FX Stripped):** `152.33%` · **Direct `BTCTMN` Hold:** `1675.41%`
