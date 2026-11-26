# v3 Dynamic Per-Moment Instrument Resolver — 4-Way Head-to-Head Study

- **Generated:** `2026-11-25T14:00:10.148911+00:00` · **Executor:** `DISARMED` (`PAPER_ONLY`)
- **Purged Walk-Forward 11-feat Path-PnL GRU OOS AUC:** `0h = 0.5627` · `+1h = 0.5982`
- **Frozen v2 Champion Reference (`V2_CHAMPION_60_40_NBX16_REF`):** NAV `$1215.25` (`+21.52%`), Bear `+1.28%`, Sharpe `0.675`, MaxDD `6.11%`
- **Top Local Dynamic Resolver:** `H12_HYBRID_LOCAL_5X_LONG_ONLY` — NAV `$1163.08` (`+16.32%`), Bear `+3.55%`, Sharpe `0.470`, MaxDD `12.84%`, Liqs `0`

## 1. Local Venues (`Nobitex + Wallex`, Asymmetric Tight-Stop Cap up to `5.0×`)

| Arm | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe (0h / 1h) | MaxDD | Liqs | Max Lev | Spot / MLong / MShort / PerpS | Borrow / Pool ($) | vs v2 (bps/d, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `A1_UTILITY_LOCAL_5X` | `$927.89` | `-7.20%` | `-8.67%` | `-0.010` (`-0.503`/`0.368`) | `33.97%` | `0` | `5.0×` | `282 / 8 / 472 / 0` | `$49.76 / +$55.56` | `-2.01` `[-6.83, +3.46]` |
| `A2_SIGNED_ADMM_LOCAL_5X` | `$977.18` | `-2.27%` | `+22.35%` | `0.061` (`-0.169`/`0.272`) | `32.43%` | `0` | `3.5×` | `280 / 10 / 513 / 0` | `$27.45 / +$59.45` | `-1.62` `[-6.80, +4.08]` |
| `A3_STATE_MACHINE_LOCAL_5X` | `$972.06` | `-2.78%` | `+4.68%` | `0.081` (`-0.258`/`0.345`) | `36.91%` | `0` | `3.0×` | `214 / 0 / 524 / 0` | `$44.67 / +$53.36` | `-1.41` `[-7.07, +4.82]` |
| `H12_HYBRID_LOCAL_5X` | `$1198.47` | `+19.86%` | `+22.95%` | `0.415` (`0.105`/`0.650`) | `19.09%` | `0` | `5.0×` | `212 / 25 / 489 / 0` | `$31.09 / +$66.75` | `+0.20` `[-4.67, +5.95]` |

## 2. Local Venues Leverage Ceiling Ablation (`2.0×` Cap)

| Arm | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe (0h / 1h) | MaxDD | Liqs | Max Lev | Spot / MLong / MShort / PerpS | Borrow / Pool ($) | vs v2 (bps/d, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `A1_UTILITY_LOCAL_2X` | `$955.07` | `-4.48%` | `-6.85%` | `0.034` (`-0.483`/`0.425`) | `33.05%` | `0` | `2.0×` | `282 / 8 / 470 / 0` | `$50.21 / +$56.02` | `-1.75` `[-6.65, +3.79]` |
| `A2_SIGNED_ADMM_LOCAL_2X` | `$973.32` | `-2.66%` | `+22.30%` | `0.054` (`-0.176`/`0.266`) | `32.34%` | `0` | `2.0×` | `282 / 10 / 512 / 0` | `$27.16 / +$59.25` | `-1.65` `[-6.83, +4.05]` |
| `A3_STATE_MACHINE_LOCAL_2X` | `$979.78` | `-2.01%` | `+3.35%` | `0.091` (`-0.244`/`0.354`) | `37.29%` | `0` | `2.0×` | `214 / 0 / 514 / 0` | `$45.01 / +$53.67` | `-1.35` `[-6.95, +4.85]` |
| `H12_HYBRID_LOCAL_2X` | `$1169.29` | `+16.95%` | `+22.38%` | `0.372` (`0.105`/`0.582`) | `20.72%` | `0` | `2.0×` | `212 / 22 / 488 / 0` | `$30.49 / +$66.33` | `-0.03` `[-4.82, +5.81]` |
| `H12_HYBRID_LOCAL_5X_LONG_ONLY` | `$1163.08` | `+16.32%` | `+3.55%` | `0.470` (`0.102`/`0.722`) | `12.84%` | `0` | `5.0×` | `210 / 21 / 0 / 0` | `$2.05 / +$71.11` | `-0.34` `[-2.79, +2.07]` |
| `H12_HYBRID_LOCAL_2X_LONG_ONLY` | `$1144.18` | `+14.43%` | `+3.61%` | `0.429` (`0.092`/`0.673`) | `12.67%` | `0` | `2.0×` | `212 / 20 / 0 / 0` | `$1.72 / +$70.57` | `-0.50` `[-2.98, +1.85]` |

## 3. Pluggable Hyperliquid Perp Readiness Check (`5 bps` leg, `+1 bps/8h` funding paid to shorts)

| Arm | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe (0h / 1h) | MaxDD | Liqs | Max Lev | Spot / MLong / MShort / PerpS | Borrow / Pool ($) | vs v2 (bps/d, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `A1_UTILITY_PLUS_PERP_5X` | `$1426.70` | `+42.68%` | `+34.10%` | `0.620` (`-0.120`/`0.999`) | `28.12%` | `0` | `5.0×` | `16 / 0 / 0 / 492` | `$0.00 / +$61.50` | `+2.08` `[-3.72, +10.14]` |
| `H12_HYBRID_PLUS_PERP_5X` | `$1343.35` | `+34.34%` | `+34.31%` | `0.600` (`0.376`/`0.760`) | `15.46%` | `0` | `3.5×` | `16 / 0 / 0 / 578` | `$0.00 / +$68.70` | `+1.30` `[-3.38, +7.16]` |

## 4. Key Takeaways

- Every arm consumed the exact same causal `MarketView` stream and ran through one shared multi-instrument ledger (`0h` + `+1h` twin-phase average, exact Nobitex `0.05%/d` EOD UTC borrow, `$0` intraday, `+2.64%` idle USDT pool, exact intra-bar high/low stops & liquidations).
- Comparing `A1_UTILITY`, `A2_SIGNED_ADMM`, `A3_STATE_MACHINE`, and `H12_HYBRID` directly reveals whether per-moment instrument pre-pricing + covariance netting beats standalone utility, post-solve routing, or discrete state ladders.
- Frozen v1 and v2 forward shadow journals remain untouched.
