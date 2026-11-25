# Quantitative Research Studies — Executive Summary

This compendium synthesizes every strictly causal, zero-lookahead study executed on the TradingGYM self-financing ledger (`gym-core/src/gym/services/experiments/`). All historical metrics are **seen-replay benchmarks** (`PAPER_ONLY`, `TradingGYMExecutor DISARMED`); live prospective confirmation is tracked separately in [../forward/](../forward/) and [../research-dashboard.html](../research-dashboard.html).

---

## 1. Champion Evolution (Single Shared-Ledger Overlap, `2024–2026` Chop + Bear)

From [ignition-and-ml/v2-champion-verification.md](ignition-and-ml/v2-champion-verification.md) (`$1,000` start, `1h` overlap, strict single `SelfFinancingLedger`, zero-lookahead purged walk-forward GRUs):

| Strategy Arm | Venue Cost | Ending NAV | Full Return | Bear Stress | Ann. Sharpe | MaxDD | Fills | Fees ($) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BASE_13_100PCT` | `NBX16` (16 bps/side) | `$1,189.79` | `+18.98%` | `-2.81%` | `0.467` | `11.96%` | `593` | `$23.54` |
| `V1_CHAMPION_70_30` | `NBX16` | `$1,250.47` | `+25.05%` | `+2.24%` | `0.657` | `8.55%` | `985` | `$81.13` |
| `V2_GRU11_PATHPNL_70_30` | `NBX16` | `$1,287.89` | `+28.79%` | `+3.28%` | `0.804` | `7.03%` | `1,259` | `$69.96` |
| `V2_GRU8_CONFORMAL_60_40` | `NBX16` | **`$1,305.48`** | **`+30.55%`** | **`+5.56%`** | **`0.874`** | **`6.46%`** | `1,233` | `$83.16` |
| `BASE_13_100PCT` | `WLX25` (25 bps/side) | `$1,176.20` | `+17.62%` | `-3.19%` | `0.441` | `12.04%` | `593` | `$36.57` |
| `V1_CHAMPION_70_30` | `WLX25` | `$1,203.50` | `+20.35%` | `+1.08%` | `0.556` | `8.60%` | `982` | `$124.16` |
| `V2_GRU11_PATHPNL_70_30` | `WLX25` | `$1,220.31` | `+22.03%` | `+2.08%` | `0.663` | `7.60%` | `1,154` | `$98.78` |
| `V2_GRU8_CONFORMAL_60_40` | `WLX25` | **`$1,244.59`** | **`+24.46%`** | **`+5.19%`** | **`0.747`** | **`6.86%`** | `1,135` | `$119.45` |

*Full 1,638-day (`2022-06..2026-11`) `1d` core benchmark:* `BASE_13_S1_S5` (`SR 1.011`, `+157.5%`, MaxDD `22.38%`) → `BASE_13 + ACCEL_BLEND_20` (`SR 1.116`, `+173.4%`, MaxDD `21.74%`).

---

## 2. Verified Winners vs. Retired Dead Ends

### Verified Winners (Kept in Production Shadow / v2 Architecture)
1. **1d Slow Core (`S1 + S5 + ADMM` + `ACCEL_BLEND_20` + `11A` Metals Reserve):** Dropping noisy `S2` and solving jointly with L1 fee-zone ADMM established the `+27.65%/yr` OLS alpha core; adding causal 2nd-order velocity/acceleration (`ACCEL_BLEND_20`) lifted 1,638-day Sharpe `1.011 → 1.116`, and multi-issuer defensive metals reserve (`XAUT` + `PAXG` + `SLVON`) improved Sharpe `1.011 → 1.023` ([first-ensemble-experiment.md](core-ensemble/first-ensemble-experiment.md), [higher-order-and-sparse.md](core-ensemble/higher-order-and-sparse.md), [core-engine-ablation.md](core-ensemble/core-engine-ablation.md)).
2. **2h Rare Momentum Ignition + Pure-NumPy Purged Walk-Forward GRU (`GRU8` / `GRU11` Path-PnL):** Near-zero correlation (`r ≈ 0.08`) to the 1d core. Upgrading from 6 features (`AUC 0.558`) to 8-feat acceleration (`SR 0.811`) and 11-feat continuous Path-PnL (`+1h` OOS `AUC 0.6051`, MaxDD `10.6%`) drove positive bear-year alpha ([gru-prototypes.md](ignition-and-ml/gru-prototypes.md), [ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md)).
3. **Conformal Rank + 5% Trailing-DD Leverage Governor:** Lifted `2h` ignition Sharpe `0.811 → 0.857` (`NBX16`) and `0.611 → 0.670` (`WLX25`) while cutting MaxDD by `24%–29%` ([ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md)).
4. **50/50 Twin-Phase (`0h` + `1h`) 2h Book:** Eliminated bar-boundary clock fragility and rescued tiered sparse expansion ([ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md)).
5. **Joint Single-ADMM Cross-Sleeve Netting:** Beat post-hoc `70/30` sleeve blending on both venues (`SR 0.650 → 0.685` `NBX16`, `0.554 → 0.582` `WLX25`) while cutting Wallex fills by `-21%` ([diffusion-and-netting.md](execution-and-venues/diffusion-and-netting.md)).
6. **Multi-Venue Side-Asymmetric Smart Execution (`SIDE_ASYMMETRIC_ROUTER`):** Matched live 5-level L2 book audits saved `+8.1` to `+21.9 bps/leg` across `4/4` live pairs, with live 15-pair Nobitex↔Wallex dislocations offering `+15–95 bps` entry-guard/exit-rebate capture ([venue-execution-cost.md](execution-and-venues/venue-execution-cost.md), [smart-execution.md](execution-and-venues/smart-execution.md), [diffusion-and-netting.md](execution-and-venues/diffusion-and-netting.md)).

### Cleanly Retired Mechanisms (Do Not Re-Introduce Without New Orthogonal Data)
- **`S2` Cross-Sectional Relative Strength & `S2` Hysteresis (`25/55`)** — negative incremental Sharpe ([leader-deep-dive.md](core-ensemble/leader-deep-dive.md)).
- **`S3` / `S4` Fast Mean-Reversion / Breakout Sleeves & `15m`/`30m` Sub-Hourly Ignition** — destroyed by round-trip fee + spread drag ([ignition-expansion.md](ignition-and-ml/ignition-expansion.md)).
- **`2h`/`3h`/`6h` Intraday Crash Breakers** — pre-fix `EXP_B2`/`EXP_B3` retracted due to same-day `ts_avail` leak; strictly causal versions all underperformed `BASE_13` (`SR 0.207–0.961 < 1.011`) ([family-and-timeframes.md](core-ensemble/family-and-timeframes.md)).
- **Savitzky–Golay Trend Filter, Path-Efficiency IC Scaling, and Hierarchical Risk Parity (`HRP`)** — all underperformed `ACCEL_BLEND_20` + ADMM ([core-engine-ablation.md](core-ensemble/core-engine-ablation.md)).
- **2h Flush Rebound, Dead-Cat Short, Covariance-Only `GRU-Vol`, Two-Tranche Partial Profit-Lock, Volume Absorption Throttle, and `2h` Lead-Lag Diffusion** — all failed causal ablation ([orthogonal-alpha.md](core-ensemble/orthogonal-alpha.md), [ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md), [diffusion-and-netting.md](execution-and-venues/diffusion-and-netting.md)).
- **Wallex Margin Shorting (`32.85%/yr` borrow) & Broad `33`-Asset Flat Expansion** — borrow bleed and thin-book spread drag erased gross alpha ([short-and-leverage.md](ignition-and-ml/short-and-leverage.md), [higher-order-and-sparse.md](core-ensemble/higher-order-and-sparse.md)).

---

## 3. Study Catalogue

### A. Core Ensemble & 1d Signal Geometry (`core-ensemble/`)
| Study | Report | JSON Receipt | Primary Finding |
| --- | --- | --- | --- |
| First Ensemble & ML-Veto Ablation | [first-ensemble-experiment.md](core-ensemble/first-ensemble-experiment.md) | [JSON](core-ensemble/first-ensemble-decision-receipt.json) | `DROP_S2 (S1 + S5 + ADMM)` beat S1 alone, Adaptive Vote, and Logistic Veto (`SR 1.011`, `1,638d`). |
| Standing Leader Deep-Dive | [leader-deep-dive.md](core-ensemble/leader-deep-dive.md) | [JSON](core-ensemble/leader-deep-dive.json) | Retires `S2` hysteresis; proves `+27.65%/yr` OLS alpha over BTC/Gold and causal BUY/SELL asymmetry. |
| Fast-Sleeve Attribution (`S3`/`S4`) | — | [JSON](core-ensemble/fast-sleeve-attribution.json) | `+1h` UTC clock-shift attribution showing `S3`/`S4` fee fragility. |
| Multi-Asset Expansion & Margin *(partial retraction)* | [expansion-and-margin.md](core-ensemble/expansion-and-margin.md) | [JSON](core-ensemble/expansion-and-margin.json) | `33`-asset plain expansion diluted Sharpe (`0.748`); `EXP_B2`/`EXP_B3` retracted with notice. |
| Family & Multi-Timeframe Audit | [family-and-timeframes.md](core-ensemble/family-and-timeframes.md) | [JSON](core-ensemble/family-and-timeframes.json) | Retires causal `2h`/`3h`/`6h` crash breakers; discovers rare momentum ignition. |
| Orthogonal Alpha Audit (`3A`/`3B`/`3C`) | [orthogonal-alpha.md](core-ensemble/orthogonal-alpha.md) | [JSON](core-ensemble/orthogonal-alpha.json) | Retires flush rebound, dead-cat short, and cov-only `GRU-Vol`; confirms `XAUT > PAXG`. |
| Higher-Order Momentum & Tiered Sparse | [higher-order-and-sparse.md](core-ensemble/higher-order-and-sparse.md) | [JSON](core-ensemble/higher-order-and-sparse.json) | 2nd-order acceleration lifts `BASE_13` `1.011 → 1.116`; catches `+1h` fragility on meme satellites. |
| Track I Core Engine Ablations | [core-engine-ablation.md](core-ensemble/core-engine-ablation.md) | [JSON](core-ensemble/core-engine-ablation.json) | `ACCEL_BLEND_20` + `11A` Metals Reserve beat Savitzky–Golay, Path-Efficiency IC, and `HRP`. |

### B. Momentum Ignition, ML & Unified v2 Champion (`ignition-and-ml/`)
| Study | Report | JSON Receipt | Primary Finding |
| --- | --- | --- | --- |
| Ignition Live-Spread & `+1h` Validation | [ignition-validation.md](ignition-and-ml/ignition-validation.md) | [JSON](ignition-and-ml/ignition-validation.json) | `70/30` shared-ledger blend lifts Sharpe `+37%–+51%`, cuts MaxDD `-29%`. |
| 18-Market & Sub-Hourly Ignition Expansion | [ignition-expansion.md](ignition-and-ml/ignition-expansion.md) | [JSON](ignition-and-ml/ignition-expansion.json) | Confirms `2h` 18-coin sweet spot; retires `15m`/`30m` sub-hourly floor. |
| Event-Scoped Leverage & 2h Shorts | [short-and-leverage.md](ignition-and-ml/short-and-leverage.md) | [JSON](ignition-and-ml/short-and-leverage.json) | `1.5×`/`2.0×` event leverage outperforms long-held margin under exact `0.015%/4h` borrow; `2h` shorts fail. |
| Walk-Forward GRU Prototypes | [gru-prototypes.md](ignition-and-ml/gru-prototypes.md) | [JSON](ignition-and-ml/gru-prototypes.json) | Pure-NumPy purged walk-forward `GRU-Ignition` (`AUC 0.558`) wins dynamic `0.5×/1.0×/1.5×` sizing. |
| Track II Ignition & GRU Ablations | [ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md) | [JSON](ignition-and-ml/ignition-upgrade-ablation.json) | Conformal + 5% DD governor, 11-feat Path-PnL GRU, and `50/50` twin-phase book all win; profit-lock & absorption retired. |
| Unified v2 Champion Verification | [v2-champion-verification.md](ignition-and-ml/v2-champion-verification.md) | [JSON](ignition-and-ml/v2-champion-verification.json) | End-to-end single shared-ledger proof: `V2` beats `V1` and `BASE_13` across both `NBX16` and `WLX25`. |

### C. Execution, Multi-Venue Depth & Cross-Sleeve Netting (`execution-and-venues/`)
| Study | Report | JSON Receipt | Primary Finding |
| --- | --- | --- | --- |
| Experiment 0 Execution Ceiling | [experiment-0-execution-ceiling.md](execution-and-venues/experiment-0-execution-ceiling.md) | — | Hindsight DP ceiling & adversarial duplicate-print bounds on live Wallex books. |
| Venue Execution-Cost Audit (L1) | [venue-execution-cost.md](execution-and-venues/venue-execution-cost.md) | [JSON](execution-and-venues/venue-execution-cost.json) | Matched live Wallex vs. Nobitex (`-30%`) spread audit: `+6.2` to `+12.0 bps/leg` saving. |
| Side-Asymmetric Smart Execution (L2) | [smart-execution.md](execution-and-venues/smart-execution.md) | [JSON](execution-and-venues/smart-execution.json) | Walked 5-level L2 depth `$250` audit: `+8.1` to `+21.9 bps/leg` saving across `4/4` live pairs. |
| Track III Diffusion, Netting & Dislocations | [diffusion-and-netting.md](execution-and-venues/diffusion-and-netting.md) | [JSON](execution-and-venues/diffusion-and-netting.json) | Joint Single-ADMM netting beats post-hoc `70/30` (`-21%` Wallex fills); live 15-pair dislocations verified; `2h` diffusion retired. |
| Nobitex Margin vs. Wallex Margin & Fixed Trade-Credit | [nobitex-margin-vs-wallex-credit.md](execution-and-venues/nobitex-margin-vs-wallex-credit.md) | [JSON](execution-and-venues/nobitex-margin-vs-wallex-credit.json) | Idle USDT pool (`+2.64% APR`) lifts 1d Core `SR 1.099 → 1.179`; Nobitex `2.0x` top-tercile `2h` GRU (`18/18` live pairs) lifts `v2` to `SR 0.894` (`$3.42` borrow, `6.45%` MaxDD); `1d` bear short retired; Wallex `5x` Trade-Credit loses `-81%` to `-91%` from fixed `$15/30d` dead-cash bleed. |
| v3 Dynamic Per-Moment Instrument Resolver (4-Way Study) | [dynamic-instrument-resolver.md](execution-and-venues/dynamic-instrument-resolver.md) | [JSON](execution-and-venues/dynamic-instrument-resolver.json) | Hybrid `H12` decisively beats standalone `A1`/`A2`/`A3` (`0` liqs across all arms; `5×` tight-stop beats `2×`); `H12_LOCAL_5X` (`+19.86%`, Bear `+22.95%`, `SR 0.415`) and `H12_LOCAL_5X_LONG_ONLY` (`+16.32%`, `SR 0.470`, `MaxDD 12.84%`, `$2.05` borrow) still trail frozen `V2_CHAMPION` (`+21.52%`, `SR 0.675`, `MaxDD 6.11%`) on local `16 bps` fees, while plugging in `PERP_FUTURE` (`5 bps`, Hyperliquid-ready) lifts `H12` to `+34.34%` (Bear `+34.31%`, `SR 0.600`, `MaxDD 15.46%`) with zero solver changes. |
