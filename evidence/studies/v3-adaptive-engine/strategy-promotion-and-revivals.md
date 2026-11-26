# Strategy Promotion, Conditional Capital Admission, Internal Netting & Partial Revivals

Generated UTC: `2026-11-26T15:28:24.422035+00:00` · Execution Mode: `PAPER_ONLY` (`TradingGYMExecutor DISARMED`, `$0` funded budget).

## 1. Conditional Capital Admission Hybrid & Contested-Capital Fork (`2h` Overlap, `16 bps/side`)

| Arm | Ending NAV | Return | Ann. Sharpe | MaxDD | Fees ($) | Full / Partial / Rejected Ign | Displaced Slow Buys |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |
| `SLOW_ALONE` | `$1,183.16` | `+18.32%` | `0.469` | `10.72%` | `$27.18` | `0 / 0 / 0` | `0` |
| `IGNITION_ALONE` | `$969.49` | `-3.05%` | `-0.030` | `14.81%` | `$177.78` | `192 / 0 / 0` | `0` |
| `ORDINARY_SHARING` | `$1,101.31` | `+10.13%` | `0.268` | `14.42%` | `$169.43` | `166 / 0 / 61` | `60` |
| `FIXED_SPLIT_70_30` | `$1,119.11` | `+11.91%` | `0.387` | `8.41%` | `$72.26` | `192 / 0 / 0` | `0` |
| `CONDITIONAL_SHARING_RES15` | `$1,114.90` | `+11.49%` | `0.295` | `14.10%` | `$141.15` | `82 / 55 / 97` | `0` |

- **Contested-Capital 24h Shadow Auction:** `30` contested slots -> Ignition win rate `63.3%`, mean `(Ignition - Slow)` = **`+135.58 bps`**.

## 2. Standalone Cross-Sleeve Internal Netting (`Slow $700` + `Ignition $300`, Identical Aggregate Exposure)

- **Crossed Events:** `2` · **Crossed Notional:** `$2.66`
- **Fees:** Separate Routing `$77.45` -> Internal Netting `$77.44` (**saved `$0.01` / `0.01%`**, aggregate exposure invariant verified: `True`).

## 3. Four Partial Revivals (Narrower Roles on Frozen Targets / Lots)

### 3A. S2 No-Trade Hysteresis Band (`1d` Slow `S1+S5`, `16 bps`)

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.91` | `+148.29%` | `0.775` | `23.65%` | `2715` | `$99.33` | `6.43%` |
| `FIXED_BAND_3PCT` | `$2,461.36` | `+146.14%` | `0.779` | `23.13%` | `685` | `$77.12` | `8.36%` |
| `COST_AWARE_BAND` | `$2,516.84` | `+151.68%` | `0.790` | `22.66%` | `646` | `$77.64` | `8.56%` |

### 3B. Bellman Exit-Only Challenger (Forked at First Disagreement on Identical `2h` Ignition Lots)

- **Status:** `OK` · **OOS Lots / States Evaluated:** `104` / `683` · **Disagreements (Early Close):** `6`
- **Mean `(Bellman - Incumbent)`:** **`-121.98 bps`** · Avoided Losses: `3` · Cut Winners: `3`

### 3C. Structural Bear Trigger as 1-Bar New-Spot-Buy Deferral vs Equal-Exposure Cash Control

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Mean Invested | Deferred Buys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.91` | `+148.29%` | `0.775` | `23.65%` | `22.95%` | `0` |
| `BEAR_DEFER_BUY_ONLY` | `$2,329.78` | `+132.98%` | `0.735` | `23.69%` | `21.88%` | `779` |
| `EQUAL_EXPOSURE_CASH_CONTROL` | `$2,399.79` | `+139.98%` | `0.777` | `22.50%` | `21.93%` | `0` |

### 3D. Trend Acceleration as Execution-Speed Control Toward Approved Targets

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.91` | `+148.29%` | `0.775` | `23.65%` | `2715` | `$99.33` | `6.43%` |
| `FIXED_PARTIAL_50PCT` | `$2,439.77` | `+143.98%` | `0.764` | `23.09%` | `2821` | `$82.31` | `7.66%` |
| `ACCEL_ADAPTIVE_SPEED` | `$2,439.70` | `+143.97%` | `0.763` | `23.36%` | `2544` | `$85.03` | `7.09%` |

## 4. Offline Research Gates (Hindsight Feasibility Ceiling & `0h` vs `+1h` Bar-Offset Harness)

| Mechanism | `0h` Signals | `+1h` Signals | Matched `<=2h` | Overlap % | Sensitivity Label |
| --- | ---: | ---: | ---: | ---: | :---: |
| `MOMENTUM_IGNITION` | `267` | `269` | `146` | `54.7%` | **`STABLE`** |
| `FAILED_DOWNSIDE_AUCTION` | `603` | `638` | `170` | `28.2%` | **`TIMING_SENSITIVE`** |

- **Offline Hindsight DP Ceiling (`BTCUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$1,692,168,975,741.54` across `12502` bars.
- **Offline Hindsight DP Ceiling (`ETHUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$1,798,728,432,726.70` across `8334` bars.
- **Offline Hindsight DP Ceiling (`SOLUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$396,375,294,298,271.69` across `8335` bars.
