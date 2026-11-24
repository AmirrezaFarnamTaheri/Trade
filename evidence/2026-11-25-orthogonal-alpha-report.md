# Orthogonal Alpha Study (3A: Flush Rebound & Dead-Cat Short, 3B: Covariance-Only GRU-Vol, 3C: PAXG & Macro Commodities)

- **Generated:** `2026-11-24T21:14:38.131237+00:00`
- **Causality:** Strict next-bar open execution, purged yearly walk-forward for GRU-Vol, exact Wallex `0.015%/4h` borrow & bar-high liquidations on shorts.

## Study 3A — 2h Spot Capitulation-Flush Rebound & Bear Dead-Cat Exhaustion Short

| Arm | Offset | Cost (bps) | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Liqs | Borrow | Corr vs Base |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `FLUSH_REBOUND_2H_NBX16_OFF0H` | `+0h` | `16.0` | `$993.67` | `-0.63%` | `+14.70%` | `0.066` | `19.36%` | `325` | `46.8%` | `0` | `$0.00` | `-0.024` |
| `FLUSH_REBOUND_2H_WLX25_OFF0H` | `+0h` | `25.0` | `$833.52` | `-16.65%` | `+5.19%` | `-0.301` | `26.64%` | `325` | `44.9%` | `0` | `$0.00` | `-0.015` |
| `FLUSH_REBOUND_2H_NBX16_OFF1H` | `+1h` | `16.0` | `$610.56` | `-38.94%` | `-18.79%` | `-0.701` | `41.05%` | `368` | `40.2%` | `0` | `$0.00` | `-0.015` |
| `FLUSH_REBOUND_2H_WLX25_OFF1H` | `+1h` | `25.0` | `$500.21` | `-49.98%` | `-26.97%` | `-1.007` | `50.73%` | `368` | `38.6%` | `0` | `$0.00` | `-0.007` |
| `FLUSH_REBOUND_BEAR45_NBX16_OFF0H` | `+0h` | `16.0` | `$861.28` | `-13.87%` | `+3.92%` | `-0.281` | `27.32%` | `238` | `45.4%` | `0` | `$0.00` | `-0.028` |
| `FLUSH_REBOUND_BEAR45_NBX16_OFF1H` | `+1h` | `16.0` | `$628.68` | `-37.13%` | `-20.71%` | `-0.932` | `41.10%` | `267` | `37.5%` | `0` | `$0.00` | `-0.021` |
| `DEADCAT_SHORT_2H_NBX16_OFF0H` | `+0h` | `16.0` | `$503.06` | `-49.69%` | `-21.67%` | `-0.875` | `60.60%` | `497` | `37.6%` | `0` | `$93.05` | `-0.009` |
| `DEADCAT_SHORT_2H_WLX25_OFF0H` | `+0h` | `25.0` | `$384.63` | `-61.54%` | `-32.30%` | `-1.244` | `69.10%` | `497` | `35.4%` | `0` | `$82.96` | `-0.005` |
| `DEADCAT_SHORT_2H_NBX16_OFF1H` | `+1h` | `16.0` | `$421.99` | `-57.80%` | `-28.12%` | `-1.196` | `65.41%` | `487` | `38.2%` | `0` | `$87.09` | `-0.015` |
| `DEADCAT_SHORT_2H_WLX25_OFF1H` | `+1h` | `25.0` | `$324.22` | `-67.58%` | `-37.34%` | `-1.572` | `72.58%` | `487` | `36.3%` | `0` | `$78.02` | `-0.010` |

## Study 3B — GRU-Vol Wired Strictly Into Covariance / Vol-Target (mu_h Untouched)

| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | Mean Uplift (bps/d) | 95% CI (bps/d) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_13_S1_S5` | `$2574.92` | `+157.52%` | `-1.84%` | `1.011` | `22.38%` | `$72.18` | `0.00` | `baseline` |
| `GRU_VOL_COV_ONLY` | `$1977.90` | `+97.80%` | `-3.70%` | `0.740` | `25.78%` | `$80.37` | `-1.54` | `[-3.85, +0.52]` |
| `GRU_VOL_COV_PLUS_VT22` | `$1663.91` | `+66.40%` | `-2.07%` | `0.710` | `23.75%` | `$72.14` | `-2.97` | `[-5.71, -0.06]` |

## Study 3C — PAXG Gold Upgrade & Standalone Non-Crypto Macro Commodity Sleeve

| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | Corr / Uplift |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_13_XAUT (841d gold)` | `$2574.92` | `+157.52%` | `-1.84%` | `1.011` | `22.38%` | `$72.18` | `baseline` |
| `BASE_13_PAXG (1635d gold)` | `$2407.40` | `+140.77%` | `-6.38%` | `0.865` | `23.24%` | `$86.95` | `vs XAUT: -0.20 bps/d [-1.39, +1.48]` |
| `MACRO_COMMODITIES_RP_TREND` | `$1243.46` | `+24.35%` | `-9.35%` | `0.453` | `20.98%` | `$32.75` | `corr vs Base: +0.082, avg exp 27.4%` |
| `BLEND_80_PAXG13_20_MACRO` | `$2157.83` | `+115.78%` | `-6.81%` | `0.722` | `18.15%` | `$74.63` | `vs PAXG13: -0.99 bps/d [-2.49, +0.27]` |
