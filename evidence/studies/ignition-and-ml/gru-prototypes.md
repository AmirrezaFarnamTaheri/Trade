# GRU Prototypes Empirical Evaluation (Purged Walk-Forward, Zero Lookahead)

- **Generated:** `2026-11-24T20:14:19.317746+00:00`
- **Engine:** Pure-NumPy 3-seed `EnsembleGRU` (`hidden=12–16`), exact BPTT + Adam + L2 + strict chronological purged walk-forward.
- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`

## 1. Prototype 1 — `GRU-Vol` (20d Volatility Forecaster Fed Into ADMM on `BASE_13_S1_S5`)

- **Out-of-Sample Vol Forecast (`N=20182`):** GRU RMSE = **`0.01768`** (`R² = +0.1743`) vs Static Yang–Zhang RMSE = **`0.06670`** (`R² = -10.7583`)

| Arm (`1,638` Days) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Paired Uplift vs Base (bps/day, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BASE_13_S1_S5_YANG_ZHANG` | `$2574.92` | `+157.52%` | `1.011` | `22.38%` | `-1.84%` | `$72.18` | Baseline |
| `GRU_VOL_ADMM` | `$2262.55` | `+126.27%` | `0.883` | `21.54%` | `-4.96%` | `$82.31` | `-0.78` `[-3.55, +1.72]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |
| `GRU_VOL_ADMM_DYNAMIC_CASH` | `$2265.93` | `+126.61%` | `0.887` | `21.54%` | `-4.96%` | `$82.45` | `-0.78` `[-3.49, +1.70]` (`NO_EVIDENCE_NOT_ESTABLISHED`) |

## 2. Prototype 2 — `GRU-Ignition` (36-Bar `2h` Pre-Breakout Scorer & Dynamic `0.5x/1.0x/1.5x` Sizer)

- **Out-of-Sample Breakout Classification (`N=746` of `877` episodes):** ROC AUC = **`0.5578`**, Bottom-Tercile Win Rate = **`38.3%`** vs Top-Tercile Win Rate = **`50.8%`** (Base = `46.1%`)

| Arm (`18` Markets, `2h` Ignition) | Cost (bps) | Ending NAV | Ret % | Bear Stress % | Ann. Sharpe | MaxDD % | Entries | Win % | Liq | Borrow ($) | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `PLAIN_IGN18_1.0X_NBX16` | `16.0` | `$1266.68` | `+26.67%` | `+6.80%` | `0.640` | `13.51%` | `175` | `37.7%` | `0` | `$0.00` | `$193.08` |
| `PLAIN_IGN18_1.5X_NBX16` | `16.0` | `$1365.80` | `+36.58%` | `+8.53%` | `0.608` | `19.87%` | `175` | `37.7%` | `0` | `$23.67` | `$303.10` |
| `GRU_SIZED_IGN18_NBX16` | `16.0` | `$1321.41` | `+32.14%` | `+9.90%` | `0.658` | `16.58%` | `175` | `37.7%` | `0` | `$11.06` | `$218.55` |
| `GRU_SIZED_IGN18_WLX25` | `25.0` | `$1190.45` | `+19.04%` | `+6.19%` | `0.442` | `18.22%` | `175` | `37.7%` | `0` | `$10.51` | `$323.89` |

## 3. Prototype 3 — `GRU-Exec` (Live Wallex `book_top` 5-Min Adverse-Drift Predictor & Execution Router)

- **OOS Tick Classification (`Train=3534`, `OOS=2210`):** 5-Min Direction ROC AUC = **`0.4831`**
- **Average OOS Execution Cost (12 Symbol×Side Pairs):** Immediate Taker = **`30.17 bps`**, Static `p35` Passive = **`28.76 bps`**, **`GRU-Exec` Routed = `28.90 bps`** (Saving **`+1.27 bps`** vs Immediate, **`-0.14 bps`** vs Static `p35`)

| Symbol | Side | N | Immediate (bps) | Static p35 (bps) | GRU-Routed (bps) | GRU vs Imm (bps) | GRU vs p35 (bps) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `BTCUSDT` | `BUY` | `10` | `22.97` | `24.09` | `24.09` | `-1.12` | `+0.00` |
| `BTCUSDT` | `SELL` | `10` | `22.95` | `20.02` | `20.95` | `+2.00` | `-0.93` |
| `ETHUSDT` | `BUY` | `10` | `22.13` | `17.44` | `19.02` | `+3.12` | `-1.58` |
| `ETHUSDT` | `SELL` | `10` | `22.11` | `27.86` | `21.23` | `+0.88` | `+6.62` |
| `SOLUSDT` | `BUY` | `10` | `46.61` | `44.77` | `41.03` | `+5.58` | `+3.74` |
| `SOLUSDT` | `SELL` | `10` | `46.52` | `44.37` | `47.24` | `-0.72` | `-2.87` |
| `XRPUSDT` | `BUY` | `10` | `28.29` | `25.85` | `25.85` | `+2.44` | `+0.00` |
| `XRPUSDT` | `SELL` | `10` | `28.25` | `31.84` | `29.36` | `-1.11` | `+2.48` |
| `XAUTUSDT` | `BUY` | `10` | `24.62` | `18.77` | `20.52` | `+4.10` | `-1.75` |
| `XAUTUSDT` | `SELL` | `10` | `24.59` | `26.20` | `24.80` | `-0.22` | `+1.40` |
| `PEPEUSDT` | `BUY` | `10` | `36.54` | `39.56` | `39.51` | `-2.97` | `+0.05` |
| `PEPEUSDT` | `SELL` | `10` | `36.48` | `24.32` | `33.23` | `+3.25` | `-8.90` |
