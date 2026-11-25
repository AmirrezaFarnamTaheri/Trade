# Sprint 0 / Experiment 0 Empirical Feasibility Report

**Data cutoff (UTC):** `2026-11-24T08:08:09.738662+00:00` · **Lookback:** `72h` · **Source:** `data/live/market.db` (read-only)

## 1. Constrained Hindsight DP Ceiling (Exact Wallex L1 Received-Asset Fees)

| Symbol | Quote | Quotes Evaluated | Optimal Trades | Hindsight Ceiling (bps) | Beats Cash Hurdle |
| --- | --- | ---: | ---: | ---: | --- |
| `BTCUSDT` | USDT | 7996 | 2 | 27.75 | `True` |
| `BTCTMN` | TMN | 7996 | 2 | 68.14 | `True` |
| `ETHUSDT` | USDT | 7994 | 6 | 49.46 | `True` |
| `ETHTMN` | TMN | 7995 | 2 | 5.02 | `True` |
| `SOLUSDT` | USDT | 7999 | 2 | 42.08 | `True` |
| `SOLTMN` | TMN | 7999 | 4 | 57.65 | `True` |
| `XRPUSDT` | USDT | 7996 | 4 | 110.85 | `True` |
| `XRPTMN` | TMN | 7995 | 2 | 65.13 | `True` |
| `XAUTUSDT` | USDT | 7984 | 8 | 222.43 | `True` |
| `XAUTTMN` | TMN | 7995 | 2 | 334.21 | `True` |
| `PEPEUSDT` | USDT | 7992 | 10 | 1522.04 | `True` |
| `PEPETMN` | TMN | 7993 | 14 | 1282.67 | `True` |
| `USDTTMN` | TMN | 7969 | 4 | 400.11 | `True` |

## 2. Passive Maker Replay vs. Forced Deadline Unwind (3 Print Modes)

