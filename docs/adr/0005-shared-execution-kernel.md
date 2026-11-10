# ADR 0005: One execution kernel for research and the executor

Status: Proposed; stages 1-2 started (finding A-1 step 2; a quarter-scale project)

## Context

The Python simulator (`gym/domain/sim.py`) and the Rust executor price, size and settle orders in separate
code. Today the only money rule both compute is the ticket quote envelope, and it is pinned by shared vectors
(`contracts/v1/fixtures/ticket-envelopes.json`). The executor has no pricing or fill engine yet, so a paper edge
cannot be shown to survive the executor's own arithmetic.

## Proposal, in stages that each ship on their own

1. **Vectors first (done for the envelope).** Every new money rule gets a shared fixture before it gets a
   second implementation: quantity flooring to venue precision, fee-in-received-asset, minimum notional, the 2%
   venue price guard, depth-walk notional.
2. **Rust becomes the reference.** Implement those rules in `exec-core` as pure integer-quanta functions
   (`size`, `walk`, `fee`, `settle`), each passing the shared fixtures. Python keeps its implementation and the
   fixtures keep them equal.
3. **Bridge.** Build an `exec-core` Python extension with PyO3 (maturin, built in CI for the pinned Python) that
   exposes those functions. `sim.py` calls them behind a flag; the seeded market-order properties and the golden
   run-identity tests must pass bit-for-bit both ways.
4. **Switch.** Make the Rust kernel the default in the simulator; keep the Python path one release for
   comparison, then remove it.

## Consequences and costs

- A native build in the Python toolchain (maturin, a compiler in CI, wheels per platform) where today the
  product has four pure-Python dependencies.
- Decimal-to-quanta conversion becomes an explicit boundary; the 28-digit context issues found by the
  property tests (unknown venue precision) disappear because the kernel requires a known precision.
- Benefit: a paper fill and a live fill come from the same code, which is what turns research into a credible
  path to execution.

## Progress (2026-11-10)

- `exec-core/src/kernel.rs` holds the first reference rule, `sellable` (floor to venue precision, minimum
  quantity, minimum notional), in exact integer arithmetic. `contracts/v1/fixtures/sizing.json` pins it and
  `gym/domain/sim.py` `sellable_quantity` to the same 12 cases (`exec-core/tests/kernel_conformance.rs`,
  `gym-core/tests/test_market_order_properties.py`).
- `kernel::walk` (depth-walk notional) and `kernel::settle` (fee in the received asset, balance deltas) follow,
  pinned with the simulator's `_walk` and `_settle` by `contracts/v1/fixtures/fills.json`.
- `kernel::trips_price_guard` (the 2% venue guard, exact at the boundary) is pinned with `_trips_price_guard` by
  `contracts/v1/fixtures/price-guard.json`.
- Next: order sizing from cash or holdings, then the PyO3 bridge (stage 3), which adds a native build to the
  Python toolchain and needs its own CI wheel job.
