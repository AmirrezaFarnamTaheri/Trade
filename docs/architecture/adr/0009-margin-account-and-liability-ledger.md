# ADR 0009: Spot-Only Admission Gate & Future `MarginAccount` / `LiabilityLedger` Contract

- **Status:** Accepted (Spot-Only Gate Active) / Proposed (Margin Extension Deferred)
- **Date:** 2026-11-26
- **Context:** Quantitative research explores Nobitex isolated margin, Wallex credit, and bear-regime shorting (`docs/venues/nobitex/margin_trade.yaml`, `docs/venues/wallex/margin.json`, `bear_majors_sleeve.py`), whereas the authoritative Rust custody plane (`executor/exec-core`, `executor/exec-svc`) implements strictly spot-only cash reservations (`available - active_holds`).

## Decision

1. **Hard Spot-Only Admission Gate (Active Now):**
   - No leveraged (`leverage > 1.0`) or short-selling strategy may be promoted to default capital or admitted to live execution while `exec-core` models spot-only balances (`enforce_spot_only_strategy` in `gym/domain/promoted_strategies.py`).
   - `TradingGYMExecutor` remains `DISARMED` (`$0` funded budget) with spot-only `ArmPolicy` presets.

2. **Mandatory Invariants Before Any Future Margin Activation:**
   Before any leveraged or short strategy can be armed with funded capital, `executor/exec-core` MUST implement:
   - **`MarginAccount` & `LiabilityLedger`:** Explicit tracking of borrowed principal, hourly/4h accrued borrow/funding carry, initial vs. maintenance margin haircuts, and unrealized mark-to-market PnL in integer quanta.
   - **`LiquidationWatchdog`:** Jump-gap stress bound verifying a 99.9th-percentile 4h adverse move (Student-$t$, $\nu \in [3, 5]$) remains $\ge 2\times$ inside venue maintenance margin, coupled with automated `CancelAll` + protective-exit transport on `STOP`.
   - **Denomination Safety:** Compile-time currency separation (`Irr`, `Tmn`, `Usdt`) with a 10× Rial/Toman sanity guard against consensus FX before any order admission.
   - **Chaos & Recovery Proof:** Seeded deterministic recovery tests covering partial fills, forced venue liquidations, and out-of-order balance snapshots with zero conservation-of-funds violations.

## Consequences
- Research may continue evaluating short/margin hypotheses strictly in paper simulation (`PAPER_ONLY`).
- Live execution remains provably isolated from unmodeled borrow accrual and forced liquidation until every invariant above is implemented and verified.
