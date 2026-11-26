# Cross-Layer Trading Design Diagnostics (Exit Specialist, Confirmation Price, Ambiguity, 2×2 Conflict, Time-to-Decision & Sham Control)

- **Generated:** `2026-11-25T21:45:01.181769+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## 1. Exit Specialist vs. Incumbent Exits (Identical `MOMENTUM_IGNITION` Entries)

| Exit Policy | Fills | Early Exits | Win% | Ending NAV | Return | Sharpe | MaxDD | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `INCUMBENT_EXIT` | `192` | `0` | `39.1%` | `$928.19` | `-7.18%` | `-0.193` | `16.60%` | `$144.28` |
| `THESIS_FAILURE_4BAR` | `206` | `68` | `38.3%` | `$887.54` | `-11.25%` | `-0.432` | `14.73%` | `$158.43` |
| `PROFIT_STALL_6BAR` | `199` | `32` | `35.2%` | `$864.05` | `-13.59%` | `-0.469` | `19.24%` | `$149.06` |

## 2. Confirmation Price (Scored Per Original Alert, Including Runaway Winners)
- **Alerts:** `267` · **Confirmed:** `117` · **Unconfirmed Runaway Winners:** `63`
- **Enter Now (100%):** `+33.72 bps` · **Wait 1b Confirm:** `-10.88 bps` · **Split 50/50:** `+11.42 bps`

## 3. Intrabar Path-Ambiguity Bounds (Stop `-4%` vs Target `+8%`)
- **Evaluated Trades:** `267` · **Ambiguous Bars:** `2` (`0.75%`)
- **Optimistic (Target First):** `+50.89 bps` · **Adverse (Stop First):** `+41.90 bps` · **Gap:** `8.99 bps` · **Sign Flips:** `False`

## 4. 2×2 Capital-Conflict Interaction (`$1,000` Shared Capital)
- **Neither (Cash):** `$1000.00` · **Slow A Only:** `$1158.28` · **Ignition B Only:** `$1051.58` · **Both Shared:** `$1142.81` (displaced fast=`58`)
- **Interaction Term `W(AB) - W(A) - W(B) + W(0)`:** **`$-67.05`**

## 5. Time-to-Decision Learning Horizon (80% Power, `alpha=0.05`)

| Mechanism | Indep. Episodes | Episodes/Mo | Ep. Std (bps) | Needed (`100bp`) | Months (`100bp`) | Months (`50bp`) | Disposition |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `MOMENTUM_IGNITION` | `140` | `3.93` | `536.1` | `226` | `57.4m` | `229.2m` | `PARK_TOO_SLOW` |
| `FAILED_DOWNSIDE_AUCTION` | `279` | `7.84` | `387.6` | `118` | `15.0m` | `60.2m` | `POOL_MARKETS` |
| `PEER_RELATIVE_CATCHUP` | `135` | `3.79` | `321.1` | `81` | `21.3m` | `85.4m` | `PARK_TOO_SLOW` |

## 6. Matched Sham-Entry Control & Zero-Trade-Week Diagnostic Funnel
- **Real Ignition 24h Net:** `+33.72 bps` · **Asset/Hour-Matched Sham:** `-3.10 bps` · **Real − Sham:** **`+36.82 bps`**
- **Zero-Trade Weeks:** `102 / 156` (`59` due to low breadth `< 0.45`; `43` due to no breakout signal in eligible breadth weeks)
