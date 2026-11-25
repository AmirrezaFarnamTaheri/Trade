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

### 1B. v3 Unified Multi-Horizon Engine Evolution (`MultiHorizonBook`, `1,085d` `2024–2026`, `NBX16`)

From [v3-adaptive-engine/bear-regime-and-timeframe-study.md](v3-adaptive-engine/bear-regime-and-timeframe-study.md) (after fixing the twin-phase `1h`-offset daily-signal clock bug so **both** `0h` and `1h` phases execute daily Slow Core + Bear-Majors rebalancing causally):

| Unified Engine Variant | 24h / 72h / 7d (Bear Week) | Ending NAV | Full Return | Bear Stress | Ann. Sharpe | MaxDD | Liqs | 2024 / 2025 / 2026 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `MAIN_E3_V2_STANDALONE` *(fixed twin-phase)* | `+0.01% / +0.02% / +0.05%` | `$1,557.58` | `+55.75%` | `+4.42%` | `0.942` | `10.84%` | `0` | `+9.6% / +35.4% / +3.3%` |
| **`E3_V2_UNIFIED_BEAR50_BR30`** *(Best Sharpe)* | `+0.92% / +1.91% / +3.32%` | **`$1,862.61`** | **`+86.25%`** | **`+21.18%`** | **`1.114`** | `15.11%` | **`0`** | `+7.9% / +41.1% / +20.9%` |
| **`E3_V2_UNIFIED_BEAR75_BR30`** *(Hits 1/2/5 NS)* | **`+1.50% / +3.18% / +5.02%`** | **`$1,892.41`** | **`+89.23%`** | **`+25.32%`** | **`0.987`** | `19.96%` | **`0`** | `+7.0% / +38.6% / +26.2%` |
| **`E3_V2_PLUS_CTA_VOLTGT80_M4_XAUT`** *(Hits 3/5/15 NS!)* | **`+4.91% / +7.83% / +18.12%`** | **`$2,424.64`** | **`+142.45%`** | **`+54.15%`** | **`0.996`** | `30.79%` | **`0`** | `+5.9% / +41.5% / +60.7%` |
| `E3_V2_UNIFIED_BEAR100_BR35` *(Max Return)* | **`+1.96% / +4.17% / +7.40%`** | **`$1,992.04`** | **`+99.19%`** | **`+31.08%`** | `0.951` | `24.50%` | **`0`** | `+3.8% / +45.9% / +30.2%` |

---

## 2. Verified Winners vs. Retired Dead Ends

### Verified Winners (Kept in Production Shadow / v2–v3 Architecture)
1. **1d Slow Core (`S1 + S5 + ADMM` + `ACCEL_BLEND_20` + `11A` Metals Reserve):** Dropping noisy `S2` and solving jointly with L1 fee-zone ADMM established the `+27.65%/yr` OLS alpha core; adding causal 2nd-order velocity/acceleration (`ACCEL_BLEND_20`) lifted 1,638-day Sharpe `1.011 → 1.116`, and multi-issuer defensive metals reserve (`XAUT` + `PAXG` + `SLVON`) improved Sharpe `1.011 → 1.023` ([first-ensemble-experiment.md](core-ensemble/first-ensemble-experiment.md), [higher-order-and-sparse.md](core-ensemble/higher-order-and-sparse.md), [core-engine-ablation.md](core-ensemble/core-engine-ablation.md)).
2. **2h Rare Momentum Ignition + Pure-NumPy Purged Walk-Forward GRU (`GRU8` / `GRU11` Path-PnL):** Near-zero correlation (`r ≈ 0.08`) to the 1d core. Upgrading from 6 features (`AUC 0.558`) to 8-feat acceleration (`SR 0.811`) and 11-feat continuous Path-PnL (`+1h` OOS `AUC 0.6051`, MaxDD `10.6%`) drove positive bear-year alpha ([gru-prototypes.md](ignition-and-ml/gru-prototypes.md), [ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md)).
3. **Conformal Rank + 5% Trailing-DD Leverage Governor & 50/50 Twin-Phase (`0h` + `1h`) 2h Book:** Lifted `2h` ignition Sharpe `0.811 → 0.857` (`NBX16`) while cutting MaxDD by `24%–29%` and eliminating bar-boundary clock fragility ([ignition-upgrade-ablation.md](ignition-and-ml/ignition-upgrade-ablation.md)).
4. **Multi-Venue Smart Execution & Tehran Liquidity-Clock Rebalancing (`10:00 UTC` Passive):** Matched live 5-level L2 book audits saved `+8.1` to `+21.9 bps/leg`; live `book_top` (`1.37M` ticks) confirmed `~10.1 bps` Tehran-hour spread swing and synthetic `Asset/TMN ↔ USDTTMN` savings (`+77–84 bps` on `SOL`/`BTC` BUYs) ([smart-execution.md](execution-and-venues/smart-execution.md), [multi-horizon-adaptive-engine.md](v3-adaptive-engine/multi-horizon-adaptive-engine.md)).
5. **True Lot-Scoped `MultiHorizonBook` + Nonlinear Bellman Optimal Stopping (`E3_V2`):** Eliminated cross-sleeve cash-pool interference, enabled safe `5×` tight-stop Nobitex overlay (`0` liqs) + `+2.64%` idle USDT pool yield, and used purged walk-forward `E[Hold]` stopping to exit losing/exhausted trades pre-UTC-midnight (`$0` borrow) while pyramiding fat-tail winners ([optimal-position-closing.md](v3-adaptive-engine/optimal-position-closing.md), [bellman-stopping-and-resurrection.md](v3-adaptive-engine/bellman-stopping-and-resurrection.md)).
6. **Calm Daily `S1 + Accel` Bear-Majors Short Sleeve (`bear_majors_sleeve.py`):** Exact downside mirror of the Slow Long Core applied strictly to liquid Nobitex majors (`BTC/ETH/SOL/BNB`) when `daily_breadth <= 0.30` (`s1 < -0.25`, `accel <= +0.12` V-bottom exit). Absorbed inside the unified `MultiHorizonBook` at `50%` budget, it lifted full `1,085d` return `+55.75% → +86.25%`, Bear Stress `+4.42% → +21.18%`, and Sharpe `0.942 → 1.114` (`0` liqs, positive in `2024`, `2025`, and `2026`); at `75%`, it hit all three bear-week Northstar targets (`+1.50% / +3.18% / +5.02%`) with `+89.23%` full return and `SR 0.987` ([bear-regime-and-timeframe-study.md](v3-adaptive-engine/bear-regime-and-timeframe-study.md)).

