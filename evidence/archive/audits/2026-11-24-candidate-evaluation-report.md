# Optimized Walk-Forward Development Evaluation — Candidates A, B, and C

**Generated (UTC):** `2026-11-24T08:33:09.240047+00:00` · **Source:** `data/live/market.db` (read-only) · **Authority:** Paper development evaluation only (`DISARMED`, `$0` funded budget).

## 1. Candidate A (Track A) — Anti-Churn 6-Triangle FX Basis (`z >= 3.0`, `>= 45 bps` hurdle, 50/50 Walk-Forward)

- **Verdict:** **`RETIRE_ON_WALLEX_TEST_NOBITEX`**

| Split | Minutes | Trades | Wallex Maker (bps) | Wallex Taker (bps) | Nobitex -30% Maker (bps) | Daily Sharpe | DSR Prob | Placebo p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Train (first 50%) | 3451 | 94 | 2626.19 | 2062.19 | 3190.19 | 1.3482 | 0.7854 | 0.004 |
| **OOS (second 50%)** | 3452 | 119 | 266.71 | -447.29 | 980.71 | 0.9298 | 0.4792 | 0.3154 |

## 2. Candidate B (Track B) — Horizon-Matched Multi-Asset Vector Allocation (`verdict=TRACK_B_CANDIDATE_MONITOR`)

### Panel 1: 5-Asset Gold + Crypto Core (`BTC, ETH, SOL, XRP, XAUT`)

- **Full:** `2024-10-10 .. 2026-11-23` (`775d`) · **OOS Second Half:** `2025-11-01 .. 2026-11-23` (`388d`) · **Causality:** `True` · **Placebo p:** `0.1796`
- **Latest Horizon-Matched Convex Weights:** `{'BTCUSDT': 0.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.0, 'XRPUSDT': 0.0, 'XAUTUSDT': 0.0}`

| Allocator | Full Ann. Sharpe | Full DSR (`N=21`) | Full Ret (%) | Full MaxDD (%) | Turnover | OOS Ann. Sharpe | OOS Ret (%) | OOS MaxDD (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Horizon-Matched Convex L1 (`G1+G4`)** | 0.985 | 0.313 | 66.95% | 20.52% | 10.8 | -0.249 | -5.11% | 11.57% |
| Simple `10%` No-Trade Band | 0.853 | 0.2485 | 68.68% | 33.41% | 17.91 | -0.378 | -16.26% | 33.41% |
| Equal-Weight Buy & Hold | 0.383 | — | 15.37% | 55.84% | 0.0 | -1.054 | -47.29% | 49.65% |

### Panel 2: 4-Year Crypto Core (`BTC, ETH, SOL, XRP`)

- **Full:** `2022-05-22 .. 2026-11-23` (`1646d`) · **OOS Second Half:** `2024-08-23 .. 2026-11-23` (`823d`) · **Causality:** `True` · **Placebo p:** `0.3952`
- **Latest Horizon-Matched Convex Weights:** `{'BTCUSDT': 0.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.0, 'XRPUSDT': 0.0}`

| Allocator | Full Ann. Sharpe | Full DSR (`N=21`) | Full Ret (%) | Full MaxDD (%) | Turnover | OOS Ann. Sharpe | OOS Ret (%) | OOS MaxDD (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Horizon-Matched Convex L1 (`G1+G4`)** | 0.745 | 0.367 | 80.98% | 19.45% | 21.02 | 0.765 | 33.25% | 17.25% |
| Simple `10%` No-Trade Band | 0.531 | 0.2137 | 90.75% | 47.41% | 52.66 | 0.376 | 16.86% | 37.38% |
| Equal-Weight Buy & Hold | 0.603 | — | 127.17% | 64.09% | 0.0 | 0.269 | -3.89% | 64.09% |

## 3. Candidate C (Track B) — Preview-Reconciled TMN-Borrow Carry vs. `1x` Spot

| Symbol | Days | Leverage | Status | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) | 21d Rolls | Warnings |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `USDTTMN` | 365 | 1.5x | `CLOSED_AT_HORIZON` | 164.05% | 139.92% | 24.13% | 17 | 0 |
| `USDTTMN` | 365 | 2.0x | `CLOSED_AT_HORIZON` | 205.82% | 139.92% | 65.9% | 17 | 0 |
| `XAUTTMN` | 365 | 1.5x | `CLOSED_AT_HORIZON` | 143.3% | 127.67% | 15.63% | 17 | 0 |
| `XAUTTMN` | 365 | 2.0x | `CLOSED_AT_HORIZON` | 178.14% | 127.67% | 50.47% | 17 | 0 |

### 180-Day FX Appreciation Break-Even Sweep (`1.5x` Leverage on `USDTTMN`)

| Annual FX Appreciation | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) |
| ---: | ---: | ---: | ---: |
| 0%/yr | -16.87% | -0.6% | -16.28% |
| 25%/yr | 1.05% | 11.66% | -10.61% |
| 50%/yr | 18.97% | 23.91% | -4.94% |
| 75%/yr | 36.89% | 36.17% | 0.73% |
