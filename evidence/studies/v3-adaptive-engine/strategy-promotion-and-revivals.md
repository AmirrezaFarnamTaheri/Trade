# Strategy Promotion, Conditional Capital Admission, Internal Netting & Partial Revivals

Generated UTC: `2026-11-26T08:47:48.337291+00:00` · Execution Mode: `PAPER_ONLY` (`TradingGYMExecutor DISARMED`, `$0` funded budget).

## 1. Conditional Capital Admission Hybrid & Contested-Capital Fork (`2h` Overlap, `16 bps/side`)

| Arm | Ending NAV | Return | Ann. Sharpe | MaxDD | Fees ($) | Full / Partial / Rejected Ign | Displaced Slow Buys |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |
| `SLOW_ALONE` | `$1,181.55` | `+18.15%` | `0.469` | `10.72%` | `$27.08` | `0 / 0 / 0` | `0` |
| `IGNITION_ALONE` | `$969.49` | `-3.05%` | `-0.030` | `14.81%` | `$177.78` | `192 / 0 / 0` | `0` |
| `ORDINARY_SHARING` | `$1,099.81` | `+9.98%` | `0.268` | `14.42%` | `$169.14` | `166 / 0 / 61` | `60` |
| `FIXED_SPLIT_70_30` | `$1,117.95` | `+11.79%` | `0.386` | `8.40%` | `$72.19` | `192 / 0 / 0` | `0` |
| `CONDITIONAL_SHARING_RES15` | `$1,113.39` | `+11.34%` | `0.295` | `14.10%` | `$140.89` | `82 / 55 / 97` | `0` |

- **Contested-Capital 24h Shadow Auction:** `30` contested slots -> Ignition win rate `63.3%`, mean `(Ignition - Slow)` = **`+135.58 bps`**.

## 2. Standalone Cross-Sleeve Internal Netting (`Slow $700` + `Ignition $300`, Identical Aggregate Exposure)

- **Crossed Events:** `2` · **Crossed Notional:** `$2.66`
- **Fees:** Separate Routing `$77.38` -> Internal Netting `$77.37` (**saved `$0.01` / `0.01%`**, aggregate exposure invariant verified: `True`).

## 3. Four Partial Revivals (Narrower Roles on Frozen Targets / Lots)

### 3A. S2 No-Trade Hysteresis Band (`1d` Slow `S1+S5`, `16 bps`)

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.75` | `+148.28%` | `0.775` | `23.65%` | `2715` | `$99.33` | `6.43%` |
| `FIXED_BAND_3PCT` | `$2,461.36` | `+146.14%` | `0.779` | `23.13%` | `685` | `$77.12` | `8.36%` |
| `COST_AWARE_BAND` | `$2,516.75` | `+151.67%` | `0.790` | `22.66%` | `646` | `$77.64` | `8.56%` |

### 3B. Bellman Exit-Only Challenger (Forked at First Disagreement on Identical `2h` Ignition Lots)

- **OOS States Evaluated:** `749` · **Disagreements (Early Close):** `19`
- **Mean `(Bellman - Incumbent)`:** **`-66.64 bps`** · Avoided Losses: `7` · Cut Winners: `12`

### 3C. Structural Bear Trigger as 1-Bar New-Spot-Buy Deferral vs Equal-Exposure Cash Control

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Mean Invested | Deferred Buys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.75` | `+148.28%` | `0.775` | `23.65%` | `22.95%` | `0` |
| `BEAR_DEFER_BUY_ONLY` | `$2,329.64` | `+132.96%` | `0.735` | `23.69%` | `21.88%` | `779` |
| `EQUAL_EXPOSURE_CASH_CONTROL` | `$2,399.64` | `+139.96%` | `0.777` | `22.50%` | `21.93%` | `0` |

### 3D. Trend Acceleration as Execution-Speed Control Toward Approved Targets

| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IMMEDIATE_0PCT` | `$2,482.75` | `+148.28%` | `0.775` | `23.65%` | `2715` | `$99.33` | `6.43%` |
| `FIXED_PARTIAL_50PCT` | `$2,439.77` | `+143.98%` | `0.764` | `23.09%` | `2821` | `$82.31` | `7.66%` |
| `ACCEL_ADAPTIVE_SPEED` | `$2,439.70` | `+143.97%` | `0.763` | `23.36%` | `2544` | `$85.03` | `7.09%` |

## 4. Offline Research Gates (Hindsight Feasibility Ceiling & `0h` vs `+1h` Bar-Offset Harness)

| Mechanism | `0h` Signals | `+1h` Signals | Matched `<=2h` | Overlap % | Sensitivity Label |
| --- | ---: | ---: | ---: | ---: | :---: |
| `MOMENTUM_IGNITION` | `267` | `269` | `146` | `54.7%` | **`STABLE`** |
| `FAILED_DOWNSIDE_AUCTION` | `603` | `638` | `170` | `28.2%` | **`TIMING_SENSITIVE`** |

- **Offline Hindsight DP Ceiling (`BTCUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$5,652,246,339,665,292.00` across `12503` bars.
- **Offline Hindsight DP Ceiling (`ETHUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$8,560,694,627,510,774.00` across `8331` bars.
- **Offline Hindsight DP Ceiling (`SOLUSDT`, `2h`, `16 bps/side`, `24h` max hold):** `$6,542,399,868,819,755,008.00` across `8332` bars.