### Cleanly Retired Mechanisms (Do Not Re-Introduce Without New Orthogonal Data)
- **`S2` Cross-Sectional Relative Strength & `S2` Hysteresis (`25/55`)** — negative incremental Sharpe ([leader-deep-dive.md](core-ensemble/leader-deep-dive.md)).
- **`S3` / `S4` Fast Mean-Reversion / Breakout Sleeves & `15m`/`30m` Sub-Hourly Taker Ignition** — blocked by Nobitex's `0.38×`-of-sigma round-trip taker fee wall (`30m` median bar vol `84.0 bps` vs `32 bps` RT taker); note `1h` GRU+Bellman+Maker (`8.5 bps`) reaches standalone `SR 0.436` (`+7.46%`, `77.4%` pre-EOD `$0` borrow) but remains inferior to `2h` and dilutes `E3_V2` when blended ([ignition-expansion.md](ignition-and-ml/ignition-expansion.md), [bear-regime-and-timeframe-study.md](v3-adaptive-engine/bear-regime-and-timeframe-study.md)).
- **`2h`/`3h`/`6h` Intraday Crash Breakers** — pre-fix `EXP_B2`/`EXP_B3` retracted due to same-day `ts_avail` leak; strictly causal versions all underperformed `BASE_13` ([family-and-timeframes.md](core-ensemble/family-and-timeframes.md)).
- **Savitzky–Golay Trend Filter, Path-Efficiency IC Scaling, `HRP`, `F3` Lagging IC, Tight `3.4×` OCO TP Cap, `F6` RV Hedge, and Rigid Mechanical Exits (`E1`/`E2`/`E4`)** — all underperformed ADMM + `E3_V2` Bellman stopping ([core-engine-ablation.md](core-ensemble/core-engine-ablation.md), [optimal-position-closing.md](v3-adaptive-engine/optimal-position-closing.md)).
- **High-Frequency Intraday Shorting (`1h` `N1`/`N2`/`N4` Churn, `2h` Flush Rebound, Breakdown Short, Uncensored `z>=1.5` Early Ignition, Alt-Chasing L/S)** — destroyed by altcoin short squeezes and `$250–$757` fee churn over `1,085d` (`-19%` to `-77%`), even with Bellman optimal closing ([bellman-stopping-and-resurrection.md](v3-adaptive-engine/bellman-stopping-and-resurrection.md), [bear-regime-and-timeframe-study.md](v3-adaptive-engine/bear-regime-and-timeframe-study.md)).
- **Wallex Margin Shorting (`32.85%/yr` borrow), Wallex `5×` Fixed Trade-Credit (`-81%` to `-91%`), & Broad `33`-Asset Flat Expansion** — borrow/dead-cash bleed and thin-book spread drag erased gross alpha ([short-and-leverage.md](ignition-and-ml/short-and-leverage.md), [nobitex-margin-vs-wallex-credit.md](execution-and-venues/nobitex-margin-vs-wallex-credit.md)).

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
| Nobitex Margin vs. Wallex Margin & Fixed Trade-Credit | [nobitex-margin-vs-wallex-credit.md](execution-and-venues/nobitex-margin-vs-wallex-credit.md) | [JSON](execution-and-venues/nobitex-margin-vs-wallex-credit.json) | Idle USDT pool (`+2.64% APR`) lifts 1d Core `SR 1.099 → 1.179`; Nobitex `2.0x` top-tercile `2h` GRU (`18/18` live pairs) lifts `v2` to `SR 0.894` (`$3.42` borrow, `6.45%` MaxDD); Wallex `5x` Trade-Credit loses `-81%` to `-91%` from fixed `$15/30d` dead-cash bleed. |

