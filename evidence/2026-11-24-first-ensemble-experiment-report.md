# First Paper Experiment — Slow Sleeves, Fixed Controls & Veto-Only Calibrated Logistic Challenger

**Generated (UTC):** `2026-11-24T10:23:20.333067+00:00` · **Primary Bar Source:** `NATIVE_1D` · **Estimand:** `RETROSPECTIVE_CURATED_LIQUID_WALLEX_USDT_COHORT` · **Disposition:** **`RETIRE_INCREMENT`**
**Stress Window Classification:** `BEAR_STRESS_REPLAY_SEEN (2025-11-24..2026-11-23)` (previously seen — never counted as untouched final holdout). **Executor:** `DISARMED` (`$0` funded budget).

## 1. Repaired Solver & Synthetic Falsification Gate

- **Binding-Budget Solver Check (`(0.5, 0.5) -> (0.0, 1.0)`):** weights=`[0.0, 1.0]`, utility=`0.054` (expected `0.0540`), converged=`True`.
- **Synthetic Null Panel:** `rejected_noise=True`, `BSS=-0.0033`, `accept_rate=0.0`.
- **Synthetic Planted-Edge Panel:** `recovered=True`, `BSS=0.6935`, `veto_uplift=+150.99 bps`.

## 2. Arm-by-Arm Self-Financing Wallex Spot Comparison (`$1,000` Starting Cash, Exact Received-Asset Fees)

| Arm | Full Ending ($) | Full Ret (%) | Full Sharpe | Full MaxDD (%) | Dev Ret (%) | Stress-Seen Ret (%) | Stress MaxDD (%) | Fills | Fees ($) | Turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CASH_USDT` | 1000.0 | 0.0% | 0.0 | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0 | 0.0x |
| `STATIC_GOLD_AND_CRYPTO` | 1999.07 | 100.15% | 0.558 | 58.24% | 210.8% | -36.44% | 43.64% | 4535 | 55.38 | 42.6x |
| `FIXED_S1` | 2533.54 | 153.39% | 0.996 | 22.38% | 160.99% | -2.88% | 10.95% | 2068 | 66.64 | 51.26x |
| `FIXED_ENSEMBLE_S1_S2_S5` | 2783.43 | 178.34% | 0.94 | 25.79% | 215.35% | -11.47% | 16.81% | 2516 | 223.08 | 171.6x |
| `ADAPTIVE_VOTE` | 2507.88 | 150.79% | 0.955 | 22.24% | 179.79% | -10.16% | 15.25% | 2224 | 159.43 | 122.64x |
| `LOGISTIC_VETO` | 2072.1 | 107.21% | 0.834 | 24.74% | 129.27% | -9.35% | 15.58% | 1866 | 130.95 | 100.73x |

### Paired Bootstrap & Logistic Veto Shadow Diagnostics

- **Logistic Train Calibration (Chronological Inner Fold):** `proposals=6340`, `Brier=0.2466`, `BSS=0.0133`, `ECE=0.0035`.
- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Full):** status=`NO_EVIDENCE_NOT_ESTABLISHED`, CI95=`[-0.000662267972865439, 0.00016278070948271881]`.
- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Bear Stress):** status=`NO_EVIDENCE_NOT_ESTABLISHED`, CI95=`[-1.853027850158994e-05, 0.00017094489209011624]`.
- **Shadow Veto Audit:** `{'total_proposals': 4401, 'accepted_count': 2007, 'vetoed_count': 2394, 'accepted_mean_net_bps': 38.8, 'vetoed_mean_net_bps': 23.09, 'avoided_losses_count': 1332, 'foregone_winners_count': 1062, 'net_veto_uplift_bps': 8.55}`
- **Wallex Path Under Hypothetical Nobitex `-30%` Fee Counterfactual (`FIXED_ENSEMBLE_S1_S2_S5`):** `{'days': 1638, 'ending_nav': 2930.19, 'ret_pct': 193.02, 'ann_sharpe': 0.979, 'max_dd_pct': 25.05}`

## 3. Leave-One-Sleeve-Out Marginal Contribution (`FIXED_ENSEMBLE_S1_S2_S5`)

| Ablation | Ending ($) | Full Ret (%) | Ann. Sharpe | MaxDD (%) |
| --- | ---: | ---: | ---: | ---: |
| `DROP_S1` | 2561.54 | 156.15% | 0.794 | 30.91% |
| `DROP_S2` | 2574.9 | 157.52% | 1.011 | 22.38% |
| `DROP_S5` | 2736.67 | 173.67% | 0.927 | 25.79% |

## 4. 2025 Coverage & Native `1d` vs Resampled `1h` Bar-Parity Audit

| Symbol | Daily Bars | Zero-Vol Days | Hourly Bars | Zero-Vol Hours | Complete Days Compared | Unequal Open Days | Max Open Gap (bps) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BTCUSDT` | 327 | 0 | 7825 | 33 | 326 | 9 | 225.29 |
| `ETHUSDT` | 327 | 0 | 7825 | 45 | 326 | 14 | 477.48 |
| `SOLUSDT` | 327 | 0 | 7825 | 66 | 326 | 13 | 640.2 |
| `AAVEUSDT` | 327 | 0 | 7804 | 3745 | 320 | 184 | 917.43 |
| `XAUTUSDT` | 327 | 0 | 7818 | 1365 | 323 | 115 | 153.29 |

- **Bar-Source Sensitivity (`FIXED_S1` on `RESAMPLED_1H` 2025–2026):** `{'days': 613, 'ending_nav': 1137.51, 'ret_pct': 13.76, 'ann_sharpe': 0.643, 'max_dd_pct': 9.41}`
