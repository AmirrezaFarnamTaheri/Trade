# Roadmap

One question governs the work: is there a net edge on Wallex after costs, against holding USDT?
The [trial log](trial-log.md) holds the answer so far. This page lists open work only; finished work is in Git.

## Scope freeze (2026-11-24)

To focus engineering time on establishing a genuine net edge rather than infrastructure:

- **Universe narrowed to 40 curated markets (`core-40-wallex`, 2 WebSocket shards)** covering top TMN pairs plus 100% of active forward-journal USDT pairs (`Install-Collector.ps1`, watchlist `5078e0c5a62155c6`).
- **Frozen until a strategy clears Gate G2 (Track A or Track B):** 373-market whole-catalogue replay expansions, new EN/FA UI views, Rust executor changes (`DISARMED`), and generic single-venue spot TA sweeps.
- **Paused:** the five hourly `ema-trend 8/21` scheduled jobs in `data/live/research.sqlite3` (lost in 320/337 markets).
- **Venue cost & expansion map:** Wallex published Level-1 fees are **0.25% maker / 0.30% taker on TMN** and **0.10% maker / 0.13% taker on USDT** (ingested via `/v2/structured-fee`). Active development focuses on the **Wallex 40-market core engine first** (financial engine, multi-signal vector framework, and quantitative modeling), with **Nobitex** (`-30%` fee tier) and **AbanTether** (tokenized US equities/bonds/commodities) scheduled as clean Phase B plug-ins. Full specification: [profitable-system-plan.md](../../docs/profitable-system-plan.md).

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
