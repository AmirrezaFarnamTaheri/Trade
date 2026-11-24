# Standing Leader Deep-Dive: S2 Hysteresis, Factor & 2x2 Entry/Exit Attribution, and Causal Execution

- **Generated:** `2026-11-24T11:38:50.162725+00:00`
- **Eval Days:** `1639` (`1d` cohort panel from `2022-06-01`, exact `SelfFinancingLedger`, `$1,000` start, `13 bps` Wallex L1 fee)

## 1. Study A — Low-Turnover S2 Incumbent Retention Hysteresis Band

| Arm | Full Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress Ret % | Fees ($) | Turnover | Mean Uplift vs DROP_S2 (bps/day) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `DROP_S2_LEADER` | `$2574.92` | `+157.52%` | `1.011` | `22.38%` | `-1.84%` | `$72.18` | `55.5x` | `+0.00` [+0.00, +0.00] (BASELINE) |
| `RAW_S1_S2_S5` | `$2783.43` | `+178.34%` | `0.940` | `25.79%` | `-11.47%` | `$223.08` | `171.6x` | `+0.83` [-2.72, +4.36] (NO_EVIDENCE_NOT_ESTABLISHED) |
| `S2_HYSTERESIS_25_55` | `$2827.31` | `+182.74%` | `0.921` | `29.95%` | `-11.23%` | `$198.25` | `152.5x` | `+1.05` [-2.43, +4.67] (NO_EVIDENCE_NOT_ESTABLISHED) |
| `S2_HYSTERESIS_25_70` | `$2808.48` | `+180.86%` | `0.912` | `29.91%` | `-11.73%` | `$197.41` | `151.8x` | `+1.02` [-2.54, +4.73] (NO_EVIDENCE_NOT_ESTABLISHED) |

## 2. Study B1 — BTC + Gold Factor Attribution (OLS on Daily Returns)

| Arm | Obs | Ann. Alpha % | Beta BTC | Beta Gold | R² | Residual Ann. Sharpe | Total Ann. Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `DROP_S2_LEADER` | `839` | `+27.65%` | `0.221` | `0.099` | `0.213` | `1.346` | `1.416` |
| `RAW_S1_S2_S5` | `839` | `+25.34%` | `0.276` | `0.095` | `0.247` | `1.114` | `1.189` |
| `S2_HYSTERESIS_25_55` | `839` | `+26.95%` | `0.294` | `0.088` | `0.260` | `1.166` | `1.223` |
| `STATIC_GOLD_AND_CRYPTO` | `839` | `+5.78%` | `0.974` | `0.045` | `0.714` | `0.211` | `0.391` |

## 3. Study B2 — 2x2 Entry vs. Exit Decomposition on `S1 + S5`

| Cell | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress Ret % | Avg Gross Exp | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `REAL_ENTRY_SLEEVE_EXIT` | `$2209.25` | `+121.00%` | `0.640` | `42.39%` | `-3.78%` | `0.659` | `$130.55` |
| `REAL_ENTRY_FIXED_20D_EXIT` | `$2227.51` | `+122.82%` | `0.647` | `41.49%` | `-12.39%` | `0.679` | `$160.10` |
| `RANDOM_ENTRY_SLEEVE_EXIT_5SEED_AVG` | `$2055.60` | `+105.63%` | `0.594` | `46.69%` | `-2.97%` | `0.653` | `$242.31` |
| `RANDOM_ENTRY_FIXED_20D_EXIT_5SEED_AVG` | `$1156.65` | `+15.70%` | `0.306` | `59.71%` | `-30.31%` | `0.815` | `$275.83` |

## 4. Study C — Causal Execution-Policy Comparison (Zero Lookahead `p35`, BUY & SELL, Displayed Size)

| Symbol | Side | N | Causal p35 (bps) | Immediate (bps) | Fixed Passive (bps) | Opportunistic (bps) | FP Savings (bps) | Opp Savings (bps) | Unfilled (I/F/O) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BTCUSDT` | `BUY` | `12` | `30.34` | `26.13` | `15.99` | `15.99` | `+10.14` | `+10.14` | `8/9/9` |
| `BTCUSDT` | `SELL` | `12` | `30.34` | `26.09` | `32.09` | `32.09` | `-6.00` | `-6.00` | `5/6/6` |
| `ETHUSDT` | `BUY` | `12` | `28.18` | `26.55` | `27.05` | `28.06` | `-0.50` | `-1.50` | `7/6/6` |
| `ETHUSDT` | `SELL` | `12` | `28.18` | `26.52` | `30.26` | `30.20` | `-3.74` | `-3.68` | `4/4/4` |
| `SOLUSDT` | `BUY` | `12` | `33.24` | `28.97` | `10.35` | `8.80` | `+18.62` | `+20.17` | `6/7/6` |
| `SOLUSDT` | `SELL` | `12` | `33.24` | `28.93` | `47.45` | `47.45` | `-18.52` | `-18.52` | `5/8/8` |
| `XRPUSDT` | `BUY` | `12` | `32.53` | `26.78` | `26.81` | `26.81` | `-0.03` | `-0.03` | `5/6/6` |
| `XRPUSDT` | `SELL` | `12` | `32.53` | `26.75` | `29.94` | `29.86` | `-3.19` | `-3.11` | `8/8/8` |
| `XAUTUSDT` | `BUY` | `12` | `39.78` | `53.32` | `48.74` | `48.74` | `+4.58` | `+4.58` | `10/11/11` |
| `XAUTUSDT` | `SELL` | `12` | `39.78` | `53.22` | `57.32` | `57.32` | `-4.10` | `-4.10` | `9/8/8` |
| `PEPEUSDT` | `BUY` | `12` | `46.36` | `36.96` | `25.89` | `27.19` | `+11.07` | `+9.78` | `7/6/5` |
| `PEPEUSDT` | `SELL` | `12` | `46.36` | `36.90` | `48.53` | `44.53` | `-11.63` | `-7.63` | `4/7/7` |