| Symbol | Mode | Intended ($) | Filled ($) | Ambig. Share | Fees ($) | 5m Markout Cov. | Residual ($) | Net Incr. ($) | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BTCUSDT` | `optimistic` | 3000.04 | 388.5 | 0.257 | 0.6955 | 1.0 | 150.9235 | -1.7166 | **DIAGNOSTIC** |
| `BTCUSDT` | `deduplicated` | 3000.04 | 388.5 | 0.0 | 0.7679 | 1.0 | 95.1712 | -1.8368 | **DIAGNOSTIC** |
| `BTCUSDT` | `adversarial_lower_bound` | 3000.04 | 388.5 | 0.257 | 0.6955 | 1.0 | 150.9235 | -1.7166 | **RETIRE** |
| `ETHUSDT` | `optimistic` | 3000.0 | 399.36 | 0.143 | 0.7434 | 1.0 | 132.9493 | -2.1034 | **DIAGNOSTIC** |
| `ETHUSDT` | `deduplicated` | 3000.0 | 399.36 | 0.0 | 0.7434 | 1.0 | 132.9493 | -2.1034 | **DIAGNOSTIC** |
| `ETHUSDT` | `adversarial_lower_bound` | 3000.0 | 399.36 | 0.143 | 0.7434 | 1.0 | 132.9493 | -2.1034 | **RETIRE** |
| `SOLUSDT` | `optimistic` | 3000.0 | 99.91 | 0.0 | 0.1994 | 1.0 | 22.6069 | -0.8739 | **DIAGNOSTIC** |
| `SOLUSDT` | `deduplicated` | 3000.0 | 99.91 | 0.0 | 0.1994 | 1.0 | 22.6069 | -0.8739 | **DIAGNOSTIC** |
| `SOLUSDT` | `adversarial_lower_bound` | 3000.0 | 99.91 | 0.0 | 0.1994 | 1.0 | 22.6069 | -0.8739 | **RETIRE** |
| `XRPUSDT` | `optimistic` | 3000.0 | 99.86 | 0.0 | 0.2288 | 1.0 | 0.0 | -0.8032 | **DIAGNOSTIC** |
| `XRPUSDT` | `deduplicated` | 3000.0 | 99.86 | 0.0 | 0.2288 | 1.0 | 0.0 | -0.8032 | **DIAGNOSTIC** |
| `XRPUSDT` | `adversarial_lower_bound` | 3000.0 | 99.86 | 0.0 | 0.2288 | 1.0 | 0.0 | -0.8032 | **RETIRE** |
| `XAUTUSDT` | `optimistic` | 3000.0 | 199.56 | 0.0 | 0.3357 | 1.0 | 94.2693 | -0.6804 | **DIAGNOSTIC** |
| `XAUTUSDT` | `deduplicated` | 3000.0 | 199.56 | 0.0 | 0.3357 | 1.0 | 94.2693 | -0.6804 | **DIAGNOSTIC** |
| `XAUTUSDT` | `adversarial_lower_bound` | 3000.0 | 199.56 | 0.0 | 0.3357 | 1.0 | 94.2693 | -0.6804 | **RETIRE** |
| `PEPEUSDT` | `optimistic` | 3000.0 | 298.78 | 0.3338 | 0.5602 | 1.0 | 93.5804 | -4.3561 | **DIAGNOSTIC** |
| `PEPEUSDT` | `deduplicated` | 3000.0 | 298.78 | 0.0 | 0.4517 | 1.0 | 176.7869 | -4.5161 | **DIAGNOSTIC** |
| `PEPEUSDT` | `adversarial_lower_bound` | 3000.0 | 298.78 | 0.3338 | 0.5602 | 1.0 | 93.5804 | -4.3561 | **RETIRE** |

## 3. Execution-Timing Overlay (`IMMEDIATE` vs `FIXED_PASSIVE` vs `OPPORTUNISTIC_RECOVERY`)

| Symbol | p35 Spread (bps) | Immediate Cost (bps) | Fixed Passive (bps) | Opportunistic (bps) | Overlay Savings (bps) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `BTCUSDT` | 32.51 | 23.48 | 53.47 | 53.47 | -29.98 |
| `ETHUSDT` | 26.26 | 24.53 | 44.01 | 44.01 | -19.48 |
| `SOLUSDT` | 30.54 | 28.26 | 35.2 | 35.2 | -6.94 |
| `XRPUSDT` | 28.03 | 20.32 | 41.55 | 41.55 | -21.23 |
| `XAUTUSDT` | 30.2 | 23.97 | 23.97 | 23.97 | 0.0 |
| `PEPEUSDT` | 55.1 | 42.19 | 42.19 | 42.19 | 0.0 |

## 4. Leave-One-Coin-Out 6-Triangle FX Factor Snapshot

| Coin | Status | Fresh Peers | Peer FX Center (TMN/USDT) | Basis vs Peer FX (bps) |
| --- | --- | ---: | ---: | ---: |
| `BTC` | `OK` | 5 | 281591.59 | 14.01 |
| `ETH` | `OK` | 5 | 281591.59 | 23.15 |
| `SOL` | `OK` | 5 | 281591.59 | 8.69 |
| `XRP` | `OK` | 5 | 281843.13 | -13.33 |
| `XAUT` | `OK` | 5 | 281843.13 | -9.08 |
| `PEPE` | `OK` | 5 | 281843.13 | -15.58 |

## 5. Top Active Markets Coverage Matrix (`40` symbols observed)

| Symbol | Book Rows | Two-Sided (%) | L2 Depth5 Rows | Trade Prints |
| --- | ---: | ---: | ---: | ---: |
| `BNBUSDT` | 51015 | 99.98% | 3603 | 416 |
| `SOLTMN` | 50067 | 99.99% | 3833 | 2998 |
| `DASHTMN` | 48540 | 99.99% | 0 | 844 |
| `XRPUSDT` | 48372 | 99.98% | 3790 | 1576 |
| `ETHTMN` | 48051 | 99.99% | 3834 | 6604 |
| `AVAXTMN` | 48041 | 99.99% | 0 | 323 |
| `XRPTMN` | 44690 | 99.98% | 3507 | 5325 |
| `SOLUSDT` | 44399 | 99.98% | 3889 | 1650 |
| `BNBTMN` | 43619 | 99.99% | 0 | 1330 |
| `DOTUSDT` | 43062 | 100.0% | 0 | 71 |
| `DOGEUSDT` | 42428 | 99.98% | 3658 | 416 |
| `AAVEUSDT` | 41806 | 99.94% | 2990 | 254 |
| `BCHUSDT` | 41716 | 99.94% | 2038 | 138 |
| `ADATMN` | 41074 | 100.0% | 0 | 1862 |
| `DASHUSDT` | 40672 | 99.95% | 3764 | 113 |
| `LTCTMN` | 40096 | 99.99% | 0 | 457 |
| `ETHUSDT` | 39912 | 99.98% | 3734 | 5617 |
| `LTCUSDT` | 38786 | 99.93% | 3427 | 284 |
| `BTCUSDT` | 38750 | 99.98% | 2944 | 4600 |
| `CAKETMN` | 38160 | 99.99% | 0 | 645 |
