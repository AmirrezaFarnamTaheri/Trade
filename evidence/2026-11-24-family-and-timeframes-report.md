# Multi-Timeframe (2h/3h/6h), Asset-Family Architecture (13 vs 18 vs 33), and Rare High-Momentum Ignition

- **Generated:** `2026-11-24T19:08:09.924496+00:00`
- **Eval Days:** `1639` (`2022-06-01..2026-11-24`, `$1,000` start, exact `SelfFinancingLedger`)
- **Intraday Crash Days Triggered:** `2h=86`, `3h(0h)=81`, `3h(+1h)=84`, `6h(0h)=77`, `6h(+1h)=73`
- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`

## 1. Portfolio Arms: 2h/3h/6h Crash Breakers (+1h Clock-Shift Check) & Family-Differentiated 18/33-Asset Cores

| Arm | Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Uplift vs Base 13 (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_13_S1_S5` | `$2574.92` | `+157.52%` | `1.011` | `22.38%` | `-1.84%` | `$72.18` | `55.5x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `CORE_13_CRASH_2H_0H` | `$2304.17` | `+130.45%` | `0.913` | `22.07%` | `-0.42%` | `$107.72` | `82.9x` | `-0.70` `[-1.71, +0.01]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `CORE_13_CRASH_3H_0H` | `$2415.77` | `+141.61%` | `0.961` | `22.07%` | `+0.39%` | `$112.73` | `86.7x` | `-0.41` `[-1.33, +0.31]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `CORE_13_CRASH_3H_1H_SHIFT` | `$2370.64` | `+137.09%` | `0.941` | `22.07%` | `+0.37%` | `$102.32` | `78.7x` | `-0.52` `[-1.37, +0.19]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `CORE_13_CRASH_6H_0H` | `$2304.35` | `+130.46%` | `0.913` | `22.07%` | `-2.90%` | `$102.92` | `79.2x` | `-0.69` `[-1.68, -0.02]` (`BELOW_THRESHOLD`) |
| `CORE_13_CRASH_6H_1H_SHIFT` | `$2323.54` | `+132.38%` | `0.922` | `22.07%` | `+0.59%` | `$103.59` | `79.7x` | `-0.65` `[-1.75, +0.20]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `MACRO_18_FAMILY_ONLY` | `$2558.04` | `+155.84%` | `0.897` | `23.50%` | `-8.90%` | `$112.00` | `86.2x` | `+0.23` `[-1.46, +1.98]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `MACRO_18_FAMILY_CRASH_3H` | `$2388.59` | `+138.89%` | `0.847` | `23.50%` | `-6.75%` | `$151.21` | `116.3x` | `-0.20` `[-1.88, +1.61]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `MACRO_18_FAMILY_CRASH_6H` | `$2273.83` | `+127.41%` | `0.805` | `23.50%` | `-9.93%` | `$140.02` | `107.7x` | `-0.50` `[-2.38, +1.20]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `MACRO_18_CRASH_3H_NOBITEX_FEE` | `$2462.24` | `+146.25%` | `0.871` | `23.40%` | `-7.20%` | `$121.60` | `133.6x` | `-0.01` `[-1.75, +1.77]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `FAMILY_GATED_33_ASSETS_PLAIN` | `$2381.48` | `+138.18%` | `0.853` | `23.58%` | `-6.50%` | `$125.24` | `96.3x` | `-0.25` `[-1.80, +1.66]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `FAMILY_GATED_33_ASSETS_CRASH_3H` | `$2223.69` | `+122.40%` | `0.803` | `23.58%` | `-6.34%` | `$155.53` | `119.6x` | `-0.69` `[-2.53, +1.55]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `FAMILY_GATED_33_ASSETS_CRASH_6H` | `$2090.35` | `+109.06%` | `0.749` | `23.58%` | `-9.77%` | `$146.72` | `112.9x` | `-1.06` `[-2.98, +0.78]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |

## 2. Rare Ultra-Strong High-Momentum Ignition Sleeve (`1h`, `2h`, `3h` + `+1h` Clock-Shift & Nobitex Counterfactual)

| Sleeve | Bar | Offset | Fee (bps) | Days | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees ($) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IGNITION_1H_WALLEX` | `1h` | `+0h` | `13.0` | `1043` | `$1199.56` | `+19.96%` | `0.712` | `9.67%` | `138` | `40.6%` | `$123.83` |
| `IGNITION_1H_NOBITEX` | `1h` | `+0h` | `9.1` | `1043` | `$1239.40` | `+23.94%` | `0.829` | `8.88%` | `138` | `42.8%` | `$88.17` |
| `IGNITION_2H_0H_WALLEX` | `2h` | `+0h` | `13.0` | `1043` | `$1220.90` | `+22.09%` | `0.733` | `9.24%` | `106` | `40.6%` | `$93.98` |
| `IGNITION_3H_0H_WALLEX` | `3h` | `+0h` | `13.0` | `1043` | `$1064.62` | `+6.46%` | `0.282` | `13.96%` | `88` | `36.4%` | `$74.07` |
| `IGNITION_3H_1H_SHIFT_WALLEX` | `3h` | `+1h` | `13.0` | `1043` | `$1273.63` | `+27.36%` | `0.942` | `10.61%` | `83` | `43.4%` | `$75.91` |
| `IGNITION_3H_0H_NOBITEX` | `3h` | `+0h` | `9.1` | `1043` | `$1086.72` | `+8.67%` | `0.360` | `13.31%` | `88` | `36.4%` | `$52.39` |
