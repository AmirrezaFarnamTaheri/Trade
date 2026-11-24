# Experiments A, B, and C: 33-Market Multi-Asset Expansion, ML Tilt + 4h Exit, and Paper Margin

- **Generated:** `2026-11-24T17:05:04.795206+00:00`
- **Eval Days:** `1639` (`2022-06-01..2026-11-24`, `$1,000` start, exact `SelfFinancingLedger`)
- **4h Crash Circuit-Breaker Days Triggered:** `76`
- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`

## 1. Spot Multi-Asset, Liquidity-Scaled ADMM, ML Tilt, 4h Exit & Tactical Leverage

| Arm | Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Borrow ($) | Turnover | Uplift vs 13-Asset Leader (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_13_S1_S5_LEADER` | `$2574.92` | `+157.52%` | `1.011` | `22.38%` | `-1.84%` | `$72.18` | `$0.00` | `55.5x` | `+0.00` `[+0.00, +0.00]` (`BASELINE`) |
| `EXP_A1_33_ASSETS_PLAIN` | `$2145.44` | `+114.57%` | `0.748` | `25.49%` | `-13.30%` | `$129.12` | `$0.00` | `99.3x` | `-0.81` `[-3.16, +1.53]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_A2_33_ASSETS_DEPTH_L2` | `$2146.32` | `+114.66%` | `0.750` | `25.44%` | `-12.73%` | `$122.00` | `$0.00` | `93.8x` | `-0.81` `[-3.11, +1.47]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_A3_33_ASSETS_DEPTH_L2_SPREAD_L1` | `$1957.74` | `+95.79%` | `0.695` | `23.86%` | `-10.44%` | `$66.24` | `$0.00` | `51.0x` | `-1.47` `[-3.86, +1.19]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_A4_33_ASSETS_NOBITEX_FEE` | `$2253.42` | `+125.36%` | `0.787` | `25.22%` | `-10.95%` | `$99.10` | `$0.00` | `108.9x` | `-0.51` `[-2.91, +1.89]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_B1_13_ASSETS_ML_CONTINUOUS_TILT` | `$2523.79` | `+152.41%` | `1.008` | `22.85%` | `-1.65%` | `$70.22` | `$0.00` | `54.0x` | `-0.15` `[-0.49, +0.13]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_B2_13_ASSETS_4H_CRASH_EXIT` | `$2754.52` | `+175.49%` | `1.089` | `22.07%` | `+5.76%` | `$113.54` | `$0.00` | `87.3x` | `+0.39` `[-0.40, +1.23]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_B3_33_ASSETS_DEPTH_ML_4H_COMBO` | `$2080.29` | `+108.05%` | `0.758` | `26.94%` | `-0.98%` | `$146.57` | `$0.00` | `112.8x` | `-1.14` `[-3.40, +1.33]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `EXP_C3_13_ASSETS_TACTICAL_1.35X_BULL` | `$2587.54` | `+158.79%` | `0.971` | `22.07%` | `-1.79%` | `$72.89` | `$145.14` | `56.1x` | `+0.13` `[-0.20, +0.42]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |

## 2. Standalone Paper Margin Strategies (Exact Wallex `0.015%/4h` = `32.85%/yr` Borrow + Bar-High Liquidations)

| Strategy | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Trades | Liquidations | Borrow ($) | Fees+Slip ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CRASH_CASCADE_SHORTS_1.5X` | `$1034.00` | `+3.40%` | `0.135` | `25.29%` | `99` | `0` | `$116.55` | `$144.79` |
| `MARKET_NEUTRAL_L1_PAIRS` | `$119.14` | `-88.09%` | `-1.209` | `89.00%` | `936` | `4` | `$292.01` | `$519.20` |
