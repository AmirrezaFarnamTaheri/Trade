# Development Evaluation Packet — Candidates A, B, and C

**Generated (UTC):** `2026-11-24T08:27:55.282657+00:00` · **Source:** `data/live/market.db` (read-only) · **Authority:** Paper development evaluation only (`DISARMED`, `$0` funded budget).

## 1. Candidate A (Track A) — 6-Triangle Leave-One-Out FX Basis + Kalman Filter

- **Aligned 1-min observations:** `6904` (`10` days) · **Verdict:** **`RETIRE_OR_REFINE`**
- **2×2 Attribution (bps):** `A (Cash) = 0.0`, `B (Signal+Taker) = -21289.99`, `C (Exec Only) = 0.0`, `D (Signal+Maker) = -13363.99` (`Signal=-21289.99`, `Exec=0.0`, `Interaction=7926.0`).
- **Daily Sharpe:** `1.0426` · **DSR Prob:** `0.8341` · **500-Run Placebo p-value:** `0.002`

| Coin | Closed Trades | Net Maker (bps) | Net Taker (bps) |
| --- | ---: | ---: | ---: |
| `BTC` | 201 | -1516.38 | -2722.38 |
| `ETH` | 207 | -2895.14 | -4137.14 |
| `SOL` | 212 | -2510.72 | -3782.72 |
| `XRP` | 216 | -2353.94 | -3649.94 |
| `XAUT` | 162 | -2403.63 | -3375.63 |
| `PEPE` | 323 | -1684.19 | -3622.19 |

## 2. Candidate B (Track B) — Multi-Asset Vector Allocation (`mix-journal-v2`)

- **Window:** `2024-10-10 .. 2026-11-23` (`775` days) · **Causality Gate:** `True` · **Verdict:** **`PROMISING_NEEDS_LONGER_OOS`**
- **500-Run Path-Preserving Placebo p-value (BTC sleeve):** `0.6826` · **180d Power at +8 bps/day (`DSR>=0.95`):** `0.0`
- **Latest Convex Weights:** `{'BTCUSDT': 0.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.2032, 'XRPUSDT': 0.3036, 'XAUTUSDT': 0.0319}`

| Allocator | Ann. Sharpe | DSR Prob (`N=21`) | Total Return (%) | Cumulative Turnover |
| --- | ---: | ---: | ---: | ---: |
| **Convex L1 Optimizer (`G1+G4`)** | 0.233 | 0.0567 | 4.64% | 3.7 |
| Simple `10%` No-Trade Band | 0.853 | 0.2485 | 68.68% | 17.91 |
| Equal-Weight Buy & Hold | 0.383 | — | 15.37% | 0.0 |

## 3. Candidate C (Track B) — Preview-Reconciled TMN-Borrow Carry vs. `1x` Spot

### Historical Real-Price Replay (Last 365 Daily Bars)

| Symbol | Days | Leverage | Status | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) | 21d Rolls | Warnings |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `USDTTMN` | 365 | 1.5x | `CLOSED_AT_HORIZON` | 164.05% | 139.92% | 24.13% | 17 | 0 |
| `USDTTMN` | 365 | 2.0x | `CLOSED_AT_HORIZON` | 205.82% | 139.92% | 65.9% | 17 | 0 |
| `XAUTTMN` | 365 | 1.5x | `CLOSED_AT_HORIZON` | 143.3% | 127.67% | 15.63% | 17 | 0 |
| `XAUTTMN` | 365 | 2.0x | `CLOSED_AT_HORIZON` | 178.14% | 127.67% | 50.47% | 17 | 0 |

### 180-Day FX Appreciation Scenario Sweep (`1.5x` Leverage on `USDTTMN`)

| Annual FX Appreciation | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) |
| ---: | ---: | ---: | ---: |
| 0%/yr | -16.87% | -0.6% | -16.28% |
| 25%/yr | 1.05% | 11.66% | -10.61% |
| 50%/yr | 18.97% | 23.91% | -4.94% |
