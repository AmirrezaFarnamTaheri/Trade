# Ignition Expansion Study: 18-Market 1h/2h Scanner, 70/30 Shared-Ledger Blends, and 15m/30m Sub-Hourly Probe

- **Generated:** `2026-11-24T19:26:47.528713+00:00`
- **Correlation vs `S1+S5`:** `IGN18_2H` = **`+0.2033`**, `IGN18_1H` = **`+0.2133`**
- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`

## 1. Part A — 18-Market Rare Ignition (`1h` & `2h`, `0h`/`+1h` Offset, Live All-In Spread+Fee)

| Sleeve | Bar | Offset | All-In Cost (bps) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees+Spread ($) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IGN18_1H_NOBITEX_16BPS` | `1h` | `+0h` | `16.0` | `$1036.40` | `+3.64%` | `0.164` | `16.39%` | `214` | `36.4%` | `$219.59` |
| `IGN18_1H_WALLEX_25BPS` | `1h` | `+0h` | `25.0` | `$922.84` | `-7.72%` | `-0.181` | `20.53%` | `214` | `35.5%` | `$323.82` |
| `IGN18_2H_0H_NOBITEX_16BPS` | `2h` | `+0h` | `16.0` | `$1320.28` | `+32.03%` | `0.754` | `13.21%` | `175` | `37.7%` | `$198.44` |
| `IGN18_2H_1H_SHIFT_NOBITEX_16BPS` | `2h` | `+1h` | `16.0` | `$1178.82` | `+17.88%` | `0.492` | `9.41%` | `170` | `37.1%` | `$183.68` |
| `IGN18_2H_0H_WALLEX_25BPS` | `2h` | `+0h` | `25.0` | `$1200.00` | `+20.00%` | `0.519` | `14.85%` | `175` | `37.7%` | `$295.15` |
| `IGN18_2H_1H_SHIFT_WALLEX_25BPS` | `2h` | `+1h` | `25.0` | `$1075.31` | `+7.53%` | `0.255` | `11.48%` | `170` | `35.3%` | `$273.81` |

## 2. Part B — Single Shared-Ledger Blends (`70% BASE_13_S1_S5 + 30% IGNITION_2H` / `18MKT`)

| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Paired Uplift vs Solo (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SOLO_100_S1S5_NOBITEX_16BPS` | `$1153.29` | `+15.33%` | `0.404` | `11.96%` | `-2.84%` | `$22.39` | `14.0x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `BLEND_70_30_IGN8_2H_NOBITEX_16BPS` | `$1161.86` | `+16.19%` | `0.512` | `8.50%` | `-0.51%` | `$48.94` | `30.6x` | `-0.06` `[-1.60, +1.35]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `BLEND_70_30_IGN18_2H_NOBITEX_16BPS` | `$1216.13` | `+21.61%` | `0.610` | `8.54%` | `+2.14%` | `$72.55` | `45.3x` | `+0.41` `[-1.07, +1.90]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `BLEND_70_30_IGN18_1H_NOBITEX_16BPS` | `$1104.50` | `+10.45%` | `0.351` | `11.74%` | `-3.63%` | `$83.59` | `52.2x` | `-0.54` `[-2.00, +0.92]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `SOLO_100_S1S5_WALLEX_25BPS` | `$1138.84` | `+13.88%` | `0.375` | `12.15%` | `-3.36%` | `$34.75` | `13.9x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `BLEND_70_30_IGN18_2H_WALLEX_25BPS` | `$1174.56` | `+17.46%` | `0.513` | `8.61%` | `+0.75%` | `$111.26` | `44.5x` | `+0.19` `[-1.34, +1.67]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |

## 3. Part C — Sub-Hourly `15m` & `30m` Probe (25-Day Live `1min` Archive, `2026-10-30..2026-11-24`)

| Sleeve | Bar | Cost (bps) | Days | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees ($) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IGN_30M_NOBITEX_16BPS` | `30m` | `16.0` | `24` | `$965.45` | `-3.45%` | `-4.188` | `4.16%` | `4` | `25.0%` | `$3.34` |
| `IGN_30M_WALLEX_25BPS` | `30m` | `25.0` | `24` | `$963.64` | `-3.64%` | `-4.332` | `4.26%` | `4` | `25.0%` | `$5.22` |
| `IGN_15M_NOBITEX_16BPS` | `15m` | `16.0` | `24` | `$974.26` | `-2.57%` | `-4.286` | `3.51%` | `4` | `75.0%` | `$3.80` |
| `IGN_15M_WALLEX_25BPS` | `15m` | `25.0` | `24` | `$972.17` | `-2.78%` | `-4.565` | `3.64%` | `4` | `50.0%` | `$5.94` |
