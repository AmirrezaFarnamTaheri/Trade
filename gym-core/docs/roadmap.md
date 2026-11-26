# Roadmap

One question governs the work: is there a net edge on Wallex after costs, against holding USDT?
The [trial log](trial-log.md) holds the answer so far. This page lists open work only; finished work is in Git.

## Current baseline & scope freeze (2026-11-25)

To keep engineering focused on untouched forward evidence and execution efficiency rather than backtest overfitting:

- **Live observation infrastructure running:** 40-market Wallex collector (`core-40-wallex`, 2 WS shards, `--depth-levels 5`), 20-symbol Nobitex live order-book recorder (`TradingGYM Multi-Venue Recorder` → `data/live/multi_venue_quotes.sqlite3`), and read-only operational health watchdog (`scripts/check_operational_health.py`).
- **Frozen v1 & parallel v2 Champion prospective forward tracking active (zero order authority):**
  - `TradingGYM Champion Forward Journal` (every 2h): frozen v1 `70% BASE_13_S1_S5 (XAUT) + 30% 2h GRU-Ignition` (`data/live/models/gru-ignition-v1.json`) with live Wallex/Nobitex spread telemetry and sequential `e_process` scoring.
  - `TradingGYM Champion V2 Forward Journal` (hourly, twin `0h+1h` phase): frozen parallel v2 (`1d ACCEL_BLEND_20 + 11A Metals Reserve + Joint ADMM Netting + 50/50 Twin-Phase 2h GRU11 Path-PnL + Conformal/5% DD Leverage Governor`, `data/live/models/gru-ignition-v2-pathpnl.json`).
  - `TradingGYM S1-S5 Leader Journal` (daily `03:55`): standalone 13-asset `S1+S5 + ADMM` baseline.
  - Background monitors retained unchanged: `mix-journal-v2`, `breadth-trend-forward`, `btc-daily-trend` (`allocation/journal.jsonl`).
- **Decisively retired dead ends (do not re-run):** hourly `ema-trend 8/21`, `S2` residual momentum (raw & hysteresis), `S3` panic reversion, `S4` vol breakout, binary/continuous ML veto on `S1+S5`, flat 33-asset crypto ADMM dilution, intraday `2h`/`3h`/`6h` crash circuit breakers, sub-hourly `15m`/`30m` ignition, `2h` flush-rebound & dead-cat shorts, slow Wallex margin leverage/pairs (`32.85%/yr` borrow), `GRU-Vol` ADMM covariance scaling, Path-Efficiency IC modulation, Savitzky–Golay polynomial filters, `HRP` trend anchoring, two-tranche partial profit-locks, absorption-ratio slot throttling, and `2h` lead-lag diffusion.
- **Future research candidates (strictly parked while v1 & v2 accumulate untouched forward days):**
  1. **Non-price modalities:** global perpetual funding/OI feeds and local-vs-global venue basis.
  2. **Standalone macro commodities sleeve (`PAXG/SLVON/USOON/COPXON/UNGON`):** positive & orthogonal (`+24.4%`, corr `+0.082`), waiting for `2+` years of tokenized ETF history.
- **Frozen until Gate G2 passes:** 373-market whole-catalogue sweeps, new EN/FA UI views, and Rust executor changes (`DISARMED`). Full architecture spec: [profitable-system-plan.md](../../docs/profitable-system-plan.md).

## Evidence

- Track the passive multi-asset mix on Wallex prices daily (`gymctl mix-journal`). A historical pass does not establish a Wallex edge.
- Follow `breadth-trend-forward` daily at 15:00 Tehran (`gymctl breadth-journal --refresh`, task `TradingGYM Breadth
  Journal`); score it after 2027-05-19 against USDT and an equal-weight hold of the same coins.
- Follow the BTCUSDT 50-day trend rule (`btc-daily-trend`) on paper every day until the 2027-02-08 checkpoint.
- Later trials use orthogonal multi-signal vectors rather than redundant single-venue price indicators: cross-venue oracle lead (`Hyperliquid` / `Nobitex` vs `Wallex`), order-book imbalance, implied Toman premium, perpetual funding rates, and volatility/breadth regime, paired with passive cancel/replace execution (`simulate_passive_cancel_replace`).
- Score `funding-confirmed-trend-forward` after 2027-02-08, once the archive's monthly funding files cover that day:
  `scripts/binance_archive.py fetch`, then `scripts/held_out_followups.py --forward`.
- The broad Binance held-out set (2024 to 2026, about 450 coins) is consumed for daily trend and breakout rules. New trials
  need new data: intraday bars, order-book data, cross-venue oracle feeds, or the forward record.
- Research budget: at most two **active** registered hypothesis trials open at a time, each with new information or new data. Long-horizon background forward monitors (`funding-confirmed-trend-forward`, `breadth-trend-forward`) are tracked separately so they do not freeze active R&D, while every trial still counts in the multiplicity (BH/DSR) denominator.
- Forward journals report anytime-valid sequential e-values (`sequential_e_process`) alongside continuity and accounting parity.
- Machine-learning and reinforcement-learning models stay paper-only and wait for orthogonal features that show value in simple linear/rule baselines. `logistic-entry-gate` failed on price-only features; a larger model on the same inputs is not new evidence.

## Paper engine

- Extend strategy stop-market support to stop-limit and trailing orders after their paper contracts are defined.
- Reconstruct in-run fee-tier and catalogue fee changes when historical receipts exist.
- Collect the margin long/short ratio and `/v2/structured-fee`.

## Funded path

Disarmed. Arming is not the next routine milestone: it waits for the 2027-02-08 checkpoint, a published bundle,
owner approval and installed-host qualification, in that order. If the checkpoint shows no edge, the observatory
is the product and funded-path work stops. Trading-credit packages stay separate from position margin: they put
money in a sub-account and are a different risk contract, not a leverage setting. The wiring order is in
[ADR 0007](../../docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md). Review v2, active holds and
checkpoint events, independent startup audit, privileged approval, native admission and one-shot LIMIT
transport/settlement are wired and locally fault tested. Remaining: owner review/publication of the complete
binary bundle, installed-host/venue qualification and the registered prospective checkpoint.
The owner accepted [service receipt ordering](../../docs/adr/0008-balance-observation-ordering.md): two fresh
reads, own-activity fencing, disagreement disarm and conservative held-funds subtraction. That contract is
implemented. The venue's undocumented balance sequence is no longer a requirement.

## Operations

- Qualify each reviewed native service build on the installed Windows host before use.

The owner canceled off-machine backup scheduling and second-machine restoration on 2026-11-16. That accepts a
known exposure: losing this laptop or its disk loses everything since the last copy the owner made by hand.
Local restore drills prove the backup files decrypt; they do not remove that exposure.
