# 3-Part Validation: Ignition Live-Spread Stress, Shared-Ledger 70/30 Blend, and True Intraday 3h Exit

- **Generated:** `2026-11-24T19:21:38.225388+00:00`
- **Daily Return Correlation (`S1+S5` vs `IGNITION_1H`):** Full `1,043d` = **`+0.1830`**, Bear Stress `366d` = **`+0.2251`**
- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`

## 1. Part 1 — Realistic Live-Spread Stress Test (`IGNITION_1H` & `IGNITION_2H` + `+1h` Offset)

| Sleeve | Bar | Offset | All-In Cost (bps/leg) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees+Spread ($) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IGNITION_1H_FEE13` | `1h` | `+0h` | `13.0` | `$1199.56` | `+19.96%` | `0.712` | `9.67%` | `138` | `40.6%` | `$123.83` |
| `IGNITION_1H_NOBITEX_ALLIN_16BPS` | `1h` | `+0h` | `16.0` | `$1170.21` | `+17.02%` | `0.623` | `10.26%` | `138` | `39.9%` | `$150.47` |
| `IGNITION_1H_WALLEX_ALLIN_25BPS` | `1h` | `+0h` | `25.0` | `$1086.18` | `+8.62%` | `0.351` | `12.02%` | `138` | `38.4%` | `$226.28` |
| `IGNITION_2H_0H_NOBITEX_16BPS` | `2h` | `+0h` | `16.0` | `$1198.19` | `+19.82%` | `0.668` | `9.79%` | `106` | `38.7%` | `$114.52` |
| `IGNITION_2H_1H_SHIFT_NOBITEX_16BPS` | `2h` | `+1h` | `16.0` | `$1293.13` | `+29.31%` | `1.064` | `6.83%` | `100` | `35.0%` | `$116.54` |
| `IGNITION_2H_0H_WALLEX_25BPS` | `2h` | `+0h` | `25.0` | `$1131.27` | `+13.13%` | `0.471` | `11.43%` | `106` | `38.7%` | `$173.80` |
| `IGNITION_2H_1H_SHIFT_WALLEX_25BPS` | `2h` | `+1h` | `25.0` | `$1225.01` | `+22.50%` | `0.855` | `7.61%` | `100` | `33.0%` | `$177.01` |

## 2. Part 2 — Single Shared-Ledger Combined Portfolio (`S1+S5` + `IGNITION_1H`, Exact `1h` Overlap)

| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Paired Uplift vs Matched Solo (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SOLO_100_S1_S5_FEE13` | `$1157.61` | `+15.76%` | `0.413` | `11.93%` | `-2.71%` | `$18.23` | `14.0x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `BLEND_70_30_S1S5_IGN1H_FEE13` | `$1176.95` | `+17.69%` | `0.555` | `9.29%` | `-1.30%` | `$49.60` | `38.1x` | `+0.02` `[-1.30, +1.33]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `BLEND_80_20_S1S5_IGN1H_FEE13` | `$1171.45` | `+17.15%` | `0.504` | `9.96%` | `-1.98%` | `$39.15` | `30.1x` | `+0.01` `[-0.95, +0.96]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `SOLO_100_S1_S5_NOBITEX_16BPS` | `$1153.29` | `+15.33%` | `0.404` | `11.96%` | `-2.84%` | `$22.39` | `14.0x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `BLEND_70_30_NOBITEX_16BPS` | `$1165.24` | `+16.52%` | `0.525` | `9.36%` | `-1.68%` | `$60.73` | `38.0x` | `-0.04` `[-1.37, +1.30]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `SOLO_100_S1_S5_WALLEX_25BPS` | `$1138.84` | `+13.88%` | `0.375` | `12.15%` | `-3.36%` | `$34.75` | `13.9x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `BLEND_70_30_WALLEX_25BPS` | `$1130.74` | `+13.07%` | `0.434` | `9.53%` | `-2.82%` | `$93.40` | `37.4x` | `-0.21` `[-1.55, +1.16]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |

## 3. Part 3 — True Intraday `3h` Execution Exit (Immediate Next-`3h`-Open Exit, Zero Lookahead)

| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Intraday Exits | Fees ($) | Paired Uplift vs No-Exit (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_3H_CLOCK_NO_EXIT_FEE13` | `$1156.91` | `+15.69%` | `0.419` | `10.39%` | `-2.10%` | `0` | `$18.13` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `TRUE_INTRADAY_3H_EXIT_0H_FEE13` | `$1056.04` | `+5.60%` | `0.207` | `11.95%` | `-2.67%` | `270` | `$59.37` | `-0.91` `[-2.22, +0.12]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `TRUE_INTRADAY_3H_EXIT_1H_SHIFT_FEE13` | `$1000.00` | `+0.00%` | `0.000` | `0.00%` | `+0.00%` | `0` | `$0.00` | `-1.70` `[-5.76, +1.90]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `TRUE_INTRADAY_3H_EXIT_0H_NOBITEX_16BPS` | `$1042.40` | `+4.24%` | `0.174` | `12.54%` | `-3.22%` | `270` | `$72.58` | `-1.03` `[-2.35, +0.01]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
