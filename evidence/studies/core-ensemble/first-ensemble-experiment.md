# First Paper Experiment — Slow Sleeves, Fixed Controls & Veto-Only Calibrated Logistic Challenger

**Generated (UTC):** `2026-11-25T20:30:47.160772+00:00` · **Primary Bar Source:** `NATIVE_1D` · **Estimand:** `RETROSPECTIVE_CURATED_LIQUID_WALLEX_USDT_COHORT` · **Disposition:** **`INCONCLUSIVE`**
**Stress Window Classification:** `BEAR_STRESS_REPLAY_SEEN (2025-11-24..2026-11-23)` (previously seen — never counted as untouched final holdout). **Executor:** `DISARMED` (`$0` funded budget).

## 1. Repaired Solver & Synthetic Falsification Gate

- **Binding-Budget Solver Check (`(0.5, 0.5) -> (0.0, 1.0)`):** weights=`[0.0, 1.0]`, utility=`0.054` (expected `0.0540`), converged=`True`.
- **Synthetic Null Panel:** `rejected_noise=True`, `BSS=-0.0033`, `accept_rate=0.0`.
- **Synthetic Planted-Edge Panel:** `recovered=True`, `BSS=0.6935`, `veto_uplift=+150.99 bps`.

## 2. Arm-by-Arm Self-Financing Wallex Spot Comparison (`$1,000` Starting Cash, Exact Received-Asset Fees)

| Arm | Full Ending ($) | Full Ret (%) | Full Sharpe | Full MaxDD (%) | Dev Ret (%) | Stress-Seen Ret (%) | Stress MaxDD (%) | Fills | Fees ($) | Turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `CASH_USDT` | 1000.0 | 0.0% | 0.0 | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0 | 0.0x |
| `STATIC_GOLD_AND_CRYPTO` | 1345.2 | 34.69% | 0.392 | 60.36% | 117.02% | -38.99% | 44.97% | 12 | 1.24 | 0.95x |
| `FIXED_S1` | 2537.59 | 153.79% | 0.997 | 22.21% | 161.42% | -2.89% | 10.95% | 2070 | 66.76 | 51.35x |
| `FIXED_ENSEMBLE_S1_S2_S5` | 2678.14 | 167.92% | 0.91 | 25.75% | 204.0% | -11.61% | 16.83% | 2525 | 216.84 | 166.8x |
| `ADAPTIVE_VOTE` | 2455.52 | 145.65% | 0.935 | 22.21% | 174.3% | -10.24% | 15.25% | 2236 | 157.56 | 121.2x |
| `LOGISTIC_VETO` | 2682.26 | 168.33% | 0.911 | 25.75% | 204.0% | -11.47% | 16.7% | 2523 | 216.7 | 166.7x |

### Paired Bootstrap & Logistic Veto Shadow Diagnostics

- **Logistic Train Calibration (Chronological Inner Fold):** `proposals=6362`, `Brier=0.247`, `BSS=0.0118`, `ECE=0.0051`.
- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Full):** status=`NO_EVIDENCE_NOT_ESTABLISHED`, CI95=`[-6.312329576420056e-13, 2.7622876675806403e-06]`.
- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Bear Stress):** status=`POSITIVE_EXPLORATORY`, CI95=`[6.573755375956032e-11, 1.635938474436474e-05]`.
- **Shadow Veto Audit:** `{'total_proposals': 513, 'accepted_count': 468, 'vetoed_count': 45, 'accepted_mean_net_bps': -42.1, 'vetoed_mean_net_bps': -264.75, 'avoided_losses_count': 30, 'foregone_winners_count': 15, 'net_veto_uplift_bps': 19.53}`
- **Wallex Path Under Hypothetical Nobitex `-30%` Fee Counterfactual (`FIXED_ENSEMBLE_S1_S2_S5`):** `{'days': 1639, 'ending_nav': 2818.6, 'ret_pct': 181.94, 'ann_sharpe': 0.948, 'max_dd_pct': 25.01}`

## 3. Leave-One-Sleeve-Out Marginal Contribution (`FIXED_ENSEMBLE_S1_S2_S5`)

| Ablation | Ending ($) | Full Ret (%) | Ann. Sharpe | MaxDD (%) |
| --- | ---: | ---: | ---: | ---: |
| `DROP_S1` | 2520.34 | 152.13% | 0.782 | 31.26% |
| `DROP_S2` | 2579.41 | 157.97% | 1.012 | 22.21% |
| `DROP_S5` | 2632.85 | 163.39% | 0.896 | 25.75% |

## 4. 2025 Coverage & Native `1d` vs Resampled `1h` Bar-Parity Audit

| Symbol | Daily Bars | Zero-Vol Days | Hourly Bars | Zero-Vol Hours | Complete Days Compared | Unequal Open Days | Max Open Gap (bps) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BTCUSDT` | 327 | 0 | 7825 | 33 | 326 | 9 | 225.29 |
| `ETHUSDT` | 327 | 0 | 7825 | 45 | 326 | 14 | 477.48 |
| `SOLUSDT` | 327 | 0 | 7825 | 66 | 326 | 13 | 640.2 |
| `AAVEUSDT` | 327 | 0 | 7804 | 3745 | 320 | 184 | 917.43 |
| `XAUTUSDT` | 327 | 0 | 7818 | 1365 | 323 | 115 | 153.29 |

- **Bar-Source Sensitivity (`FIXED_S1` on `RESAMPLED_1H` 2025–2026):** `{'days': 621, 'ending_nav': 1137.02, 'ret_pct': 13.72, 'ann_sharpe': 0.637, 'max_dd_pct': 9.41}`
