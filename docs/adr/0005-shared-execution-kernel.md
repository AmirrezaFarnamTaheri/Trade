# ADR 0005: One execution kernel for research and the executor

Status: Exact sizing API available; depth, guard and settlement bridged; contextual sizing integration and stage 4 pending

## Context

At this ADR's introduction, the Python simulator (`gym/domain/sim.py`) and Rust executor computed money rules
separately, sharing only the ticket quote envelope through `contracts/v1/fixtures/ticket-envelopes.json`.
The reference rules and bridge described below now share more arithmetic, but the executor still has no
complete venue fill engine, so a paper edge cannot be shown to survive actual execution.

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

## Stage 3 done (2026-11-10)

- `executor/exec-kernel-py` (PyO3, abi3 for Python 3.11+) exposes `sellable`, `walk` and `trips_price_guard`
  to Python as decimal strings. It builds with maturin outside the main workspace, so the executor never links
  Python, and the product's four runtime dependencies are unchanged (the kernel is optional).
- `GYM_RUST_KERNEL=1` makes the package root inject it into `gym.domain.sim` (`sim.use_kernel`); the domain reads
  no environment. With it, the whole Python suite passes, and `test_rust_kernel_gives_byte_identical_orders_to_the_python_path`
  shows 4,000 random market orders byte-identical to the Python path wherever venue precision is known.
- Where venue precision is unknown, Python rounds in its 28-digit context and the kernel stays exact (for example a
  walked buy priced exactly at the ask instead of one unit below it). Past the kernel's 38-digit exact range the
  simulator falls back to the Python path rather than round in Rust.
- CI job `rust-kernel` builds the wheel and runs the whole suite on it.
- Stage 4, making the kernel the default, needs the wheel in the normal install path (a build step in
  `Start-Workspace.ps1` or a published wheel); recommended once the remaining money rules (cash and holdings
  sizing, fee pricing with cost models) are in the kernel.

## Sizing and settlement bridge (2026-11-11)

- `cash_quantity` sizes from the cash fraction at the touch or across observed depth, flooring only to a known
  venue quantity precision. `holdings_quantity` floors the actual holding fraction. Shared
  `contracts/v1/fixtures/order-sizing.json` vectors cover recurring division, insufficient cash, zero fractions,
  shallow depth and sub-lot depth remainders. A separate rational-arithmetic Python oracle exercises 2,000 walks.
  These exact APIs are available through the bridge; the simulator retains contextual Python sizing because
  intermediate multiplication, depth accumulation and quantize traps are part of historical run identities.
  Exact native sizing can differ even at known venue precision, so integration requires an explicitly versioned
  rounding contract rather than silently changing the comparison path.
- The Python bridge now exposes `settle` with exact fee/base/quote deltas. The simulator obtains its fee from
  that rule, including a dated model's selected maker/taker fee, while retaining the existing gross posting
  sequence and Decimal context so historical cashbook identities are preserved.
- Ordinary source installation supports `uv sync --project gym-core --extra kernel --locked`. The locked local
  PyO3 project builds its wheel through maturin; an installed Rust compiler is required. Kernel selection remains
  explicit (`GYM_RUST_KERNEL=1`); the collector and scheduler startup defaults have not changed.
- Unknown quantity precision and values outside the u128 exact range retain the existing Python comparison
  path. The native functions themselves reject invalid fractions, zero divisors and unrepresentable results;
  they never return floating-point approximations. A native refusal is not proof that a venue order is executable.
- Model estimation, causal receipt selection, modeled-impact budget resizing, capacity/quota caps and cashbook
  posting still have Python owners. In particular, the 60-digit square-root impact estimate is not an exact
  finite-decimal Rust rule. Stage 4 still requires an explicit scientific rounding/version contract for any
  changed identities and complete default-engine conformance; this bridge does not establish that gate.