### D. v3 Adaptive Engine, Optimal Closing & Bear-Regime Research (`v3-adaptive-engine/`)
| Study | Report | JSON Receipt | Primary Finding |
| --- | --- | --- | --- |
| v3 Dynamic Per-Moment Instrument Resolver (4-Way Study) | [dynamic-instrument-resolver.md](v3-adaptive-engine/dynamic-instrument-resolver.md) | [JSON](v3-adaptive-engine/dynamic-instrument-resolver.json) | Hybrid `H12` decisively beats standalone `A1`/`A2`/`A3` (`0` liqs across all arms; `5×` tight-stop beats `2×`); plugging in `PERP_FUTURE` (`5 bps`, Hyperliquid-ready) lifts `H12` to `+34.34%` (Bear `+34.31%`, `SR 0.600`) with zero solver changes. |
| Multi-Horizon Adaptive Engine (`F1`–`F6` Ablation & Live Audits) | [multi-horizon-adaptive-engine.md](v3-adaptive-engine/multi-horizon-adaptive-engine.md) | [JSON](v3-adaptive-engine/multi-horizon-adaptive-engine.json) | True lot-scoped `MultiHorizonBook` + `5×` tight-stop Nobitex overlay + Idle Pool + Tehran `10:00 UTC` passive rebalance + in-position ML exit/pyramid beats frozen `V2_CHAMPION` (`+38.50%`, `SR 0.952` vs `0.849`, `0` liqs); live `book_top` proves `~10 bps` Tehran-hour spread swing and `+77–84 bps` `TMN` triangle savings. |
| Optimal Position-Closing & Exit-Timing Study (`E1`–`E4`) | [optimal-position-closing.md](v3-adaptive-engine/optimal-position-closing.md) | [JSON](v3-adaptive-engine/optimal-position-closing.json) | `E3_OPTIMAL_STOPPING_ML` (10-feature purged walk-forward Bellman `E[Hold]` with `hours_to_utc_eod`) lifts identical entries to `+42.84%` (`SR 1.067`, `0` liqs, `35.6%` pre-EOD `$0` borrow); mechanical exits (`E1`/`E2`/`E4`) retired. |
| Bellman V2 Nonlinear Stopping & Strategy Resurrection | [bellman-stopping-and-resurrection.md](v3-adaptive-engine/bellman-stopping-and-resurrection.md) | [JSON](v3-adaptive-engine/bellman-stopping-and-resurrection.json) | `E3_V2_NONLINEAR_BELLMAN` (16-feature interaction + 2-seed residual MLP) reaches `+42.98%` (`SR 1.090`, MaxDD `8.17%`, `0` liqs); proves Bellman amplifies real edge but cannot rescue fee-negative `flush_rebound`, `breakdown_short`, or `early_ignition_z15`. |
| Bear-Regime Discovery & `1h` / `0.5h` (`30m`) Timeframe Study | [bear-regime-and-timeframe-study.md](v3-adaptive-engine/bear-regime-and-timeframe-study.md) | [JSON](v3-adaptive-engine/bear-regime-and-timeframe-study.json) | Fixes twin-phase `1h` daily-clock bug (`E3_V2` standalone `+55.75%`, `SR 0.942`); discovers Calm Daily `S1 + Accel` Bear-Majors Short (`BEAR50` lifts unified `E3_V2` to **`+86.25%` / Bear `+21.18%` / `SR 1.114` / `0` liqs**; `BEAR75` hits all 3 bear-week Northstar targets at `+89.23%` / `SR 0.987`). Re-testing `1h`/`30m`: Bellman+Maker rescues `1h` Ignition (`SR 0.436`, `77.4%` pre-EOD `$0` borrow), while `30m` faces a `0.38×`-of-sigma Taker fee wall. |
| Convex Cross-Asset Bear Short (`+3%/5%/15%`) & Unified Absorption | [convex-bear-cross-asset-study.md](v3-adaptive-engine/convex-bear-cross-asset-study.md) | [JSON](v3-adaptive-engine/convex-bear-cross-asset-study.json) | 7-family diverse bear exploration proves **Institutional CTA 20d Vol-Targeting on Liquid Crypto Majors (`BTC/ETH/SOL/BNB`) + Orthogonal Gold (`XAUTUSDT` `5×` Nobitex Margin)** beats alt-chasing, tight trailing-stop pyramiding, and ML downside regression (`0` liqs, standalone `SR 0.780–0.894`, `+78.7%` to `+108.5%`, all `7/7` hit `3%/5%/15%`). Absorbed inside unified `MultiHorizonBook` with `E3_V2`, **`E3_V2_PLUS_CTA_VOLTGT80_M4_XAUT`** hits **`+4.91%` (1d) / `+7.83%` (3d) / `+18.12%` (7d)** while lifting `1,085d` NAV to **`$2,424.64` (`+142.45%`, Bear `+54.15%`, `SR 0.996`, `0` liqs, `2024 +5.9% / 2025 +41.5% / 2026 +60.7%`)**. |
